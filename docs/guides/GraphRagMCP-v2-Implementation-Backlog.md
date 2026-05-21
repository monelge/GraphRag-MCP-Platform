# GraphRagMCP v2 Implementation Backlog

## Faz 0 — Foundation Cleanup

### 0.1 Duplicate source tree kaldır
- Durum: `done`
- Hedef: `src/src/` kopya ağacını kaldır

### 0.2 MCP server decomposition
- Durum: `done`
- Çıktı: `src/mcp/server.py` + `src/mcp/tool_registry.py` + `src/mcp/schemas.py`
  `src/mcp_server.py` entry-point facade olarak korundu.

## Faz 1 — Knowledge Plane

### 1.1 Project registry
- Durum: `done`
- Çıktı:
  - `src/shared/project_registry.py`
  - Docker persistent `/app/data/project_registry.json`

### 1.2 Repository summary indexing
- Durum: `done`
- Çıktı:
  - `src/indexing/pipelines/project_intelligence.py`
  - `summarize_repository`
  - `search_repo_architecture`

### 1.3 Rich ontology extraction
- Durum: `done`
- Hedef:
  - `CALLS`, `IMPORTS`, `DEPENDS_ON` ilişkileri eklendi.
  - ASTChunker zenginleştirildi.

### 1.4 Global Context & Community Reports
- Durum: `done`
- Hedef:
  - Modüller arası etkileşim özeti.
  - Mimari diyagram desteği.

## Faz 2 — Knowledge Plane v2 (Impact & Provenance)

### 2.1 Provenance standardı
- Durum: `done`
- Çıktı: `project`, `commit_sha`, `branch`, `indexed_at` alanları eklendi.

### 2.2 Advanced Impact Analysis
- Durum: `done`
- Çıktı: `src/retrieval/search/impact_analysis.py` (3 seviyeli tracing + risk scoring).

### 2.3 Rich Ontology (Bases & Config)
- Durum: `done`
- Çıktı: `IMPLEMENTS` ve `USES_CONFIG` ilişkileri eklendi.

## Faz 3 — Memory Plane v2 (Typed & Temporal)

### 3.1 Typed decision memory
- Durum: `done`
- Çıktı: `store_decision_memory`, `search_decisions`.

### 3.2 Temporal memory (Temporal Facts)
- Durum: `done`
- Çıktı: `valid_from`, `valid_to`, `status` alanları ve `include_invalid` filtreleme desteği eklendi.

### 3.3 Memory compaction
- Durum: `done`
- Çıktı: `src/memory/services/memory_compaction.py` (LLM-based merging).

## Faz 4 — Agent Plane (Stateful Orchestration)

### 4.1 Task state machine
- Durum: `done`
- Çıktı: `src/agent/orchestrator/state_machine.py` (Handler-based FSM).

### 4.2 Checkpoint/resume
- Durum: `done`
- Çıktı: `src/agent/orchestrator/checkpoints.py` (CheckpointStore + task_checkpoints tablosu)
  `resume_task` MCP tool eklendi.
  Her node öncesi/sonrası otomatik checkpoint.

### 4.4 complete_task tool
- Durum: `done`
- Çıktı: `complete_task` MCP tool — herhangi bir durumdan DONE'a geçiş; task_steps de güncellenir.

### 4.3 Approval gates
- Durum: `done`
- Çıktı: `WAITING_APPROVAL` status ve `approve_task_step` tool'u.

## Faz 5 — Execution Plane (Secure Sandbox)

### 5.1 Sandbox runtime manager
- Durum: `done`
- Çıktı: `src/execution/runners/command_runner.py` ve `src/execution/sandbox/runtime_manager.py`.

### 5.2 Repo profile execution presets
- Durum: `done`
- Çıktı: `dotnet`, `python`, `node`, `flutter` profilleri ve `run_verification_plan` tool'u.

### 5.3 Agent pipeline nodes
- Durum: `done`
- Çıktı: `src/agent/nodes/` (planner, retriever, explainer, editor, verifier, reviewer, summarizer)
  BaseNode + NodeResult interface.
  PlannerNode LLM-tabanlı adım üretimi.
  EditorNode patch üretir (write-only: Docker mount read-only).
  VerifierNode build/test çalıştırır.
  ReviewerNode impact analysis + risk skoru.

## Faz 6 — Control Plane (Model Gateway & Evals)

### 6.1 Model gateway
- Durum: `done`
- Çıktı: `src/control/models/gateway.py` (Multi-provider tracking).

### 6.2 Eval harness
- Durum: `done`
- Çıktı: `src/control/evals/runner.py` (Hit@K, MRR metrics).

## 🏆 GraphRagMCP v2 — Tamamlandı

Tüm fazlar başarıyla uygulandı ve sistem v2 mimarisine taşındı.
- Multi-project registry
- Rich ontology (Inheritance & Config)
- Deep impact analysis
- Temporal & Compacted memory
- Stateful task orchestration
- Secure execution sandbox
- Control Plane observability


- Multi-project project registry
- Persistent docker data mount
- Repository intelligence sync
- Repository summary generation
- Architecture search
- Change impact analysis
- Project-scoped decision memory
- Vendoris ve WareLogisticcBYS smoke testleri
