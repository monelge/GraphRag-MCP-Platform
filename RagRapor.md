# RAG Raporu

## Amaç

Bu raporun amacı, `GraphRagMCP` projesini daha güçlü, sürdürülebilir ve gerçekten proje-hakim bir yardımcı ajana dönüştürmek için hangi mimari yönlerin benimsenmesi gerektiğini değerlendirmektir.

Buradaki hedef:

- Frankenstein tarzı araç yığını kurmak değil
- mevcut çekirdeği çöpe atmak değil
- proje bağlamını anlayan, zamanla öğrenen, güvenli çalışan bir ajan altyapısı kurmaktır

Kısa sonuç:

`GraphRagMCP` bugün zayıf bir temel değildir. Ancak şu anda daha çok iyi bir indeksleme ve arama sunucusudur. Hedeflenen yapı ise bundan daha fazlasıdır: repo bilgisini taşıyan, hafıza oluşturan, kontrollü şekilde iş yapan, uzun görevleri yönetebilen bir ajan sistemi.

Bu nedenle öneri:

`GraphRagMCP`'yi bırakmak değil, onu 4 ana katmana evriltmektir:

1. Knowledge Plane
2. Memory Plane
3. Agent Plane
4. Control + Execution Plane

---

## Mevcut Sistemin Güçlü Yanları

Mevcut projede zaten doğru yönde önemli yapıtaşları vardır:

- AST + graph + vector birlikte kullanılıyor
- `incremental_index_project` ile artımlı indeksleme var
- `search_code` ve `explain_code` ayrımı mevcut
- agent docs ayrı indeksleniyor
- Redis cache, Neo4j graph, Qdrant retrieval ve PostgreSQL trace ayrışmış durumda
- cost guardrail başlangıcı var
- pipeline tracer var

Bu nedenle sistemin sıfırdan başka bir agent framework'e taşınması gerekmez.

Doğru yaklaşım:

- mevcut çekirdeği korumak
- eksik katmanları sistematik biçimde eklemek

---

## Araştırmada İncelenen Güçlü Projeler

Araştırma sırasında, yüksek benimsenme görmüş ve benzer problemleri çözmeye çalışan projeler incelendi.

GitHub yıldızları 2026-05-13 itibarıyla:

- MCP Servers: 85.5k
- OpenHands: 73.2k
- Mem0: 55.5k
- LiteLLM: 46.7k
- Aider: 44.7k
- GraphRAG: 32.9k
- LangGraph: 31.9k
- Graphiti: 26k
- Roo Code: 24k

İncelenen ana kaynaklar:

- `GraphRAG`
  - GitHub: https://github.com/microsoft/graphrag
  - Query Overview: https://microsoft.github.io/graphrag/query/overview/
  - Prompt Tuning: https://microsoft.github.io/graphrag/prompt_tuning/overview/

- `LangGraph`
  - GitHub: https://github.com/langchain-ai/langgraph
  - Durable Execution: https://docs.langchain.com/oss/python/langgraph/durable-execution
  - Interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts

- `Aider`
  - GitHub: https://github.com/Aider-AI/aider

- `OpenHands`
  - GitHub: https://github.com/OpenHands/OpenHands
  - Runtime Architecture: https://docs.openhands.dev/openhands/usage/architecture/runtime

- `Mem0`
  - GitHub: https://github.com/mem0ai/mem0
  - Memory Evaluation: https://docs.mem0.ai/core-concepts/memory-evaluation

- `Graphiti`
  - GitHub: https://github.com/getzep/graphiti

- `LiteLLM`
  - GitHub: https://github.com/BerriAI/litellm

- `Model Context Protocol Servers`
  - GitHub: https://github.com/modelcontextprotocol/servers

---

## Bu Projelerden Çıkan Ana Dersler

### 1. GraphRAG'den Alınacak Esas Fikir

`GraphRAG`'ın değeri yalnızca graph üretmesi değildir.

Önemli olan:

- indexing workflow'larının net tanımlanması
- query tiplerinin ayrıştırılması
- local search ve global search ayrımı
- domain-adapted prompt tuning önerisi

`GraphRagMCP` için karşılığı:

- sadece chunk + relation üretmek yetmez
- repo summary, module summary, architectural search gibi katmanlar da gerekir

### 2. LangGraph'tan Alınacak Esas Fikir

`LangGraph`'ın en güçlü tarafı stateful orchestration'dır.

