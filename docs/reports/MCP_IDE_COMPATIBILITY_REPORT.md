# 🔌 GraphRagMCP V2 — IDE Uyumluluğu ve MCP Köprüsü Araştırma Raporu

Bu rapor; JetBrains Rider, GitHub Copilot, Gemini ve Claude gibi popüler AI araçlarının Model Context Protocol (MCP) sunucularını okumada/bağlanmada yaşadığı entegrasyon zorluklarını aşmak, bu yapıyı daha sürdürülebilir kılmak ve MCP desteği olmayan istemcilere (clients) köprü (bridge) kurmak amacıyla hazırlanmıştır.

---

## 🗺️ 1. JetBrains Rider (Aktif IDE) ve MCP Entegrasyonu

Geliştirme yaptığınız **JetBrains Rider** ortamı, son güncellemelerle (v2025.2 ve üzeri) birlikte sektöre öncülük eden çok güçlü bir **çift yönlü MCP altyapısına** sahiptir. Bu sayede harici köprülere ihtiyaç duymadan doğrudan entegrasyon sağlayabilirsiniz.

### A. Rider'ı bir MCP İstemcisi (AI Assistant) Olarak Kullanma
Rider'ın kendi yerel **AI Assistant** paneline `GraphRagMCP` sunucunuzu doğrudan bir araç olarak bağlayabilirsiniz:
1.  Rider ayarlarını açın: `Settings | Tools | AI Assistant | Model Context Protocol (MCP)`.
2.  **Add New MCP Server** butonuna tıklayın:
    *   **Name:** `GraphRagMCP`
    *   **Command:** `docker`
    *   **Arguments:** `["exec", "-i", "graph-mcp", "python", "-m", "src.mcp_server"]`
3.  Artık Rider'ın yapay zeka chat ekranında, GraphRagMCP araçları otomatik olarak AI asistanı tarafından kullanılabilir hale gelecektir.

### B. Rider'ı bir MCP Sunucusu Olarak Dışarıya Açma
Rider, projenizin AST yapısını, dosyalarını ve terminal yeteneklerini harici AI ajanlarına (örn. Claude Desktop) sunabilir:
*   `Settings | Tools | MCP Server` sekmesinden Rider'ın yerel MCP sunucusunu aktif hale getirebilirsiniz. Bu sayede harici ajanlar projenizi çok daha derinlemesine okuyabilir.

---

## 🤖 2. GitHub Copilot ve Gemini Entegrasyon Çözümleri

**GitHub Copilot Chat** ve **Gemini (IDE / Codex)** gibi araçlar, standart olarak kapalı ekosistemlerde çalıştıkları için yerel stdio tabanlı MCP sunucularını okumakta veya doğrudan tetiklemekte zorlanabilirler. Bu durumları aşmak için 3 ana çözüm yolu bulunmaktadır:

```
┌─────────────────────────────────┐
│     GitHub Copilot / Gemini     │ (OpenAI API Protokolü)
└────────────────┬────────────────┘
                 │
                 ▼ (v1/chat/completions)
┌─────────────────────────────────┐
│  GraphRagMCP OpenAI API Gateway  │ (FastAPI Köprüsü)
└────────────────┬────────────────┘
                 │
                 ▼ (MCP Protocol)
┌─────────────────────────────────┐
│      GraphRagMCP V2 Server      │
└─────────────────────────────────┘
```

### Çözüm A: OpenAI Uyumlu API Geçidi (Gateway Bridge) — *Tavsiye Edilen Ekstra Yapı*
Eğer kullandığınız araç (Copilot, Gemini vb.) sadece OpenAI API biçiminde konuşuyorsa, GraphRagMCP V2'nin `Control Plane` katmanına bir **OpenAI API Gateway** modülü ekleyebiliriz.

1.  **Nasıl Çalışır?**
    *   Sisteminizde (FastAPI üzerinde) `/v1/chat/completions` ve `/v1/embeddings` standart uç noktalarını (endpoints) sunan hafif bir API servis katmanı yazılır.
    *   Copilot veya Gemini gibi araçlar bu API'yi standart bir OpenAI veya Custom endpoint (`http://localhost:5555/v1`) olarak görür.
    *   Kullanıcı chat penceresinden soru sorduğunda, bu geçit gelen soruyu alır, arka planda `search_code` veya `search_repo_architecture` MCP araçlarını tetikler, gelen semantik kod bağlamını (context) sorunun üstüne ekler (prompt injection) ve LLM'e (OpenRouter veya doğrudan Gemini API) yönlendirir.
