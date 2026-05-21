**İnceleme Bulguları**

## DOSYA
[docker-compose.yml](/Volumes/MacBook/RiderProjects/GraphRagMCP/docker-compose.yml:6), [SERVICES.md](/Volumes/MacBook/RiderProjects/GraphRagMCP/SERVICES.md:7), [README.md](/Volumes/MacBook/RiderProjects/GraphRagMCP/README.md:294), [.env.example](/Volumes/MacBook/RiderProjects/GraphRagMCP/.env.example:1)
## DURUM
- CRITICAL
## PROBLEM
Varsayılan şifreler dokümantasyonda açıkça veriliyor ve servisler host portlarına açılıyor. `neo4j/password`, `graphmcp`, `admin/admin` kombinasyonları production dışı. `qdrant/qdrant:latest`, `dpage/pgadmin4:latest`, `redisinsight:latest` da deterministik değil.
## ETKİSİ
- Güvenlik: yetkisiz erişim ve credential stuffing riski.
- Sürdürülebilirlik: ortamlar arasında sürüm drift’i.
- Developer experience: “çalışıyor” gibi görünür ama güvenli değildir.
## ÇÖZÜM
Tüm default credential’ları kaldırın, UI portlarını varsayılan kapalı yapın, image digest veya sabit sürüm kullanın, production profile ekleyin.
## KOD ÖRNEĞİ
```yaml
profiles: ["dev"]
ports: []
environment:
  NEO4J_AUTH: ${NEO4J_AUTH:?required}
```
## ÖNCELİK
- CRITICAL

## DOSYA
[src/mcp_server.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/mcp_server.py:94), [src/chunker/secret_scanner.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/chunker/secret_scanner.py:1)
## DURUM
- CRITICAL
## PROBLEM
`secret_scanner` mevcut ama kaynak kod indeksleme akışında kullanılmıyor. `index_project()` ham kodu embedleyip Qdrant’a yazıyor; `search_code()` da ham kodu döndürüyor.
## ETKİSİ
- Güvenlik: secret, token, connection string ve private key’ler retrieval/LLM context’ine sızabilir.
- Token tüketimi: gereksiz hassas içerik embed edilip saklanır.
- AI-agent uyumluluğu: poisoned context üretir.
## ÇÖZÜM
Kod chunk’larını da indeksleme öncesi ve çıktı öncesi tarayın; yüksek riskli chunk’ları skip edin, orta risklileri redact edin.
## KOD ÖRNEĞİ
```python
scan = secret_scanner.scan(c.code)
if scan.should_skip:
    continue
c.code = scan.redacted_text
```
## ÖNCELİK
- CRITICAL

## DOSYA
[src/mcp_server.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/mcp_server.py:335), [src/storage/redis_store.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/storage/redis_store.py:86)
## DURUM
- HIGH
## PROBLEM
`get_retrieval` ve `set_retrieval` imzaları `(query, collection)` iken çağrılar `(collection, query)` ile yapılıyor. Exact cache tesadüfen çalışsa da namespace query bazlı oluşuyor; `invalidate_retrieval(collection)` bu key’leri temizleyemiyor. Semantic cache de `__hash__:` akışında hiç hit üretemiyor.
## ETKİSİ
- Performans: stale cache, gereksiz Redis scan, gereksiz embedding/LLM maliyeti.
- Maintainability: API kontratı ile kullanım çelişkili.
- Token tüketimi: bozuk cache yüzünden tekrar işleme.
## ÇÖZÜM
İmza ve tüm çağrıları `collection, query` olacak şekilde normalize edin. Semantic cache lookup’ı da aynı şemaya bağlayın.
## KOD ÖRNEĞİ
```python
async def get_retrieval(self, collection: str, query: str) -> str | None: ...
async def set_retrieval(self, collection: str, query: str, result: str) -> None: ...
```
## ÖNCELİK
- HIGH