Sağladığı şeyler:

- durable execution
- checkpointing
- resume
- human-in-the-loop interrupt
- uzun görevleri güvenli yönetme

`GraphRagMCP` için karşılığı:

- bugün retrieval iyi olabilir
- ama uzun görev yapan ajan davranışı için yürütme durumu yok
- bu eksik katman tamamlanmalıdır

### 3. Aider'dan Alınacak Esas Fikir

`Aider` büyük depolarda codebase map + git-native çalışma döngüsü ile güçleniyor.

Özellikle önemli olan:

- codebase map
- git entegrasyonu
- değişiklik sonrası doğrulama
- diff-temelli çalışma

`GraphRagMCP` için karşılığı:

- retrieval sadece "kod bulma" olmamalı
- değişiklik, diff, etki analizi ve verification loop ile bağlanmalı

### 4. OpenHands'tan Alınacak Esas Fikir

`OpenHands` agent execution'ı host sistem üzerinde serbest bırakmıyor.

Önemli yaklaşım:

- sandboxed runtime
- reproducible environment
- project-specific execution image
- güvenli araç erişimi

`GraphRagMCP` için karşılığı:

- retrieval ayrı, execution ayrı güvenlik katmanına sahip olmalı
- yazan/test eden ajan için sandbox şart

### 5. Mem0 ve Graphiti'den Alınacak Esas Fikir

`Mem0` ve `Graphiti` ortak olarak şunu gösteriyor:

- hafıza sadece chat geçmişi değildir
- user/session/agent state ayrılmalıdır
- zaman boyutu önemlidir
- provenance çok kritiktir

`Graphiti` ayrıca önemli bir fark koyuyor:

- static graph yerine temporal context graph
- değişen bilgiyi yok etmek yerine geçerlilik penceresi ile yönetmek

`GraphRagMCP` için karşılığı:

- memory sadece episodic not olmamalı
- karar, olay, mimari bilgi, commit bağı, zaman ve güven skoru ile tutulmalı

### 6. LiteLLM'den Alınacak Esas Fikir

`LiteLLM` çok-provider ortamında operasyonel istikrar sağlıyor.

Önemli tarafları:

- unified API
- provider abstraction
- spend tracking
- guardrails
- load balancing

`GraphRagMCP` için karşılığı:

- tek API sağlayıcısına sıkı bağımlılık azaltılmalı
- model seçimi kontrol düzlemine taşınmalı

### 7. MCP Ekosisteminden Alınacak Esas Fikir

`MCP` tarafında en doğru yön, açık tool protokolünü korumaktır.

`GraphRagMCP` için karşılığı:

- kendi sunucunu koru
- tool yüzeyini bilinçli genişlet
- shell binary gibi çalışan kapalı bir sistem kurma

---

## Mevcut Sistemde Eksik Olan Temel Katmanlar

Bugün sistemde eksik olan esas başlıklar:

1. Repo-özel bilgi modeli
2. Zaman boyutlu hafıza
3. Durumlu ajan orkestrasyonu
4. Human approval noktaları
5. Güvenli execution sandbox
6. Sistematik evaluation altyapısı
7. Git-native çalışma döngüsü
8. Model/provider abstraction

---

## Önerilen Hedef Mimari

Öneri, tek ürün içinde ama çok katmanlı bir mimari:

### A. Knowledge Plane

Bu katmanda mevcut `GraphRagMCP` çekirdeği korunur ve zenginleştirilir.

Eklenmesi gerekenler:

- repo ontology
  - `Module`
  - `Service`
  - `Endpoint`
  - `Entity`
  - `Config`
  - `Migration`
  - `UIFlow`
  - `BusinessRule`
  - `Owner`

- multi-layer index
  - raw chunk
  - symbol graph
  - file summary
  - module summary
  - repo summary
  - decision memory link

- query tiers
  - `local_search`
  - `architectural_search`
  - `global_repo_search`
  - `change_impact_search`

- prompt tuning
  - generic extraction prompt yerine repo ve domain uyarlanmış prompt setleri

Bu katmanda hedef:

- sadece kod parçaları değil
- repo'nun kavramsal modeli de sorgulanabilir hale gelsin

### B. Memory Plane

Mevcut `store_memory` / `recall_memory` başlangıçtır, ama tek başına yeterli değildir.

Eklenmesi gereken hafıza türleri:

- `user_memory`
- `repo_memory`
- `decision_memory`
- `incident_memory`
- `task_memory`
- `temporal_fact_memory`

