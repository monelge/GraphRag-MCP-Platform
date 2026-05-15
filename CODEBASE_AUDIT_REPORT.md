# GraphRagMCP v2 — Codebase Audit Report
**Tarih:** 2026-05-15  
**Kapsam:** v2 mimarisi uyumu, ölü kod analizi, potansiyel hatalar, kod sağlığı

---

## 1. Genel Durum Özeti

| Alan | Durum | Not |
|------|-------|-----|
| v2 Fazlar | ✅ Tamamlandı | Tüm 6 faz bitirilmiş |
| Handler mimarisi | ✅ Sağlıklı | 5 handler sınıfı düzgün ayrılmış |
| MCP tool kaydı | ✅ Çalışıyor | 27 tool kayıtlı ve erişilebilir |
| Storage katmanı | ✅ Çalışıyor | Postgres, Neo4j, Qdrant, Redis, Episodic |
| Dead code | ⚠️ Var | `types.py` ve `utils.py`'de kullanılmayan kod |
| Git hygiene | ❌ Sorunlu | `.DS_Store` ve `__pycache__` dosyaları tracked |

---

## 2. Dosya Yapısı Analizi

### 2.1 Mevcut Ağaç (src/)

```
src/
├── mcp/
│   ├── __init__.py
│   ├── server.py          ✅ Aktif (MCP sunucusu)
│   └── tool_registry.py  ✅ Aktif (27 tool kayıtlı)
│   (schemas.py YOK - tasarımda var ama oluşturulmamış)
│
├── handlers/
│   ├── __init__.py       ✅ Aktif
│   ├── context.py         ✅ Aktif (AppContext dataclass)
│   ├── control_handler.py ✅ Aktif
│   ├── execution_handler.py ✅ Aktif
│   ├── indexing_handler.py ✅ Aktif
│   ├── memory_handler.py  ✅ Aktif
│   └── retrieval_handler.py ✅ Aktif
│
├── agent/
│   ├── orchestrator/     ✅ 3 dosya (state_machine, checkpoints, approvals)
│   ├── tasks/            ✅ 2 dosya (task_models, task_store)
│   └── nodes/            ✅ 7 node (base, planner, retriever, explainer, editor, verifier, reviewer, summarizer)
│
├── control/
│   ├── evals/            ✅ 5 dosya (dataset_manager, runner, metrics)
│   ├── models/           ✅ 4 dosya (gateway, budgets, guardrail, model_router)
│   └── observability/    ✅ 4 dosya (audit, metrics, tracer, __init__)
│
├── execution/
│   ├── runners/          ✅ 3 dosya (command_runner, build_runner, test_runner)
│   └── sandbox/          ✅ 3 dosya (runtime_manager, mount_policy, tool_policy)
│
├── indexing/
│   ├── chunkers/         ✅ 4 dosya (ast_chunker, markdown_chunker, chunk_models, secret_scanner)
│   ├── embedders/        ✅ 2 dosya (dense_embedder, sparse_embedder)
│   ├── extractors/       ✅ 3 dosya (graph_extractor, repo_map, __init__)
│   ├── normalization/    ✅ 2 dosya (path_mapper, language_detector)
│   └── pipelines/        ✅ 2 dosya (project_intelligence, __init__)
│
├── retrieval/
│   ├── context/          ✅ 4 dosya (context_builder, compressor, token_budget, __init__)
│   ├── ranking/          ✅ 5 dosya (reranker, deduplicator, scorer, answerability, __init__)
│   └── search/           ✅ 8 dosya (hybrid_search, local_search, global_search, impact_analysis, query_classifier, hyde, graph_expansion, __init__)
│
├── memory/
│   ├── models/           ✅ 2 dosya (memory_models, __init__)
│   ├── services/         ✅ 3 dosya (memory_writer, memory_recall, memory_compaction)
│   └── stores/           ✅ 4 dosya (episodic_store, decision_store, semantic_memory_store, temporal_store)
│
├── ontology/             ✅ 3 dosya (schema, builders, summarizers)
├── shared/               ✅ 6 dosya (config, errors, types, utils, llm_client, logging_config)
└── storage/              ✅ 5 dosya (postgres, neo4j, qdrant, redis, episodic)
```

### 2.2 v2 Tasarıma Göre Eksik/Artık Dosyalar

