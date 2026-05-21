# GraphRagMCP v2

## Amaç

Bu belge, `GraphRagMCP` projesinin v2 mimari tasarım dokümanıdır.

Amaç:

- mevcut sistemi çöpe atmadan güçlendirmek
- `graph-mcp`'yi yalnızca bir retrieval server olmaktan çıkarıp
- repo'ya hakim, hafızası olan, güvenli çalışan ve ölçülebilir bir yardımcı ajan altyapısına dönüştürmektir

Bu belge özellikle şu sorulara cevap verir:

- Hangi klasör yapısına geçilmeli?
- Hangi yeni tool'lar eklenmeli?
- Hangi veri modeli kurulmalı?
- Hangi şeyler özellikle eklenmemeli?
- Faz faz uygulanacak plan ne olmalı?

---

## V2 Hedefi

`GraphRagMCP v2`, şu 5 rolü tek sistem içinde yerine getirmelidir:

1. Repo bilgi sistemi
2. Hafıza katmanı
3. Durumlu ajan orkestratörü
4. Güvenli execution denetleyicisi
5. Ölçülebilir kalite ve maliyet kontrol düzlemi

Bu yüzden v2 mimarisi şu katmanlar üzerinde tanımlanır:

1. Knowledge Plane
2. Memory Plane
3. Agent Plane
4. Execution Plane
5. Control Plane

---

## Mevcut Durumdan Çıkan Mimari Notlar

Bugünkü projede güçlü bir çekirdek zaten vardır:

- AST chunking var
- graph extraction var
- hybrid retrieval var
- incremental indexing var
- agent docs indexing var
- basic episodic memory var
- Redis, Qdrant, Neo4j, PostgreSQL ayrıştırılmış durumda

Ancak aşağıdaki yapısal eksikler büyümeyi zorlaştırır:

- `src/` ile `src/src/` arasında duplicate kod yapısı var
- repo bilgisi için resmi ontology yok
- orchestration state yok
- approval gate yok
- execution sandbox yok
- benchmark/eval sistemi yok
- memory tipi ayrışmamış
- retrieval ile action aynı soyut seviyede ele alınıyor

V2, bu eksikleri çözerken mevcut akışı korumalıdır.

---

## Mimari İlkeler

V2 boyunca değiştirilmeyecek tasarım ilkeleri:

1. Önce bilgi modeli, sonra ajan davranışı
2. Retrieval ile execution aynı katman değildir
3. Memory, chat history değildir
4. Her önemli sonuç provenance taşımalıdır
5. Tool sayısı değil, tool tasarımı önemlidir
6. Eval olmadan iyileştirme kabul edilmez
7. Full model fine-tune ilk çözüm değildir

---

## Hedef Klasör Yapısı

V2 için önerilen klasör yapısı:

```text
src/
  mcp/
    server.py
    tool_registry.py
    schemas.py

  indexing/
    chunkers/
      ast_chunker.py
      markdown_chunker.py
    extractors/
      graph_extractor.py
      summary_extractor.py
      ontology_extractor.py
    pipelines/
      full_index_pipeline.py
      incremental_index_pipeline.py
      docs_index_pipeline.py
    normalization/
      path_mapper.py
      language_detector.py

  retrieval/
    search/
      hybrid_search.py
      local_search.py
      global_search.py
      impact_search.py
    ranking/
      reranker.py
      deduplicator.py
      scorer.py
    context/
      context_builder.py
      compressor.py
      token_budget.py

  memory/
    models/
      memory_models.py
      provenance_models.py
    stores/
      episodic_store.py
      semantic_memory_store.py
      decision_memory_store.py
      temporal_memory_store.py
    services/
      memory_writer.py
      memory_recall.py
      memory_compaction.py

  ontology/
    schema.py
    builders.py
    summarizers.py

  agent/
    orchestrator/
      state_machine.py
      checkpoints.py
      approvals.py
    nodes/
      planner.py
      retriever.py
      explainer.py
      editor.py
      verifier.py
      reviewer.py
      summarizer.py
    tasks/
      task_models.py
      task_store.py

  execution/
    sandbox/
      runtime_manager.py
      mount_policy.py
      tool_policy.py
    runners/
      command_runner.py
      test_runner.py
      build_runner.py

  control/
    models/
      gateway.py
      router.py
      budgets.py
    observability/
      tracer.py
      metrics.py
      audit.py
    evals/
      datasets/
      runners/
      scoring/

  storage/
    qdrant_store.py
    neo4j_store.py
    redis_store.py
    postgres_store.py

  shared/
    config.py
    errors.py
    types.py
    utils.py
```

