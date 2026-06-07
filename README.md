# 🧠 GraphRagMCP V2 — Advanced Code Memory & Agent Platform

<p align="center">
  <img src="https://img.shields.io/badge/Version-2.0.0-blue.svg?style=for-the-badge&logo=github" alt="Version">
  <img src="https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge" alt="License">
  <img src="https://img.shields.io/badge/Framework-MCP-orange.svg?style=for-the-badge" alt="MCP Framework">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg?style=for-the-badge&logo=python" alt="Python Version">
  <img src="https://img.shields.io/badge/Docker-Supported-cyan.svg?style=for-the-badge&logo=docker" alt="Docker">
  <img src="https://img.shields.io/badge/MCP_Tools-34-purple.svg?style=for-the-badge" alt="MCP Tools">
  <img src="https://img.shields.io/badge/Services-9-teal.svg?style=for-the-badge" alt="Services">
</p>

**GraphRagMCP V2**, büyük ve karmaşık kod depolarını (monorepo) derinlemesine anlamak, analiz etmek ve doğal dille sorgulamak için tasarlanmış, **SOTA (State-of-the-Art) GraphRAG v2** mimarisine sahip gelişmiş bir **Model Context Protocol (MCP)** sunucusudur. 🚀

Geleneksel RAG sistemlerinin aksine, kodun yalnızca düz metnini parçalamakla kalmaz; **AST (Abstract Syntax Tree)** çözümlemesini, **PageRank bağımlılık analizlerini**, **semantik topluluk yapılarını (Community Detection)** ve **kalıcı anlamsal bellek katmanlarını** kullanarak yapay zeka ajanlarına premium bir bağlam sağlar.

---

## 🏗️ Mimari Genel Bakış (V2 Architecture)

`GraphRagMCP v2` sistemi, kod anlama ve ajansal kodlama süreçlerini **5 Temel Katman (Plane)** ve **1 Birleşik Orkestratör (Unified Orchestrator)** yapısında organize eder:

```
                            ┌────────────────────────────────────────┐
                            │      AI Agent / Copilot Client         │
                            └───────────────────┬────────────────────┘
                                                │ (MCP Protocol / OpenAI Bridge)
                                                ▼
                            ┌────────────────────────────────────────┐
                            │    Unified Orchestrator V2 (Master)    │
                            └───────────────────┬────────────────────┘
                                                │
         ┌──────────────────────┬───────────────┼───────────────┬──────────────────────┐
         ▼                      ▼               ▼               ▼                      ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ 📚 Knowledge     │  │ 🧠 Memory        │  │ 🤖 Agent     │  │ ⚡ Execution      │  │ ⚙️ Control        │
│    Plane (V2)    │  │    Plane (V2)    │  │    Plane V2  │  │    Plane (V2)    │  │    Plane (V2)    │
├──────────────────┤  ├──────────────────┤  ├──────────────┤  ├──────────────────┤  ├──────────────────┤
│ • AST Indexing   │  │ • Semantic Facts │  │ • Stateful   │  │ • Isolated       │  │ • LLM Routing    │
│ • Neo4j Graph    │  │ • mem0 Approach  │  │   Checkpoints│  │   Sandbox        │  │ • Guardrails     │
│ • Qdrant Vector  │  │ • Compacting     │  │ • Reflection │  │ • Command        │  │ • Strict Failure │
│ • PageRank SOTA  │  │ • Temporal Mem   │  │   Loops      │  │   Safety Checks  │  │ • Audit Logging  │
│ • Community Det. │  │ • Decision Store │  │ • 8 Node Types│  │ • Mount Policy  │  │ • Token Budget   │
└──────────────────┘  └──────────────────┘  └──────────────┘  └──────────────────┘  └──────────────────┘
```

