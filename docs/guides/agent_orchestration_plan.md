# 🤖 GraphRAG-Augmented Coding Agent — Production Orkestrasyon Planı

> **Tarih:** 2026-06-07
> **Revizyon:** v4 — Son küçük iyileştirmeler entegre edildi
> **Durum:** Planlama TAMAMLANDI — Uygulama aşamasına geçilecek
> **Hedef:** Karmaşıklığa göre akıllı model seçen, GraphRAG bağlamıyla güçlendirilmiş, test-driven, production-grade coding agent sistemi

---

## 1. Araştırma Özeti — SOTA Bulgular

### 1.1 Hangi Yaklaşım En Yüksek Başarıyı Verir?

| Yaklaşım | SWE-bench Sonucu | Kaynak |
|----------|-----------------|--------|
| **Meta Context Engineering** — bağlamı optimizasyon problemi olarak ele almak | **%89.1** | Ye et al., 2026 |
| OpenHands CodeAct v3 + Claude Opus 4.6 | %68.4 | OpenHands, 2026 |
| Augment Code (200K token repo indexer) | %70.6 | Augment, 2026 |
| GraphRAG + Retrieval tabanlı bağlam | baseline üstü | SWE Context Bench, 2026 |

**Kritik bulgu:** En yüksek skor model büyüklüğünden değil **bağlam kalitesinden** geliyor. GraphRAG tabanlı bağlam enjeksiyonu bu boşluğu kapatır.

### 1.2 En İyi Kodlama Modelleri (2026)

| Tier | Model | Kullanım | Maliyet | HumanEval |
|------|-------|----------|---------|-----------|
| **Tier 3 — Reasoning** | `anthropic/claude-sonnet-4-6` | Mimari, refactor, hata analizi | Yüksek | %80+ |
| **Tier 3 — Reasoning** | `deepseek/deepseek-v3` (API) | Python/JS ağırlıklı | $0.35/M | %82.4 |
| **Tier 2 — Cheap** | `google/gemini-2.5-flash` | Orta karmaşıklık, hızlı | Düşük | %75+ |
| **Tier 2 — Cheap** | `mistralai/codestral-latest` | Küçük düzeltmeler | Düşük | %73+ |
| **Tier 1 — Local** | `qwen2.5-coder:32b` (Ollama) | Basit görevler, offline | Ücretsiz | %92.7* |
| **Tier 1 — Local** | `deepseek-coder-v2:16b` (Ollama) | Python/JS yerel | Ücretsiz | %81+ |

> \*Multi-file agent görevlerinde Tier 2'ye kıyasla zayıflayabilir — escalation mekanizması bunu karşılar.

### 1.3 TDAD: Test-Driven Agentic Development

1. **Önce test yaz** — fail-first doğrulama zorunlu
2. **Kod üret** — testin geçmesini hedefle
3. **Graph-tabanlı etki analizi** ile regression kontrolü
4. **CI/PR** kapısından geçmeden merge yok

Regresyonları %60+ azaltıyor (TDAD paper, 2026).

---

## 2. Mimari Tasarım Kararları

### 2.1 Sadeleştirilmiş Runtime Katmanları

5 Plane → 3 Runtime Katmanı. Görev başarısız olduğunda karar yetkisi **Control Layer / Escalation Manager**'a aittir.

| Runtime Katman | İçerdiği Plane'ler | Sorumluluk |
|---------------|-------------------|------------|
| **Knowledge Layer** | Knowledge Plane + Memory Plane | Bağlam, retrieval, bellek, patch memory |
| **Execution Layer** | Agent Plane + Execution Plane | CodeAct loop, sandbox, test runner |
| **Control Layer** | Control Plane + Orchestrator | Routing, escalation, audit, budget |

### 2.2 MCP Proxy Mimarisi — Seçenek A

MCP proxy ara katmanı teknik borç oluşturma riski taşıdığından tercih edilen mimari **Seçenek A**'dır:

```
FastAPI (port 8001)   →   /v1   OpenAI bridge
                      →   /agent  Coding Agent API

graph-mcp (port 8000)  →   Bağımsız servis (MCP + SSE)
```

`agent_api` içindeki CodeAct runner, graph-mcp'yi doğrudan iç ağdan çağırır (`http://graph-mcp:8000/sse`). Ara `/mcp` proxy rotası **eklenmez**.

### 2.3 Birleşik FastAPI — İki Rota

`openai-bridge` servisi docker-compose'dan kaldırılır, işlevi yeni `api` servisine taşınır:

```
/v1/*     →  OpenAI uyumlu bridge (mevcut openai_bridge.py işlevi)
/agent/*  →  Coding Agent REST API (yeni)
```

Auth, logging, telemetry tek noktada yönetilir.

### 2.4 Complexity Router — Sadeleştirilmiş İlk Sürüm

30+ sinyal yerine 4 ana sinyal. Telemetry verisi biriktikçe genişletilir:

```python
score = (
    0.40 * file_count_signal +       # multi-file referans
    0.30 * stacktrace_signal +        # stack trace / exception var mı
    0.20 * architecture_keywords +    # refactor, mimari, tasarla...
    0.10 * token_count_signal         # sorgu uzunluğu
)
```

```
[0.00 ── 0.30)  →  TIER_LOCAL    Ollama — ücretsiz, offline
[0.30 ── 0.70)  →  TIER_CHEAP    OpenRouter ucuz model
[0.70 ── 1.00]  →  TIER_REASON   Güçlü akıl yürütme
```