Not:

- `src/src/` tamamen kaldırılmalı
- tool tanımları `server.py` içinde tutulsa da gerçek iş mantığı katmanlara bölünmeli
- `mcp_server.py` tek dev dosya olmaktan çıkarılmalı

---

## Bilinçli Refactor Hedefleri

İlk büyük temizlik işleri:

1. `src/src/` duplicate ağacını kaldır
2. `mcp_server.py` içindeki tool implementasyonlarını servis/pipeline katmanına ayır
3. retrieval ile indexing kodlarını fiziksel olarak ayır
4. memory API'sini tool API'den ayır
5. config erişimini merkezi hale getir

Bu refactor yapılmadan v2 genişletmesi teknik borcu artırır.

---

## Veri Modeli

### 1. Repo Ontology

V2'de graph sadece `Module -> Class -> Function` ilişkisiyle sınırlı kalmamalıdır.

Önerilen temel node tipleri:

- `Repository`
- `Module`
- `Package`
- `File`
- `Class`
- `Interface`
- `Function`
- `Method`
- `Endpoint`
- `Entity`
- `DTO`
- `Config`
- `Migration`
- `UIComponent`
- `BusinessRule`
- `Decision`
- `Owner`

Önerilen temel edge tipleri:

- `CONTAINS`
- `OWNS`
- `CALLS`
- `IMPLEMENTS`
- `DEPENDS_ON`
- `EXPOSES_ENDPOINT`
- `USES_CONFIG`
- `MUTATES_ENTITY`
- `READS_ENTITY`
- `RELATES_TO_RULE`
- `AFFECTS_MODULE`
- `SUPERSEDES_DECISION`

### 2. Summary Katmanları

Her repo için şu summary seviyeleri oluşturulmalıdır:

- `file_summary`
- `module_summary`
- `subsystem_summary`
- `repo_summary`
- `decision_summary`

Bu summary katmanları retrieval için ayrı collection/payload olarak tutulmalıdır.

### 3. Provenance Modeli

Her retrieval ve memory kaydında şu alanlar bulunmalıdır:

- `project`
- `collection`
- `commit_sha`
- `branch`
- `source_path`
- `source_type`
- `indexed_at`
- `valid_from`
- `valid_to`
- `confidence`
- `generated_by`

### 4. Memory Tipleri

Memory tek tip olmamalı.

Önerilen memory türleri:

- `episodic`
- `semantic`
- `decision`
- `incident`
- `task`
- `temporal_fact`

---

## Yeni Tool Listesi

V2'de tool genişlemesi kontrollü yapılmalıdır.

### Korunacak Mevcut Tool'lar

- `index_project`
- `incremental_index_project`
- `search_code`
- `explain_code`
- `index_agent_docs`
- `search_agent_docs`
- `store_memory`
- `recall_memory`

### Yeni Eklenecek Tool'lar

#### 1. `search_repo_architecture`

Amaç:

- broad summary
- subsystem analysis
- katman ilişkileri
- entrypoint zinciri

Örnek:

```text
search_repo_architecture(query="auth akışı ve tenant geçiş mekanizması", collection="Vendoris")
```

#### 2. `analyze_change_impact`

Amaç:

- değişen dosyanın hangi modülleri etkilediğini bulmak
- riskli call-chain ve config etkilerini çıkarmak

Örnek:

```text
analyze_change_impact(paths=["/projects/Vendoris/backend/src/.../AuthService.cs"], collection="Vendoris")
```

#### 3. `summarize_repository`

Amaç:

- onboarding için repo özeti
- subsystem map
- teknoloji envanteri

#### 4. `search_decisions`

Amaç:

- geçmiş mimari kararları
- incident sonrası alınmış önlemleri
- commit bağlamlı notları aramak

#### 5. `store_decision_memory`

Amaç:

- önemli mimari ve operasyonel kararları provenance ile kaydetmek

#### 6. `run_verification_plan`

Amaç:

- agent tarafından önerilen build/test/lint planını güvenli execution katmanında koşturmak

#### 7. `resume_task`

Amaç:

- yarım kalmış uzun ajan görevini checkpoint'ten devam ettirmek

### Şimdilik Eklenmeyecek Tool'lar

- `auto_open_pr`
- `auto_merge_fix`
- `mass_edit_repo`
- `self_rewrite_prompts`
- `spawn_n_agents`

---

## Query Mimarisi

V2 query sistemi dört seviyeli olmalıdır:

### 1. Local Search

En iyi kullanım:

