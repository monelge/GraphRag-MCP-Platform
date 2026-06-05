# GraphRagMCP — Piyasa Üstü Seviye Analiz Raporu

**Tarih**: 2026-06-05  
**Versiyon**: V2  
**Hazırlayan**: Claude Code (Otomatik Analiz)

---

## Genel Değerlendirme

Proje **ambitiyöz ve mimari açıdan güçlü** — Knowledge/Memory/Agent üçlü plane mimarisi, hybrid retrieval (dense+sparse+graph), MCP protokolü — rakip ürünlerde olmayan özgün avantajlar mevcut. Ancak belirli kritik alanlarda kapatılması gereken açıklar tespit edildi.

---

## Mevcut Güçlü Yönler (Neden Farklısın)

| Özellik | Diğer Araçlar | GraphRagMCP |
|---|---|---|
| Graph-native retrieval | Yok / sınırlı | ✅ Neo4j PageRank + CONTAINS/CALLS traversal |
| Hybrid RRF Search | Çoğunda var | ✅ Dense + Sparse + Graph birleşimi |
| Episodic memory | Kapalı / yok | ✅ Qdrant üzerinde kalıcı hafıza |
| Sandbox execution | Çoğunda yok | ✅ Docker tabanlı izole ortam |
| Agent orchestration | Çoğunda yok | ✅ Reflection loops, guardrails |
| OpenSource + Self-host | Çoğu SaaS | ✅ Tam kontrol |

---

## Kategori Bazlı Puan Tablosu

| Kategori | Puan | Durum | Not |
|---|---|---|---|
| Retrieval Kalitesi | 6.5/10 | ⚠️ Eksikler var | Hybrid + graph iyi, reranking zayıf |
| **Güvenlik** | **2.0/10** | **🔴 KRİTİK** | Command injection, cypher injection, secret leak |
| Gözlemlenebilirlik | 5.0/10 | ⚠️ Orta | JSON logging iyi, distributed tracing yok |
| Agent Hafıza | 4.5/10 | ⚠️ Yarım kalmış | Episodic var, semantic/compaction eksik |
| MCP Tool Coverage | 6.0/10 | ⚠️ Boşluklar var | 21 tool, test/bug/refactor araçları yok |
| Performans | 5.5/10 | ⚠️ Orta | Caching iyi, parallelization yok |
| Enterprise Hazırlık | 2.5/10 | 🔴 Yok | RBAC yok, compliance yok, SLA yok |
| Dokümantasyon | 7.0/10 | ✅ İyi | Mimari dokümantasyon sağlam |

---

## P0 — KRİTİK Güvenlik Açıkları (Hemen — 2 Hafta)

### 1. Command Injection (CVSS 9.8)

**Dosya**: `src/execution/runners/command_runner.py`

`BLOCKED_BASH_FLAGS` yalnızca `-` kontrol ediyor; `shlex.split()` argüman injection'a açık. `rm -rf /path` türü komutlar, executable whitelist'te varsa geçebiliyor.

**Çözüm**:
```python
# AST-level komut doğrulama
ALLOWED_EXECUTABLES = {"/usr/bin/dotnet", "/usr/bin/python3", ...}
BLOCKED_ARGS = {"-rf", "--force", "--no-verify", ...}

def _validate_command(self, cmd_parts: list[str]) -> None:
    exe = self._resolve_executable(cmd_parts[0])
    if exe not in ALLOWED_EXECUTABLES:
        raise ValueError(f"Command not allowed: {exe}")
    for arg in cmd_parts[1:]:
        if arg in BLOCKED_ARGS:
            raise ValueError(f"Argument not allowed: {arg}")
```

**Etki**: Host system compromise, veri imhası, lateral movement

---

### 2. Cypher Injection (CVSS 8.6)

**Dosya**: `src/storage/neo4j_store.py`

Label ve relationship type'lar doğrudan Cypher'e ekleniyor, allowlist kontrolü yok.

