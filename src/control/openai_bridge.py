from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Dict, List, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, Field
import uvicorn

from src.mcp.server import _app_ctx, _retrieval, _memory, _model_gateway
from src.shared.logging_config import get_logger, setup_logging
from src.shared.config import config

# OpenAI model isimlerini ucuz OpenRouter modellerine yönlendir
_MODEL_REMAP = {
    "gpt-4":               None,  # reasoning_model kullan
    "gpt-4o":              None,
    "gpt-4-turbo":         None,
    "gpt-4o-mini":         "budget",   # budget_model kullan
    "gpt-3.5-turbo":       "budget",
    "graph-mcp":           "analysis", # analysis_model kullan
    "default":             "analysis",
}

setup_logging()
logger = get_logger(__name__)

# FastAPI Lifespan to connect database connections
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("OpenAI API Bridge Gateway starting up...")
    await _app_ctx.redis.connect()
    await _app_ctx.postgres.connect()
    await _app_ctx.neo4j.connect()
    try:
        yield
    finally:
        logger.info("OpenAI API Bridge Gateway shutting down...")
        await _app_ctx.redis.close()
        await _app_ctx.postgres.close()
        await _app_ctx.neo4j.close()
        close_episodic = getattr(_app_ctx.episodic, "close", None)
        if callable(close_episodic):
            await close_episodic()

app = FastAPI(
    title="GraphRagMCP OpenAI API Bridge Gateway",
    version="2.0.0",
    lifespan=lifespan
)

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 1.0
    n: Optional[int] = 1
    stream: Optional[bool] = False
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = 0.0
    frequency_penalty: Optional[float] = 0.0
    user: Optional[str] = None

class ChatChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str = "stop"

class ChatUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[ChatChoice]
    usage: ChatUsage

