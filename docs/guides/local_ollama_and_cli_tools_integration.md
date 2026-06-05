# 🦙 GraphRagMCP V2 — Yerel Ollama ve CLI Araçları Entegrasyon Kılavuzu

Bu kılavuz, **GraphRagMCP V2** platformunun yerel yapay zeka altyapınız (**Ollama**) ile nasıl çalıştırılacağını ve kullandığınız terminal tabanlı profesyonel geliştirici araçları (**Claude Code**, **Copilot CLI**, **Gemini CLI**) ile nasıl entegre edileceğini adım adım açıklar.

---

## 🦙 1. Yerel Ollama Entegrasyonu (Host <-> Docker)

Yerel makinenizde çalışan **Ollama**'yı GraphRagMCP V2'nin Docker servislerine bağlamak için izlemeniz gereken adımlar şunlardır:

### A. Ollama Model Hazırlığı
Öncelikle yerel terminalinizde kodlama ve mimari analizler için en kararlı ve güçlü açık kaynaklı model olan **`qwen2.5-coder:latest`** modelini çekin:
```bash
ollama pull qwen2.5-coder:latest
```
*(Alternatif olarak `deepseek-coder:6.7b` veya `llama3.1` kullanabilirsiniz).*

### B. `.env` Dosyası Yapılandırması
Docker içerisinden Host makinenizde çalışan Ollama'ya güvenli bir şekilde erişebilmek için projenizin kök dizinindeki [`.env`](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/.env) dosyasını aşağıdaki gibi güncelleyin:

```env
# ── LLM Sağlayıcısı (Ollama Köprüsü) ──────────────────────────────────────
# Docker konteynerlerinin host makinedeki Ollama portuna (11434) erişmesi için:
LLM_BASE_URL=http://host.docker.internal:11434/v1

# Ollama şifre doğrulaması istemez ancak kütüphane uyumluluğu için rastgele bir değer verin:
OPENAI_API_KEY=ollama

# ── Kullanılacak Yerel Modeller ──────────────────────────────────────────
ANALYSIS_MODEL=qwen2.5-coder:latest
REASONING_MODEL=qwen2.5-coder:latest
```

> [!IMPORTANT]
> **Vektör Veritabanı ve Embedding Uyumluluğu:** 
> Projelerinizdeki mevcut indeksleri (Neo4j ve Qdrant) bozmamak için `EMBEDDING_MODEL` ayarını değiştirmemeniz önerilir. Sistem, büyük miktarda token tüketen chat ve analiz işlemlerini tamamen **ücretsiz ve yerel Ollama** üzerinden çalıştırırken; yüksek hassasiyetli kod arama vektörleri için mevcut embedding sağlayıcınızı (OpenRouter/OpenAI) kullanmaya devam ederek hızı ve uyumluluğu korur.

---

## 🤖 2. Claude Code (v2.1.148) Entegrasyonu

**Claude Code CLI** (`claude`), projenizdeki yerel MCP sunucularını doğrudan tanıyabilen son derece gelişmiş bir ajan aracıdır. Terminal üzerinde çalıştığı için Docker'a doğrudan erişebilir.

### Entegrasyon Adımları:
1. Projenizin kök dizinine (`GraphRagMCP`, `Vendoris` veya `WareLogisticcBys`) gidin.
2. Terminalinizden `claude` komutunu çalıştırarak asistanı başlatın:
   ```bash
   claude
   ```
3. Ajan ilk açılışta proje kökündeki `.mcp.json` dosyasını tarayacaktır. Karşınıza şu onay sorusu gelecektir:
   > `Allow project MCP servers? (y/N)`
4. **`y` (Yes)** yazıp onaylayın.
5. Claude Code, arka plandaki `graph-mcp` Docker sunucunuzla el sıkışacak ve tüm semantik araçları (`search_code`, `execute_agent_task` vb.) komut paletine yükleyecektir.
6. Ajanın yerel verileri verimli kullanabilmesi için ilk komutunuzu şu şekilde verin:
   > *"Lütfen bu projeyi `index_project` aracıyla semantik olarak indeksler misin?"*

---

## 🚀 3. Copilot (v1.0.51) ve OpenAI API Bridge Entegrasyonu