## DOSYA
[src/mcp_server.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/mcp_server.py:345)
## DURUM
- HIGH
## PROBLEM
Semantic cache akışında mevcut sorgu embedding’i önce Redis’e yazılıyor, sonra benzer sorgu aranıyor. Bu, sorgunun kendisinin hemen taranmasına yol açıyor; ardından fake `__hash__:` retrieval key’i deneniyor ve miss oluyor.
## ETKİSİ
- Performans: her sorguda gereksiz O(n) scan.
- Token tüketimi: embedding/retrieval tekrarları.
## ÇÖZÜM
Önce benzer cache’i ara, sonra yoksa query embedding’i kaydet. Semantic hit için gerçek retrieval key’ini saklayın.
## KOD ÖRNEĞİ
```python
similar = await _redis.find_similar_cached_query(collection, query_emb)
if not similar:
    await _redis.set_query_embedding(collection, query, query_emb)
```
## ÖNCELİK
- HIGH

## DOSYA
[src/storage/episodic_store.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/storage/episodic_store.py:138), [src/storage/qdrant_store.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/storage/qdrant_store.py:87), [src/search/hybrid_search.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/search/hybrid_search.py:87)
## DURUM
- CRITICAL
## PROBLEM
`store_memory()` `upsert_chunks(..., extra_payload=...)` çağırıyor ama `QdrantStore.upsert_chunks()` böyle bir parametre kabul etmiyor. Ayrıca `episodic_memory` payload’ı `HybridSearcher._format_hit()` içinde ayrı ele alınmıyor. Hafıza özelliği pratikte kırık.
## ETKİSİ
- Mimari: README’de vaat edilen memory katmanı çalışmıyor.
- AI-agent uyumluluğu: karar/hata hafızası yok.
- Maintainability: feature complete görünmesine rağmen broken.
## ÇÖZÜM
`upsert_chunks` için `extra_payload` desteği ekleyin veya memory için ayrı upsert metodu yazın. `HybridSearcher` içine `episodic_memory` formatter ekleyin.
## ÖNCELİK
- CRITICAL

## DOSYA
[src/pipeline/repo_map.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/pipeline/repo_map.py:55), [src/storage/neo4j_store.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/storage/neo4j_store.py:27), [src/storage/redis_store.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/storage/redis_store.py:32), [README.md](/Volumes/MacBook/RiderProjects/GraphRagMCP/README.md:262)
## DURUM
- HIGH
## PROBLEM
`repo_map.py` ölü kod. `neo4j.query`, `redis.set_raw`, `redis.get_raw` yok; `mcp_server.py` içinde de kullanılmıyor. README’de aktif pipeline parçası gibi anlatılıyor.
## ETKİSİ
- Mimari: belge-kod ayrışması.
- AI-agent uyumluluğu: ajan yanlış modüllerin çalıştığını varsayar.
- Maintainability: sahte abstraction.
## ÇÖZÜM
Ya feature’ı gerçekten entegre edin ya da dosyayı ve README bloklarını kaldırın.
## ÖNCELİK
- HIGH

## DOSYA
[src/chunker/ast_chunker.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/chunker/ast_chunker.py:13), [README.md](/Volumes/MacBook/RiderProjects/GraphRagMCP/README.md:55)
## DURUM
- HIGH
## PROBLEM
Kod `.go` ve `.rs` uzantılarını destekliyor gibi davranıyor ama parser sadece Python, TypeScript, C# için kuruluyor. Go/Rust dosyaları sessizce atlanıyor.
## ETKİSİ
- Mimari: underengineering ve yanıltıcı capability.
- Developer experience: indeksleme tamamlandı sanılır, coverage eksik kalır.
- AI-agent uyumluluğu: retrieval eksikliği hallucination üretir.
## ÇÖZÜM
Go/Rust parser’larını gerçekten ekleyin veya uzantıları destek listesinden çıkarın ve dokümanı düzeltin.
## ÖNCELİK
- HIGH

## DOSYA
[src/chunker/graph_extractor.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/chunker/graph_extractor.py:13), [src/mcp_server.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/mcp_server.py:273), [src/storage/neo4j_store.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/storage/neo4j_store.py:58), [src/pipeline/graph_expansion.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/pipeline/graph_expansion.py:177)
## DURUM
- HIGH
## PROBLEM
Graph sadece `CONTAINS/OWNS` üretiyor; README’deki `CALLS`, `DEPENDS_ON`, centrality zenginliği fiilen yok. Incremental index yorumunda “eski ilişkileri temizler” deniyor ama store sadece `MERGE` yapıyor. `get_centrality()` de collection filtresi kullanmıyor; proje isimleri çakışırsa cross-project sonuç üretir.
## ETKİSİ
- Mimari: bounded context izolasyonu kırılır.
- Performans: yanlış graph augmentation gereksiz candidate üretir.
- AI-agent uyumluluğu: akış analizi olduğundan güçlü görünür ama zayıf.
## ÇÖZÜM
Gerçek çağrı/bağımlılık extraction ekleyin, changed file için graph cleanup yapın, tüm graph sorgularına collection filtresi zorunlu kılın.
## ÖNCELİK
- HIGH

