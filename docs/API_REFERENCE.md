# GraphRag MCP Platform — API Referans Dökümanı

> **Son güncelleme:** 2026-05-14  
> **Kaynak:** `src/mcp_server.py` — tüm `@app.tool()` dekoratörlü fonksiyonlar MCP protokolü üzerinden çağrılabilir.

---

## İçindekiler

1. [Genel Bakış](#genel-bakış)
2. [İndeksleme Araçları](#1-i̇ndeksleme-araçları)
3. [Arama & Retrieval Araçları](#2-arama--retrieval-araçları)
4. [Hafıza Yönetimi](#3-hafıza-yönetimi)
5. [Görev Yönetimi (Agent Tasks)](#4-görev-yönetimi-agent-tasks)
6. [Doğrulama & Değerlendirme](#5-doğrulama--değerlendirme)
7. [Kontrol Düzlemi (Control Plane)](#6-kontrol-düzlemi-control-plane)
8. [Karar Belleği](#7-karar-belleği)
9. [Dahili Modüller (Internal API)](#8-dahili-modüller-internal-api)
10. [Kullanım Senaryoları](#9-kullanım-senaryoları)
11. [Dead Code Analizi](#10-dead-code-analizi)

---

## Genel Bakış

Bu platform, büyük kod tabanlarını **graf + vektör** hibrit yapısıyla indeksleyen ve MCP (Model Context Protocol) üzerinden AI ajanlarına sunan bir sistemdir.

```
AI Agent / Copilot
      │
      ▼ MCP (stdio / HTTP)
 mcp_server.py  ←→  handlers/
      │
      ├── IndexingHandler   → Qdrant + Neo4j'e yazar
      ├── RetrievalHandler  → Hibrit arama yapar
      ├── MemoryHandler     → Episodik bellek
      ├── ExecutionHandler  → Görev + doğrulama
      └── ControlHandler    → Kayıt + özet + istatistik
```

**Gerekli servisler:** Redis, PostgreSQL, Neo4j, Qdrant (embedding store)

---

## 1. İndeksleme Araçları

### `index_project`

Bir projenin tamamını indeksler. Kod dosyalarını AST ile parçalar, embedding oluşturur, Qdrant ve Neo4j'e yazar.

```python
index_project(
    project_path: str,          # Zorunlu: proje kök dizini (mutlak yol)
    collection: str = "",       # Opsiyonel: koleksiyon adı (boşsa proje adından türetilir)
    batch_size: int = 32        # Opsiyonel: batch boyutu
) -> str                        # JSON sonuç mesajı
```

**Ne zaman kullanılır?**
- Yeni bir projeyi ilk kez platforma eklerken
- Proje büyük çaplı değişiklik geçirdikten sonra tam yeniden indeksleme gerektiğinde

**Örnek:**
```
index_project("/app/projects/MyService", collection="MyService")
```

---

### `incremental_index_project`

Yalnızca değişen dosyaları indeksler. `graph_mcp_hook.py` tarafından otomatik tetiklenir.

```python
incremental_index_project(
    project_path: str,
    changed_files: list[str] | None = None,  # None ise git diff ile otomatik algılar
    batch_size: int = 32
) -> str
```

**Ne zaman kullanılır?**
- CI/CD pipeline'ında commit sonrası otomatik güncelleme için
- `graph_mcp_hook.py` hook'u üzerinden tetiklenir

---

### `index_agent_docs`

Proje içindeki `docs/` ve `*.md` dosyalarını özel ajan-döküman formatında indeksler.

```python
index_agent_docs(
    project_path: str   # Proje kök dizini
) -> str
```

**Ne zaman kullanılır?**
- Mimari kararlar, ADR'ler ve teknik dökümanların aranabilir olmasını sağlamak için

---

### `search_agent_docs`

İndekslenmiş ajan dökümanlarını arar.

```python
search_agent_docs(
    query: str,
    collection: str = "",
    layer: str | None = None,          # Örn: "api", "domain", "infra"
    doc_priority: str | None = None    # Örn: "high", "medium", "low"
) -> str
```

---

## 2. Arama & Retrieval Araçları

### `search_code`

Hibrit (dense + sparse + graph) arama. En sık kullanılan tool.

```python
search_code(
    query: str,
    collection: str = "",
    top_k: int = 0,                    # 0 = otomatik seçim
    rewrite_query: bool | None = None  # None = akıllı karar
) -> str                               # JSON: chunks listesi + skor
```

**Örnek:**
```
search_code("kullanıcı kimlik doğrulama akışı", collection="MyService", top_k=10)
```

---

### `explain_code`

Bir kavram veya bileşen hakkında LLM destekli açıklama üretir. `search_code` + LLM synthesis.

```python
explain_code(
    query: str,
    collection: str = "",
    top_k: int = 5
) -> str   # Doğal dil açıklama
```

---

### `search_repo_architecture`

Mimari katmanları, modül ilişkilerini ve sistem tasarımını sorgular. Graf tabanlı arama.

```python
search_repo_architecture(
    query: str,
    collection: str = "",
    top_k: int = 6
) -> str
```

**Örnek:**
```
search_repo_architecture("servis bağımlılıkları ve veri akışı", collection="MyService")
```

---

## 3. Hafıza Yönetimi

### `store_memory`

Episodik bellek kaydı oluşturur. AI ajanın bağlam hafızası için kullanılır.

```python
store_memory(
    title: str,
    content: str,
    memory_type: str = "general",     # "general" | "code" | "decision" | "error" | vb.
    tags: list[str] | None = None,
    collection: str = "",
    module: str = "",                 # Hangi modülle ilgili
    commit_sha: str = "",
    provenance: str = "",             # Kaynağı (agent/user/system)
    valid_days: int | None = None,    # TTL — None = kalıcı
    status: str = "active"           # "active" | "archived"
) -> str
```

---

### `recall_memory`

Geçmiş episodik bellek kayıtlarını sorgular.

```python
recall_memory(
    query: str,
    memory_type: str | None = None,
    memory_layer: str | None = None,
    collection: str = "",
    include_invalid: bool = False,    # Süresi dolmuş kayıtları dahil et
    top_k: int = 5
) -> str
```

---

### `compact_memory`

Benzer ve eski bellek kayıtlarını LLM ile özetleyip sıkıştırır.

```python
compact_memory(
    collection: str,
    query: str = "*"    # Hangi kayıtları sıkıştıracağını filtreler
) -> str
```

---

## 4. Görev Yönetimi (Agent Tasks)

### `create_agent_task`

Çok adımlı bir ajan görevi oluşturur. Human-in-the-loop onay akışı destekler.

```python
create_agent_task(
    title: str,
    description: str,
    collection: str        # Hangi projeyle ilişkili
) -> str                   # JSON: task_id
```

---

### `get_task_status`

Görevin mevcut durumunu ve adımlarını getirir.

```python
get_task_status(
    task_id: str
) -> str   # JSON: status, steps, current_step
```

**Durum değerleri:** `pending` | `in_progress` | `waiting_approval` | `completed` | `failed`

---

### `approve_task_step`

Bekleyen adımı onaylar veya geri bildirim verir.

```python
approve_task_step(
    task_id: str,
    feedback: str = "approved"    # "approved" | "rejected" | özel mesaj
) -> str
```

---

### `list_agent_tasks`

Görev listesini filtreli olarak getirir.

```python
list_agent_tasks(
    collection: str = "",   # Boş = tüm projeler
    status: str = ""        # Boş = tüm durumlar
) -> str
```

---

## 5. Doğrulama & Değerlendirme

### `run_verification_plan`

Proje üzerinde build + test + lint çalıştırır.

```python
run_verification_plan(
    project_path: str,
    run_build: bool = True,
    run_tests: bool = True,
    run_lint: bool = False
) -> str   # JSON: her adımın çıktısı ve başarı durumu
```

---

### `run_retrieval_eval`

Tanımlı bir dataset üzerinde retrieval kalitesini ölçer (precision, recall, MRR).

```python
run_retrieval_eval(
    dataset_name: str,   # `src/control/evals/` altında tanımlı dataset adı
    collection: str
) -> str
```

---

## 6. Kontrol Düzlemi (Control Plane)

### `register_project`

Bir projeyi platforma kaydeder ve opsiyonel olarak indeksler.

```python
register_project(
    project_path: str,
    collection: str = "",
    index_code: bool = True,
    index_docs: bool = True,
    batch_size: int = 32
) -> str
```

> **Not:** `index_project` yerine bu fonksiyon önerilir — kayıt + indekslemeyi tek seferde yapar.

---

### `list_projects`

Platforma kayıtlı tüm projeleri listeler.

```python
list_projects() -> str   # JSON: proje listesi + metadata
```

---

### `summarize_repository`

Projenin üst düzey mimari özetini oluşturur / günceller.

```python
summarize_repository(
    project_path: str,
    collection: str = ""
) -> str
```

---

### `get_control_plane_stats`

Tüm servislerin durumunu ve istatistiklerini getirir.

```python
get_control_plane_stats() -> str
# Döner: Redis/Neo4j/Postgres/Qdrant bağlantı durumu, indeks boyutları, görev sayıları
```

---

### `analyze_change_impact`

Değişen dosyaların hangi modülleri / bağımlılıkları etkilediğini graf üzerinde analiz eder.

```python
analyze_change_impact(
    project_path: str,
    changed_paths: list[str],   # Değişen dosyaların yolları
    collection: str = ""
) -> str   # JSON: etkilenen modüller, bağımlılık zinciri
```

---

## 7. Karar Belleği

### `store_decision_memory`

Mimari kararları (ADR benzeri) kayıt altına alır.

```python
store_decision_memory(
    title: str,
    content: str,
    collection: str,
    module: str = "",
    commit_sha: str = "",
    provenance: str = "",
    tags: list[str] | None = None
) -> str
```

---

### `search_decisions`

Geçmiş mimari kararları sorgular.

```python
search_decisions(
    query: str,
    collection: str = "",
    top_k: int = 5
) -> str
```

---

## 8. Dahili Modüller (Internal API)

Bu modüller doğrudan MCP üzerinden çağrılmaz; handler'lar tarafından kullanılır.

| Modül | Sınıf/Fonksiyon | Sorumluluğu |
|---|---|---|
| `src/indexing/chunkers/` | `ASTChunker`, `MarkdownChunker` | Kod ve md dosyalarını parçalar |
| `src/indexing/extractors/` | `GraphExtractor`, `build_repo_map` | AST'den graf çıkarır |
| `src/indexing/embedders/` | `DenseEmbedder`, `SparseEmbedder` | Vektör üretir |
| `src/retrieval/search/` | `HybridSearcher`, `GraphExpander` | Arama pipeline'ı |
| `src/retrieval/search/` | `ImpactAnalyzer` | Graf tabanlı etki analizi |
| `src/retrieval/context/` | `TokenBudgetOptimizer`, `ContextBuilder` | Token bütçe yönetimi |
| `src/retrieval/ranking/` | `LocalReranker`, `SemanticDeduplicator` | Sıralama ve tekilleştirme |
| `src/storage/` | `QdrantStore`, `RedisStore`, `Neo4jStore`, `PostgresStore` | Depolama katmanı |
| `src/agent/` | `TaskOrchestrator`, `TaskStore` | Görev durum makinesi |
| `src/control/` | `ModelGateway`, `PipelineTracer`, `EvalRunner` | Model yönetimi + izleme |
| `src/memory/services/` | `MemoryCompactor`, `BatchJobScheduler` | Arka plan bellek işleri |
| `src/shared/` | `LLMClient`, `ProjectRegistry`, `get_logger` | Ortak yardımcılar |

---

## 9. Kullanım Senaryoları

### Yeni Proje Ekleme
```
1. register_project("/app/MyService", collection="MyService")
2. summarize_repository("/app/MyService", collection="MyService")
```

### Kod Arama
```
search_code("authentication middleware", collection="MyService")
explain_code("JWT token yenileme akışı", collection="MyService")
```

### Mimari Analiz
```
search_repo_architecture("servis katmanları arası bağımlılıklar", collection="MyService")
analyze_change_impact("/app/MyService", ["src/auth/token.py"], collection="MyService")
```

### Hafıza Akışı
```
store_memory("Önemli Bulgu", "TokenService rate-limit olmadan çağrılıyor", memory_type="error", collection="MyService")
recall_memory("rate limit", collection="MyService")
```

### Karar Kaydı
```
store_decision_memory(
    title="JWT yerine Opaque Token seçildi",
    content="Revoke kabiliyeti için opaque token tercih edildi...",
    collection="MyService",
    module="auth",
    tags=["security", "auth"]
)
```

### CI/CD Hook
```bash
# git post-commit hook olarak:
python graph_mcp_hook.py
# → değişen dosyaları algılar → incremental_index_project tetikler
```

---

## 10. Dead Code Analizi

Tüm public fonksiyonlar aktif olarak kullanılmaktadır. Aşağıdaki tespitler yapılmıştır:

| Durum | Modül / Fonksiyon | Açıklama |
|---|---|---|
| ✅ Aktif | Tüm `@app.tool()` fonksiyonları | `mcp_server.py` + testler üzerinden kullanılıyor |
| ✅ Aktif | Tüm handler sınıfları | `mcp_server.py` tarafından instantiate ediliyor |
| ✅ Aktif | Tüm storage sınıfları | Handler'lar tarafından kullanılıyor |
| ⚠️ Script-only | `graph_mcp_hook.py` içindeki fonksiyonlar | Yalnızca bu scriptin kendi `__main__` akışında kullanılıyor; dışarıdan import edilmiyor |
| ✅ Aktif | `src/memory/services/` | `mcp_server.py` üzerinden dolaylı kullanım (batch scheduler) |

**Genel sonuç:** Repo'da net "dead code" tespit edilmedi. Tüm modüller ya doğrudan MCP tool katmanından ya da handler'lar üzerinden bağlı.