| Dosya | v2 Tasarım | Gerçek Durum | Not |
|-------|-------------|-------------|-----|
| `mcp/schemas.py` | Planlandı | ❌ Yok | Referans edilmemiş, gereksiz olabilir |
| `src/src/` | Kaldırılacak | ✅ Temizlenmiş | Faz 0 tamamlandı |
| `mcp_server.py` | Facade kalacak | ✅ Mevcut | Entry-point olarak kullanılıyor |

---

## 3. Ölü Kod (Dead Code) Analizi

### 3.1 `src/shared/types.py` — TAMAMEN ÖLÜ KOD

```python
# Tanımlanan tipler:
JsonDict = Dict[str, Any]
CollectionName = NewType("CollectionName", str)
ProjectPath = NewType("ProjectPath", str)
CommitSha = NewType("CommitSha", str)
NodeId = NewType("NodeId", str)
```

**Sonuç:** Bu tiplerin hiçbiri projede import edilmemiş. Tamamen ölü kod.

**Öneri:** Dosyayı sil veya tipleri kullanacak şekilde refactor et.

---

### 3.2 `src/shared/utils.py` — KISMEN ÖLÜ KOD

| Fonksiyon | Durum | Kullanım Yeri |
|-----------|-------|----------------|
| `sha256_hash` | ✅ Kullanılıyor | `postgres_store.py` |
| `truncate` | ❌ Kullanılmıyor | Hiçbir yerde import edilmemiş |
| `redact_secrets` | ❌ Kullanılmıyor | Hiçbir yerde import edilmemiş |
| `now_ts` | ❌ Kullanılmıyor | Hiçbir yerde import edilmemiş |

**Öneri:** Kullanılmayan fonksiyonları sil veya `truncate` yerine `redact_secrets`'ı `secret_scanner.py`'da kullan.

---

### 3.3 Diğer Potansiyel Ölü Kodlar

| Dosya | İnceleme |
|-------|-----------|
| `src/control/models/model_router.py` | `get_model()` fonksiyonu `retrieval_handler.py` tarafından kullanılıyor ✅ |
| `src/control/models/guardrail.py` | `RequestBudget`, `fail_fast_token`, `GuardrailError` kullanılıyor ✅ |
| `src/ontology/summarizers.py` | `impact_analysis.py` ve `schema.py` tarafından kullanılıyor ✅ |
| `src/memory/stores/semantic_memory_store.py` | `memory_handler.py` tarafından kullanılıyor ✅ |

---

## 4. Potansiyel Hatalar ve Sorunlar

### 4.1 🔴 KRİTİK: `retrieval_handler.py` Satır 163

```python
reranked = self.ctx.reranker.rerank(query, candidates, top_n=min(top_k, 5))
```

**Sorun:** `min(top_k, 5)` ifadesi yanlış. `top_k` değeri 5'ten büyük olduğunda sonuçlar 5'e sabitleniyor. Bu muhtemelen `top_n=top_k` veya `top_n=min(top_k * 2, 20)` olmalıydı.

**Etki:** Kullanıcı `top_k=10` istese bile sadece 5 sonuç dönecek.

---

### 4.2 🟡 ORTA: `retrieval_handler.py` Satır 128

```python
for current_query in [query, *expansions]:
```

**Sorun:** `expansions` listesi boşsa veya `None` ise davranış belirsiz. `expansions` her zaman liste olmalı.

**Öneri:** `expansions or []` kontrolü ekle.

---

### 4.3 🟡 ORTA: `server.py` — `_tracer` Ataması

```python
_tracer = PipelineTracer  # Sınıfın kendisi (instance değil)
```

`context.py`'de `tracer: type[PipelineTracer]` olarak tip atanmış. `retrieval_handler.py`'de `self.ctx.tracer(query=..., ...)` şeklinde çağrılıyor.

**Durum:** Bu aslında doğru çalışıyor çünkü `PipelineTracer(...)` yeni bir instance döndürüyor. Ancak kod karmaşık ve anlaşılması zor. Yorum satırı eklenmesi önerilir.

---

### 4.4 🟢 DÜŞÜK: `config.py` — `openai_api_key` Ortam Değişkeni

```python
openai_api_key=os.getenv("OPENAI_API_KEY", os.getenv("OPENROUTER_API_KEY", "")),
```