### 1. 📚 Knowledge Plane (V2)
Kod tabanını semantik parçalara (chunks) böler, AST (soyut sözdizim ağacı) ilişkilerini çıkarır ve Neo4j üzerinde bir **Bilgi Grafiği** oluşturur. V2 ile birlikte gelen **PageRank ve Community Detection** algoritmaları, kritik bileşenleri önceliklendirerek aramayı daha isabetli hale getirir. Hibrit arama motoru; Dense (Qdrant), Sparse (BM25) ve CrossEncoder reranker bileşenlerini **Reciprocal Rank Fusion (RRF)** ile birleştirir. Redis katmanı ise hem exact-match hem de semantik sonuçları önbelleğe alır.

### 2. 🧠 Memory Plane (V2)
Ajanın geçmiş deneyimlerini, yaptığı hataları ve kullanıcı tercihlerini unutmaması için **Episodic**, **Semantic**, **Decision** ve **Temporal Memory** katmanları sunar. Mem0 yaklaşımını temel alan **Semantic Facts** mekanizması, ham logları kalıcı bilgi parçacıklarına dönüştürür.

### 3. 🤖 Agent Plane (V2)
Ajanın durumlu (stateful) orkestrasyonunu üstlenir. **8 farklı node tipi** (Planner, Editor, Verifier, Reviewer, Reflector vb.) ile birlikte çalışır. Ajan bir görevi yaparken hata alırsa, otomatik olarak çalışan **Reflection Loop** mekanizması (Editor ➔ Verifier ➔ Reviewer döngüsü) sayesinde kendi hatasını kendi kendine düzeltir.

### 4. ⚡ Execution Plane (V2)
Ajanın kod yazdıktan sonra testleri, derleme süreçlerini ve araçları güvenli bir şekilde koşturabileceği izole edilmiş bir sandbox ortamıdır. **Mount Policy** ve **Tool Policy** katmanları sayesinde, çalıştırılan komutlar önceden güvenlik taramasından geçirilir. Build, test ve lint runner'ları mevcuttur.

### 5. ⚙️ Control Plane (V2)
Yönetişim (Governance), bütçeleme ve gözlemlenebilirlik düzlemidir. Token tüketimini takip eder, ardışık **2 hatada** runaway koruması gereği işlemi durduran **Strict Failure Limit** kuralını uygular ve tüm akışı PostgreSQL üzerinde audit logları ile kayıt altına alır. OpenTelemetry ve Prometheus entegrasyonları sayesinde pipeline izlemesi yapılabilir.

---

## ✨ Öne Çıkan V2 Yetenekleri

- **🔍 Hibrit Semantik Arama:** Dense (Qdrant) ve Sparse (BM25) aramaları CrossEncoder reranking + RRF ile birleştirir.
- **📈 Kod Etki Analizi:** Bir dosyada değişiklik yapılacağı zaman, bağımlılık grafı üzerinden etkilenebilecek diğer kritik bileşenleri (PageRank >= 15%) hesaplar.
- **🔄 Reflection Loop:** Ajan hatalı kod ürettiğinde, insan müdahalesi gerekmeden 3 döngüye kadar kendi kodunu denetleyip düzeltir.
- **💾 Semantic Facts:** Episodik bellekleri periyodik olarak sıkıştırarak kalıcı "Semantic Fact"lere dönüştürür.
- **🛡️ Runaway Guardrails:** Bütçe ve verim denetimi sayesinde ajanın sonsuz döngüye girmesi engellenir.
- **🔒 SAST Güvenlik Taraması:** SQL injection, hardcoded secrets, eval/exec, XSS ve path traversal gibi 8+ güvenlik açığı pattern tabanlı olarak taranır.
- **♻️ Refactor & Clone Detection:** AST tabanlı kod kokusu tespiti (uzun metodlar, derin iç içe yapı, tanrı sınıfları) ve Qdrant embedding benzerliğiyle semantik kopya kod tespiti.
- **🧪 Test Öneri Motoru:** Kapsam açıklarını analiz ederek unit test önerileri üretir.
- **📡 OpenAI Bridge Gateway:** MCP desteği olmayan araçları (Copilot, Gemini CLI) port 5555 üzerinden standart OpenAI endpoint olarak GraphRAG belleğinize bağlar.
- **📋 Çoklu Proje Yönetimi:** Birden fazla projeyi aynı anda kayıt altında tutabilir, her biri için ayrı koleksiyon profili kullanabilirsiniz.
- **📊 Gerçek Zamanlı Log Viewer:** Port 8080 üzerinden canlı log akışı izlenebilir.

