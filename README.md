# 🧠 GraphRagMCP V2 — Advanced Code Memory & Agent Platform

<p align="center">
  <img src="https://img.shields.io/badge/Version-2.0.0-blue.svg?style=for-the-badge&logo=github" alt="Version">
  <img src="https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge" alt="License">
  <img src="https://img.shields.io/badge/Framework-MCP-orange.svg?style=for-the-badge" alt="MCP Framework">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg?style=for-the-badge&logo=python" alt="Python Version">
  <img src="https://img.shields.io/badge/Docker-Supported-cyan.svg?style=for-the-badge&logo=docker" alt="Docker">
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
                                                │ (MCP Protocol)
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
│ • Qdrant Vector  │  │ • Compacting     │  │ • Reflection │  │ • Command        │  │ • strict failures│
│ • PageRank SOTA  │  │ • Temporal Mem   │  │   Loops      │  │   Safety Checks  │  │ • Pipeline Trace │
└──────────────────┘  └──────────────────┘  └──────────────┘  └──────────────────┘  └──────────────────┘
```

### 1. 📚 Knowledge Plane (V2)
Kod tabanını semantik parçalara (chunks) böler, AST (soyut sözdizim ağacı) ilişkilerini çıkarır ve Neo4j üzerinde bir **Bilgi Grafiği** oluşturur. V2 ile birlikte gelen **PageRank ve Community Detection** algoritmaları, kritik bileşenleri önceliklendirerek aramayı daha isabetli hale getirir.

### 2. 🧠 Memory Plane (V2)
Ajanın geçmiş deneyimlerini, yaptığı hataları ve kullanıcı tercihlerini unutmaması için **Episodic** ve **Semantic Memory** katmanları sunar. Mem0 yaklaşımını temel alan **Semantic Facts** mekanizması, ham logları kalıcı bilgi parçacıklarına dönüştürür.

### 3. 🤖 Agent Plane (V2)
Ajanın durumlu (stateful) orkestrasyonunu üstlenir. Ajan bir görevi yaparken hata alırsa, otomatik olarak çalışan **Reflection Loop** mekanizması (Editor ➔ Verifier ➔ Reviewer döngüsü) sayesinde kendi hatasını kendi kendine düzeltir.

### 4. ⚡ Execution Plane (V2)
Ajanın kod yazdıktan sonra testleri, derleme süreçlerini ve araçları güvenli bir şekilde koşturabileceği izole edilmiş bir sandbox ortamıdır. Çalıştırılan komutlar önceden güvenlik taramasından geçirilir.

### 5. ⚙️ Control Plane (V2)
Yönetişim (Governance), bütçeleme ve gözlemlenebilirlik düzlemidir. Token tüketimini takip eder, ardışık **2 hatada** runaway koruması gereği işlemi durduran **Strict Failure Limit** kuralını uygular ve tüm akışı PostgreSQL üzerinde loglar.

---

## 📂 Düzenli Proje Yapısı

Karmaşayı önlemek amacıyla platformumuzun dokümantasyon ve betik (script) altyapısı tamamen kategorize edilmiştir:

```
GraphRagMCP/
├── 📂 docs/                           # 📄 Tüm Platform Dokümantasyonu
│   ├── 📂 architecture/               # 🏗️ Mimari & Katman (Plane) Detayları
│   │   ├── GraphRagMCP-v2.md          # Ana V2 Tasarım Belgesi
│   │   ├── AGENT_PLANE_V2.md          # Stateful Ajan & Reflection Tasarımı
│   │   └── KNOWLEDGE_PLANE_V2.md      # PageRank & Graph RAG Zenginleştirme
│   ├── 📂 reports/                    # 📊 Sistem Denetim & Analiz Raporları
│   │   ├── ARCHITECTURE_REVIEW_REPORT.md
│   │   └── CODEBASE_AUDIT_REPORT.md
│   └── 📂 guides/                     # 💡 Kullanım Kılavuzları & Backlog'lar
│       ├── adim.md                    # Adım Adım İşlem Kılavuzu
│       └── indexleme.md               # Neo4j/Qdrant İndeksleme Kılavuzu
│
├── 📂 scripts/                        # 🛠️ Geliştirici Betikleri
│   ├── 📂 indexing/                   # ⚡ Kod İndeksleme ve Güncelleme
│   │   ├── index_v2.py                # SOTA İndeksleyici (PageRank + Community)
│   │   └── reindex_v2_auto.py         # incremental Otomatik Yeniden İndeksleyici
│   ├── 📂 verification/               # 🛡️ Düzlem & Entegrasyon Testleri
│   │   ├── agent_plane_v2_verification.py
│   │   └── mcp_server_full_orchestration_verification.py
│   ├── 📂 launchers/                  # 🚀 Host üzerinden Docker Tetikleyicileri
│   │   ├── verify_full_system_v2.sh   # Tam Sistem V2 Testi
│   │   └── verify_kp_v2.sh            # Knowledge Plane V2 Testi
│   └── 📝 README.md                   # Detaylı Script Kataloğu & Komutları
│
├── 📂 src/                            # 💻 Uygulama Kaynak Kodu
├── 📂 tests/                          # 🧪 Test Süreçleri
├── 🐳 Dockerfile & docker-compose.yml # 📦 Konteyner Konfigürasyonu
└── 🤖 GEMINI.md                       # 🛡️ En üst düzey Ajan Protokolü (SOTA)
```

---

## ✨ Öne Çıkan V2 Yetenekleri

- **🔍 Hibrit Semantik Arama:** Dense (Qdrant) ve Sparse (BM25) aramaları Reciprocal Rank Fusion (RRF) kullanarak birleştirir.
- **📈 Kod Etki Analizi:** Bir dosyada değişiklik yapılacağı zaman, bağımlılık grafı üzerinden etkilenebilecek diğer kritik bileşenleri (PageRank >= 15%) hesaplar.
- **🔄 Reflection Loop:** Ajan hatalı kod ürettiğinde, insan müdahalesi gerekmeden 3 döngüye kadar kendi kodunu denetleyip düzeltebilir.
- **💾 Semantic Facts:** Episodik bellekleri periyodik olarak sıkıştırarak kalıcı "Semantic Fact"lere dönüştürür.
- **🛡️ Runaway Guardrails:** Bütçe ve verim denetimi sayesinde ajanın sonsuz döngüye girmesi engellenir.

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

### 2️⃣ Platform Servislerini Başlatma
Docker container yapılarını arka planda ayağa kaldırın:
```bash
docker compose up -d
```
*Bu komut; Neo4j, Qdrant, Redis, Postgres, pgAdmin ve GraphMCP sunucusunu başlatır.*

### 3️⃣ AI Ajanınıza (Copilot/Cline) Entegre Etme
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

---

## ⚡ Hızlı Doğrulama ve Test Komutları

Yeniden düzenlenen yapıda, tüm doğrulama komutları `/scripts/launchers/` altında yer almaktadır. Host makineden Docker konteyneri içindeki testleri çalıştırmak için:

> [!TIP]
> **Executable Yetkisi Verme:**
> Script'leri çalıştırmadan önce çalıştırma yetkisi verdiğinizden emin olun:
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

Sistemi izlemek ve görselleştirmek için Docker compose ile birlikte gelen dashboard'lara yerel tarayıcınızdan erişebilirsiniz:

*   🌐 **Neo4j Browser:** [http://localhost:7474](http://localhost:7474) *(Grafik Veri Görselleştirme)*
*   🔎 **Qdrant Dashboard:** [http://localhost:6333/dashboard](http://localhost:6333/dashboard) *(Vektör Koleksiyonları)*
*   ⚡ **RedisInsight:** [http://localhost:5540](http://localhost:5540) *(Hızlı Önbellek İzleme)*
*   🐘 **pgAdmin:** [http://localhost:5050](http://localhost:5050) *(Denetim/Audit Veritabanı Arayüzü)*

---

## 🤝 Katkıda Bulunma (Contributing)

1.  Projenin bir kopyasını fork edin (`Fork`).
2.  Yeni bir özellik dalı oluşturun (`git checkout -b feature/AmazingFeature`).
3.  Değişikliklerinizi commit edin (`git commit -m 'feat: Add AmazingFeature'`).
4.  Dalı push edin (`git push origin feature/AmazingFeature`).
5.  Bir Pull Request (PR) oluşturun.

---

## 👥 Geliştirici & Yazar (Author & Developer)

- **Mehmet ÖNELGE** ([@monelge](https://github.com/monelge)) - *Lead Developer & Architect*

---

## 📄 Lisans

Bu proje **MIT Lisansı** altında lisanslanmıştır. Detaylar için [LICENSE](LICENSE) dosyasına göz atabilirsiniz.