- belirli fonksiyon
- belirli dosya
- config lookup

### 2. Relational Search

En iyi kullanım:

- call-chain
- dependency zinciri
- impact analysis

### 3. Architectural Search

En iyi kullanım:

- modül ilişkileri
- subsystem sınırları
- domain flow

### 4. Global Search

En iyi kullanım:

- onboarding
- repo summary
- "bu proje nasıl organize edilmiş?"

Bu query tipleri farklı retrieval stratejileri kullanmalıdır.

---

## Memory Mimarisi

### Memory Yazma Kuralları

Memory sadece önemli durumlarda yazılmalı:

- mimari karar
- tekrar eden hata
- incident çözümü
- kullanıcı tercihi
- repo kuralları
- uzun görev özeti

### Memory Geri Çağırma Kuralları

Memory doğrudan retrieval yerine körlemesine bind edilmemeli.

Önce:

- query tipi sınıflandırılmalı
- ilgili memory türü seçilmeli
- confidence ve freshness kontrol edilmeli

### Temporal Memory

Özellikle şu alanlar zaman duyarlı tutulmalı:

- deployment bilgileri
- branch/release durumu
- geçici workaround'lar
- known issue kayıtları
- deprecated kararlar

---

## Agent Orchestration Tasarımı

V2'de önerilen temel görev akışı:

```text
task_create
  -> task_classify
  -> retrieve_context
  -> explain_context
  -> propose_plan
  -> approval_gate?
  -> execute_step
  -> verify_step
  -> update_index
  -> summarize_result
  -> write_memory
  -> task_close
```

### Task State'leri

- `PLANNED`
- `RETRIEVING`
- `ANALYZING`
- `WAITING_APPROVAL`
- `EXECUTING`
- `VERIFYING`
- `SUMMARIZING`
- `DONE`
- `FAILED`
- `ABORTED`

### Approval Gerekli Olan Noktalar

- destructive command
- bulk edit
- migration
- dependency install
- production-like verification
- external network call

---

## Execution Plane Tasarımı

Execution plane için öneri:

- retrieval container ile execution container ayrılmalı
- repo bazlı image profilleri tanımlanmalı
- mount policy açık olmalı
- allowed command categories tanımlanmalı

Örnek execution profilleri:

- `python-repo`
- `dotnet-repo`
- `node-repo`
- `polyglot-repo`

Her profile şu metadata eklenmeli:

- build command
- test command
- lint command
- package manager
- language detectors

---

## Control Plane Tasarımı

### Model Gateway

Tek provider bağımlılığı azaltılmalı.

Önerilen sorumluluklar:

- provider selection
- fallback routing
- cost tracking
- latency tracking
- per-task model policy

### Budgeting

Var olan `RequestBudget` genişletilmeli:

- tool budget
- model budget
- task budget
- daily project budget

### Audit

Audit trail şu olayları saklamalı:

- retrieval request
- selected context
- execution command
- approval decision
- index invalidation
- memory write

---

## Eval Sistemi

V2'de eval zorunludur.

### Gerekli Eval Setleri

#### 1. Retrieval Eval

Örnek sorular:

- "auth flow nerede başlıyor?"
- "tenant switch hangi middleware ile yapılıyor?"
- "bu config hangi endpoint'i etkiliyor?"

Ölçümler:

- hit@k
- MRR
- source diversity

#### 2. Explanation Eval

Ölçümler:

- answer faithfulness
- missing dependency rate
- hallucination rate

#### 3. Impact Analysis Eval

Ölçümler:

- true affected file coverage
- false positive rate

#### 4. Memory Eval

Ölçümler:

- recall precision
- stale memory rate
- accepted memory usage

#### 5. Agent Task Eval

Ölçümler:

- task completion rate
- human override rate
- verification success rate
- rollback need rate

---

## Faz Bazlı Uygulama Planı

## Faz 0: Temizlik ve Refactor Hazırlığı

Amaç:

- duplicate yapıları temizlemek
- v2 için zemin hazırlamak

İşler:

1. `src/src/` kaldır
2. `mcp_server.py` böl
3. config erişimini merkezileştir
4. tool registration katmanı çıkar

Teslim kriteri:

- tek kaynak ağaç
- aynı işi yapan duplicate dosya yok

## Faz 1: Knowledge Plane v2

Amaç:

- ontology + summary katmanlarını kurmak

İşler:

1. ontology schema tanımla
2. summary extractor ekle
3. repo/module summary indeksle
4. `search_repo_architecture` ekle
5. `summarize_repository` ekle

Teslim kriteri:

