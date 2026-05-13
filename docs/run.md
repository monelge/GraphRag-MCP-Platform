# GraphRagMCP — Çalıştırma & İndeksleme Komutları

## 1. Servisleri Kontrol Etme
```bash
# Tüm konteynerlerin durumunu gör
docker ps | grep -E "qdrant|graph-mcp|neo4j"
```

## 2. Sistemi Başlatma / Durdurma
```bash
# Başlat (Arka planda)
docker compose -f /Volumes/MacBook/RiderProjects/GraphRagMCP/docker-compose.yml up -d

# Durdur
docker compose -f /Volumes/MacBook/RiderProjects/GraphRagMCP/docker-compose.yml down
```

## 3. Proje İndeksleme (Yeni Proje Tanıtma)

### Otomatik (Script ile)
```bash
docker exec graph-mcp python /app/scripts/index_vendoris.py /projects/PROJE_ADI
```

### Manuel (Python komutu ile)
```bash
# Örnek: PoliNexus projesini indeksle
docker exec graph-mcp python -c "
import asyncio
from src.mcp_server import index_project
asyncio.run(index_project('/projects/PoliNexus'))
"
```

## 3.1 Artımlı İndeksleme Notu

`incremental_index_project` aracı container içinde öncelikle `changed_files` listesiyle çalışacak şekilde tasarlanmalıdır.

- En güvenli kullanım: post-commit hook veya otomasyon üzerinden `changed_files` geçirmek
- `changed_files` verilmezse araç container içinden `git diff HEAD~1 HEAD` denemesi yapar
- `graph-mcp` image'ında `git` kurulu olduğu için bu fallback doğrudan kullanılabilir
- Proje bir git repo değilse veya `HEAD~1` yoksa `changed_files` ile çağırmak gerekir
- Gönderilen dosya yolları container içinde `/projects/...` formatında olmalıdır

Örnek:

```bash
docker exec graph-mcp python -c "
import asyncio
from src.mcp_server import incremental_index_project
asyncio.run(incremental_index_project('/projects/Vendoris', ['/projects/Vendoris/src/app.py']))
"
```

## 4. Semantik Arama Testi
Sistemin doğru çalışıp çalışmadığını terminalden test edebilirsiniz:

```bash
docker exec graph-mcp python -c "
import asyncio
from src.search.hybrid_search import HybridSearcher
async def test():
    hs = HybridSearcher()
    res = await hs.search('auth mechanism', collection_name='PoliNexus')
    for r in res:
        print(f'-> {r.payload[\"file_path\"]} (Score: {r.score})')
asyncio.run(test())
"
```

## 5. Logları İzleme
```bash
# MCP sunucusunun canlı logları
docker logs graph-mcp -f

# Sadece son 50 satır
docker logs graph-mcp --tail 50
```

## 6. Geliştirici Komutları

### Konteyneri Yeniden Başlat (Kod değişikliği sonrası)
```bash
docker compose -f /Volumes/MacBook/RiderProjects/GraphRagMCP/docker-compose.yml restart graph-mcp
```

### Bağımlılıkları Güncelle ve Build Et
```bash
docker compose -f /Volumes/MacBook/RiderProjects/GraphRagMCP/docker-compose.yml up -d --build
```

### Veritabanını Tamamen Sıfırlama (DİKKAT!)
```bash
# Qdrant'taki tüm koleksiyonları siler
docker exec graph-mcp python -c "
from qdrant_client import QdrantClient
client = QdrantClient('http://qdrant:6333')
cols = client.get_collections().collections
for c in cols:
    client.delete_collection(c.name)
    print(f'Deleted: {c.name}')
"
```
