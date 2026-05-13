# GraphMCP — Kurulum ve Kullanım Adımları

## 1. Proje Konumu ve Hazırlık
Projenin ana dizinine gidin:
```bash
cd /Volumes/MacBook/RiderProjects/GraphMCP
```

`.env` dosyanızı oluşturun ve API anahtarınızı ekleyin.

## 2. Docker Sistemini Başlatma
```bash
docker compose up -d
```

**Başarı Kontrolü:**
Konteynerlerin çalıştığından emin olun:
```bash
docker ps
# graph-mcp, qdrant, redis, postgres, neo4j, pgadmin, redisinsight
```

## 3. Cursor Ayarları
Cursor üzerinde GraphMCP'yi kullanmak için:

1. **Cursor Settings** -> **MCP** sekmesine gidin.
2. **Add New MCP Server** butonuna tıklayın.
3. Bilgileri girin:
   - **Name:** `GraphMCP`
   - **Type:** `command`
   - **Command:** `docker exec -i graph-mcp python -m src.mcp_server`

## 4. Bir Projeyi İndeksleme
Cursor'ın bir projeyi tanıması için önce onu veritabanına almalısınız:

1. Terminalde şu komutu çalıştırın (Örnek: `TedarikBYS` projesi):
   ```bash
   cd /Volumes/MacBook/RiderProjects/GraphMCP
   docker exec graph-mcp python -c "import asyncio; from src.mcp_server import index_project; asyncio.run(index_project('/projects/TedarikBYS'))"
   ```
2. İndeksleme bitene kadar bekleyin (Proje boyutuna göre 1-5 dk sürebilir).

## 5. Kullanım (Chat)
Cursor Chat (`Cmd+L`) açın ve `@GraphMCP` yazarak sorunuzu sorun:
- `@GraphMCP TedarikBYS projesinde login akışı nasıl?`
- `@GraphMCP Hangi veritabanı tabloları kullanılıyor?`

---

## Faydalı İpuçları

### Logları İzleme
Bir sorun olduğunda konteynerin ne dediğine bakın:
```bash
docker logs graph-mcp -f
```

### Claude Desktop Entegrasyonu
Eğer Cursor yerine Claude Desktop kullanıyorsanız, `claude_desktop_config.json` dosyasına şunu ekleyin:

```json
{
  "mcpServers": {
    "graph-mcp": {
      "command": "docker",
      "args": ["exec", "-i", "graph-mcp", "python", "-m", "src.mcp_server"]
    }
  }
}
```

### Yeni Dosya Eklemek
Projeye yeni dosyalar eklediyseniz, yukarıdaki **indeksleme komutunu** tekrar çalıştırmanız yeterlidir. Sistem sadece değişen/yeni dosyaları işleyecektir.

---

## Manuel Kurulum Notları (Opsiyonel)
Eğer Docker dışında çalıştırmak isterseniz:
1. `pip install -r requirements.txt`
2. `.env` ayarlarını yapın.
3. `python -m src.mcp_server` komutu ile başlatın.
   *(Ancak Docker kullanımı tavsiye edilir; Postgres/Redis bağımlılıkları nedeniyle).*