## DOSYA
[src/mcp_server.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/mcp_server.py:497), [src/pipeline/guardrail.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/pipeline/guardrail.py:83), [src/pipeline/tracer.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/pipeline/tracer.py:13), [src/storage/postgres_store.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/storage/postgres_store.py:90)
## DURUM
- WARNING
## PROBLEM
`explain_code()` final LLM call için `consume_final_llm()` kullanmıyor, timeout/circuit breaker yok, trace’i persist etmiyor, loglama yapmıyor, cache de kullanmıyor. Guardrail ve observability altyapısı yarım entegre.
## ETKİSİ
- Performans: yüksek latency ve maliyet.
- Token tüketimi: tekrar explain çağrıları pahalı.
- Maintainability: policy var, enforcement yok.
## ÇÖZÜM
`explain_code()` için guardrail, timeout, cache ve trace persistence ekleyin.
## ÖNCELİK
- MEDIUM

## DOSYA
[Dockerfile](/Volumes/MacBook/RiderProjects/GraphRagMCP/Dockerfile:1)
## DURUM
- HIGH
## PROBLEM
Container uygulamayı başlatmıyor; `tail -f /dev/null` ile ayakta tutuluyor. Operasyonel model `docker exec` bağımlı. Healthcheck, non-root user, slim runtime hardening yok.
## ETKİSİ
- Production readiness: zayıf.
- DX: restart ve orchestration davranışı kırılgan.
- Güvenlik: container hardening yok.
## ÇÖZÜM
Doğrudan `python -m src.mcp_server` ile çalıştırın, non-root user ekleyin, healthcheck tanımlayın.
## ÖNCELİK
- HIGH

## DOSYA
[run.md](/Volumes/MacBook/RiderProjects/GraphRagMCP/run.md:12), [NEW_PROJECT_SETUP.md](/Volumes/MacBook/RiderProjects/GraphRagMCP/NEW_PROJECT_SETUP.md:9)
## DURUM
- HIGH
## PROBLEM
Dokümanlarda repo yolu `GraphMCP` olarak geçiyor, mevcut dizin `GraphRagMCP`. `run_agent_index.py` dosyası yok. `HybridSearch` sınıfı da yok; gerçek sınıf `HybridSearcher`.
## ETKİSİ
- Onboarding: ilk kullanım kırılır.
- AI-agent uyumluluğu: ajan yanlış komut önerir.
- Maintainability: docs güvenilmez hale gelir.
## ÇÖZÜM
README dışındaki yardımcı dökümanları kodla senkronize edin; çalışmayan komutları kaldırın.
## ÖNCELİK
- HIGH

## DOSYA
[requirements.txt](/Volumes/MacBook/RiderProjects/GraphRagMCP/requirements.txt:1)
## DURUM
- WARNING
## PROBLEM
Bağımlılıkların çoğu pin’li değil; lock file yok. `fastembed`, `openai`, `qdrant-client`, `neo4j` gibi kritik runtime parçaları sürüm drift’ine açık.
## ETKİSİ
- Sürdürülebilirlik: reproducible build yok.
- Performans/güvenlik: upstream breaking change riski.
## ÇÖZÜM
Tam sürüm pinleyin ve lock mekanizması ekleyin.
## ÖNCELİK
- MEDIUM

## DOSYA
[data/**], [src/**/__pycache__], [.DS_Store](/Volumes/MacBook/RiderProjects/GraphRagMCP/.DS_Store:1), [.gitignore](/Volumes/MacBook/RiderProjects/GraphRagMCP/.gitignore:2)
## DURUM
- WARNING
## PROBLEM
Çalışma ağacında Redis/Postgres/Neo4j/Qdrant state’i, loglar, `auth.ini`, `__pycache__` ve `.DS_Store` var. `.gitignore` bazılarını dışlıyor ama repo ağacı yine de operasyonel çöplük taşıyor.
## ETKİSİ
- AI-agent uyumluluğu: context gürültüsü çok yüksek.
- Güvenlik: state/log sızıntısı riski.
- Performans: repo tarama maliyeti gereksiz büyüyor.
## ÇÖZÜM
Runtime state’i repo dışına taşıyın, temiz workspace politikası uygulayın, artefact cleanup ekleyin.
## ÖNCELİK
- MEDIUM

