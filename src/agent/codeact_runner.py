"""
CodeAct Runner — tam 8 adımlı TDAD döngüsü.

SPEC → TEST → CONTEXT → EDIT → VERIFY → IMPACT → REFLECT → COMMIT

Her adım geçişinde AgentStateMachine checkpoint alır.
Başarısızlık → EscalationManager.decide() → tier yükseltme veya HUMAN_REVIEW.
HITL zaman aşımı: HITL_TIMEOUT_SECONDS (varsayılan 300s).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional

from src.agent.context_assembler import ContextAssembler, get_context_assembler
from src.agent.session_context import SessionContext, SessionContextStore, get_session_store
from src.agent.spec_builder import SpecBuilder, TaskSpec, get_spec_builder
from src.agent.state_machine import AgentCheckpoint, AgentStateMachine
from src.agent.workspace_manager import WorkspaceInfo, get_workspace_manager
from src.control.models.complexity_router import ModelTier, RoutingDecision, get_complexity_router
from src.control.models.escalation_manager import (
    EscalationAction,
    EscalationManager,
    EscalationState,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

HITL_TIMEOUT_S: int = int(os.getenv("HITL_TIMEOUT_SECONDS", "300"))
MAX_REFLECTIONS: int = int(os.getenv("CODEACT_MAX_REFLECTIONS", "5"))
VERIFY_TIMEOUT_S: int = int(os.getenv("VERIFY_TIMEOUT_SECONDS", "120"))


class TDADStep(str, Enum):
    SPEC    = "SPEC"
    TEST    = "TEST"
    CONTEXT = "CONTEXT"
    EDIT    = "EDIT"
    VERIFY  = "VERIFY"
    IMPACT  = "IMPACT"
    REFLECT = "REFLECT"
    COMMIT  = "COMMIT"
    DONE    = "DONE"
    FAILED  = "FAILED"
    WAITING = "WAITING_APPROVAL"


@dataclass
class RunConfig:
    task_id:      str
    goal:         str
    collection:   str
    project_path: str
    hitl_enabled: bool = True
    tier_override: Optional[str] = None


@dataclass
class StepEvent:
    """SSE akışı için adım olayı."""
    step:    str
    status:  str  # started | completed | failed | waiting
    message: str  = ""
    data:    dict = field(default_factory=dict)


class CodeActRunner:
    """
    TDAD görev döngüsünü yönetir.

    Bağımlılıklar inject edilir; test edilebilirlik için mock edilebilir.
    """

    def __init__(
        self,
        state_machine:      AgentStateMachine,
        session_store:      SessionContextStore,
        spec_builder:       SpecBuilder,
        context_assembler:  ContextAssembler,
        escalation_manager: EscalationManager,
        llm_client=None,
        mcp_handler=None,
        approval_queue: Optional[asyncio.Queue] = None,
    ) -> None:
        self._sm       = state_machine
        self._sessions = session_store
        self._specs    = spec_builder
        self._ctx_asm  = context_assembler
        self._esc      = escalation_manager
        self._llm      = llm_client
        self._mcp      = mcp_handler
        self._approvals= approval_queue or asyncio.Queue()

    # ── Ana giriş noktası ─────────────────────────────────────────────────

    async def run(self, config: RunConfig) -> AsyncIterator[StepEvent]:
        """
        Görev döngüsünü başlatır ve adım olaylarını yayınlar.
        `async for event in runner.run(cfg):` şeklinde tüketilir.
        """
        task_id = config.task_id

        # Routing
        decision = await self._route(config)
        tier = ModelTier(config.tier_override) if config.tier_override else decision.tier

        # Checkpoint ve oturum oluştur/yükle
        cp = await self._sm.load(task_id) or await self._sm.create(
            task_id=task_id,
            goal=config.goal,
            collection=config.collection,
            project_path=config.project_path,
            tier=tier.value,
            model=decision.model,
        )
        await self._sm.create_task_record(cp, status="RUNNING")

        ctx = await self._sessions.load(task_id) or SessionContext(
            task_id=task_id,
            goal=config.goal,
            collection=config.collection,
            project_path=config.project_path,
            tier=tier.value,
        )

        esc_state = EscalationState(
            task_id=task_id,
            current_tier=tier,
            reflection_count=cp.reflection_count,
            last_failures=list(cp.last_failures),
        )

        ws: Optional[WorkspaceInfo] = None
        spec: Optional[TaskSpec] = None

        try:
            async for event in self._loop(config, cp, ctx, esc_state, decision, ws, spec):
                yield event
        except Exception as exc:
            logger.exception("CodeAct run sırasında beklenmedik hata: %s", exc)
            cp.step = TDADStep.FAILED.value
            await self._sm.save(cp)
            await self._sm.update_task_status(task_id, "FAILED")
            yield StepEvent(step="FAILED", status="failed", message=str(exc))
        finally:
            if ws:
                try:
                    await get_workspace_manager().remove(ws)
                except Exception:
                    pass
            await self._sessions.delete(task_id)

    # ── Ana döngü ─────────────────────────────────────────────────────────

    async def _loop(
        self,
        config: RunConfig,
        cp: AgentCheckpoint,
        ctx: SessionContext,
        esc_state: EscalationState,
        decision: RoutingDecision,
        ws: Optional[WorkspaceInfo],
        spec: Optional[TaskSpec],
    ) -> AsyncIterator[StepEvent]:
        step = TDADStep(cp.step) if cp.step in TDADStep._value2member_map_ else TDADStep.SPEC

        while step not in (TDADStep.DONE, TDADStep.FAILED):

            # ── SPEC ──────────────────────────────────────────────────────
            if step == TDADStep.SPEC:
                yield StepEvent(step="SPEC", status="started")
                spec = self._specs.heuristic_build(
                    task_id=config.task_id,
                    goal=config.goal,
                    collection=config.collection,
                    project_path=config.project_path,
                    complexity_score=decision.score,
                )
                cp.step = TDADStep.TEST.value
                await self._checkpoint(cp, ctx)
                yield StepEvent(step="SPEC", status="completed",
                                data={"task_type": spec.task_type, "criteria": spec.acceptance_criteria})
                step = TDADStep.TEST

            # ── TEST ──────────────────────────────────────────────────────
            elif step == TDADStep.TEST:
                yield StepEvent(step="TEST", status="started")
                test_code = await self._generate_test(spec, ctx, decision)
                ctx.test_code = test_code
                cp.step = TDADStep.CONTEXT.value
                await self._checkpoint(cp, ctx)
                yield StepEvent(step="TEST", status="completed",
                                data={"test_lines": len(test_code.splitlines())})
                step = TDADStep.CONTEXT

            # ── CONTEXT ───────────────────────────────────────────────────
            elif step == TDADStep.CONTEXT:
                yield StepEvent(step="CONTEXT", status="started")
                widen = esc_state.reflection_count >= 2
                assembly = await self._ctx_asm.assemble(spec, ctx, decision.token_budget, widen)
                ctx.tokens_used += assembly.tokens_used
                cp.opened_files = [c["file_path"] for c in assembly.code_chunks]

                # Patch memory recall (PATCH_MEMORY_ENABLED=true ise)
                if os.getenv("PATCH_MEMORY_ENABLED", "false").lower() == "true" and spec:
                    try:
                        from src.agent.patch_memory import get_patch_memory_store
                        examples = await get_patch_memory_store().recall_similar(
                            goal=config.goal,
                            task_type=spec.task_type,
                            language=getattr(spec, "language_hint", "python") or "python",
                            collection=config.collection,
                            limit=2,
                        )
                        if examples:
                            ctx.patch_examples = [
                                {"goal": r.goal, "patch": r.patch_content[:500],
                                 "tier": r.tier, "task_type": r.task_type}
                                for r in examples
                            ]
                            logger.info("PatchMemory: %d örnek bulundu", len(examples))
                    except Exception as _pm_exc:
                        logger.debug("PatchMemory recall atlandı: %s", _pm_exc)

                cp.step = TDADStep.EDIT.value
                await self._checkpoint(cp, ctx)
                yield StepEvent(step="CONTEXT", status="completed",
                                data={"chunks": len(assembly.code_chunks), "tokens": assembly.tokens_used,
                                      "patch_examples": len(ctx.patch_examples)})
                step = TDADStep.EDIT

            # ── EDIT ──────────────────────────────────────────────────────
            elif step == TDADStep.EDIT:
                yield StepEvent(step="EDIT", status="started")

                # Workspace oluştur
                if ws is None:
                    ws = await get_workspace_manager().create(config.task_id, config.project_path)
                    cp.workspace_path = str(ws.path)
                    cp.current_branch = f"agent/task-{config.task_id}"
                    cp.snapshot_ref   = ws.snapshot_ref or ""

                patch = await self._generate_edit(spec, ctx, decision)
                ctx.edit_patch = patch

                # Patch'i workspace'e uygula
                if patch:
                    await self._apply_patch(ws, patch)

                cp.step = TDADStep.VERIFY.value
                await self._checkpoint(cp, ctx)
                yield StepEvent(step="EDIT", status="completed",
                                data={"patch_lines": len(patch.splitlines())})
                step = TDADStep.VERIFY

            # ── VERIFY ────────────────────────────────────────────────────
            elif step == TDADStep.VERIFY:
                yield StepEvent(step="VERIFY", status="started")
                verify_ok, verify_out = await self._run_verify(spec, ws)
                ctx.verify_output = verify_out

                if not verify_ok:
                    esc_state.record_failure(verify_out[:200])
                    cp.reflection_count = esc_state.reflection_count
                    cp.last_failures = esc_state.last_failures

                    esc_result = self._esc.decide(esc_state)
                    logger.info("Verify başarısız → %s", esc_result.action)

                    if esc_result.action == EscalationAction.HUMAN_REVIEW:
                        cp.step = TDADStep.WAITING.value
                        await self._checkpoint(cp, ctx)
                        await self._sm.update_task_status(config.task_id, "SUSPENDED")
                        yield StepEvent(step="WAITING_APPROVAL", status="waiting",
                                        message="Max reflection aşıldı, insan onayı gerekli",
                                        data={"verify_output": verify_out[:500]})
                        approved = await self._wait_approval(config.task_id)
                        if not approved:
                            step = TDADStep.FAILED
                            break
                        step = TDADStep.REFLECT
                    else:
                        # Tier güncelle ve EDIT'e dön
                        if esc_result.new_tier != esc_state.current_tier:
                            decision = self._apply_tier(esc_result, decision)
                            esc_state.current_tier = esc_result.new_tier
                            cp.current_tier    = esc_result.new_tier.value
                            cp.selected_model  = decision.model
                        cp.step = TDADStep.EDIT.value
                        await self._checkpoint(cp, ctx)
                        yield StepEvent(step="VERIFY", status="failed",
                                        message=esc_result.reason,
                                        data={"reflection": esc_state.reflection_count})
                        step = TDADStep.EDIT
                    continue

                cp.step = TDADStep.IMPACT.value
                await self._checkpoint(cp, ctx)
                yield StepEvent(step="VERIFY", status="completed",
                                data={"output": verify_out[:300]})
                step = TDADStep.IMPACT

            # ── IMPACT ────────────────────────────────────────────────────
            elif step == TDADStep.IMPACT:
                yield StepEvent(step="IMPACT", status="started")
                impact_summary = await self._analyze_impact(spec)
                ctx.impact_summary = impact_summary
                cp.step = TDADStep.REFLECT.value
                await self._checkpoint(cp, ctx)
                yield StepEvent(step="IMPACT", status="completed",
                                data={"summary": impact_summary[:200]})
                step = TDADStep.REFLECT

            # ── REFLECT ───────────────────────────────────────────────────
            elif step == TDADStep.REFLECT:
                yield StepEvent(step="REFLECT", status="started")
                notes = await self._reflect(spec, ctx, decision)
                ctx.reflection_notes = notes

                # HITL onayı
                if config.hitl_enabled:
                    cp.step = TDADStep.WAITING.value
                    await self._checkpoint(cp, ctx)
                    await self._sm.update_task_status(config.task_id, "SUSPENDED")
                    yield StepEvent(step="WAITING_APPROVAL", status="waiting",
                                    message="İnsan onayı bekleniyor",
                                    data={"reflection": notes[:300], "impact": ctx.impact_summary[:200]})
                    approved = await self._wait_approval(config.task_id)
                    if not approved:
                        step = TDADStep.FAILED
                        break

                cp.step = TDADStep.COMMIT.value
                await self._checkpoint(cp, ctx)
                yield StepEvent(step="REFLECT", status="completed",
                                data={"notes": notes[:300]})
                step = TDADStep.COMMIT

            # ── COMMIT ────────────────────────────────────────────────────
            elif step == TDADStep.COMMIT:
                yield StepEvent(step="COMMIT", status="started")
                commit_hash = await self._commit(config, ws, spec)
                ctx.commit_hash = commit_hash

                cp.step = TDADStep.DONE.value
                await self._checkpoint(cp, ctx)

                # Başarı memory'ye yaz
                await self._esc.record_success(esc_state, config.goal, self._mcp)
                await self._sm.update_task_status(config.task_id, "COMPLETED")

                # Patch memory'ye kaydet (PATCH_MEMORY_ENABLED=true ise)
                if os.getenv("PATCH_MEMORY_ENABLED", "false").lower() == "true":
                    if ctx.edit_patch and commit_hash:
                        try:
                            from src.agent.patch_memory import PatchRecord, get_patch_memory_store
                            await get_patch_memory_store().store_patch(PatchRecord(
                                task_id=config.task_id,
                                goal=config.goal,
                                task_type=spec.task_type if spec else "unknown",
                                language=getattr(spec, "language_hint", "python") or "python" if spec else "python",
                                patch_content=ctx.edit_patch,
                                affected_files=spec.affected_files if spec else [],
                                affected_symbols=spec.affected_symbols if spec else [],
                                acceptance_criteria=spec.acceptance_criteria if spec else [],
                                tier=esc_state.current_tier.value,
                                reflection_count=esc_state.reflection_count,
                                commit_hash=commit_hash,
                                verify_output=ctx.verify_output,
                                collection=config.collection,
                            ))
                            logger.info("PatchMemory: patch kaydedildi (task=%s)", config.task_id)
                        except Exception as _pm_exc:
                            logger.warning("PatchMemory store atlandı: %s", _pm_exc)

                yield StepEvent(step="COMMIT", status="completed",
                                data={"commit": commit_hash})
                yield StepEvent(step="DONE", status="completed",
                                message=f"Görev tamamlandı: {commit_hash}",
                                data={"task_id": config.task_id, "goal": config.goal})
                step = TDADStep.DONE

        if step == TDADStep.FAILED:
            await self._sm.update_task_status(config.task_id, "FAILED")
            yield StepEvent(step="FAILED", status="failed", message="Görev başarısız oldu")

    # ── Yardımcı adım işleyicileri ────────────────────────────────────────

    async def _generate_test(
        self, spec: TaskSpec, ctx: SessionContext, decision: RoutingDecision
    ) -> str:
        if not self._llm:
            return f"# TODO: {spec.task_type} testi\ndef test_{spec.task_id[:8]}():\n    pass\n"
        prompt = (
            f"Görev: {spec.goal}\nTip: {spec.task_type}\n"
            f"Dil: {spec.language_hint or 'python'}\n"
            f"Başarı kriterleri: {spec.acceptance_criteria}\n\n"
            f"Önce başarısız olan (fail-first) birim testini yaz. Sadece test kodunu döndür."
        )
        return await self._llm_complete(decision, prompt, max_tokens=1000)

    async def _generate_edit(
        self, spec: TaskSpec, ctx: SessionContext, decision: RoutingDecision
    ) -> str:
        if not self._llm:
            return ""
        context_text = ctx.build_context_text(decision.token_budget)
        prompt = (
            f"{spec.to_prompt_block()}\n\n"
            f"## Mevcut Kod Bağlamı\n{context_text}\n\n"
            f"## Mevcut Test\n```\n{ctx.test_code}\n```\n\n"
            f"Testi geçirecek minimum kodu üret. "
            f"Unified diff formatında patch döndür."
        )
        return await self._llm_complete(decision, prompt, max_tokens=3000)

    async def _run_verify(
        self, spec: TaskSpec, ws: Optional[WorkspaceInfo]
    ) -> tuple[bool, str]:
        if ws is None:
            return True, "Workspace yok, verify atlandı"
        ws_path = str(ws.path)
        cmd = self._build_test_command(spec, ws_path)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=ws_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=VERIFY_TIMEOUT_S
            )
            output = (stdout + stderr).decode(errors="replace")
            return proc.returncode == 0, output
        except asyncio.TimeoutError:
            return False, f"Verify zaman aşımı ({VERIFY_TIMEOUT_S}s)"
        except Exception as exc:
            return False, f"Verify hatası: {exc}"

    async def _analyze_impact(self, spec: TaskSpec) -> str:
        if not self._mcp or not spec.affected_files:
            return "Etki analizi mevcut değil"
        try:
            result = await self._mcp.analyze_change_impact(
                project_path=spec.project_path,
                changed_paths=spec.affected_files[:5],
                collection=spec.collection,
            )
            if isinstance(result, dict):
                return str(result.get("summary", result))[:500]
            return str(result)[:500]
        except Exception as exc:
            logger.debug("Impact analiz hatası: %s", exc)
            return "Etki analizi yapılamadı"

    async def _reflect(
        self, spec: TaskSpec, ctx: SessionContext, decision: RoutingDecision
    ) -> str:
        if not self._llm:
            return (
                f"Görev: {spec.goal}\n"
                f"Adımlar tamamlandı. Verify: {'OK' if 'PASS' in ctx.verify_output.upper() else 'FAIL'}\n"
                f"Etki: {ctx.impact_summary[:100]}"
            )
        prompt = (
            f"Görev: {spec.goal}\n"
            f"Başarı kriterleri: {spec.acceptance_criteria}\n"
            f"Test çıktısı: {ctx.verify_output[:400]}\n"
            f"Etki özeti: {ctx.impact_summary[:300]}\n\n"
            f"Tüm başarı kriterleri karşılandı mı? Kısa değerlendirme yaz."
        )
        return await self._llm_complete(decision, prompt, max_tokens=500)

    async def _commit(
        self,
        config: RunConfig,
        ws: Optional[WorkspaceInfo],
        spec: Optional[TaskSpec],
    ) -> str:
        if ws is None or not (ws.path / ".git").exists() if hasattr(ws, "path") else True:
            return "no-commit"
        try:
            msg = f"agent: {spec.task_type if spec else 'task'} — {config.goal[:60]}"
            proc = await asyncio.create_subprocess_exec(
                "git", "add", "-A", cwd=str(ws.path),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            proc = await asyncio.create_subprocess_exec(
                "git", "commit", "-m", msg, cwd=str(ws.path),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode()
            # commit hash al
            import re
            match = re.search(r"[0-9a-f]{7,40}", output)
            return match.group() if match else "committed"
        except Exception as exc:
            logger.warning("Commit hatası: %s", exc)
            return "commit-failed"

    async def _wait_approval(self, task_id: str) -> bool:
        """HITL onay kuyruğundan onay bekler; zaman aşımında False döner."""
        try:
            approved = await asyncio.wait_for(
                self._approvals.get(), timeout=HITL_TIMEOUT_S
            )
            await self._sm.update_task_status(task_id, "RUNNING")
            return bool(approved)
        except asyncio.TimeoutError:
            logger.warning("HITL timeout (%ds) — task iptal edildi: %s", HITL_TIMEOUT_S, task_id)
            return False

    async def _apply_patch(self, ws: WorkspaceInfo, patch: str) -> None:
        """Unified diff patch'i workspace'e uygular."""
        if not patch or not patch.strip():
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "patch", "-p1", "--forward", "--batch",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ws.path),
            )
            await proc.communicate(input=patch.encode())
        except Exception as exc:
            logger.warning("Patch uygulama hatası: %s", exc)

    async def _checkpoint(self, cp: AgentCheckpoint, ctx: SessionContext) -> None:
        await asyncio.gather(
            self._sm.save(cp),
            self._sessions.save(ctx),
            return_exceptions=True,
        )

    async def _route(self, config: RunConfig) -> RoutingDecision:
        router = get_complexity_router()
        return await router.route(config.goal)

    def _apply_tier(self, esc_result, current_decision: RoutingDecision) -> RoutingDecision:
        router = get_complexity_router()
        cfg = router.get_config(esc_result.new_tier)
        return RoutingDecision(
            tier=esc_result.new_tier,
            score=current_decision.score,
            model=cfg.model,
            base_url=cfg.base_url,
            token_budget=cfg.token_budget,
            signals=current_decision.signals,
        )

    async def _llm_complete(
        self, decision: RoutingDecision, prompt: str, max_tokens: int = 1000
    ) -> str:
        if not self._llm:
            return f"[LLM yok — prompt: {prompt[:80]}...]"
        try:
            return await self._llm.complete(
                model=decision.model,
                base_url=decision.base_url,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=min(max_tokens, decision.token_budget),
                temperature=0.1,
            )
        except Exception as exc:
            logger.warning("LLM complete hatası (%s): %s", decision.model, exc)
            return f"[LLM hatası: {exc}]"

    @staticmethod
    def _build_test_command(spec: Optional[TaskSpec], ws_path: str) -> list[str]:
        lang = spec.language_hint if spec else ""
        if lang == "go":
            return ["go", "test", "./..."]
        if lang in ("typescript", "javascript"):
            return ["npx", "jest", "--passWithNoTests", "--forceExit"]
        # Python varsayılan
        return ["python", "-m", "pytest", "--tb=short", "-q", "--no-header"]


def build_runner(
    postgres_store=None,
    redis_store=None,
    llm_client=None,
    mcp_handler=None,
    approval_queue: Optional[asyncio.Queue] = None,
) -> CodeActRunner:
    """Bağımlılıkları enjekte ederek CodeActRunner oluşturur."""
    sm     = AgentStateMachine(postgres_store, redis_store)
    store  = get_session_store(redis_store, postgres_store)
    specs  = get_spec_builder()
    ctx_asm= get_context_assembler(mcp_handler)
    esc    = EscalationManager()
    return CodeActRunner(
        state_machine=sm,
        session_store=store,
        spec_builder=specs,
        context_assembler=ctx_asm,
        escalation_manager=esc,
        llm_client=llm_client,
        mcp_handler=mcp_handler,
        approval_queue=approval_queue,
    )