```python
# Mevcut — ZAFİYETLİ
MERGE (s:{source['label']})   # Label doğrulanmıyor
[:{rel_type}]                  # rel_type doğrulanmıyor

# Çözüm
VALID_LABELS = {"Node", "Function", "Class", "Module", "File"}
VALID_REL_TYPES = {"CONTAINS", "OWNS", "CALLS", "IMPORTS"}

if source_label not in VALID_LABELS:
    raise ValueError(f"Invalid label: {source_label}")
```

**Etki**: Graph DB manipülasyonu, veri bütünlüğü ihlali, privilege escalation

---

### 3. Secret Scanner Bypass (CVSS 7.5)

**Dosya**: `src/indexing/chunkers/markdown_chunker.py`

```python
# Mevcut — BYPASS RİSKİ
_WHITELIST_SKIP_SCANNING = {
    "security.md", "backend.md", "frontend.md"  # Hardcoded!
}
if not skip_scanning:
    scan = secret_scanner.scan(sub_text)
else:
    final_text = sub_text  # TARAMA YOK!
```

**Çözüm**: Whitelist'i config'den yükle, dev/prod ayrımı ekle, production'da whitelist'i devre dışı bırak.

---

### 4. Fake Sandbox (CVSS 7.8)

**Dosya**: `docker-compose.yml`, `src/execution/sandbox/`

Docker kullanılıyor ancak seccomp profile, read-only mount enforcement ve kernel namespace tam izolasyonu uygulanmıyor.

**Çözüm**:
```yaml
# docker-compose.yml
graph-mcp:
  security_opt:
    - seccomp:./seccomp-profile.json
    - no-new-privileges:true
  read_only: true
  tmpfs:
    - /tmp
```

---

## P1 — Yüksek Öncelik (4 Hafta)

### 5. CrossEncoder Reranking Eksik

Şu anki reranking sadece `keyword_density * 0.50 + token_overlap * 0.30 + name_bonus * 0.20` — LLM yok, CrossEncoder yok. Cursor, Cody, Copilot Enterprise'ın hepsinde neural reranking mevcut.

**Öneri**: `sentence-transformers/ms-marco-MiniLM-L-6-v2`
- Model boyutu: ~80MB
- Ek latency: +15ms
- Retrieval quality artışı: **~%20**

```python
# src/retrieval/rerankers/cross_encoder_reranker.py
from sentence_transformers import CrossEncoder

class CrossEncoderReranker:
    def __init__(self):
        self.model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

    def rerank(self, query: str, candidates: list[Chunk]) -> list[Chunk]:
        pairs = [(query, c.text) for c in candidates]
        scores = self.model.predict(pairs)
        return [c for _, c in sorted(zip(scores, candidates), reverse=True)]
```

---

### 6. Memory Compaction Tamamlanmamış

Episodic memory birikiyor, `SUPERSEDES` edge'i yok, semantic condensing yok, temporal decay yok. Mem0 ve Zep/Graphiti bu konuda çok önde.

**Eksik bileşenler**:
- `TemporalStore` — planlandı ama implement edilmedi
- `MemoryCompactionWorker` — Redis Pub/Sub async worker
- `SUPERSEDES` graph edge — çakışan memory resolution
- `MemoryConsistencyChecker` — drift detection

**Öneri**: Her N episodic fact → LLM ile 1 semantic özet, eski episodic'ler `archived` olarak işaretle.

---

### 7. Cache TTL / Invalidation Yok

Redis'teki query cache'leri süresiz birikiyor. Proje yeniden indexlendiğinde stale sonuçlar dönüyor.

**Çözüm**:
```python
# redis_store.py
RETRIEVAL_CACHE_TTL = 3600       # 1 saat
EMBEDDING_CACHE_TTL = 86400      # 1 gün
QUERY_CACHE_TTL = 1800           # 30 dakika

# Reindex tetiklendiğinde:
await redis.delete_pattern(f"retrieval:{collection}:*")
```

---

### 8. Log Rotation Eksik

`FileHandler` kullanılıyor — disk dolacak. `data/graphmcp/graph-mcp.log` sınırsız büyüyor.