@app.get("/v1/models")
async def list_models():
    """Exposes standard models for client validation."""
    return {
        "object": "list",
        "data": [
            {
                "id": "graph-mcp",
                "object": "model",
                "created": 1677610200,
                "owned_by": "graphmcp"
            },
            {
                "id": "gpt-4o-mini",
                "object": "model",
                "created": 1677610200,
                "owned_by": "graphmcp"
            },
            {
                "id": "gpt-4o",
                "object": "model",
                "created": 1677610200,
                "owned_by": "graphmcp"
            },
            {
                "id": "claude-3-5-sonnet",
                "object": "model",
                "created": 1677610200,
                "owned_by": "graphmcp"
            }
        ]
    }

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(req: ChatCompletionRequest, request: Request):
    """
    OpenAI-compatible chat completion gateway.
    Intercepts last user message, executes hybrid retrieval across project codebase,
    augments prompt with AST & memory context, and forwards call to LLM.
    """
    # 1. Determine collection/project
    collection = request.query_params.get("collection") or request.query_params.get("project")
    
    # ── Smart Dynamic Project Routing (V2) ───────────────────────────────────
    # Scan incoming messages for known project keywords to prevent cold 'DefaultCol' issues.
    prompt_text = ""
    for msg in req.messages:
        prompt_text += f"\n{msg.content}"
        
    detected_project = None
    if "vendoris" in prompt_text.lower():
        detected_project = "Vendoris"
    elif "warelogistic" in prompt_text.lower():
        detected_project = "WareLogisticcBYS"
    elif "graphragmcp" in prompt_text.lower() or "graphmcp" in prompt_text.lower():
        detected_project = "GraphRagMCP"
        
    if detected_project:
        collection = detected_project
        logger.info("Smart project routing detected target collection from prompt keywords", extra={"collection": collection})
    elif not collection or collection in ("DefaultCol", "default", "codebase"):
        collection = config.default_collection or "codebase"
    # ─────────────────────────────────────────────────────────────────────────
        
    logger.info("OpenAI bridge completions request received", extra={"collection": collection, "model": req.model})

    # 2. Extract last user message
    user_query = ""
    for msg in reversed(req.messages):
        if msg.role == "user":
            user_query = msg.content
            break

    combined_context = ""
    if user_query:
        logger.info("Executing codebase semantic retrieval for query", extra={"query": user_query[:120]})
        try:
            # Execute search_code, search_repo_architecture and search_decisions
            # We run these concurrently to minimize latency
            search_task = _retrieval.search_code(user_query, collection=collection, top_k=5)
            arch_task = _retrieval.search_repo_architecture(user_query, collection=collection, top_k=3)
            decision_task = _memory.search_decisions(user_query, collection=collection, top_k=3)
            memory_task = _memory.recall_memory(user_query, collection=collection, top_k=3)
            
            search_res, arch_res, dec_res, mem_res = await asyncio.gather(
                search_task, arch_task, decision_task, memory_task,
                return_exceptions=True
            )
            
            context_blocks = []
            if isinstance(search_res, str) and "No results" not in search_res:
                context_blocks.append(f"### Relevant Code & AST Semantics:\n{search_res}")
            if isinstance(arch_res, str) and "No results" not in arch_res:
                context_blocks.append(f"### Subsystem & Architectural Map:\n{arch_res}")
            if isinstance(dec_res, str) and "No decisions" not in dec_res:
                context_blocks.append(f"### Historical Architectural Decisions:\n{dec_res}")
            if isinstance(mem_res, str) and "No memory" not in mem_res:
                context_blocks.append(f"### Stored Facts & Memories:\n{mem_res}")
                
            if context_blocks:
                combined_context = "\n\n".join(context_blocks)
                logger.info("Semantic context successfully gathered", extra={"context_len": len(combined_context)})
        except Exception as exc:
            logger.error("Failed to perform codebase retrieval, proceeding without context enrichment", exc_info=True)

    # 3. Augment prompt
    augmented_messages = []
    
    # Check if there is already a system prompt
    system_prompt_exists = False
    for msg in req.messages:
        if msg.role == "system":
            system_prompt_exists = True
            break
            
    if combined_context:
        context_instruction = (
            "You are an expert AI software architect and senior developer working inside the JetBrains Rider IDE.\n"
            "Below is the extremely detailed codebase context, AST structural map, and memories retrieved from the user's project repository database.\n"
            "Use this context as your source of truth to answer queries, locate bugs, explain flows, and generate precise code improvements.\n\n"
            f"--- START RETRIEVED CODEBASE CONTEXT ---\n{combined_context}\n--- END RETRIEVED CODEBASE CONTEXT ---"
        )
        if system_prompt_exists:
            # We append it to the existing system prompt
            for msg in req.messages:
                if msg.role == "system":
                    augmented_messages.append({
                        "role": "system",
                        "content": f"{msg.content}\n\n{context_instruction}"
                    })
                else:
                    augmented_messages.append({"role": msg.role, "content": msg.content})
        else:
            # Inject a new system prompt at the beginning
            augmented_messages.append({"role": "system", "content": context_instruction})
            for msg in req.messages:
                augmented_messages.append({"role": msg.role, "content": msg.content})
    else:
        # No context retrieved, forward unmodified messages
        for msg in req.messages:
            augmented_messages.append({"role": msg.role, "content": msg.content})

    # 4. Forward to the real LLM (via ModelGateway's client)
    logger.info("Forwarding request to LLM provider", extra={"model": req.model})
    
    # We resolve the model. If user requests 'graph-mcp' or a placeholder, we use the default analysis model.
    # Pahalı OpenAI modellerini ucuz OpenRouter karşılıklarına yönlendir
    tier = _MODEL_REMAP.get(req.model)
    if tier == "budget":
        model_to_use = config.budget_model
    elif tier == "analysis":
        model_to_use = config.analysis_model
    elif tier is None and req.model in _MODEL_REMAP:
        model_to_use = config.reasoning_model
    else:
        model_to_use = req.model
        
    try:
        completion_params = {
            "model": model_to_use,
            "messages": augmented_messages,
            "temperature": req.temperature,
            "top_p": req.top_p,
            "n": req.n,
            "stream": False,  # Wait for full response
        }
        if req.max_tokens is not None:
            completion_params["max_tokens"] = req.max_tokens

        t0 = time.monotonic()
        response = await _model_gateway.client.chat.completions.create(**completion_params)
        latency = int((time.monotonic() - t0) * 1000)
        
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else 0

        # Optional: Write usage stats to Postgres
        if _app_ctx.postgres and _app_ctx.postgres.available:
            try:
                await _app_ctx.postgres.log_llm_usage(
                    model=model_to_use,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency,
                    task_id="openai-bridge",
                    node_name="openai_bridge"
                )
            except Exception:
                logger.debug("log_llm_usage writing failed", exc_info=True)

        logger.info("LLM response successfully returned", extra={
            "model": model_to_use,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "latency_ms": latency
        })

        return ChatCompletionResponse(
            model=req.model,
            choices=[
                ChatChoice(
                    index=choice.index,
                    message=ChatMessage(
                        role=choice.message.role,
                        content=choice.message.content or ""
                    ),
                    finish_reason=choice.finish_reason or "stop"
                ) for choice in response.choices
            ],
            usage=ChatUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens
            )
        )
    except Exception as exc:
        logger.error("LLM forwarding call failed", exc_info=True)
        raise HTTPException(status_code=500, detail=f"LLM Bridge Gateway Error: {str(exc)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5555)