**Donanım duyarlılığı:** Ollama yanıt vermiyorsa veya p95 latency > 5 sn ise Tier 1 → Tier 2 otomatik geçiş.

### 2.5 Aşamalı Reflection Döngüsü

| Aşama | Eylem | Deneme Hakkı |
|-------|-------|-------------|
| 1 | Aynı model, aynı context | 2 |
| 2 | Tier yükselt + context genişlet | 2 |
| 3 | 32K context, TIER_REASON | 1 |
| 4 | HUMAN_REVIEW | — |

### 2.6 Background Worker Teknolojisi — ARQ

Redis zaten sistemde mevcut olduğundan ek broker gerektirmeyen **ARQ** seçilmektedir.

- Hafif, async, FastAPI uyumlu
- Celery / Dramatiq / RQ'ya kıyasla sıfır ek bağımlılık

### 2.7 Verify Sandbox Stratejisi — subprocess + worktree

Docker-in-Docker (tam konteyner) yerine:

```
git worktree  →  subprocess  →  pytest/ruff/mypy
```

Tam konteyner açmanın riskleri: yüksek açılış süresi, macOS uyumsuzlukları, CI karmaşıklığı. Gerekirse `firejail` veya `uv sandbox` eklenir.

### 2.8 Feature Creep Kararı

**Patch Memory** ve **Semantic Diff** mimariye dahil edilmektedir ancak **v1 TDAD döngüsü stabil olduktan sonra** devreye alınacaktır. İlk çalışan sistemde bu katmanlar devre dışıdır (`PATCH_MEMORY_ENABLED=false`, `SEMANTIC_DIFF_ENABLED=false`).

---

## 3. Hedef Mimari

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     AI İstemcisi / IDE / CLI                           │
└─────────────────────────┬────────────────────────���──────────────────────┘
                          │ REST + SSE (port 8001)
                          ▼
         ┌─────────────────────────────────────────────┐
         │        Unified FastAPI (port 8001)          │
         │   /v1     OpenAI bridge                     │
         │   /agent  Coding Agent API                  │
         └──────────────────┬──────────────────────────┘
                            │
         ┌──────────────────▼────────────────────────���─┐
         │             CONTROL LAYER                   │
         │                                             │
         │  Complexity Router (4 sinyal)               │
         │  + Ollama yük / latency kontrolü            │
         │                                             │
         │  ┌────────────┐ ┌─────────────┐ ┌────────┐ │
         │  │ TIER_LOCAL │ │ TIER_CHEAP  │ │TIER_R  │ │
         │  │ qwen2.5:32b│ │gemini-flash │ │claude  │ │
         │  │ (Ollama)   │ │codestral    │ │deepseek│ │
         │  └────────────┘ └─────────────┘ └────────┘ │
         │                                             │
         │  Escalation Manager — 4 aşamalı            │
         │  State Machine — PostgreSQL checkpoint      │
         │  HITL Timeout — TTL(30dk) + SUSPENDED       │
         └──────────────────┬──────────────────────────┘
                            │
         ┌──────────────────▼──────────────────────────┐
         │             KNOWLEDGE LAYER                 │
         │                                             │
         │  GraphRAG Context Engine:                   │
         │    search_code(spec)                        │
         │    analyze_change_impact(files)             │
         │      hibrit: 0.4 call + 0.3 dep             │
         │              0.2 pagerank + 0.1 git         │
         │    recall_memory(patterns)                  │
         │    recall_patch(problem) [v2 sonrası]       │
         │    search_agent_docs(rules)                 │
         │                                             │
         │  Token Bütçesi:                             │
         │    LOCAL 8K / CHEAP 16K / REASON 32K        │
         └──────────────────┬──────────────────────────┘
                            │
         ┌──────────────────▼──────────────────────────┐
         │             EXECUTION LAYER                 │
         │                                             │
         │  Repository Snapshot → snapshot_{task_id}   │
         │  Ephemeral Workspace → git worktree         │
         │  Session Context → Redis (TTL=1h)           │
         │    fallback: PostgreSQL rehydration         │
         │  Worktree GC → lifespan + periyodik temizlik│
         │                                             │
         │  TDAD CodeAct Loop:                         │
         │  ①SPEC→②TEST(fail-first)→③CONTEXT          │
         │  →④EDIT→⑤VERIFY(subprocess)                │
         │  →⑥IMPACT→⑦REFLECT→⑧COMMIT                │
         │                                             │
         │  Semantic Diff [v2 sonrası]                 │
         └─────────────────────���───────────────────────┘
                            │
         ┌──────────────────▼─────────���────────────────┐
         │          graph-mcp (port 8000)              │
         │          Bağımsız servis — SSE              │
         └─────────────────────────────────────────────┘
```

---

## 4. TDAD CodeAct Loop — Adım Adım

### Adım ① SPEC — Görev Sözleşmesi

```
Girdi: kullanıcı hedefi (string)

İşlem:
  search_agent_docs(goal)    → AGENTS.md kuralları ve kısıtlar
  search_decisions(goal)     → geçmiş mimari kararlar
  recall_patch(goal)         → benzer başarılı patch örnekleri [PATCH_MEMORY_ENABLED ise]

Çıktı: TaskSpec {
  hedef, kısıtlar, kabul_kriterleri,
  etkilenen_dosyalar, referans_patchler
}