Her memory kaydında olması gerekenler:

- proje adı
- modül
- commit SHA
- tarih
- provenance
- güven skoru
- geçerlilik durumu

Hedef:

- ajan yalnızca anlık retrieval yapmasın
- proje geçmişini, kararları ve tekrar eden sorunları da hatırlasın

### C. Agent Plane

Bu katmanda retrieval server, durumlu ajana dönüşür.

Önerilen roller:

- planner
- retriever
- explainer
- editor
- verifier
- reviewer
- memory_writer

Ama bunlar bağımsız dağınık ajanlar olarak değil, tek orchestrator altında node'lar olarak tasarlanmalıdır.

Örnek akış:

`plan -> retrieve -> explain -> propose -> approve? -> execute -> verify -> index -> summarize -> memory_write`

### D. Execution Plane

Kod yazan ve test eden ajan, retrieval ile aynı güvenlik modelinde olmamalıdır.

Eklenmesi gerekenler:

- izole runtime container
- repo-specific base image
- tool allowlist
- command policy
- build/test sandbox
- rollback metadata

Hedef:

- ajan proje üzerinde iş yapabilsin
- ama bunu host sisteme risk taşımadan yapsın

### E. Control Plane

Bu katman operasyon ve ölçüm için gerekir.

Eklenmesi gerekenler:

- model gateway
- provider routing
- per-tool budget
- latency/cost metrics
- approval policy
- audit trail
- eval harness

Hedef:

- sistemin sadece "çalışması" değil
- yönetilebilir ve gözlemlenebilir olmasıdır

---

## Sisteme Eklenmesi Gerekenler

Kesinlikle değerlendirilmesi gerekenler:

- repo ontology
- global repo search
- change impact search
- temporal memory
- provenance standardı
- prompt tuning pipeline
- checkpoint/resume
- HITL approval gates
- sandbox runtime
- eval suite
- model gateway

---

## Şimdilik Eklenmemesi Gerekenler

Frankenstein etkisi yaratmamak için şu şeyler şimdilik eklenmemelidir:

- gösteriş amaçlı tam multi-agent "dev team" kurgusu
- çok fazla yeni MCP tool
- doğrulanmamış autonomous PR bot
- tam model fine-tune
- her trende göre yeni graph abstraction

Önce çekirdek sistem kuvvetlenmeli, sonra genişletme düşünülmelidir.

---

## Neden Fine-Tune İlk Adım Olmamalı

Tam model fine-tune bu aşamada önerilmez.

Nedenleri:

- repo bilgisi sürekli değişir
- fine-tune hızlı bayatlar
- hatalı bilgi modelin içine gömülürse düzeltmesi zor olur
- maliyet yüksektir
- verimliliği ancak güçlü eval sistemi varsa anlamlı ölçülür

Önce güçlendirilmesi gerekenler:

- retrieval
- memory
- policy
- evaluation
- orchestration

Sonraki aşamada düşünülebilecek daha kontrollü seçenekler:

- reranker fine-tune
- query classifier fine-tune
- repo-specific prompt packs
- memory scoring modeli

---

## Faz Analizi

### Faz 1: Repository Intelligence Core

#### Fazın amacı

Mevcut sistemi "kod arama" katmanından "repo bilgi sistemi" katmanına yükseltmek.

#### Sisteme etkisi

- bilgi kalitesi artar
- broad ve architectural sorgular daha tutarlı hale gelir
- proje özeti üretimi güçlenir

#### Etkilenecek modüller

- `src/chunker/*`
- `src/pipeline/*`
- `src/storage/neo4j_store.py`
- `src/storage/qdrant_store.py`
- `src/mcp_server.py`

#### Teknik riskler

- index maliyeti artabilir
- özet katmanları yanlış tasarlanırsa duplicate veri üretilebilir

#### Mimari riskler

- ontology çok karmaşık kurulursa bakım zorlaşır

#### Güvenlik riskleri

- düşük

#### Performans etkileri

- index sırasında maliyet artar
- sorgu sırasında doğru katman kullanılırsa kalite artışı sağlar

#### Mevcut sistemle uyumluluk

- yüksek

### Faz 2: Stateful Agent Runtime

#### Fazın amacı

Uzun görevleri checkpoint/resume ile yönetebilen ajan orkestrasyonu kurmak.

#### Sisteme etkisi

- tek-shot araçtan çok-adımlı ajana geçiş olur

