# GraphRagMCP V2 — Tool Dokümantasyonu

**26 MCP Tool | SOTA GraphRAG | CrossEncoder Reranking | PostgreSQL + Qdrant + Redis + Neo4j**

MCP Endpoint: `http://deva.adanaekspres.com:8000/sse`  
Dashboard: `http://deva.adanaekspres.com:8080`

---

## İçindekiler

1. [Ana Orkestrasyon](#1-ana-orkestrasyon)
2. [Knowledge Plane — Bilgi & Kod Araması](#2-knowledge-plane--bilgi--kod-araması)
3. [Memory Plane — Hafıza & Deneyim](#3-memory-plane--hafıza--deneyim)
4. [Analiz & Kalite Plane](#4-analiz--kalite-plane)
5. [Execution Plane — Görev & Doğrulama](#5-execution-plane--görev--doğrulama)
6. [Agent Docs Plane](#6-agent-docs-plane)
7. [Kullanım Senaryoları](#7-kullanım-senaryoları)
8. [Operasyonel Protokoller](#8-operasyonel-protokoller)

---

## 1. Ana Orkestrasyon

### `execute_agent_task`

**Öncelik:** #1 — Karmaşık multi-step görevlerin başlangıç noktası.

Verilen hedefi otonom olarak gerçekleştirir. Tüm V2 Plane'lerini (Knowledge, Memory, Agent, Execution, Control) devreye alır. İçeriden `create_agent_task → recall_memory → search_code → run_verification_plan` döngüsünü yönetir.

```
execute_agent_task(
    goal: str,          # "UserService'e JWT refresh token ekle"
    project_path: str,  # "/home/monelge/WareLogisticcBYS"
    collection: str     # "WareLogisticcBYS"
)
```

**Ne zaman kullanılır:**
- Birden fazla adım içeren her görevde.
- Strateji belirsizliğinde — araç kendi planning loop'unu çalıştırır.
- Refactor, yeni feature, bug fix orchestration'ında.

**Ne zaman kullanılmaz:**
- Tek bir arama / sorgulama yeterliyse.
- Bağımsız bir `security_scan` veya `search_code` çağrısında.

**Örnek çıktı:** Görev planı, execution log, doğrulama sonuçları.

---

## 2. Knowledge Plane — Bilgi & Kod Araması

### `index_project`

Projenin tamamını sıfırdan indeksler. AST analizi, Neo4j graf oluşturma, PageRank hesaplama ve Repo Map üretimini tetikler.

```
index_project(
    project_path: str,   # "/home/monelge/WareLogisticcBYS"
    collection: str,     # "WareLogisticcBYS"
    batch_size: int      # varsayılan: 32
)
```

**Zorunlu durum:** Yeni modül ekleme, 20+ dosya değişimi, namespace refactor, dependency graph değişikliği, build pipeline güncellemesi.

---

### `incremental_index_project`

Yalnızca değiştirilen dosyaları yeniden indeksler. `index_project`'e göre çok daha hızlıdır.

```
incremental_index_project(
    project_path: str,
    changed_files: list[str] | None  # None ise git diff ile otomatik algılar
)
```

**Kural:** <20 dosya değişiminde bu araç tercih edilir. Her oturum başında çalıştırılması önerilir.

---

### `search_code`

Semantik + BM25 hibrit arama. Sorgu tipi otomatik sınıflandırılır (factual, broad, architectural). CrossEncoder reranking ile sonuçlar yeniden sıralanır. HyDE (Hypothetical Document Embedding) ile sorgu genişletme desteklenir.

```
search_code(
    query: str,                  # "JWT token yenileme mantığı nerede"
    collection: str,             # "WareLogisticcBYS"
    top_k: int,                  # 0 = otomatik (sorgu tipine göre)
    rewrite_query: bool | None   # None = otomatik karar
)
```

**Arama modları (otomatik seçilir):**
| Sorgu tipi | Mod |
|---|---|
| `factual_doc`, `config_lookup` | Local search |
| `broad_summary` | Global search |
| Diğer | Hybrid search (BM25 + dense) |

**Redis cache:** Aynı query 2. kez çalışırsa cache'den döner (exact + semantic cache).

---

### `explain_code`

Bulunan kod parçalarının ne yaptığını LLM destekli derin analizle açıklar. `search_code` ile bulunan sonuçlar üzerine detaylı mantık çözümlemesi yapar.

```
explain_code(
    query: str,        # "UserRepository neden Unit of Work kullanıyor"
    collection: str,
    top_k: int         # varsayılan: 5
)
```

**Kural:** `search_code` sonucu yeterliyse bu araç çağrılmaz (token ekonomisi).

---

### `grep_exact_string`

Dosya sistemi üzerinde deterministik metin araması. `find + grep` kombinasyonunun MCP uyumlu, güvenli alternatifi.

```
grep_exact_string(
    query: str,              # "IOrderRepository"
    collection: str,         # koleksiyondan proje yolunu otomatik çözer
    project_path: str,       # doğrudan yol (opsiyonel)
    file_extension: str,     # "cs", "py", "ts" — boş = hepsi
    case_sensitive: bool     # varsayılan: False
)
```

**Ne zaman tercih edilir:** Sınıf adı, interface, sabit değer gibi kesin metin aramasında. 3 başarısız semantic arama sonrası bu araca geçilmesi zorunludur.

**Sınırlar:** Max 100 eşleşme, 30 dosya. Binary ve build dizinleri otomatik atlanır.

---

### `search_repo_architecture`

Servis ilişkileri, modül sınırları, bağımlılık grafı gibi mimari sorulara yanıt verir. Qdrant'taki architectural chunk'lardan arama yapar.

```
search_repo_architecture(
    query: str,       # "Order servisinin bağımlılıkları"
    collection: str,
    top_k: int        # varsayılan: 6
)
```

---

### `summarize_repository`

Projenin yüksek seviyeli semantik haritasını (Repo Map) döner. Modüller, servisler, önemli dosyalar ve katmanlı mimari özeti içerir.

```
summarize_repository(
    project_path: str,
    collection: str
)
```

**Kullanım:** Oturum başında projeyi tanımak, mimariye genel bakış için.

---

### `analyze_change_impact`

Bir veya birden fazla dosyadaki değişikliğin Neo4j graf üzerindeki etki alanını analiz eder. Hangi servisler, sınıflar, test dosyaları etkilenecek gösterir.

```
analyze_change_impact(
    project_path: str,
    changed_paths: list[str],   # ["src/Services/OrderService.cs"]
    collection: str
)
```

**ZORUNLUDUR:** Kritik dosyalarda (servis, repository, migration) herhangi bir değişiklik öncesi.

---

### `register_project`

Yeni bir projeyi GraphRagMCP sistemine kaydeder. İsteğe bağlı olarak kod ve dokümantasyon indekslemesini de başlatır.

```
register_project(
    project_path: str,
    collection: str,
    index_code: bool,   # varsayılan: True
    index_docs: bool,   # varsayılan: True
    batch_size: int     # varsayılan: 32
)
```

---

### `list_projects`

Sisteme kayıtlı tüm projelerin listesini ve meta verilerini döner.

```
list_projects()
```

---

## 3. Memory Plane — Hafıza & Deneyim

### `recall_memory`

Geçmiş oturumlardan öğrenilen deneyimleri, episodic olayları ve yazılı notları arar. Strateji kurmadan önce çalıştırılması zorunludur.

```
recall_memory(
    query: str,                  # "Order servisi refactor nasıl yapıldı"
    memory_type: str | None,     # "general", "decision", "error", "lesson"
    memory_layer: str | None,    # "episodic", "semantic", "decision"
    collection: str,
    include_invalid: bool,       # süresi dolmuş kayıtları dahil et
    top_k: int                   # varsayılan: 5
)
```

**Doğrulama kuralı:** 18 aydan eski kararlar "historical" kabul edilir ve doğrulanmadan uygulanamaz.

---

### `search_decisions`

Mimari kararları, tasarım tercihlerini ve başarılı görev özetlerini arar. `recall_memory`'den farkı: yalnızca kalıcı Decision Layer'ı tarar.

```
search_decisions(
    query: str,       # "CQRS pattern neden seçildi"
    collection: str,
    top_k: int        # varsayılan: 5
)
```

---

### `store_memory`

Episodic hafızaya yeni kayıt yazar. Bir oturumda öğrenilen deneyim, hata veya çözüm saklanır.

```
store_memory(
    title: str,
    content: str,
    memory_type: str,   # "general", "error", "lesson", "decision"
    tags: list | None,
    collection: str,
    module: str,
    commit_sha: str,
    provenance: str,
    valid_days: int | None,   # None = sonsuz
    status: str               # "active"
)
```

---

### `store_decision_memory`

Kalıcı mimari kararları Decision Layer'a yazar. `store_memory`'den farkı: bu kayıtlar `compact_memory` ile silinmez ve `search_decisions` ile sorgulanır.

```
store_decision_memory(
    title: str,
    content: str,
    collection: str,
    module: str,
    commit_sha: str,
    provenance: str,
    tags: list | None
)
```

**Ne zaman kullanılır:** "Bu servis Event Sourcing kullanacak çünkü..." gibi geri dönüşü olmayan mimari kararlar için.

---

### `compact_memory`

Belirtilen koleksiyondaki benzer ve çakışan episodic hafıza kayıtlarını LLM ile tek bir semantik özete birleştirir. Token kullanımını azaltır.

```
compact_memory(
    collection: str,
    query: str   # "*" = tümü, ya da konu filtresi
)
```

---

### `run_memory_cycle`

Tam hafıza döngüsünü çalıştırır: episodic kayıtları atomic fact'lere dönüştürür ve süresi dolan kayıtları siler. Periyodik olarak (haftalık veya sprint sonunda) çalıştırılmalıdır.

```
run_memory_cycle(
    collection: str
)
```

**Çıktı:** Dönüştürülen kayıt sayısı, silinen kayıt sayısı, üretilen atomic fact özeti.

---

## 4. Analiz & Kalite Plane

### `security_scan`

Pattern-based SAST (Static Application Security Testing). Kaynak kodu üzerinde güvenlik açıklarını tarar.

```
security_scan(
    project_path: str,
    collection: str
)
```

**Tarama kapsamı:**

| Kategori | Açıklama |
|---|---|
| SQL Injection | String concatenation ile SQL sorgusu |
| Hardcoded Secret | API key, password, token sabit değerleri |
| eval/exec | Dinamik kod çalıştırma |
| Shell Injection | OS komut birleştirme |
| XSS | Sanitize edilmemiş HTML çıktısı |
| Path Traversal | `../` ile dizin atlaması |
| Insecure Random | `Math.random()` şifreleme bağlamında |
| Pickle Deserialization | Güvenilmez kaynaktan pickle.loads |

**Severity seviyeleri:** `CRITICAL`, `HIGH`, `MEDIUM`  
**ZORUNLU KURAL:** CRITICAL bulgu döndürürse düzeltilmeden yeni kod yazılamaz.

---

### `refactor_suggestions`

AST-based code smell tespiti. Okunabilirlik ve bakım kalitesini düşüren yapıları tespit eder.

```
refactor_suggestions(
    project_path: str,
    collection: str
)
```

**Tespit edilen code smell'ler:**

| Tür | Eşik |
|---|---|
| Long Method | >50 satır |
| Deep Nesting | >4 seviye |
| God Class | >500 satır veya >15 method |
| Large File | >800 satır |

Her bulgu için dosya, satır aralığı ve refactor önerisi döner.

---

### `test_suggestion`

Test coverage gap analizi yapar. Test dosyası olmayan public fonksiyonları tespit eder ve LLM ile test case önerileri üretir.

```
test_suggestion(
    project_path: str,
    collection: str,
    target_file: str   # boş = tüm proje
)
```

**Her fonksiyon için üretilen test tipleri:**
- Happy path (başarılı senaryo)
- Edge case (sınır koşulları)
- Hata senaryosu (exception beklenen durumlar)

---

### `code_clone_detection`

Qdrant embedding'lerini cosine similarity ile karşılaştırır. Semantik olarak aynı işi yapan kod bloklarını (clone) tespit eder.

```
code_clone_detection(
    collection: str,
    threshold: float   # varsayılan: 0.95 (0.0–1.0 arası)
)
```

**ZORUNLU:** Büyük refactor işlemlerinden önce çalıştırılmalıdır. Threshold düşürülürse (örn. 0.85) daha geniş benzerlik bulunur.

---

## 5. Execution Plane — Görev & Doğrulama

### `create_agent_task`

Onaylı ve adımlara bölünmüş bir görev planı oluşturur. PostgreSQL'e kaydedilir, `get_task_status` ile takip edilir.

```
create_agent_task(
    title: str,
    description: str,
    collection: str,
    steps: list | None   # ["1. Analiz", "2. Uygulama", "3. Test"]
)
```

---

### `get_task_status`

Görev ID'sine göre mevcut durumu, tamamlanan adımları ve notları döner.

```
get_task_status(
    task_id: str
)
```

**Durumlar:** `planned`, `in_progress`, `waiting_approval`, `completed`, `failed`

---

### `complete_task`

Görevi tamamlandı olarak işaretler ve opsiyonel not ekler.

```
complete_task(
    task_id: str,
    note: str   # "Tüm testler geçti, production'a alındı"
)
```

---

### `list_agent_tasks`

Koleksiyona veya duruma göre görevleri filtreler ve listeler.

```
list_agent_tasks(
    collection: str,   # "" = tümü
    status: str        # "" = tümü, "in_progress", "planned", "completed"
)
```

---

### `get_project_state`

PostgreSQL'den koleksiyonun tüm görev durumunu tek sorguda getirir. `state.md` veya `tasks.md` dosyası gerekmez.

```
get_project_state(
    collection: str
)
```

---

### `run_verification_plan`

Build, test ve lint araçlarını çalıştırır. Her kritik değişiklik sonrası zorunludur.

```
run_verification_plan(
    project_path: str,
    run_build: bool,   # varsayılan: True
    run_tests: bool,   # varsayılan: True
    run_lint: bool     # varsayılan: False
)
```

**Çıktı:** Her adımın exit code, stdout ve hata özeti. Başarısız step varsa sonraki adıma geçilmez.

---

### `get_control_plane_stats`

Sistemin anlık performans metriklerini döner.

```
get_control_plane_stats()
```

**Dönen metrikler:**
- Tool başına ortalama latency (ms)
- Cache hit rate (Redis)
- Hata oranı (son 100 çağrı)
- Aktif koleksiyonlar ve bellek boyutu
- Prometheus endpoint durumu

---

## 6. Agent Docs Plane

### `index_agent_docs`

`Agent.md`, `GraphMcp.md`, `CLAUDE.md` gibi ajan protokol dosyalarını özel bir dokümantasyon index'ine alır. Kod index'inden ayrıdır.

```
index_agent_docs(
    project_path: str
)
```

---

### `search_agent_docs`

Ajan kuralları, protokoller ve operasyonel kılavuzları arar.

```
search_agent_docs(
    query: str,
    collection: str,
    layer: str | None,         # "protocol", "workflow", "rule"
    doc_priority: str | None   # "high", "medium", "low"
)
```

---

## 7. Kullanım Senaryoları

### Senaryo A: Yeni Feature Geliştirme

```
1. incremental_index_project(project_path, changed_files=None)
2. recall_memory("benzer feature implementasyonu", collection=...)
3. search_decisions("ilgili mimari kararlar", collection=...)
4. execute_agent_task(goal="...", project_path=..., collection=...)
   # İçeriden: search_code → analyze_change_impact → security_scan →
   #           create_agent_task → run_verification_plan
5. store_decision_memory(title="...", content="öğrenilen...")
```

### Senaryo B: Kritik Refactor

```
1. code_clone_detection(collection=...)          # ZORUNLU — önce clone tespiti
2. refactor_suggestions(project_path=...)        # code smell analizi
3. analyze_change_impact(project_path, changed_paths=[...])
4. execute_agent_task(goal="refactor ...")
5. run_verification_plan(project_path, run_build=True, run_tests=True, run_lint=True)
6. run_memory_cycle(collection=...)              # hafızayı temizle
```

### Senaryo C: Güvenlik Denetimi

```
1. security_scan(project_path=..., collection=...)
# CRITICAL varsa: düzelt → tekrar scan → ancak devam et
2. grep_exact_string("eval(", collection=..., file_extension="py")
3. grep_exact_string("os.system", collection=..., file_extension="py")
4. store_decision_memory(title="Security audit 2025-06", content="...")
```

### Senaryo D: Kod Keşfi

```
1. search_code("Order akışındaki validasyon mantığı", collection=...)
# Yeterli değilse:
2. search_repo_architecture("Order modülü bağımlılıkları", collection=...)
# Hala bulunamazsa (3. başarısızlık):
3. grep_exact_string("ValidateOrder", collection=..., file_extension="cs")
```

### Senaryo E: Oturum Başlangıcı

```
1. list_projects()                              # kayıtlı koleksiyonları gör
2. get_control_plane_stats()                    # sistem durumu
3. incremental_index_project(project_path)      # güncelliği sağla
4. summarize_repository(project_path, collection) # projeye genel bakış
5. list_agent_tasks(collection, status="in_progress") # açık görevler
```

---

## 8. Operasyonel Protokoller

### Ajan Çalışma Modları

Ajan aynı anda yalnızca tek modda çalışır:

| Mod | Araçlar |
|---|---|
| **DISCOVERY** | `search_code`, `grep_exact_string`, `search_repo_architecture`, `summarize_repository`, `list_projects` |
| **ANALYSIS** | `explain_code`, `analyze_change_impact`, `security_scan`, `refactor_suggestions`, `code_clone_detection` |
| **PLANNING** | `create_agent_task`, `test_suggestion` |
| **EXECUTION** | `execute_agent_task`, `run_verification_plan`, `incremental_index_project` |
| **VALIDATION** | `run_verification_plan`, `get_task_status`, `get_control_plane_stats` |
| **REFLECTION** | `recall_memory`, `search_decisions`, `run_memory_cycle` |

### Token Ekonomisi Kuralları

- Önce özet, sonra detay.
- `search_code` sonucu yeterliyse `explain_code` çağrılmaz.
- Repo-wide arama (`search_code '*'`) son çaredir.
- 3 başarısız retrieval → `grep_exact_string` ile deterministik aramaya geç.
- Context window %70 üzerine çıktığında aggressive summarization zorunludur.

### Stop Conditions

İşlem şu durumlarda durdurulur:
- Aynı hata 3 kez tekrar ederse.
- Retrieval confidence düşükse.
- `security_scan` CRITICAL döndürürse.
- Tool sonuçları birbiriyle çelişiyorsa.
- Ardışık 2 başarısızlık (runaway loop koruması).

### Güvenlik Kuralları

- `.env` dosyaları asla loglanamaz ve okunamaz.
- Secret içerikleri summarize edilemez.
- Production connection string output yasaktır.
- `rm`, `drop`, `truncate` gibi destructive komutlar öncesi explicit user onayı gerekir.
- Migration sonrası schema diff doğrulanmalıdır.

---

## Hızlı Başvuru Tablosu

| Tool | Plane | Kritiklik | Cache |
|---|---|---|---|
| `execute_agent_task` | Orchestration | #1 | Hayır |
| `search_code` | Knowledge | Yüksek | Redis (exact + semantic) |
| `grep_exact_string` | Knowledge | Yüksek | Hayır |
| `index_project` | Knowledge | Yüksek | Hayır |
| `incremental_index_project` | Knowledge | Yüksek | Hayır |
| `explain_code` | Knowledge | Orta | Hayır |
| `search_repo_architecture` | Knowledge | Orta | Hayır |
| `summarize_repository` | Knowledge | Orta | Hayır |
| `analyze_change_impact` | Knowledge | Yüksek | Hayır |
| `register_project` | Knowledge | Yüksek | Hayır |
| `list_projects` | Knowledge | Düşük | Hayır |
| `recall_memory` | Memory | Yüksek | Hayır |
| `search_decisions` | Memory | Yüksek | Hayır |
| `store_memory` | Memory | Orta | Hayır |
| `store_decision_memory` | Memory | Yüksek | Hayır |
| `compact_memory` | Memory | Orta | Hayır |
| `run_memory_cycle` | Memory | Orta | Hayır |
| `security_scan` | Analysis | KRİTİK | Hayır |
| `refactor_suggestions` | Analysis | Orta | Hayır |
| `test_suggestion` | Analysis | Orta | Hayır |
| `code_clone_detection` | Analysis | Orta | Hayır |
| `create_agent_task` | Execution | Orta | Hayır |
| `get_task_status` | Execution | Düşük | Hayır |
| `complete_task` | Execution | Orta | Hayır |
| `list_agent_tasks` | Execution | Düşük | Hayır |
| `run_verification_plan` | Execution | Yüksek | Hayır |
| `get_control_plane_stats` | Control | Düşük | Hayır |

---

*GraphRagMCP V2 — Koleksiyon: `WareLogisticcBYS` — Protocol: SOTA GraphRAG V2*