→ snapshot_{task_id} alınır
→ git worktree add /tmp/task_{id} açılır
→ Redis'te session context başlatılır
```

### Adım ② TEST — Fail-First Doğrulama

```
Mevcut testler varsa:
  → Baseline çalıştır, başarısız olanları kaydet

Test yoksa:
  → test_suggestion(target_file) ile öneri al
  → Agent test dosyasını yazar
  → Patch UYGULANMADAN test çalıştırılır
  → Test FAIL etmeli — PASS ederse test hatalı yazılmış → hata fırlat

[Fail-first kontrolü halüsinasyonu keser]
```

### Adım ③ CONTEXT — GraphRAG Bağlam Enjeksiyonu

```
search_code(spec.hedef, k=10)
analyze_change_impact(spec.etkilenen_dosyalar)
  → hibrit skor: 0.4 call + 0.3 dep + 0.2 pagerank + 0.1 git
recall_memory(spec.hedef)
recall_patch(spec.problem_type)    [PATCH_MEMORY_ENABLED ise]
search_agent_docs(spec.kısıtlar)

Token bütçesi: LOCAL=8K / CHEAP=16K / REASON=32K
Sıralama: hibrit impact × CrossEncoder
```

### Adım ④ EDIT — Kod Üretimi

```
Prompt:
  [SYSTEM]          AGENTS.md kuralları
  [PATCH_EXAMPLES]  recall_patch sonuçları [PATCH_MEMORY_ENABLED ise]
  [CONTEXT]         GraphRAG bağlamı
  [SPEC]            TaskSpec
  [TESTS]           Başarısız testler
  [REQUEST]         "Bu testleri geçirecek kodu yaz"

Çıktı:
  - unified diff → ephemeral workspace'e uygulanır
  - semantic diff meta { change_type, risk, affected_classes,
      public_api_changed, db_changed, breaking_change }
    [SEMANTIC_DIFF_ENABLED ise]

Session context güncellenir: reflection_count, selected_model
```

### Adım ⑤ VERIFY — subprocess + worktree

```
Ephemeral workspace üzerinde subprocess ile:
  pytest          → geçti/kaldı
  ruff / flake8   → lint
  mypy            → tip hataları
  build           → derleme (varsa)

Tüm testler geçti + lint temiz → ⑥ IMPACT
Hata var → ⑦ REFLECT
```

### Adım ⑥ IMPACT — Değişim Etki Analizi

```
analyze_change_impact(değişen_dosyalar)
  → hibrit skor
  → risk seviyesi: LOW / MEDIUM / HIGH

Risk HIGH ise:
  → SSE event: impact_warning
  → HUMAN_APPROVAL zorunlu hale gelir
```

### Adım ⑦ REFLECT — Aşamalı Kurtarma

```
Aşama 1 (reflection_count < 2):
  Aynı tier, aynı context → ④'e dön

Aşama 2 (reflection_count == 2):
  Tier yükselt + context genişlet → ③'ten başla

Aşama 3 (reflection_count == 4):
  TIER_REASON + 32K → ③'ten başla

Aşama 4 (reflection_count > 5):
  → SUSPENDED → HUMAN_REVIEW

Kayıt:
  store_memory("Bu pattern [tier]'da başarısız oldu: [özet]")
  session context: last_failures
```

### Adım ⑧ COMMIT — Güvenli Teslim

```
HUMAN_APPROVAL=true veya risk=HIGH ise:
  → patch + semantic diff SSE ile göster
  → POST /agent/approve/{id} bekle
  → TTL (30 dk) içinde onay gelmezse → SUSPENDED

SUSPENDED sonrası kullanıcı dönerse:
  → state_machine: PostgreSQL checkpoint'ten full rehydration
  → Redis boş olsa bile devam edilebilir

Onay sonrası:
  ephemeral workspace → ana repoya merge
  store_decision_memory({ hedef, çözüm, tier, tokenlar })
  store_patch_memory({ problem, dosyalar, patch_hash, testler,
    repo_fingerprint, confidence=1.0, usage_count=0 })  [PATCH_MEMORY_ENABLED ise]
  Session context temizle (Redis)
  Görev: COMPLETED
```

---

## 5. Redis TTL / PostgreSQL Senkronizasyonu

**Risk:** Session TTL=1h, HITL timeout=30dk. Kullanıcı 65. dakikada dönerse Redis silinmiş olur.

**Çözüm:** `state_machine.py` Redis'te context bulamazsa PostgreSQL checkpoint'inden **full rehydration** uygular. Checkpoint şeması değiştiğinde geriye dönük uyumluluk için `version` alanı zorunludur:

```python
@dataclass
class Checkpoint:
    version: int = 1          # şema değişikliklerinde artırılır
    task_id: str
    step: str
    selected_model: str
    reflection_count: int
    opened_files: list[str]
    current_branch: str
    last_failures: list[str]

async def get_session(task_id: str) -> SessionContext:
    ctx = await redis.get(f"session:{task_id}")
    if ctx:
        return SessionContext.parse(ctx)
    # Redis boş → PostgreSQL'den yeniden oluştur
    checkpoint = await postgres.get_checkpoint(task_id)
    ctx = SessionContext.from_checkpoint(checkpoint)  # version'a göre migrate
    await redis.setex(f"session:{task_id}", 3600, ctx.json())
    return ctx