**Çözüm**:
```python
# src/shared/logging_config.py
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    log_file,
    maxBytes=50 * 1024 * 1024,  # 50MB
    backupCount=7
)
```

---

### 9. Temporal Decay / Recency Weighting Yok

Eski indexlenmiş dosyalar, yeni değiştirilmiş dosyalarla aynı skorla dönüyor. Recency boost yok.

**Çözüm**: Qdrant payload'a `last_modified` ekle, retrieval sırasında:
```python
recency_score = 1.0 / (1.0 + days_since_modified * 0.1)
final_score = base_score * 0.85 + recency_score * 0.15
```

---

## P2 — Orta Öncelik (8 Hafta)

### 10. Async Parallelization Eksik

Graph expansion, reranking, dedup adımları sırayla çalışıyor. Paralel çalıştırılabilecek adımlar var.

```python
# Mevcut — sıralı
graph_results = await graph_expander.augment(candidates)
reranked = await reranker.rerank(query, graph_results)

# Öneri — paralel
graph_task = asyncio.create_task(graph_expander.augment(candidates))
semantic_task = asyncio.create_task(semantic_filter.filter(candidates))
graph_results, semantic_results = await asyncio.gather(graph_task, semantic_task)
```

**Beklenen kazanım**: p95 latency **~%30 düşüş**

---

### 11. Eksik MCP Tool'ları

Rakip ürünlerde olup GraphRagMCP'de olmayan araçlar:

| Tool | Durum | Rakip Avantajı | Öncelik |
|---|---|---|---|
| `test_suggestion` | ❌ Yok | Cursor, Copilot | Yüksek |
| `bug_prediction` | ❌ Yok | Cody, Codeium | Yüksek |
| `refactor_suggestions` | ❌ Yok | Cursor, Cody | Orta |
| `code_clone_detection` | ❌ Yok | Cody | Orta |
| `documentation_generator` | ⚠️ Basit | Tümü | Orta |
| `security_scan` (SAST) | ⚠️ Pattern-based | Copilot Enterprise, Cody | Yüksek |
| `performance_analysis` | ❌ Yok | Cody | Düşük |
| `intelligent_navigation` | ⚠️ Kısmi | Cursor, Cody | Orta |

---

### 12. MCP Transport: Sadece STDIO

Şu an tek client'a hizmet verebiliyor. HTTP/SSE transport tamamlanırsa concurrent client sayısı **10x** artar.

**Mevcut**: `MCP_TRANSPORT=sse` env var var ama tam implement edilmemiş.

**Çözüm**: FastAPI üzerine tam SSE endpoint, WebSocket desteği, connection pooling.

---

### 13. OpenTelemetry Entegrasyonu Yok

Kendi custom tracer mevcut ama OTEL standardında değil. Helicone/LangSmith/Datadog/Grafana entegrasyonu yapılamıyor.

```python
# Öneri
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

tracer = trace.get_tracer("graph-mcp")

with tracer.start_as_current_span("retrieval") as span:
    span.set_attribute("query", query[:100])
    span.set_attribute("collection", collection)
    results = await retrieve(query)
```

---

## P3 — Enterprise Hazırlık (16 Hafta)

### 14. Multi-Tenancy / RBAC Yok

Collection bazlı izolasyon var ama row-level security, kullanıcı bazlı audit trail, role-based permission yok. Kurumsal deployment için şart.

**Gerekli bileşenler**:
- Tenant → Collection mapping
- JWT tabanlı kimlik doğrulama
- Tool-level permission matrix
- Per-tenant rate limiting

---

### 15. GDPR / Compliance Eksiklikleri

| Gereksinim | Durum |
|---|---|
| Veri silme (right-to-forget) | ❌ Yok |
| PII masking | ❌ Yok |
| Encryption at rest | ❌ PostgreSQL plaintext |
| Encryption in transit | ⚠️ TLS zorunlu değil |
| Audit trail | ⚠️ Kısmi |
| Data minimization | ❌ Yok |

---

### 16. Mevcut Ölçeklenebilirlik Limitleri