Kullandığınız **GitHub Copilot CLI** veya IDE Copilot eklentileri yerel MCP sunucularına doğrudan bağlanamaz. Ancak projenize yeni kazandırdığımız **OpenAI API Bridge** sayesinde, Copilot'u projenizin GraphRAG veritabanına bağlayabiliriz.

### A. OpenAI Bridge Nasıl Çalışır?
FastAPI tabanlı `openai-bridge` servisimiz host makinenizde **`5555`** portu üzerinden çalışır. Copilot chat ekranından soru sorduğunuzda:
1. Gelen soru `5555` portunda yakalanır.
2. Arka planda `search_code`, `search_repo_architecture` ve `recall_memory` asenkron olarak tetiklenir.
3. Kod tabanınızın semantik haritası ve kod parçaları sorunuza otomatik eklenir (augmented prompt).
4. İstek yerel **Ollama**'ya yönlendirilir ve OpenAI uyumlu standart bir JSON yanıtı döndürülür.

### B. Entegrasyon:
Copilot eklentinizin veya CLI aracınızın `API Base URL` alanını veya terminal environment değişkenlerini yerel OpenAI Bridge köprümüze yönlendirin:
```bash
# Terminal tabanlı araçlar veya özel OpenAI SDK'ları için:
export OPENAI_BASE_URL=http://localhost:5555/v1
export OPENAI_API_KEY=ollama
```

Eğer **Continue.dev** (Rider/VS Code eklentisi) kullanıyorsanız, `~/.continue/config.json` dosyasındaki model sağlayıcıyı şu şekilde yerel köprüye bağlayabilirsiniz:
```json
"models": [
  {
    "title": "GraphRAG-MCP Local (Ollama)",
    "provider": "openai",
    "model": "graph-mcp",
    "apiBase": "http://localhost:5555/v1"
  }
]
```

---

## ♊ 4. Gemini CLI (v0.42.0) Entegrasyonu

**Gemini CLI** (`gemini` veya `gemini-cli`), Google'ın güçlü Gemini modellerine terminalden erişmenizi sağlar. Gemini CLI ile yerel GraphRagMCP yapısını birleştirmek için en verimli yol, CLI isteklerini **OpenAI API Bridge** üzerinden yerel Ollama modelinize ve kod tabanı verilerinize yönlendirmektir.

Gemini CLI'ı yerel API köprümüze bağlamak için terminalinizde şu çevre değişkenlerini ayarlayın:

```bash
# Gemini CLI'ı yerel GraphRagMCP OpenAI API Bridge sunucusuna yönlendirin:
export GEMINI_API_BASE=http://localhost:5555/v1
export GEMINI_API_KEY=ollama
```

Artık terminalinizde Gemini CLI üzerinden sorgu yaptığınızda, istek yerel Docker köprümüze gelecek; Neo4j/Qdrant vektör arama sonuçlarınız asenkron sorgulanıp sorunuzun üzerine enjekte edilecek ve yerel **Ollama (Qwen2.5-Coder)** modeliniz tarafından yanıtlanacaktır.

---

## 📊 Özet Entegrasyon Matrisi

| Araç | Bağlantı Türü | LLM Sağlayıcı | Yapılandırma Yöntemi |
| :--- | :--- | :--- | :--- |
| **Claude Code** | **Doğrudan MCP (Stdio)** | Anthropic (Reasoning) + Local GraphRAG | Proje kökündeki `.mcp.json` üzerinden otomatik izin verilerek çalışır. |
| **Ollama (Yerel)** | **Doğrudan LLM Sağlayıcı** | Tamamen Yerel (Offline) | `.env` dosyasında `LLM_BASE_URL=http://host.docker.internal:11434/v1` tanımlanarak. |
| **Copilot** | **OpenAI API Bridge (5555)** | Local Ollama + Local GraphRAG | `http://localhost:5555/v1` base URL yönlendirmesiyle. |
| **Gemini CLI** | **OpenAI API Bridge (5555)** | Local Ollama + Local GraphRAG | `GEMINI_API_BASE=http://localhost:5555/v1` çevre değişkeniyle. |

Bu mimari sayesinde yerelde çalışan **Ollama**'nın sınırsız işlem gücünü, **GraphRagMCP V2**'nin semantik kod belleğiyle birleştirerek tamamen size özel, yüksek gizlilikli ve sıfır API maliyetli profesyonel bir yazılım geliştirme ortamına sahip olursunuz!