```

Redis sadece hızlandırıcı (cache), **asıl kaynak PostgreSQL'dir**.

---

## 6. Git Worktree Temizlik Stratejisi

**Risk:** Sistem crash'te veya uzun HITL askısında `/tmp` dolar.

**Çözüm:** `workspace_manager.py` içinde iki tetikleyici:

```python
# 1. FastAPI lifespan başlangıcında
@asynccontextmanager
async def lifespan(app):
    await workspace_manager.prune_stale_workspaces()
    yield

# 2. ARQ periyodik görevi (her 1 saatte bir)
async def periodic_gc(ctx):
    await workspace_manager.prune_stale_workspaces()

async def prune_stale_workspaces():
    # PostgreSQL'de COMPLETED/FAILED/SUSPENDED/CANCELLED olan task_id'leri al
    # WORKSPACE_BASE_PATH/task_{id} dizinleri varsa: git worktree remove --force
    # SNAPSHOT_RETENTION_HOURS aşılmış snapshot'ları sil
    # Proje başına MAX_SNAPSHOTS_PER_PROJECT üstü olanları eskiden yeniye sil
```

---

## 7. Patch Memory Yapısı (v2 sonrası)

```python
class PatchMemoryEntry:
    problem_description: str
    problem_type: str          # performance | security | refactor | bug | ...
    files_changed: list[str]
    patch_hash: str
    test_files: list[str]
    tier_used: str
    reflection_count: int
    successful: bool

    # Semantic search için
    embedding_vector: list[float]   # Qdrant'a kaydedilir

    # Repository bağlamı
    repo_fingerprint: RepoFingerprint  # commit_hash, branch, dep_hash, lockfile_hash

    # Patch çürüme kontrolü
    confidence_score: float    # başlangıç: 1.0
    usage_count: int           # kaç kez recall edildi
    success_rate: float        # recall sonrası başarı oranı
    last_used_at: datetime
    created_at: datetime
```

**Semantic search:** `recall_patch("slow query")` → "N+1 query", "lazy loading", "performance issue" benzer embedding'lere ulaşır.

**Çürüme:** `success_rate < 0.3` veya `last_used_at > 90 gün` olan entry'ler pasife alınır.

---

## 8. Semantic Diff Yapısı (v2 sonrası)

```json
{
  "change_type": "refactor",
  "risk": "medium",
  "affected_classes": ["UserService"],
  "public_api_changed": true,
  "database_changed": false,
  "migration_required": false,
  "breaking_change": false
}
```

Kullanım alanları: release notes, audit, rollback analizi, HITL approval kararı.

---

## 9. Retrieval Evaluation Dataset

Minimum 10–15 örnek, her kategori temsil edilmeli:

```
evals/retrieval/
├── performance/
│   ├── case_n_plus_one.json
│   ├── case_cache_issue.json
│   └── case_async_deadlock.json
├── security/
│   └── case_auth_bug.json
├── refactor/
│   ├── case_refactor_service.json
│   └── case_dependency_problem.json
├── data/
│   ├── case_migration_bug.json
│   └── case_schema_change.json
└── integration/
    ├── case_service_communication.json
    └── case_controller_bug.json
```

Örnek vaka formatı:
```json
{
  "query": "N+1 query problemi nerede?",
  "expected_files": ["UserRepository.cs", "OrderRepository.cs"],
  "expected_context_keywords": ["Include", "ToList", "lazy loading"]
}
```

`run_retrieval_eval` bu veri setiyle kalite skoru üretir.

---

## 10. Yeni Dosya Yapısı

```
src/
├── api/                                 # Birleşik FastAPI
│   ├── app.py                           # lifespan + middleware
│   ├── routers/
│   │   ├── agent_router.py              # /agent/*
│   │   ├── openai_router.py             # /v1/* (openai_bridge.py → buraya taşınır)
│   │   └── health_router.py             # /health, /ready, /metrics
│   ├── models/
│   │   └── api_models.py
│   ├── streaming/
│   │   └── sse_handler.py
│   └── workers/
│       └── task_worker.py               # ARQ worker
│
├── agent/
│   ├── codeact_runner.py                # TDAD CodeAct orkestratör
│   ├── state_machine.py                 # PostgreSQL checkpoint + Redis rehydration
│   ├── spec_builder.py                  # Görev spec oluşturucu
│   ├── context_assembler.py             # GraphRAG bağlam optimizörü
│   ├── workspace_manager.py             # git worktree + snapshot + GC
│   ├── session_context.py               # Redis TTL + PostgreSQL fallback
│   ├── semantic_diff.py                 # [SEMANTIC_DIFF_ENABLED] v2 sonrası
│   └── (mevcut nodes/, orchestrator/ korunur)
│
├── memory/
│   └── stores/
│       ├── patch_memory.py              # [PATCH_MEMORY_ENABLED] v2 sonrası
│       └── (mevcut stores korunur)
│
├── control/
│   └── models/
│       ├── complexity_router.py         # 4 sinyal + HW kontrolü
│       ├── escalation_manager.py        # 4 aşamalı tier yükseltme
│       └── (model_router.py korunur)
│
└── retrieval/
    └── search/
        └── impact_analysis.py           # Hibrit impact skoru güncellenir
