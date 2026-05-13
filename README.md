# graph-mcp v2 — GraphRAG Tabanlı Kod Hafıza & Ajan MCP Sunucusu

**graph-mcp**, büyük kod depolarını (monorepo) anlamak, analiz etmek ve doğal dille sorgulamak için tasarlanmış, **GraphRAG v2** mimarisine sahip gelişmiş bir **Model Context Protocol (MCP)** sunucusudur.

Geleneksel RAG sistemlerinden farklı olarak kodun yalnızca metin içeriğini değil; **AST (Abstract Syntax Tree) yapısını**, **bağımlılık ilişkilerini**, **semantik graf bağlantılarını** ve **proje mimari özetlerini** (summary layers) kullanarak derin bağlam sunar.

---

## Mimari Genel Bakış (V2)

`GraphRagMCP v2`, sistemi 5 temel düzlemde (plane) organize eder:

1.  **Knowledge Plane:** AST indexing, Neo4j graph, summary layers (repo/module summary).
2.  **Memory Plane:** Episodic, Semantic, Decision ve Temporal memory katmanları.
3.  **Agent Plane:** Durumlu (stateful) görev orkestrasyonu ve checkpoint sistemi.
4.  **Execution Plane:** Güvenli sandbox ortamında build/test süreçlerini koşturma.
5.  **Control Plane:** Model routing, bütçe yönetimi (guardrail) ve gözlemlenebilirlik (tracer).

```
┌─────────────────────────────────────────────────────────────┐
│                  AI Agent / Copilot CLI                     │
│                     (.mcp.json)                             │
└────────────────────────┬────────────────────────────────────┘
                         │ MCP stdio
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              graph-mcp  (Docker Container)                  │
│                   src/mcp_server.py                         │
│                                                             │
│  Knowledge: index_project · summarize_repository            │
│  Retrieval: search_code · analyze_change_impact             │
│  Memory:    store_memory · store_decision_memory            │
│  Agent:     create_agent_task · approve_task_step           │
│  Execution: run_verification_plan                           │
│  Control:   get_control_plane_stats · run_retrieval_eval    │
└──────┬───────────────┬────────────────┬─────────────────────┘
       │               │                │
       ▼               ▼                ▼
  ┌─────────┐   ┌────────────┐   ┌──────────────┐
  │  Neo4j  │   │   Qdrant   │   │    Redis     │
  │  Graf   │   │  Vektör DB │   │    Cache     │
  │ ilişki  │   │ dense+BM25 │   │  retrieval   │
  └─────────┘   └────────────┘   └──────────────┘
                                 ┌──────────────┐
                                 │  PostgreSQL  │
                                 │  audit log   │
                                 └──────────────┘
```

---

## Özellikler

- **Hibrit Arama:** Vektör (dense) ve anahtar kelime (sparse/BM25) aramalarını RRF ile birleştirir.
- **Graph-Augmented Retrieval:** Kod bağımlılıklarını ve çağrı zincirlerini kullanarak aramayı genişletir.
- **Episodic Memory:** Sistem, geçmişte çözülen hataları veya alınan mimari kararları "hatırlar".
- **Gelişmiş Etki Analizi:** Bir dosya değiştiğinde, graph üzerinden hangi fonksiyonların etkilenebileceğini hesaplar.
- **Güvenli Execution:** Build ve test komutlarını izole edilmiş ortamlarda çalıştırır.
- **Token Budgeting:** LLM maliyetlerini ve bağlam limitlerini yönetmek için otomatik sıkıştırma ve bütçeleme yapar.

---

## 🔒 Güvenlik (Security)

Bu proje, halka açık depolarda güvenli çalışma prensiplerine göre tasarlanmıştır:

1.  **Secret Scanner:** İndeksleme sırasında kod blokları taranır. API anahtarları veya şifreler tespit edilirse bu bloklar otomatik olarak sansürlenir veya indeks dışında bırakılır.
2.  **Environment Variables:** Tüm hassas bilgiler `.env` dosyasında tutulur ve bu dosya asla git ile paylaşılmaz.
3.  **Path Normalization:** Dosya yolları her zaman proje köküne göre normalize edilir, sistem dosyalarına erişim engellenir.
4.  **Audit Logs:** Tüm LLM çağrıları ve sistem eylemleri PostgreSQL üzerinde izlenebilir (hassas içerik hariç).

---

## Kurulum ve Çalıştırma

### Ön Koşullar
- Docker ve Docker Compose
- [OpenRouter](https://openrouter.ai/) API Anahtarı (veya desteklenen bir LLM sağlayıcısı)

### 1. Ortam Ayarları
`.env.example` dosyasını kopyalayarak kendi ayarlarınızı yapın:
```bash
cp .env.example .env
# .env dosyasını düzenleyin ve OPENROUTER_API_KEY ekleyin.
```

### 2. Servisleri Başlat
```bash
docker compose up -d
```

### 3. MCP Bağlantısı
AI aracınızın (Claude Desktop, Cursor, vb.) yapılandırma dosyasına (`.mcp.json`) aşağıdaki bloğu ekleyin:

```json
{
  "mcpServers": {
    "graph-mcp": {
      "type": "stdio",
      "command": "docker",
      "args": [
        "exec", "-i",
        "-e", "DEFAULT_COLLECTION=my_project",
        "graph-mcp",
        "python", "-m", "src.mcp_server"
      ]
    }
  }
}
```

---

## Scriptler (Komut Satırı Kullanımı)

Toplu işlemler için `scripts/` klasöründeki Python scriptlerini container içinden çalıştırabilirsiniz:

### Artımlı İndeksleme (Sadece Değişen Dosyalar)
```bash
docker exec graph-mcp python3 /app/scripts/index.py --project MyProject --path /projects/MyProject
```

### Tam Yeniden İndeksleme (Sıfırdan)
```bash
docker exec -it graph-mcp python3 /app/scripts/reindex.py --project MyProject --path /projects/MyProject
```

### V2 Mimari Sıfırlama ve Senkronizasyon
```bash
docker exec graph-mcp python3 /app/scripts/reindex_v2_auto.py
```

---

## Bağlantı Noktaları (UI)
Geliştirme sırasında veritabanlarını izlemek için aşağıdaki arayüzleri kullanabilirsiniz:
- **Neo4j Browser:** [http://localhost:7474](http://localhost:7474) (Kullanıcı: `neo4j`, Şifre: `.env`'deki şifre)
- **Qdrant Dashboard:** [http://localhost:6333/dashboard](http://localhost:6333/dashboard)
- **RedisInsight:** [http://localhost:5540](http://localhost:5540)
- **pgAdmin:** [http://localhost:5050](http://localhost:5050)

---

## Katkıda Bulunma (Contributing)

1. Bu depoyu fork edin.
2. Yeni bir feature branch oluşturun (`git checkout -b feature/YeniOzellik`).
3. Değişikliklerinizi commit edin (`git commit -am 'Yeni özellik eklendi'`).
4. Branch'inizi push edin (`git push origin feature/YeniOzellik`).
5. Bir Pull Request oluşturun.

---

## Lisans

Bu proje [MIT Lisansı](LICENSE) ile lisanslanmıştır.
