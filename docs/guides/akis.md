# GraphMCP — VS Code & GitHub Copilot CLI Kullanım Akışı

Bu doküman, GraphMCP'nin günlük geliştirme sürecine nasıl dahil edileceğini özetler.

## 1. Hazırlık (Her sabah)
Sistemin çalıştığından emin olun:

```bash
cd /Volumes/MacBook/RiderProjects/GraphMCP
docker ps
# Beklenen: qdrant → running, graph-mcp → running
```

## 2. Yeni Bir Proje Üzerinde Çalışmaya Başlama
Eğer yeni bir müşteri veya proje klasörü geldiyse, önce onu hafızaya alın:

```bash
docker exec graph-mcp python -c "import asyncio; from src.mcp_server import index_project; asyncio.run(index_project('/projects/YeniProje'))"
```

## 3. Cursor ile Kod Analizi
Cursor Chat (`Cmd+L`) üzerinden `@GraphMCP` tool'unu kullanarak sorularınızı sorun.

**Örnek Senaryolar:**
- **Analiz:** `@GraphMCP Bu projedeki ana veri modellerini ve aralarındaki ilişkiyi açıkla.`
- **Hata Bulma:** `@GraphMCP Log kaydetme işlemi neden bazen başarısız oluyor olabilir? İlgili kodları bul.`
- **Yeni Özellik:** `@GraphMCP Mevcut yapıya uygun bir 'ExportToExcel' fonksiyonu yazmak için hangi sınıfları örnek almalıyım?`

## 4. Claude Desktop / VS Code MCP Extension Kullanımı
Eğer Cursor dışındaki araçları kullanıyorsanız, MCP ayarlarınızın şu şekilde olduğundan emin olun:

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

## 5. Pratik Komutlar (Terminal)

### Bir dosyanın bağlamını hızlıca al:
```bash
docker exec graph-mcp python -c "import asyncio; from src.pipeline.context_builder import ContextBuilder; cb = ContextBuilder(); print(asyncio.run(cb.get_symbol_context('UserService', 'TedarikBYS')))"
```

### Projeleri Listele:
```bash
docker exec graph-mcp python -c "from qdrant_client import QdrantClient; client = QdrantClient('http://qdrant:6333'); print([c.name for c in client.get_collections().collections])"
```

---

## Bakım
- **Haftalık Temizlik:** Kullanmadığınız eski projeleri Qdrant dashboard üzerinden (`localhost:6333`) silebilirsiniz.
- **Model Güncelleme:** Daha iyi analiz için `.env` dosyasındaki `ANALYSIS_MODEL`'i `openai/gpt-4o` olarak güncelleyebilirsiniz.