```

---

## 11. API Endpoint Referansı

### `POST /agent/run`
```json
{
  "goal": "UserRepository sınıfındaki N+1 query sorununu düzelt",
  "project_path": "/projects/myapp",
  "collection": "myapp",
  "options": {
    "human_approval": false,
    "force_tier": null,
    "max_reflections": 5,
    "test_first": true,
    "hitl_timeout_minutes": 30
  }
}
```
**Yanıt:**
```json
{
  "task_id": "tsk_abc123",
  "status": "running",
  "estimated_tier": "TIER_CHEAP",
  "complexity_score": 0.52,
  "snapshot_id": "snapshot_tsk_abc123"
}
```

### `GET /agent/stream/{task_id}` — SSE Events
```
event: workspace_ready
data: {"path": "/tmp/task_abc123", "snapshot": "snapshot_tsk_abc123"}

event: model_selected
data: {"tier": "TIER_CHEAP", "model": "google/gemini-2.5-flash", "score": 0.52}

event: test_fail_confirmed
data: {"message": "Test FAIL (beklenen) — TDD geçerli"}

event: step_done
data: {"step": "EDIT", "tokens_used": 2840, "files_changed": ["src/repo.py"]}

event: verify_result
data: {"passed": false, "tests_failed": 2, "reflection_phase": 1}

event: escalation
data: {"phase": 2, "from": "TIER_CHEAP", "to": "TIER_REASON", "reason": "context genişletiliyor"}

event: impact_warning
data: {"risk": "HIGH", "affected": ["OrderService"], "message": "Yüksek etki — onay gerekiyor"}

event: hitl_timeout
data: {"message": "30 dk içinde onay gelmedi", "status": "SUSPENDED"}

event: complete
data: {"status": "COMPLETED", "tier_used": "TIER_REASON",
       "total_tokens": 8420, "total_cost_usd": 0.003}