---

## 🛠️ MCP Araçları (34 Tool)

Sistem toplamda **34 MCP tool** sunar. Tüm detaylar için [TOOLS.md](TOOLS.md) dosyasına bakın.

### 🔍 Arama & Bilgi (Knowledge Plane)

| Tool | Açıklama |
|------|----------|
| `search_code` | Hibrit semantik + BM25 arama + CrossEncoder reranking |
| `explain_code` | LLM destekli kod açıklama |
| `grep_exact_string` | Deterministik tam metin araması (regex destekli) |
| `search_repo_architecture` | Mimari pattern ve modül ilişkisi araması |
| `summarize_repository` | Tüm kod tabanı özeti |
| `analyze_change_impact` | PageRank tabanlı değişim etki analizi |
| `index_project` | Tam proje indeksleme (AST + PageRank + Community Detection) |
| `incremental_index_project` | Sadece değişen dosyaları indeksleme |
| `index_agent_docs` | AGENTS.md ve dokümantasyon indeksleme |
| `search_agent_docs` | Proje kuralları ve protokol araması |
| `register_project` | Yeni projeyi sisteme kaydetme |
| `list_projects` | Kayıtlı projeleri listeleme |

### 🧠 Bellek & Karar (Memory Plane)

| Tool | Açıklama |
|------|----------|
| `store_memory` | Episodik/semantik bellek kaydetme |
| `recall_memory` | Sorguya göre bellek geri çağırma |
| `store_decision_memory` | Mimari karar kaydetme |
| `search_decisions` | Geçmiş kararları arama |
| `compact_memory` | Episodik bellekleri semantik fact'lere sıkıştırma |
| `run_memory_cycle` | Bellek inceleme & sıkıştırma döngüsü |

### 🔒 Analiz & Kalite (Analysis Plane)

| Tool | Açıklama |
|------|----------|
| `security_scan` | SAST güvenlik taraması (SQL injection, XSS, hardcoded secrets vb.) |
| `refactor_suggestions` | Kod kokusu tespiti (long methods, god classes, deep nesting) |
| `test_suggestion` | Test kapsam analizi ve unit test önerisi üretimi |
| `code_clone_detection` | Semantik kopya kod tespiti (Qdrant embedding benzerliği) |

### 🤖 Görev Yönetimi (Agent & Execution Plane)

| Tool | Açıklama |
|------|----------|
| `execute_agent_task` | Otonom çok adımlı görev yürütme |
| `create_agent_task` | Checkpoint'li görev oluşturma |
| `get_task_status` | Görev durumu ve ilerleme |
| `approve_task_step` | Görev adımını onaylayıp ilerletme |
| `complete_task` | Görevi tamamlandı olarak işaretleme |
| `resume_task` | Duraklatılmış göreve devam |
| `list_agent_tasks` | Tüm görevleri listeleme |
| `get_project_state` | PostgreSQL'den proje görev durumları |
| `get_active_phase` | Aktif geliştirme fazı |
| `run_verification_plan` | Build/test/lint doğrulama çalıştırma |

### ⚙️ Kontrol & Gözlemlenebilirlik (Control Plane)

| Tool | Açıklama |
|------|----------|
| `get_control_plane_stats` | Token kullanımı, latency, model istatistikleri |
| `run_retrieval_eval` | Retrieval kalite değerlendirmesi (dataset tabanlı) |

---

## 📂 Proje Yapısı

