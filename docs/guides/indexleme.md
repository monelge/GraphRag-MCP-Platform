# GraphMCP — İndeksleme Kılavuzu (Knowledge Plane V2)

## Genel Bakış

V2 mimarisinde projenin indekslenmesi, sadece dosyaların parçalanması ve vektör veritabanına yazılması demek değildir. **Knowledge Plane V2** standartlarına göre, ajanın mimariyi tam olarak anlayabilmesi için aşağıdaki zenginleştirme (intelligence) adımlarının gerçekleştirilmesi **zorunludur**:

1. **PageRank Analizi (Centrality):** Projedeki fonksiyon ve sınıfların ne kadar çok çağrıldığına (önem derecesine) göre puanlanması.
2. **Community Detection:** Dosya klasörlerinden bağımsız olarak mantıksal toplulukların tespit edilmesi.
3. **Repo Map:** Sıkıştırılmış bir proje iskeleti haritası çıkarılması.

`scripts/` klasöründe yer alan **`index_v2.py`** scripti tüm bu adımları MCP katmanı üzerinden standartlara uygun bir şekilde otonom olarak gerçekleştirir. Eski `index.py` ve `reindex.py` V1 standartlarında olup bu zenginleştirme adımlarını içermediği için kullanılmamalıdır.

---

## Ön Koşullar

1. Container'ların çalışır olması gerekir:
   ```bash
   docker compose up -d
   ```

2. `scripts/` dizini container'a volume mount edilmiştir (`docker-compose.yml`):
   ```yaml
   - ./scripts:/app/scripts
   ```

3. Proje dizinleri host'tan container'a `/projects/` altında görünür:
   ```yaml
   - /Volumes/MacBook/RiderProjects:/projects:ro
   ```

---

## index_v2.py — Standart İndeksleme (Önerilen)

Tüm kodları indeksler ve **V2 Intelligence (PageRank, Repo Map, Communities)** adımlarını otomatik olarak çalıştırır. Arka planda MCP aracı olan `index_project`'i kullanır.

```bash
docker exec -it graph-mcp python3 /app/scripts/index_v2.py \
    --project Vendoris \
    --path /projects/Vendoris
```

```bash
docker exec -it graph-mcp python3 /app/scripts/index_v2.py \
    --project WareLogisticcBYS \
    --path /projects/WareLogisticcBYS
```

### Parametreler

| Parametre | Zorunlu | Açıklama | Örnek |
|-----------|---------|----------|-------|
| `--project` | ✅ | Koleksiyon adı (Qdrant + Neo4j'de bu isimle tutulur) | `Vendoris` |
| `--path` | ✅ | Container içindeki proje dizini | `/projects/Vendoris` |
| `--batch` | ❌ | Embedding batch boyutu (varsayılan: 32) | `16` |

---

## İzolasyon Garantisi

Her proje **tamamen izole** tutulur:

- **Qdrant**: Her proje ayrı bir collection'da (`Vendoris`, `WareLogisticcBYS`)
- **Neo4j**: Her node `{collection: "Vendoris"}` property'si taşır; sorgular bu filtreden geçer
- **Redis cache**: Collection bazlı key prefix ile izole edilmiştir

Farklı projelerdeki aynı isimli class/fonksiyon birbirine karışmaz.

---

## Ne Zaman Hangi Scripti Kullanmalı?

*   **Projeyi sıfırdan kurdunuz veya büyük bir refactoring yaptınız:** Kesinlikle `index_v2.py` çalıştırılmalıdır. V2 yetenekleri olan PageRank ve Repo Map sadece bu script (veya MCP aracı) ile üretilir.
*   *Eski `reindex.py` ve `index.py` scriptleri deprecated (kullanımdan kaldırılmış) kabul edilmektedir.* Olası hatalarda doğrudan `index_v2.py` çalıştırılarak `index_project` fonksiyonuna bırakılmalıdır.
