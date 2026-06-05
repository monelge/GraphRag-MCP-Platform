# 🌐 GraphMCP — Servis Erişim Bilgileri

Bu döküman, **GraphMCP** altyapısında çalışan tüm servislerin güncel erişim adreslerini ve doğrulanmış kimlik bilgilerini içerir.

## 📊 Veritabanları ve Arayüzler

| Servis | Adres | Kimlik Bilgileri / Bağlantı Detayları | Açıklama |
| :--- | :--- | :--- | :--- |
| **Neo4j Browser** | [http://localhost:7474](http://localhost:7474) | **Kullanıcı:** `neo4j`<br>**Şifre:** `password` | Graph veritabanı görselleştirme ve sorgulama (Cypher). |
| **pgAdmin 4** | [http://localhost:5050](http://localhost:5050) | **Giriş:** `admin@graphmcp.com` / `admin`<br>---<br>**Sunucu Ekleme (Server):**<br>• Host: `postgres`<br>• Port: `5432`<br>• Maintenance DB: `graphmcp`<br>• Username: `graphmcp`<br>• Password: `graphmcp` | PostgreSQL (Log DB) yönetim arayüzü. |
| **Qdrant Dashboard** | [http://localhost:6333/dashboard](http://localhost:6333/dashboard) | API Key: (Yok/Boş) | Vektör veritabanı yönetimi ve koleksiyon takibi. |
| **RedisInsight** | [http://localhost:5540](http://localhost:5540) | (Otomatik Bağlanır) | Redis (Cache) izleme ve veri yönetimi. |

## 🔌 API ve Bağlantı Noktaları (Internal)

Docker içi iletişimde servisler şu adresleri kullanır:

*   **Neo4j (Bolt):** `bolt://neo4j:7687`
*   **Qdrant:** `http://qdrant:6333`
*   **Redis:** `redis://redis:6379` (Internal), Port `6380` (Host)
*   **Postgres:** `postgresql://graphmcp:graphmcp@postgres:5432/graphmcp`

## 🛠️ Docker Servis İsimleri

Konteynerleri yönetmek veya loglarını izlemek için şu isimleri kullanabilirsiniz:

```bash
docker logs -f graph-mcp          # MCP Sunucu logları
docker logs -f graph-mcp-neo4j    # Neo4j logları
docker logs -f graph-mcp-postgres # Postgres logları
docker ps                         # Tüm servisleri listele
```

---
> **Önemli Not:** Docker Volume'ları kalıcıdır. Sistemi tamamen sıfırlamak ve verileri silmek isterseniz `docker compose down -v` komutunu kullanabilirsiniz.