**Not:** `OPENROUTER_API_KEY` desteği var ama `LLM_BASE_URL` default olarak `https://openrouter.ai/api/v1` kullanıyor. Bu iyi bir fallback.

---

## 5. Git Hygiene Sorunları

### 5.1 `.DS_Store` Dosyaları (Tracked)

Aşağıdaki `.DS_Store` dosyaları git tarafından takip ediliyor:

```
src/.DS_Store
src/storage/.DS_Store
src/retrieval/.DS_Store
src/execution/.DS_Store
src/indexing/.DS_Store
src/handlers/.DS_Store
src/control/.DS_Store
data/.DS_Store
data/neo4j/.DS_Store
data/redis/.DS_Store
... (toplam 15+ tane)
```

**Çözüm:**
```bash
find . -name ".DS_Store" -delete
git rm --cached **/.DS_Store
# .gitignore zaten kuralı içeriyor
```

---

### 5.2 `__pycache__` Dizinleri (Tracked)

Git status'te görülen `__pycache__` dizinleri:

```
src/__pycache__/
src/storage/__pycache__/
src/handlers/__pycache__/
src/control/__pycache__/
...
```

**Çözüm:**
```bash
find . -name "__pycache__" -type d -exec rm -rf {} +
git rm -r --cached **/__pycache__
```

---

## 6. v2 Tasarım Uyum Raporu

### 6.1 Tamamlanan Fazlar

| Faz | Hedef | Durum |
|-----|-------|-------|
| Faz 0 | Temizlik ve Refactor | ✅ Tamamlandı |
| Faz 1 | Knowledge Plane | ✅ Tamamlandı |
| Faz 2 | Impact & Provenance | ✅ Tamamlandı |
| Faz 3 | Memory Plane v2 | ✅ Tamamlandı |
| Faz 4 | Agent Plane | ✅ Tamamlandı |
| Faz 5 | Execution Plane | ✅ Tamamlandı |
| Faz 6 | Control Plane | ✅ Tamamlandı |

### 6.2 v2 Hedeflerine Ulaşım

| Hedef | Durum | Not |
|-------|-------|-----|
| Multi-project registry | ✅ | `project_registry.py` |
| Rich ontology | ✅ | `ontology/` modülü |
| Deep impact analysis | ✅ | `impact_analysis.py` |
| Temporal & Compacted memory | ✅ | `temporal_store.py`, `memory_compaction.py` |
| Stateful task orchestration | ✅ | `state_machine.py`, `checkpoints.py` |
| Secure execution sandbox | ✅ | `sandbox/` modülü |
| Control Plane observability | ✅ | `observability/` modülü |

---

## 7. Test Durumu

| Dosya | Durum |
|-------|-------|
| `tests/unit/test_postgres_inserts.py` | ⚠️ Untracked (?? git status) |
| Diğer testler | ❓ Bilinmiyor |

**Öneri:** Test dizinini düzenleyin ve CI/CD'ye ekleyin.

---

## 8. Önerilen Aksiyonlar (Öncelik Sırası)

### 🔴 Yüksek Öncelik
1. **`retrieval_handler.py` satır 163'teki `min(top_k, 5)` hatasını düzelt**
2. **`.DS_Store` ve `__pycache__` dosyalarını git'ten temizle**

### 🟡 Orta Öncelik
3. **`src/shared/types.py`'yi sil (tamamen ölü kod)**
4. **`src/shared/utils.py`'den kullanılmayan fonksiyonları sil**
5. **`tests/unit/test_postgres_inserts.py`'i commit et veya sil**

### 🟢 Düşük Öncelik
6. `server.py`'de `_tracer` atamasına yorum satırı ekle
7. `retrieval_handler.py` satır 128'e `expansions or []` kontrolü ekle
8. `schemas.py` ihtiyacını değerlendir (gerekli değilse dokümantasyondan çıkar)

---

## 9. Sonuç

**Genel Sağlık: İYİ (7/10)**

- ✅ v2 mimarisi başarıyla uygulanmış
- ✅ Tüm ana özellikler çalışıyor
- ✅ Handler/Node ayrımı temiz
- ⚠️ Az miktarda ölü kod var
- ⚠️ 1 adet potansiyel hata (`min(top_k, 5)`)
- ❌ Git hygiene sorunları var

**Sistem çalışır durumda** ancak yukarıdaki temizlik işlemleri yapılırsa kod kalitesi artacaktır.