```

---

## 12. Docker Konfigürasyonu

### Kaldırılan Servis
`openai-bridge` — işlevi `api` servisine taşınır.

### Eklenen Servis

```yaml
api:
  build: .
  command: uvicorn src.api.app:app --host 0.0.0.0 --port 8001 --workers 2
  ports:
    - "8001:8001"
  environment:
    # Routing
    - COMPLEXITY_ROUTER_ENABLED=true
    - COMPLEXITY_LOCAL_THRESHOLD=0.30
    - COMPLEXITY_REASON_THRESHOLD=0.70
    # Model Tiers
    - TIER_LOCAL_MODEL=${TIER_LOCAL_MODEL:-qwen2.5-coder:32b}
    - TIER_LOCAL_BASE_URL=${TIER_LOCAL_BASE_URL:-http://host.docker.internal:11434/v1}
    - TIER_CHEAP_MODEL=${TIER_CHEAP_MODEL:-google/gemini-2.5-flash}
    - TIER_REASON_MODEL=${TIER_REASON_MODEL:-anthropic/claude-sonnet-4-6}
    # CodeAct
    - CODEACT_MAX_REFLECTIONS=5
    - CODEACT_HUMAN_APPROVAL=false
    - CODEACT_HITL_TIMEOUT_MINUTES=30
    - CODEACT_TEST_FIRST=true
    # Context
    - CONTEXT_BUDGET_LOCAL=8000
    - CONTEXT_BUDGET_CHEAP=16000
    - CONTEXT_BUDGET_REASON=32000
    # Feature Flags
    - PATCH_MEMORY_ENABLED=false
    - SEMANTIC_DIFF_ENABLED=false
    # Internal
    - MCP_SERVER_URL=http://graph-mcp:8000/sse
  depends_on:
    - graph-mcp
    - postgres
    - redis
  volumes:
    - ${HOST_PROJECTS_ROOT}:${CONTAINER_PROJECTS_ROOT}
    - /tmp:/tmp
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
    interval: 30s
    timeout: 10s
    retries: 3
```

---

## 13. Ortam Değişkenleri

```env
# ─── Unified API ──────────────────────────��───────
API_PORT=8001

# ─── Complexity Router ────────────────────────────
COMPLEXITY_ROUTER_ENABLED=true
COMPLEXITY_LOCAL_THRESHOLD=0.30
COMPLEXITY_REASON_THRESHOLD=0.70

# ─── Model Tier Tanımları ─────────────────────────
TIER_LOCAL_ENABLED=true
TIER_LOCAL_MODEL=qwen2.5-coder:32b
TIER_LOCAL_BASE_URL=http://host.docker.internal:11434/v1
TIER_LOCAL_FALLBACK_MODEL=deepseek-coder-v2:16b

TIER_CHEAP_MODEL=google/gemini-2.5-flash
TIER_CHEAP_FALLBACK=mistralai/codestral-latest

TIER_REASON_MODEL=anthropic/claude-sonnet-4-6
TIER_REASON_FALLBACK=deepseek/deepseek-v3

# ─── TDAD CodeAct Loop ──────────────────────────���─
CODEACT_MAX_REFLECTIONS=5
CODEACT_HUMAN_APPROVAL=false
CODEACT_HITL_TIMEOUT_MINUTES=30
CODEACT_TEST_FIRST=true
CODEACT_SANDBOX_TIMEOUT=120

# ─── Token Bütçesi ────────────────────────────────
CONTEXT_BUDGET_LOCAL=8000
CONTEXT_BUDGET_CHEAP=16000
CONTEXT_BUDGET_REASON=32000

# ─── Workspace ────────────────────────────────────
WORKSPACE_BASE_PATH=/var/lib/graphrag/workspaces
SNAPSHOT_RETENTION_HOURS=24
MAX_SNAPSHOTS_PER_PROJECT=20
SESSION_CONTEXT_TTL_SECONDS=3600

# ─── Feature Flags (v2 sonrası açılır) ───────────
PATCH_MEMORY_ENABLED=false
SEMANTIC_DIFF_ENABLED=false
```

---

## 14. Task Durum Makinesi

Görev yaşam döngüsü:

```
PENDING → RUNNING → COMPLETED
                  → FAILED       (sistem hatası / max reflection aşıldı)
                  → SUSPENDED    (HITL timeout — kullanıcı dönebilir)
                  → CANCELLED    (kullanıcı iptal etti / yeni görev geçersiz kıldı)
```

`CANCELLED` durumu `FAILED`'dan ayrı tutulur: kullanıcının bilinçli iptal eylemi hata istatistiklerini kirletmemeli.

---

## 15. Uygulama Sırası — Sprint Planı

> Planlama tamamlandı. Yeni özellik eklenmeyecek. Uygulama başlıyor.

| Öncelik | Bileşen | Dosya | Süre |
|---------|---------|-------|------|
| **1** | Complexity Router (4 sinyal + HW) | `src/control/models/complexity_router.py` | ~1.5 saat |
| **2** | Escalation Manager (4 aşamalı) | `src/control/models/escalation_manager.py` | ~1 saat |
| **3** | Workspace Manager (worktree + snapshot + GC) | `src/agent/workspace_manager.py` | ~2 saat |
| **4** | State Machine (PG checkpoint + Redis rehydration) | `src/agent/state_machine.py` | ~2 saat |
| **5** | Session Context (Redis TTL + PG fallback) | `src/agent/session_context.py` | ~1 saat |
| **6** | Spec Builder | `src/agent/spec_builder.py` | ~1.5 saat |
| **7** | Context Assembler (hibrit impact + budget) | `src/agent/context_assembler.py` | ~2 saat |
| **8** | TDAD CodeAct Runner | `src/agent/codeact_runner.py` | ~4 saat |
| **9** | ARQ Task Worker | `src/api/workers/task_worker.py` | ~1.5 saat |
| **10** | Unified FastAPI (agent + openai routers) | `src/api/` | ~3 saat |
| **11** | SSE Streaming + HITL timeout | `src/api/streaming/` | ~1.5 saat |
| **12** | Hibrit impact skoru güncellemesi | `src/retrieval/search/impact_analysis.py` | ~1 saat |
| **13** | Retrieval eval dataset (10+ vaka) | `evals/retrieval/` | ~2 saat |
| **14** | Docker + .env güncelleme | `docker-compose.yml` | ~1 saat |
| — | **[Sprint 3]** Patch Memory | `src/memory/stores/patch_memory.py` | ~2 saat |
| — | **[Sprint 4]** Semantic Diff | `src/agent/semantic_diff.py` | ~1.5 saat |

**Sprint 1 (v1 core):** ~24 saat
**Sprint 3–4 ekleri:** ~3.5 saat

### Sprint Yol Haritası

| Sprint | Hedef | Çıktı |
|--------|-------|-------|
| **Sprint 1** | TDAD + Router + Worktree + State Machine | Çalışan temel sistem |
| **Sprint 2** | Gerçek kullanım verisi topla | Telemetry, token maliyeti, başarısız görev analizi |
| **Sprint 3** | `PATCH_MEMORY_ENABLED=true` | Geçmiş patch'lerden öğrenme aktif |
| **Sprint 4** | `SEMANTIC_DIFF_ENABLED=true` | Audit, release notes, approval kararları |
| **Sprint 5** | Telemetry verisine göre Learning Plane kararı | Gerekirse router otomatik kalibrasyon |

---

## 16. Sistem Doğrulama — Test Script Planı

Tüm bileşenler tamamlandıktan sonra tek komutla çalışacak toplu doğrulama scripti:

```
scripts/launchers/verify_agent_api_v1.sh
```

Her adım bağımsız olarak test edilir, hata durumunda script durur ve raporlar.

### 16.1 Script Yapısı

```bash
#!/usr/bin/env bash
# scripts/launchers/verify_agent_api_v1.sh
# Tüm Agent API bileşenlerini sırayla doğrular.

set -euo pipefail

BASE_URL="http://localhost:8001"
MCP_URL="http://localhost:8000"
PASS=0; FAIL=0

ok()   { echo "  ✅ $1"; ((PASS++)); }
fail() { echo "  ❌ $1"; ((FAIL++)); }
section() { echo; echo "━━━ $1 ━━━"; }

# ────────────────────────────────────────
section "1. Servis Sağlık Kontrolü"
# ────────────────────────────────────────
# 1.1 graph-mcp ayakta mı?
# 1.2 api servisi (port 8001) ayakta mı?
# 1.3 PostgreSQL bağlantısı
# 1.4 Redis bağlantısı
# 1.5 Ollama erişilebilir mi? (TIER_LOCAL_ENABLED=true ise)

# ────────────────────────────────────────
section "2. Complexity Router"
# ────────────────────────────────────────
# 2.1 Kısa sorgu → TIER_LOCAL (score < 0.30)
# 2.2 Mimari anahtar kelime → TIER_REASON (score ≥ 0.70)
# 2.3 Stack trace içeren sorgu → TIER_CHEAP veya üstü
# 2.4 Multi-file referans → skor yükselmeli
# 2.5 Ollama meşgul simülasyonu → TIER_LOCAL → TIER_CHEAP geçişi

# ────────────────────────────────────────
section "3. Workspace Manager"
# ────────────────────────────────────────
# 3.1 Ephemeral workspace oluşturma (git worktree add)
# 3.2 Snapshot alınması
# 3.3 Worktree temizleme (git worktree remove)
# 3.4 Stale workspace GC — eski task siliniyor mu?
# 3.5 MAX_SNAPSHOTS_PER_PROJECT limiti çalışıyor mu?

# ────────────────────────────────────────
section "4. State Machine & Session Context"
# ────────────────────────────────────────
# 4.1 Yeni checkpoint PostgreSQL'e yazılıyor mu?
# 4.2 Redis'te session context oluşuyor mu?
# 4.3 Redis TTL sona erince PostgreSQL'den rehydration
# 4.4 Checkpoint version alanı doğru kaydediliyor mu?
# 4.5 SUSPENDED → devam etme (full rehydration testi)

# ────────────────────────────────────────
section "5. Escalation Manager"
# ────────────────────────────────────────
# 5.1 Aşama 1: aynı tier, 2 deneme hakkı
# 5.2 Aşama 2: tier yükseltme tetikleniyor mu?
# 5.3 Aşama 3: TIER_REASON'a zorla geçiş
# 5.4 Aşama 4: HUMAN_REVIEW durumuna geçiş
# 5.5 Başarılı görev sonrası store_memory çağrılıyor mu?

# ────────────────────────────────────────
section "6. Spec Builder"
# ────────────────────────────────────────
# 6.1 search_agent_docs çağrısı yapılıyor mu?
# 6.2 search_decisions çağrısı yapılıyor mu?
# 6.3 TaskSpec objesi doğru alanlarla üretiliyor mu?
# 6.4 PATCH_MEMORY_ENABLED=true ise recall_patch çağrısı

# ────────────────────────────────────────
section "7. Context Assembler"
# ────────────────────────────────────────
# 7.1 search_code çağrısı yapılıyor mu?
# 7.2 analyze_change_impact hibrit skor üretiyor mu?
#     (0.4 call + 0.3 dep + 0.2 pagerank + 0.1 git)
# 7.3 Token bütçesi tier'a göre doğru uygulanıyor mu?
#     TIER_LOCAL=8K, TIER_CHEAP=16K, TIER_REASON=32K
# 7.4 CrossEncoder reranking çalışıyor mu?

# ────────────────────────────────────────
section "8. TDAD Fail-First Test Kontrolü"
# ────────────────────────────────────────
# 8.1 Test yoksa test_suggestion çağrısı yapılıyor mu?
# 8.2 Patch uygulanmadan test çalıştırılıyor mu?
# 8.3 Test PASS ederse hata fırlatılıyor mu? (halüsinasyon koruması)
# 8.4 Test FAIL ederse döngü devam ediyor mu?

# ────────────────────────────────────────
section "9. TDAD Verify — subprocess + worktree"
# ────────────────────────────────────────
# 9.1 pytest ephemeral workspace üzerinde çalışıyor mu?
# 9.2 Lint (ruff/flake8) çalışıyor mu?
# 9.3 mypy tip kontrolü çalışıyor mu?
# 9.4 Tüm testler geçince COMMIT adımına geçiyor mu?
# 9.5 Hata varsa REFLECT'e yönlendiriyor mu?

# ────────────────────────────────────────
section "10. Impact Analizi"
# ────────────────────────────────────────
# 10.1 analyze_change_impact hibrit skor üretiyor mu?
# 10.2 Risk=HIGH → HUMAN_APPROVAL zorunlu hale geliyor mu?
# 10.3 SSE impact_warning eventi yayınlanıyor mu?

# ────────────────────────────────────────
section "11. Agent API Endpoint'leri"
# ────────────────────────────────────────
# 11.1 POST /agent/run → task_id + complexity_score dönüyor mu?
# 11.2 GET  /agent/status/{id} → tüm alanlar dolu mu?
# 11.3 GET  /agent/stream/{id} → SSE bağlantısı açılıyor mu?
# 11.4 POST /agent/approve/{id} → onay işleniyor mu?
# 11.5 DELETE /agent/cancel/{id} → durum CANCELLED oluyor mu?
# 11.6 GET  /agent/history → geçmiş görevler listeleniyor mu?

# ────────────────────────────────────────
section "12. SSE Event Akışı"
# ────────────────────────────────────────
# 12.1 workspace_ready eventi geliyor mu?
# 12.2 model_selected eventi tier bilgisi içeriyor mu?
# 12.3 test_fail_confirmed eventi geliyor mu?
# 12.4 escalation eventi tier geçişini bildiriyor mu?
# 12.5 complete eventi total_tokens + cost içeriyor mu?

# ────────────────────────────────────────
section "13. HITL Timeout"
# ────────────────────────────────────────
# 13.1 Onay bekleyen görev SUSPENDED durumuna geçiyor mu?
# 13.2 TTL sonrası hitl_timeout SSE eventi yayınlanıyor mu?
# 13.3 SUSPENDED görev sonradan devam ettirilebiliyor mu?

# ────────────────────────────────────────
section "14. Task Durum Makinesi"
# ────────────────────────────────────────
# 14.1 Başarılı görev → COMPLETED
# 14.2 Max reflection aşımı → FAILED
# 14.3 HITL timeout → SUSPENDED
# 14.4 DELETE /agent/cancel → CANCELLED (FAILED değil)
# 14.5 CANCELLED görev hata istatistiklerini etkiliyor mu?

# ────────────────────────────────────────
section "15. OpenAI Bridge (/v1)"
# ────────────────────────────────────────
# 15.1 POST /v1/chat/completions → yanıt dönüyor mu?
# 15.2 Model adı "graph-mcp" kabul ediliyor mu?
# 15.3 Streaming mod çalışıyor mu?

# ────────────────────────────────────────
section "16. Retrieval Eval"
# ────────────────────────────────────────
# 16.1 run_retrieval_eval evals/retrieval/ vaka setini buluyor mu?
# 16.2 Her vaka için expected_files precision skoru hesaplanıyor mu?
# 16.3 Ortalama skor eşiği geçiyor mu? (hedef: ≥ 0.70)

# ────────────────────────────────────────
section "17. Uçtan Uca Senaryo (E2E)"
# ────────────────────────────────────────
# 17.1 Tam bir görev döngüsü:
#   POST /agent/run
#   → SSE stream takip et
#   → COMPLETED durumu bekleniyor
#   → PostgreSQL'de kayıt var mı?
#   → Workspace temizlendi mi?

# ────────────────────────────────────────
echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  SONUÇ: ✅ $PASS geçti  ❌ $FAIL kaldı"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
[ $FAIL -eq 0 ] && exit 0 || exit 1
```

### 16.2 Script Dosya Konumları

```
scripts/
└── launchers/
    └── verify_agent_api_v1.sh     # Ana toplu test scripti
```

İleride bileşenler büyüdükçe her bölüm ayrı script'e taşınabilir:

```
scripts/launchers/
├── verify_agent_api_v1.sh         # Toplu — tümünü çalıştırır
├── verify_complexity_router.sh    # Sadece router testi
├── verify_workspace.sh            # Sadece worktree + snapshot
├── verify_state_machine.sh        # Sadece PG + Redis
├── verify_tdad_loop.sh            # Sadece CodeAct döngüsü
└── verify_api_endpoints.sh        # Sadece HTTP endpoint'leri
```

### 16.3 Çalıştırma

```bash
chmod +x scripts/launchers/verify_agent_api_v1.sh
bash scripts/launchers/verify_agent_api_v1.sh
```

Sistemin çalışıyor olması gerekli:
```bash
docker compose up -d   # önce servisleri başlat
```

---

## 17. Başarı Kriterleri

| Kriter | Hedef |
|--------|-------|
| Basit görevlerde Tier 1 kullanım oranı | ≥ %60 |
| Tier 3'e escalation oranı | ≤ %25 |
| Verify'da ilk denemede başarı | ≥ %70 |
| Konteyner crash sonrası görev kurtarma | %100 |
| Patch Memory hit oranı (v2, 3. haftadan itibaren) | ≥ %20 |
| Ortalama görev süresi (Tier 1) | < 45 sn |
| Token maliyeti (Tier 2 ortalama görev) | < $0.01 |

---

## 17. V3 Yol Haritası — Learning Plane

v1 + v2 stabil olduktan sonra telemetry ile Learning Plane eklenebilir:

| Veri Kaynağı | Öğrenme Amacı |
|-------------|---------------|
| Başarılı patch'ler | Patch Memory büyütme |
| Başarısız patch'ler | Router kalibrasyonu |
| Routing sonuçları | Tier eşiklerini otomatik ayarlama |
| Retrieval eval skorları | Context kalitesini artırma |

---

## 18. Kaynaklar

- [Meta Context Engineering — %89.1 SWE-bench](https://arxiv.org/html/2512.18470v5)
- [TDAD: Test-Driven Agentic Development](https://arxiv.org/html/2603.17973v1)
- [OpenHands vs SWE-Agent 2026](https://www.codesota.com/agentic/openhands-vs-swe-agent)
- [AGENTS.md Etkisi — ETH Zurich](https://arxiv.org/html/2601.20404v2)
- [RouteLLM — LMSYS/ICLR 2025](https://www.lmsys.org/blog/2024-07-01-routellm/)
- [En İyi Yerel Kodlama LLM 2026](https://localaimaster.com/models/best-local-ai-coding-models)
- [DeepSeek vs Qwen Local Coding 2026](https://www.promptquorum.com/power-local-llm/deepseek-vs-qwen-coding-local-2026)
- [LiteLLM Routing & Fallback](https://docs.litellm.ai/docs/routing-load-balancing)
- [Dynamic Model Routing Survey](https://arxiv.org/html/2603.04445v2)
- [Agentic Coding Production Gap](https://tianpan.co/blog/2026-04-09-agentic-coding-production-swebench-gap)

---

## 19. İlgili Belgeler

- [Production İyileştirme Raporu](agent_orchestration_production_review.md)
- [Mimari İnceleme Raporu](agent_orchestration_architecture_review.md)
- [Agent Plane V2](../architecture/AGENT_PLANE_V2.md)
- [Control Plane V2](../architecture/CONTROL_PLANE_V2.md)
- [Execution Plane V2](../architecture/EXECUTION_PLANE_V2.md)