| Metrik | Mevcut Kapasite | Risk |
|---|---|---|
| Eşzamanlı MCP client | ~1 (STDIO) | Yüksek |
| Kayıtlı proje sayısı | <10 (registry memory) | Orta |
| Redis cache boyutu | 512MB hard limit | Orta |
| Neo4j heap | 1GB | Orta |
| Parallel agent tasks | ~5 (guardrail) | Düşük |
| Chunks per project | ~100k | Orta |

---

## Rakip Ürün Karşılaştırması

### Özellik Matrisi

| Özellik | GraphRagMCP | Cursor | Codeium | Copilot Enterprise | Sourcegraph Cody | Continue.dev |
|---|---|---|---|---|---|---|
| Hybrid Search | ✅ RRF | ✅ | ✅ | ✅ | ✅ | ✅ |
| Graph-based Retrieval | ✅ Güçlü | ❌ | ⚠️ | ⚠️ | ✅ Güçlü | ⚠️ |
| CrossEncoder Reranking | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Persistent Memory | ✅ Episodic | ⚠️ | ❌ | ✅ | ✅ | ❌ |
| Agent Orchestration | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ❌ |
| Sandbox Execution | ✅ Docker | ✅ IDE | ❌ | ❌ | ❌ | ❌ |
| Self-hosted | ✅ | ❌ | ✅ Enterprise | ❌ | ✅ Enterprise | ✅ |
| Test Suggestion | ❌ | ✅ | ✅ | ✅ | ✅ | ⚠️ |
| Bug Prediction | ❌ | ✅ | ✅ | ⚠️ | ✅ | ❌ |
| RBAC | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |
| OTEL Tracing | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |
| Compliance (GDPR/SOC2) | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |

---

### Rekabetçi Konumlama

**GraphRagMCP'nin kimsenin yapmadığı şeyi**:
1. **Graph Intelligence** — `CONTAINS/CALLS/OWNS` traversal + PageRank etki analizi — hiçbir rakipte bu derinlikte yok
2. **Ajansal Hafıza** — Episodic + Semantic plane tamamlanırsa Cursor/Copilot'tan çok önde
3. **Açık + Self-host + Compliance-ready potential** — GDPR gerektiren kurumlar için tek gerçekçi yol

**Şu an Continue.dev seviyesinde** (modular, developer-first, open-source) ama Graph Intelligence + Agent Orchestration avantajları sayesinde **3-6 ay içinde Cursor/Cody seviyesine çıkabilir**.

---

## Öncelikli Yol Haritası

```
Hafta 1-2   → P0: Güvenlik açıklarını kapat
              - Command injection fix
              - Cypher injection fix
              - Secret scanner hardening
              - Sandbox enforcement

Hafta 3-4   → P1: Kalite & Stabilite
              - CrossEncoder reranking entegre et
              - Cache TTL + invalidation
              - Log rotation
              - Memory compaction worker

Hafta 5-8   → P2: Performans & Tooling
              - asyncio.gather() parallelization
              - Yeni tool'lar: test_suggestion, bug_prediction, security_scan
              - HTTP/SSE transport tamamla
              - OpenTelemetry entegrasyonu

Hafta 9-16  → P3: Enterprise Hazırlık
              - RBAC + JWT auth
              - GDPR compliance (silme, PII masking)
              - Encryption at rest/in transit
              - Multi-tenancy + sharding stratejisi
```

---

## Özet

GraphRagMCP, **tasarım açısından doğru yerde** — graph-native retrieval, agent orchestration ve persistent memory kombinasyonu rakip ürünlerin büyük çoğunluğunda yok. Ancak:

- **P0 güvenlik açıkları** production'da ciddi risk oluşturuyor — önce bunları kapat
- **Retrieval quality** CrossEncoder + temporal decay ile kolayca %20+ artırılabilir
- **Memory plane** tamamlanırsa bu ürünün en güçlü differentiator'ı olacak
- **Enterprise features** olmadan kurumsal satış mümkün değil — RBAC + GDPR zorunlu

**Rakip ürünlerin önüne geçmek için gereken süre**: P0+P1+P2 tamamlandıktan sonra **3-4 ay**.
