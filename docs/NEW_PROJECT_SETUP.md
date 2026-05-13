# GraphRagMCP — Yeni Proje Kurulumu

GraphRagMCP **collection tabanlı** çalışır. Her proje kendi collection'ına sahiptir; böylece bağlamlar karışmaz.

## 1. Hazırlık
Önce sistemin (Docker konteynerlerinin) ayakta olduğundan emin olun.

```bash
cd /Volumes/MacBook/RiderProjects/GraphRagMCP
docker compose up -d
```

**Kontrol:**
```bash
docker ps
# qdrant, redis, postgres, graph-mcp → Up olmalı
```

## 2. Yeni Bir Proje İndeksleme
Varsayalım ki `/Volumes/MacBook/RiderProjects/YeniProjem` yolunda bir projeniz var.

### Adım A: Docker Volume Kontrolü
`docker-compose.yml` içinde `/Volumes/MacBook/RiderProjects` klasörünün `/projects` olarak maplendiğinden emin olun (zaten varsayılan budur).

### Adım B: İndeksleme Komutunu Çalıştırın
Terminalden şu komutu verin:

```bash
docker exec graph-mcp python /app/scripts/index_vendoris.py /projects/YeniProjem
```

*(Not: Eğer `scripts/index_vendoris.py` yerine doğrudan modül çağırmak isterseniz)*:
```bash
docker exec graph-mcp python -c "import asyncio; from src.mcp_server import index_project; asyncio.run(index_project('/projects/YeniProjem'))"
```

## 3. Cursor / VS Code Ayarı

### Cursor
1. Cursor Settings > MCP > **Add New MCP Server**
2. Name: `GraphRagMCP`
3. Type: `command`
4. Command: `docker exec -i graph-mcp python -m src.mcp_server`

### VS Code (Claude Dev / Roo Code)
MCP ayarlarında command olarak `docker` ve args olarak `["exec", "-i", "graph-mcp", "python", "-m", "src.mcp_server"]` kullanın.

## 4. Doğrulama
Chat ekranında şunları sorarak test edin:
- "Bu projenin ana amacı nedir?"
- "Hangi teknolojiler kullanılmış?"

---

## Sık Karşılaşılan Sorunlar

| Sorun | Çözüm |
|-------|-------|
| `Collection not found` | İndeksleme komutunun başarıyla tamamlandığından emin olun. |
| `OpenRouter Error` | `.env` dosyasındaki API key'i kontrol edin. |
| `index_agent_docs` timeout oldu | `docker exec graph-mcp python /app/scripts/index_vendoris.py /projects/ProjeAdı` ile çalıştır |
| Konteyner duruyor | `docker logs graph-mcp` ile hataya bakın. |