```
GraphRagMCP/
├── 📂 docs/                           # 📄 Tüm Platform Dokümantasyonu
│   ├── 📂 architecture/               # 🏗️ Mimari & Katman (Plane) Detayları
│   │   ├── GraphRagMCP-v2.md          # Ana V2 Tasarım Belgesi
│   │   ├── AGENT_PLANE_V2.md          # Stateful Ajan & Reflection Tasarımı
│   │   ├── KNOWLEDGE_PLANE_V2.md      # PageRank & Graph RAG Zenginleştirme
│   │   ├── MEMORY_PLANE_V2.md         # Episodik & Semantik Bellek Tasarımı
│   │   ├── EXECUTION_PLANE_V2.md      # Sandbox & Runner Tasarımı
│   │   ├── CONTROL_PLANE_V2.md        # Governance & Bütçe Tasarımı
│   │   ├── ORCHESTRATION_PLANE_V2.md  # Orkestratör Tasarımı
│   │   └── SERVICES.md                # Servis Konfigürasyonları
│   ├── 📂 reports/                    # 📊 Sistem Denetim & Analiz Raporları
│   │   ├── ARCHITECTURE_REVIEW_REPORT.md
│   │   ├── CODEBASE_AUDIT_REPORT.md
│   │   ├── MARKET_RESEARCH_AND_V2_OPTIMIZATION_REPORT.md
│   │   └── MCP_IDE_COMPATIBILITY_REPORT.md
│   ├── 📂 guides/                     # 💡 Kullanım Kılavuzları
│   │   ├── adim.md                    # Adım Adım İşlem Kılavuzu
│   │   ├── akis.md                    # Akış Diyagramları
│   │   ├── indexleme.md               # Neo4j/Qdrant İndeksleme Kılavuzu
│   │   ├── local_ollama_and_cli_tools_integration.md
│   │   ├── mcp_client_setup.md        # MCP İstemci Kurulumu
│   │   ├── run.md                     # Çalıştırma Kılavuzu
│   │   └── sorunlar.md                # Sorun Giderme
│   └── API_REFERENCE.md               # API Referansı
│
├── 📂 scripts/                        # 🛠️ Geliştirici Betikleri
│   ├── 📂 indexing/                   # ⚡ Kod İndeksleme ve Güncelleme (6 script)
│   │   ├── index_v2.py                # SOTA İndeksleyici (PageRank + Community)
│   │   └── reindex_v2_auto.py         # Artımlı Otomatik Yeniden İndeksleyici
│   ├── 📂 verification/               # 🛡️ Düzlem & Entegrasyon Testleri (18 script)
│   │   ├── agent_plane_v2_verification.py
│   │   ├── mcp_server_full_orchestration_verification.py
│   │   └── test_all_tools*.py         # Tüm 34 tool entegrasyon testi
│   ├── 📂 launchers/                  # 🚀 Host üzerinden Docker Tetikleyicileri (13 script)
│   │   ├── verify_full_system_v2.sh   # Tam Sistem V2 Testi
│   │   ├── verify_agent_v2.sh         # Agent Plane V2 Testi
│   │   ├── verify_kp_v2.sh            # Knowledge Plane V2 Testi
│   │   ├── verify_memory_v2.sh        # Memory Plane V2 Testi
│   │   └── verify_all_tools_v2.sh     # Tüm Araç Entegrasyon Testleri
│   └── 📝 README.md                   # Detaylı Script Kataloğu & Komutları
│
├── 📂 src/                            # 💻 Uygulama Kaynak Kodu
│   ├── mcp_server.py                  # Ana MCP Giriş Noktası
│   ├── 📂 mcp/                        # MCP Protokol Katmanı
│   │   ├── server.py                  # MCP protokol handler
│   │   └── tool_registry.py           # 34 MCP tool tanımları & facade'lar
│   ├── 📂 agent/                      # Stateful Ajan Orkestrasyon
│   │   ├── nodes/                     # 8 node tipi (planner, editor, verifier vb.)
│   │   ├── orchestrator/              # Checkpoint, onay, state machine
│   │   └── tasks/                     # Görev modelleri ve depolama
│   ├── 📂 control/                    # Yönetişim & Gözlemlenebilirlik
│   │   ├── evals/                     # Dataset manager, metrik runner'ları
│   │   ├── models/                    # Bütçe, model router, guardrail
│   │   ├── observability/             # Audit, metrik, tracer
│   │   ├── openai_bridge.py           # FastAPI gateway (port 5555)
│   │   └── log_viewer.py              # Gerçek zamanlı log dashboard (port 8080)
│   ├── 📂 execution/                  # Sandbox & Komut Çalıştırıcılar
│   │   ├── runners/                   # Build, test, komut runner'ları
│   │   └── sandbox/                   # Mount policy, tool policy
│   ├── 📂 handlers/                   # 8 handler facade
│   │   ├── analysis_handler.py        # security_scan, refactor, test_suggestion, clone_detection
│   │   ├── control_handler.py
│   │   ├── execution_handler.py
│   │   ├── indexing_handler.py
│   │   ├── memory_handler.py
│   │   ├── orchestration_handler.py
│   │   └── retrieval_handler.py
│   ├── 📂 indexing/                   # Kod Ayrıştırma & Gömme
│   │   ├── chunkers/                  # AST, markdown, secret scanner
│   │   ├── embedders/                 # Dense (Qdrant), Sparse (BM25)
│   │   ├── extractors/                # Graf çıkarma, RepoMap
│   │   ├── normalization/             # Dil tespiti, yol eşleme
│   │   └── pipelines/                 # project_intelligence.py
│   ├── 📂 memory/                     # Episodik & Semantik Bellek
│   │   ├── models/                    # Bellek modelleri
│   │   ├── services/                  # Sıkıştırma, geri çağırma, yazma
│   │   └── stores/                    # Karar, episodik, semantik, temporal
│   ├── 📂 retrieval/                  # Hibrit Arama & Sıralama
│   │   ├── search/                    # local, global, hybrid, hyde, impact_analysis
│   │   ├── ranking/                   # Reranker, CrossEncoder, deduplicator
│   │   └── context/                   # Sıkıştırıcı, context builder, token budget
│   ├── 📂 storage/                    # Veritabanı Arayüzleri
│   │   ├── neo4j_store.py
│   │   ├── qdrant_store.py
│   │   ├── redis_store.py
│   │   ├── postgres_store.py
│   │   └── episodic_store.py
│   ├── 📂 ontology/                   # Şema & Builder'lar
│   └── 📂 shared/                     # Paylaşılan Yardımcılar
│       ├── config.py
│       ├── llm_client.py
│       ├── project_registry.py        # Çoklu proje yönetimi
│       └── telemetry.py
│
├── 📂 tests/                          # 🧪 Test Süreçleri
├── 📂 .claude/commands/               # 🗂️ 40+ Türkçe Slash Command tanımı
├── 🐳 Dockerfile & docker-compose.yml # 📦 9 Servisli Konteyner Konfigürasyonu
├── 📄 TOOLS.md                        # 34 MCP Tool Dokümantasyonu
├── 📄 AGENT.md                        # Ajan Protokol Kılavuzu
├── 📄 CLAUDE.md                       # Claude Code Entegrasyon Kılavuzu
└── 📄 GEMINI.md                       # Gemini CLI Entegrasyon Kılavuzu
```