- repo summary sorguları tutarlı dönüyor

## Faz 2: Impact ve Provenance

Amaç:

- değişiklik etkisini ölçen retrieval
- provenance standardı

İşler:

1. provenance payload genişlet
2. `analyze_change_impact` ekle
3. impact scoring kur
4. graph relation türlerini artır

Teslim kriteri:

- bir dosya değişikliği için etkili modüller çıkarılabiliyor

## Faz 3: Memory Plane v2

Amaç:

- typed ve temporal memory

İşler:

1. memory türlerini ayır
2. decision memory ekle
3. temporal memory ekle
4. freshness ve confidence kuralları ekle

Teslim kriteri:

- memory recall daha tutarlı ve provenance'lı

## Faz 4: Agent Plane v2

Amaç:

- stateful task orchestration

İşler:

1. task model oluştur
2. checkpoint store ekle
3. approval gate ekle
4. `resume_task` ekle

Teslim kriteri:

- uzun görevler durdurulup devam edebiliyor

## Faz 5: Execution Plane v2

Amaç:

- güvenli build/test/edit execution

İşler:

1. sandbox runtime manager
2. repo profile sistemi
3. `run_verification_plan`
4. audit + rollback metadata

Teslim kriteri:

- build/test işleri kontrollü ve tekrar üretilebilir

## Faz 6: Eval ve Control Plane

Amaç:

- ölçülebilir kalite ve maliyet

İşler:

1. eval dataset oluştur
2. eval runner yaz
3. gateway abstraction kur
4. dashboard metric modeli çıkar

Teslim kriteri:

- sistem değişiklikleri benchmark ile ölçülebiliyor

---

## Teknik Riskler

En önemli teknik riskler:

1. Orchestration eklenirken retrieval çekirdeğini gereksiz karmaşıklaştırmak
2. Ontology'yi fazla genişletip index maliyetini patlatmak
3. Memory'yi kontrolsüz büyütmek
4. Eval olmadan "daha akıllı oldu" sanmak
5. Execution katmanını retrieval ile aynı süreçte eritmek

---

## Mimari Riskler

En önemli mimari riskler:

1. Her başarılı açık kaynak projeden biraz ekleyip bütünlüğü bozmak
2. Tool sayısını artırıp davranış modelini netleştirmemek
3. Repo-özel bilgi ile genel retrieval mantığını ayırmamak
4. Duplicate veri katmanları kurmak

---

## Güvenlik Riskleri

V2'de dikkat edilmesi gereken güvenlik başlıkları:

- command execution policy
- prompt injection via indexed docs
- stale memory misuse
- secret leakage in memory/provenance
- untrusted build/test commands
- unsafe mount topology

Bu yüzden:

- secret scanner indexing sırasında kalmalı
- execution allowlist zorunlu olmalı
- memory write filtreleri eklenmeli

---

## Özellikle Eklenmeyecek Şeyler

V2 kapsamı dışında tutulmalı:

- full autonomous coding swarm
- PR açıp merge eden tam otonom akış
- model fine-tune pipeline
- çok sağlayıcılı devops karmaşası
- gereksiz UI panel çoğaltma

---

## Başarı Ölçütleri

V2'nin başarılı sayılması için:

1. Broad ve architectural sorularda retrieval kalitesi görünür şekilde artmalı
2. Değişiklik sonrası impact analysis güvenilir olmalı
3. Hafıza tekrar eden görevlerde gerçek fayda sağlamalı
4. Uzun görevler checkpoint/resume ile sürdürülebilmeli
5. Build/test execution güvenli ve izlenebilir olmalı
6. Tüm ilerleme eval metrikleriyle ölçülebilmeli

---

## Onaya Sunulan Karar

Önerilen karar:

`GraphRagMCP v2`, yeni bir ürün gibi değil, mevcut sistemin katmanlı evrimi olarak geliştirilmelidir.

Başlangıç fazı olarak önerilen iş:

1. Faz 0
2. Faz 1
3. Faz 2

Yani hemen yapılması gereken:

- duplicate temizliği
- server decomposition
- ontology + summary layers
- impact/provenance temeli

Bu yapılmadan orchestration ve sandbox katmanına geçmek erken olur.

---

## Sonraki Adım

Bu belge onaylanırsa bir sonraki çıktı şu olmalıdır:

`GraphRagMCP-v2-Implementation-Backlog.md`

Bu backlog şu içeriği taşımalıdır:

- issue benzeri maddeler
- dosya bazlı etki alanı
- dependency sırası
- acceptance criteria
- risk notları
- test planı