## DOSYA
[src/chunker/markdown_chunker.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/chunker/markdown_chunker.py:1), [src/chunker/secret_scanner.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/chunker/secret_scanner.py:1), [src/pipeline/answerability.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/pipeline/answerability.py:1), [src/pipeline/compressor.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/pipeline/compressor.py:1), [src/pipeline/reranker.py](/Volumes/MacBook/RiderProjects/GraphRagMCP/src/pipeline/reranker.py:1)
## DURUM
- GOOD
## PROBLEM
Bu modüller kendi başına tutarlı, küçük ve amaca uygun. Özellikle markdown chunking, answerability ve conservative compression doğru yönde.
## ETKİSİ
- Maintainability: yüksek cohesion.
- Token tüketimi: iyi optimizasyon temeli.
## ÇÖZÜM
Bu modülleri koruyun; orchestration katmanını da aynı disipline çekin.
## ÖNCELİK
- LOW

**Genel Sonuç**

## 1. Genel Mimari Skoru
- 4/10

## 2. Güvenlik Skoru
- 2/10

## 3. Performans Skoru
- 5/10

## 4. AI-Agent Uyumluluk Skoru
- 4/10

## 5. Teknik Borç Seviyesi
- HIGH

## 6. En Kritik 10 Problem
- Default credential + açık admin portları.
- Source code indexing’de secret scanning yok.
- Retrieval cache API kontratı bozuk, invalidation yanlış.
- Semantic cache tasarımı fiilen çalışmıyor.
- Episodic memory feature kırık.
- RepoMap feature ölü kod.
- Graph katmanı README’de vaat edilenden çok daha zayıf.
- Incremental graph cleanup yok, stale relation birikiyor.
- Go/Rust desteği sahte.
- Dokümantasyon komutları mevcut kodla uyumsuz.

## 7. Hızlı Kazançlar
- Tüm default credential’ları kaldırın.
- `index_project()` içine secret scan ekleyin.
- Redis retrieval API imzasını düzeltin.
- `run.md` ve `NEW_PROJECT_SETUP.md` dokümanlarını temizleyin.
- `Dockerfile` içindeki `tail -f /dev/null` modelini kaldırın.

## 8. Uzun Vadeli Refactor Önerileri
- `src/mcp_server.py` içindeki orchestration’ı application service katmanlarına bölün.
- Source indexing, agent docs, memory ve retrieval’i ayrı bounded context’ler haline getirin.
- Gerçek graph extraction ekleyin: imports, calls, depends_on.
- Observability’yi gerçek hale getirin: trace persistence, error budget, timeout policy.

## 9. Gereksiz Karmaşıklıklar
- RepoMap, tracer ve guardrail kısmen var ama tam entegre değil.
- Memory taxonomy var ama runtime feature çalışmıyor.
- “Graph-first” söylemi implementation seviyesinde aşırı iddialı.

## 10. Token Optimizasyon Önerileri
- Source code için secret/redaction katmanı ekleyin.
- Semantic cache’i gerçek key modeliyle düzeltin.
- Explain sonuçlarını cache’leyin.
- Büyük runtime artefact dizinlerini çalışma ağacından çıkarın.
- README’deki capability setini küçültüp gerçek çalışan akışa indirin.

## 11. Production Readiness Değerlendirmesi
- Production-ready değil.

Bu proje şu an production’a çıkar mı? Çıkmaz. Ana nedenler güvenlik açıkları, broken feature’lar, dokümantasyon-kod ayrışması ve orchestration katmanının fazla merkezi olması. Çalışan bir demo/prototype hissi veriyor; production-grade sistem için önce güvenlik, cache doğruluğu, broken memory/repo-map akışları ve operasyon modeli düzeltilmeli.

Frontend incelemesi uygulanamadı; projede frontend bileşeni yok. Test/CI tarafında da anlamlı bir yapı tespit etmedim; bu da production kararını doğrudan aşağı çekiyor.