---

## 🐳 Docker Servisleri (9 Servis)

`docker compose up -d` komutu aşağıdaki **9 servisi** başlatır:

| Servis | Port(lar) | Açıklama |
|--------|-----------|----------|
| **neo4j** | 7474, 7687 | Bilgi grafı veritabanı |
| **qdrant** | 6333, 6334 | Vektör gömme deposu |
| **redis** | 6380 | Önbellek & gömme cache'i |
| **postgres** | 5432 | Audit log & control plane durumu |
| **graph-mcp** | 8000 | Ana MCP sunucusu (stdio + SSE) |
| **openai-bridge** | 5555 | OpenAI uyumlu FastAPI gateway |
| **pgadmin** | 5050 | PostgreSQL yönetim arayüzü |
| **redisinsight** | 15540 | Redis yönetim arayüzü |
| **log-viewer** | 8080 | Gerçek zamanlı log dashboard'u |

---

## 🚀 Kurulum ve Başlangıç

### 📋 Ön Gereksinimler
- Docker & Docker Compose
- [OpenRouter](https://openrouter.ai/) API Anahtarı

### 1️⃣ Ortam Ayarları
`.env.example` dosyasını kopyalayarak `.env` dosyasını oluşturun ve API anahtarlarınızı tanımlayın:
```bash
cp .env.example .env
# .env dosyasını açıp OPENROUTER_API_KEY ve diğer şifreleri düzenleyin.
```

Temel çevre değişkenleri:

```env
# Yollar
HOST_PROJECTS_ROOT=/path/to/your/projects
CONTAINER_PROJECTS_ROOT=/projects

# LLM Anahtarı
OPENROUTER_API_KEY=sk-...

# Model Seçimi
EMBEDDING_MODEL=text-embedding-3-small
ANALYSIS_MODEL=mistralai/mistral-nemo
REASONING_MODEL=google/gemini-2.5-flash

# Bütçe & Guardrail
GUARDRAIL_ENABLED=true
GUARDRAIL_TOKEN_HARD_LIMIT=5000
GUARDRAIL_MAX_TOTAL_LLM_CALLS=2
BUDGET_TASK_MAX_TOKENS=50000
BUDGET_DAILY_MAX_USD=10.0

# Retrieval
DEFAULT_TOKEN_BUDGET=1800
MAX_CONTEXT_CHUNKS=8
CROSS_ENCODER_ENABLED=true
```

### 2️⃣ Platform Servislerini Başlatma
```bash
docker compose up -d
```
*Bu komut; Neo4j, Qdrant, Redis, Postgres, pgAdmin, log-viewer, openai-bridge ve GraphMCP sunucusunu başlatır.*

### 3️⃣ İlk Projeyi İndeksleme
```bash
# Projeyi sisteme kaydet ve indeksle
docker exec graph-mcp python3 scripts/indexing/index_v2.py \
  --project-path /projects/my-project \
  --collection my-project
```

### 4️⃣ AI Ajanınıza (Copilot/Cline) Entegre Etme
Kullandığınız AI istemcisinin (örneğin VSCode Cline veya Roo Code) `.mcp.json` veya `mcp_config.json` dosyasına şu sunucu tanımını ekleyin:

```json
{
  "mcpServers": {
    "graph-mcp": {
      "type": "stdio",
      "command": "docker",
      "args": [
        "exec", "-i",
        "-e", "DEFAULT_COLLECTION=codebase",
        "graph-mcp",
        "python3", "-m", "src.mcp_server"
      ]
    }
  }
}
```

> **SSE Transport** için: `http://deva.adanaekspres.com:8000/sse`

---

## 🦙 Yerel Ollama & OpenAI API Gateway Entegrasyonu (V2-Bridge)

**GraphRagMCP V2**, yerel yapay zeka altyapınız (**Ollama**) ile tam uyumludur. Ayrıca sisteminize kazandırdığımız **OpenAI API Gateway Bridge** sayesinde, Model Context Protocol (MCP) desteği olmayan kapalı ekosistemlerdeki AI araçlarını (**Claude Code, Copilot, Gemini CLI**) yerel GraphRAG kod belleğinize entegre edebilirsiniz.

Ayrıntılı adım adım yönergelere **[Yerel Ollama & CLI Entegrasyon Kılavuzu](docs/guides/local_ollama_and_cli_tools_integration.md)** dosyasından erişebilirsiniz.

### 1️⃣ Yerel Ollama Kurulumu
```env
LLM_BASE_URL=http://host.docker.internal:11434/v1
OPENAI_API_KEY=ollama
ANALYSIS_MODEL=qwen2.5-coder:latest
REASONING_MODEL=qwen2.5-coder:latest
```

### 2️⃣ OpenAI Bridge Sunucusu (Port 5555)
FastAPI tabanlı `openai-bridge` servisimiz host makinenizde **`5555`** portundan hizmet verir:
- **Base URL:** `http://localhost:5555/v1`
- **Model:** `graph-mcp` veya `gpt-4o-mini`

### 3️⃣ İstemci Yapılandırmaları

- **Claude Code:** Proje kök dizininde `claude` komutunu çalıştırın ve MCP sunucusunu onaylayın:
  > `Allow project MCP servers? (y/N) -> y`
- **Copilot CLI:**
  ```bash
  export OPENAI_BASE_URL=http://localhost:5555/v1
  export OPENAI_API_KEY=ollama
  ```
- **Gemini CLI:**
  ```bash
  export GEMINI_API_BASE=http://localhost:5555/v1
  export GEMINI_API_KEY=ollama
  ```

---

## 🔒 Güvenlik & Bütçe Kontrolü

### Token Bütçeleme
Tüm LLM çağrıları token bütçe sistemiyle yönetilir:

| Parametre | Varsayılan | Açıklama |
|-----------|-----------|----------|
| `BUDGET_TASK_MAX_TOKENS` | 50.000 | Görev başına maksimum token |
| `BUDGET_DAILY_MAX_USD` | $10.00 | Günlük dolar limiti |
| `GUARDRAIL_TOKEN_HARD_LIMIT` | 5.000 | Sert token kesim sınırı |
| `GUARDRAIL_MAX_TOTAL_LLM_CALLS` | 2 | Ardışık hata toleransı (sonra dur) |

### SAST Güvenlik Taraması
`security_scan` tool'u aşağıdaki pattern'leri otomatik tarar:
- SQL Injection (`f"SELECT ... {var}"`)
- Hardcoded Secrets (`password =`, `api_key =` vb.)
- Tehlikeli fonksiyonlar (`eval()`, `exec()`, `pickle.loads()`)
- Shell Injection (`os.system()`, `subprocess` + user input)
- XSS açıkları
- Path Traversal (`../`)
- Insecure Random (`random.random()` kriptografik kullanım)

### Audit Logging
Tüm tool çağrıları PostgreSQL'e correlation ID ile kayıt edilir. pgAdmin üzerinden sorgulanabilir.

---

## 📊 Retrieval Mimarisi

```
Sorgu
  │
  ▼
Query Classifier ──► factual / broad / architectural
  │
  ├─► HyDE Query Expansion (opsiyonel)
  │
  ├─► Dense Search (Qdrant)    ──┐
  ├─► Sparse Search (BM25)     ──┼─► RRF Fusion ──► CrossEncoder Reranker ──► Context Builder
  └─► Graph Search (Neo4j)     ──┘                              │
                                                                ▼
                                                     Token Budget Manager
                                                     (varsayılan: 1800 token)
```

**Redis Cache Katmanları:**
- L1: Exact-match sorgu cache'i
- L2: Semantik benzerlik cache'i

---

## ⚡ Hızlı Doğrulama ve Test Komutları

> [!TIP]
> **Executable Yetkisi Verme:**
> ```bash
> chmod +x scripts/launchers/*.sh
> ```

| Görev | Çalıştırılacak Komut |
| :--- | :--- |
| **Tam Sistem Doğrulaması (V2)** | `bash scripts/launchers/verify_full_system_v2.sh` |
| **Agent Plane Doğrulaması (V2)** | `bash scripts/launchers/verify_agent_v2.sh` |
| **Knowledge Plane Doğrulaması (V2)** | `bash scripts/launchers/verify_kp_v2.sh` |
| **Memory Plane Doğrulaması (V2)** | `bash scripts/launchers/verify_memory_v2.sh` |
| **Tüm Araç Entegrasyon Testleri** | `bash scripts/launchers/verify_all_tools_v2.sh` |

---

## 📊 Yönetim ve Arayüz Panelleri (UI Dashboard'lar)

| Dashboard | URL | Amaç |
|-----------|-----|-------|
| 🌐 **Neo4j Browser** | [http://localhost:7474](http://localhost:7474) | Grafik veri görselleştirme |
| 🔎 **Qdrant Dashboard** | [http://localhost:6333/dashboard](http://localhost:6333/dashboard) | Vektör koleksiyonları |
| ⚡ **RedisInsight** | [http://localhost:15540](http://localhost:15540) | Hızlı önbellek izleme |
| 🐘 **pgAdmin** | [http://localhost:5050](http://localhost:5050) | Audit veritabanı yönetimi |
| 📋 **Log Viewer** | [http://localhost:8080](http://localhost:8080) | Gerçek zamanlı log akışı |
| 🔌 **OpenAI Bridge** | [http://localhost:5555/v1](http://localhost:5555/v1) | OpenAI uyumlu API endpoint |

---

## 🗂️ Türkçe Slash Komutları

`.claude/commands/` dizininde tanımlı **40+ Türkçe slash komutu** mevcuttur. Claude Code ile çalışırken kullanılabilir:

```
/g-kod-ara             → search_code
/g-kodu-açıkla         → explain_code
/g-mimari-ara          → search_repo_architecture
/g-metin-ara           → grep_exact_string
/g-indeksle            → index_project
/g-artimli-indeksle    → incremental_index_project
/g-bellek-kaydet       → store_memory
/g-bellek-ara          → recall_memory
/g-karar-kaydet        → store_decision_memory
/g-guvenlik-tara       → security_scan
/g-refactor-oner       → refactor_suggestions
/g-test-oner           → test_suggestion
/g-kopya-kod-bul       → code_clone_detection
/g-gorev-olustur       → create_agent_task
/g-ajan-calistir       → execute_agent_task
/g-istatistikler       → get_control_plane_stats
```

Tam liste için [CLAUDE.md](CLAUDE.md) dosyasına bakın.

---

## 📦 Temel Bağımlılıklar

| Kategori | Paket | Amaç |
|----------|-------|-------|
| **MCP** | `mcp==1.6.0` | Model Context Protocol |
| **Web** | `fastapi>=0.111.0`, `uvicorn` | OpenAI Bridge API |
| **AST Parsing** | `tree-sitter`, `tree-sitter-python`, `tree-sitter-typescript`, `tree-sitter-c-sharp` | Çoklu dil AST analizi |
| **Embeddings** | `fastembed==0.8.0` | Lokal embedding üretimi |
| **Reranking** | `sentence-transformers>=2.7.0` | CrossEncoder reranking |
| **Graph DB** | `neo4j==5.13.0` | Bilgi grafı |
| **Vector DB** | `qdrant-client>=1.9.0` | Vektör arama |
| **Cache** | `redis>=5.0.0` | Sorgu önbelleği |
| **Audit DB** | `asyncpg>=0.29.0` | PostgreSQL async driver |
| **LLM** | `openai==1.3.9` | OpenAI / OpenRouter istemcisi |
| **Telemetry** | `opentelemetry-sdk`, `prometheus-client` | Gözlemlenebilirlik |

---

## 🤝 Katkıda Bulunma (Contributing)

1. Projenin bir kopyasını fork edin (`Fork`).
2. Yeni bir özellik dalı oluşturun (`git checkout -b feature/AmazingFeature`).
3. Değişikliklerinizi commit edin (`git commit -m 'feat: Add AmazingFeature'`).
4. Dalı push edin (`git push origin feature/AmazingFeature`).
5. Bir Pull Request (PR) oluşturun.

---

## 👥 Geliştirici & Yazar (Author & Developer)

- **Mehmet ÖNELGE** ([@monelge](https://github.com/monelge)) - *Lead Developer & Architect*

---

## 📄 Lisans

Bu proje **MIT Lisansı** altında lisanslanmıştır. Detaylar için [LICENSE](LICENSE) dosyasına göz atabilirsiniz.