#### Etkilenecek modüller

- yeni orchestration katmanı
- task state storage
- memory integration

#### Teknik riskler

- karmaşıklık hızla artabilir

#### Mimari riskler

- node sınırları yanlış çizilirse debugging zorlaşır

#### Güvenlik riskleri

- approval gate yoksa yanlış action riskini artırır

#### Performans etkileri

- latency artabilir
- ama güvenilirlik ciddi artar

#### Mevcut sistemle uyumluluk

- orta-yüksek

### Faz 3: Safe Execution

#### Fazın amacı

Kod yazma ve test çalışma adımlarını güvenli sandbox'a almak.

#### Sisteme etkisi

- agent action güvenliği artar
- reproducibility iyileşir

#### Etkilenecek modüller

- runtime image
- execution policy
- verification flow

#### Teknik riskler

- sandbox yönetimi karmaşıklaşabilir

#### Mimari riskler

- retrieval ve execution sorumlulukları karıştırılırsa tasarım bozulur

#### Güvenlik riskleri

- iyi uygulanırsa risk azaltır

#### Performans etkileri

- ek runtime overhead oluşturur

#### Mevcut sistemle uyumluluk

- orta

### Faz 4: Evaluation ve Self-Improvement

#### Fazın amacı

Sistemin gerçekten daha iyi olup olmadığını ölçmek.

#### Sisteme etkisi

- sezgisel geliştirmeden ölçülebilir geliştirmeye geçilir

#### Etkilenecek modüller

- benchmark setleri
- eval harness
- metric dashboard

#### Teknik riskler

- benchmark hazırlığı zaman alır

#### Mimari riskler

- yanlış metrikler sistemi yanlış optimize ettirir

#### Güvenlik riskleri

- düşük

#### Performans etkileri

- doğrudan runtime etkisi yok

#### Mevcut sistemle uyumluluk

- çok yüksek

---

## Önerilen Uygulama Sırası

Öncelik sırası:

1. Repo ontology + summary layers
2. Global search + impact analysis
3. Temporal memory + provenance
4. Durable orchestration + HITL
5. Sandbox execution
6. Eval harness
7. Model gateway

Bu sıralama bilinçlidir.

Çünkü:

- önce bilgi modeli netleşmeli
- sonra ajan o bilgi modeli üzerinde çalışmalı
- sonra execution güvenli hale gelmeli
- en sonda provider bağımsızlaştırma ve optimizasyon yapılmalı

---

## Implementasyon Kuralları

Bu dönüşüm yapılırken şu kurallar korunmalıdır:

- mevcut retrieval çekirdeği çöpe atılmamalı
- gereksiz framework bağımlılığı eklenmemeli
- her katman için net sorumluluk sınırı çizilmeli
- graph, memory ve execution aynı abstraction altında ezilmemeli
- duplication yaratacak paralel veri modeli kurulmamalı
- prompt tuning ile başlanmalı, full fine-tune ile değil
- eval olmadan "gelişti" kabul edilmemeli

---

## Sonuç

Net öneri şudur:

`GraphRagMCP`'yi bırakma.

Onu şu doğrultuda evrilt:

- `GraphRAG` gibi daha iyi indexing/query modeli
- `LangGraph` gibi durumlu ajan akışı
- `OpenHands` gibi güvenli sandbox execution
- `Mem0` ve `Graphiti` gibi hafıza + provenance + temporal context
- `LiteLLM` gibi kontrol katmanı
- `MCP` gibi açık tool protokolü

Ama bunları dağınık biçimde değil, tek ürün içinde, tek operasyon modeliyle birleştir.

Bu yaklaşım:

- sana hakim bir yardımcı ajan üretir
- projeye hakim bir repository intelligence katmanı oluşturur
- bakım maliyetini patlatmadan sistemin gücünü artırır

---

## Sonraki Adım Önerisi

Bu raporun ardından en doğru sonraki adım:

`GraphRagMCP v2 Mimari Tasarım Dokümanı`

Bu dokümanda şu başlıklar çıkarılmalıdır:

- hedef klasör yapısı
- yeni tool listesi
- veri modeli
- ontology tasarımı
- memory şeması
- orchestration akışı
- sandbox yaklaşımı
- eval stratejisi
- faz faz implementasyon planı
- özellikle eklenmeyecek şeyler

Bu belge onaylandığında uygulama fazına geçmek çok daha güvenli olacaktır.