2.  **Kullanım:**
    *   GitHub Copilot'a veya Gemini'ye "Custom Endpoint / Base URL" olarak bu yerel adresi göstererek projenizin tüm GraphRAG bağlamını bu kapalı araçlara enjekte edebilirsiniz.

### Çözüm B: Continue.dev JetBrains Eklentisi (En Kolay & En Esnek Yol)
Eğer Rider içinde bağımsız, açık kaynaklı ve tüm LLM modellerini (Gemini, Claude, GPT-4) destekleyen bir AI paneli istiyorsanız, **Continue.dev** eklentisi en sürdürülebilir çözümdür:
1.  Rider eklenti marketinden **Continue** eklentisini kurun.
2.  `~/.continue/config.json` dosyasını açın ve `"mcpServers"` dizisine sunucunuzu ekleyin:
    ```json
    "mcpServers": [
      {
        "name": "graph-mcp",
        "command": "docker",
        "args": ["exec", "-i", "graph-mcp", "python3", "-m", "src.mcp_server"]
      }
    ]
    ```
3.  Continue panelinde `@graph-mcp` yazarak projenizi sorgulayabilir ve tüm semantik araçları sıfır gecikmeyle kullanabilirsiniz.

### Çözüm C: GitHub Copilot Agent Mode (v1.5.0+)
Eğer kurumsal Copilot kullanıyorsanız ve en güncel sürüme sahipseniz:
*   Copilot ayarlarından **Agent Mode**'u aktifleştirin.
*   Copilot ayarlarındaki **MCP Servers** sekmesine gidin ve `docker exec -i graph-mcp python -m src.mcp_server` komutunu sunucu olarak ekleyin.

---

## 🛠️ GraphRagMCP V2 İçin Önerilen "MCP Bridge" Yol Haritası

IDE'lerinizle tam entegrasyon sağlamak için projenize eklemenizi önerdiğimiz ekstra yapılar:

| Eklenecek Ekstra Yapı | Sorumlu Katman | Çözeceği Darboğaz | Uygulama Yöntemi |
| :--- | :--- | :--- | :--- |
| **`OpenAI API Proxy Gateway`** | **Control Plane** | Gemini ve standart Copilot'un MCP sunucusuna doğrudan erişememesi. | `src/control/gateway.py` altında FastAPI tabanlı OpenAI `/v1/chat/completions` uç noktalarının simüle edilmesi. |
| **`SSE (Server-Sent Events) Transport`** | **mcp/server.py** | stdio (standard input/output) protokolünde yaşanan boru hattı (piping) tıkanmaları ve yetki sorunları. | MCP sunucusunu stdio yerine **HTTP + SSE** üzerinden çalışacak şekilde genişletmek. |
| **`Continue.dev Entegrasyon Kılavuzu`** | **docs/guides/** | Geliştiricilerin Rider/VS Code içinde hızlıca MCP'yi aktif edememesi. | `docs/guides/continue_setup.md` dokümanının projeye eklenmesi. |

---

## 📈 Sonuç

Copilot, Gemini ve kapalı kod asistanlarının MCP okuyamaması, protokolün doğası gereği (stdio tabanlı yerel yetkilendirme) pazar genelinde yaşanan kronik bir durumdur. 

Bu sorunu aşmak için projenize ekleyeceğimiz asenkron bir **OpenAI API Gateway (Bridge)** ve **HTTP-SSE taşıma katmanı**, `GraphRagMCP V2` sunucunuzu standart bir OpenAI API ucuna dönüştürecektir. Böylece piyasadaki **herhangi bir LLM istemcisi veya IDE eklentisi**, sanki uzak bir GPT-4o modeline bağlanıyormuş gibi sizin yerel semantik kod belleğinize bağlanabilecek ve darboğazlar tamamen ortadan kalkacaktır.
