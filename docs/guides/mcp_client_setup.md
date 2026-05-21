# 🌐 GraphMCP Client Configuration & Activation Guide

Bu kılavuz, **GraphRagMCP V2** sunucunuzun diğer projelerinizde (`Vendoris` ve `WareLogisticcBys`) çalışırken yapay zeka ajanlarınız (Claude Code, Cursor, Cline/Roo Code) tarafından **kusursuz bir şekilde tanınması** ve **otomatik olarak kullanılması** için gerekli yapılandırmaları içerir.

Ajanınızın dosyaları satır satır manuel okumak (`cat`, `grep` vb.) yerine, GraphMCP'nin güçlü semantik arama ve görev yönetimi yeteneklerini kullanmasını sağlamak için aşağıdaki adımları sırasıyla uygulayın.

---

## 🔍 Sorun Neden Kaynaklanıyor?

Yapay zeka ajanı projeyi başlattığında GraphMCP araçlarını (örneğin `execute_agent_task`, `search_code`, `search_agent_docs`) kullanmak yerine doğrudan dosyaları okuyorsa, bunun 3 temel sebebi vardır:

1. **macOS GUI Çevre Değişkeni Sınırı (Path Sorunu):** macOS üzerinde VS Code, Cursor veya Rider gibi GUI uygulamaları Dock veya Finder üzerinden başlatıldığında, terminaldeki `PATH` değişkeninizi (`/usr/local/bin` vb.) devralmazlar. Dolayısıyla `.mcp.json` dosyasındaki `"command": "docker"` komutunu çalıştırırken **"docker: command not found"** hatası alırlar ve MCP sunucusuna bağlanamazlar.
2. **IDE/Client Desteği:** Kullandığınız istemcinin (Cursor vb.) projedeki yerel `.mcp.json` dosyasını otomatik olarak okuma desteği olmayabilir. Bu durumda sunucuyu manuel olarak IDE ayarlarına eklemek gerekir.
3. **Pre-flight İndeksleme Eksikliği:** Proje ilk kez açıldığında henüz indekslenmemişse, GraphMCP veri tabanında (Neo4j/Qdrant) o projeye ait veri bulunmaz ve arama sonuçları boş döner. Ajan da mecbur kalarak dosyalara doğrudan erişir.
4. **Agent Yönlendirme Eksikliği:** Ajanın sistem talimatlarında GraphMCP araçlarını önceliklendirmesi söylenmemiştir.

---

## 🛠️ Çözüm Adımları

Sorunu tamamen ortadan kaldırmak için hem **yapılandırma dosyalarınızı güncelledik** hem de **IDE/Ajan bazlı ayarları** aşağıda detaylandırdık.

### 1. `.mcp.json` Dosyalarınızı Güncelledik (Çözüldü ✅)
Ajanın `docker` binary dosyasını her ortamda (hem terminalde hem de GUI IDE'lerde) sorunsuz bulabilmesi için `.mcp.json` dosyalarınızdaki `command` alanını mutlak yol (absolute path) olan **`/usr/local/bin/docker`** ile güncelledik.

**`Vendoris` / `WareLogisticcBys` güncellenmiş `.mcp.json` yapısı:**
```json
{
  "mcpServers": {
    "graph-mcp": {
      "type": "stdio",
      "command": "/usr/local/bin/docker",
      "args": [
        "exec", "-i",
        "-e", "DEFAULT_COLLECTION=Vendoris", // Diğerinde WareLogisticcBYS
        "graph-mcp",
        "python", "-m", "src.mcp_server"
      ]
    }
  }
}
```

### 2. Ajan Kuralları (`.clauderules` ve `.cursorrules`) Eklendi (Çözüldü ✅)
Ajanınızın (özellikle **Claude Code**) projeyi ilk açtığında dosyaları doğrudan okumak yerine öncelikle **GraphMCP araçlarını kullanmasını zorunlu kılmak** amacıyla hem `Vendoris` hem de `WareLogisticcBys` kök dizinlerine `.clauderules` ve `.cursorrules` dosyalarını yazdık.

Bu kurallar ajana şunları dikte eder:
- Tüm görev yönetimini `execute_agent_task` üzerinden yap.
- Kod tabanında arama yaparken ham arama komutları yerine `search_code` ve `search_agent_docs` araçlarını kullan.
- Projede çalışmaya başlamadan önce `index_project` ile indeksleme durumunu kontrol et ve indeksle.

---

## 💻 İstemciye (IDE / CLI) Özel Etkinleştirme Adımları

Ajanı çalıştırdığınız platforma göre aşağıdaki adımları doğrulayın:

### A) Claude Code (CLI) Kullanıyorsanız
Claude CLI (`claude`), projedeki `.mcp.json` dosyasını otomatik olarak okur. 
Ancak yerel MCP sunucularını çalıştırmak için izin istemelidir.

1. Terminalinizde `Vendoris` veya `WareLogisticcBys` klasörüne gidin.
2. `claude` komutunu çalıştırın.
3. Ekrana yerel MCP sunucusunu çalıştırmak için izin isteği (`Allow project MCP servers?`) gelirse **Y (Yes)** seçeneğini seçin.
4. İlk sorunuzu sorarken ajana doğrudan **GraphMCP** protokolünü tetikleyecek bir komut verin:
   > *"Lütfen bu projeyi (Vendoris) GraphMCP ile baştan indeksle (index_project aracını çalıştır)."*
5. İndeksleme bittikten sonra görevi başlatmak için:
   > *"execute_agent_task aracını kullanarak sıradaki bekleyen görevi başlatır mısın?"*

### B) Cursor IDE Kullanıyorsanız
Cursor, proje kökündeki `.mcp.json` dosyalarını **otomatik olarak okumaz**. Cursor içerisindeki yapay zekanın GraphMCP'yi görebilmesi için sunucuyu manuel eklemeniz gerekir:

1. **Cursor Settings** (Sağ üstteki çark simgesi veya `Cmd + ,`) açın.
2. **Features** sekmesine gelin ve aşağı kaydırarak **MCP** bölümünü bulun.
3. **+ Add New MCP Server** butonuna tıklayın:
   - **Name:** `graph-mcp-vendoris` (veya projenize göre)
   - **Type:** `command`
   - **Command:** 
     ```bash
     /usr/local/bin/docker exec -i -e DEFAULT_COLLECTION=Vendoris graph-mcp python -m src.mcp_server
     ```
     *(WareLogisticcBYS için collection değerini `WareLogisticcBYS` yapın)*
4. **Save** butonuna tıklayın. Alt kısımda yeşil renkli **Connected** ibaresini görmelisiniz.
5. Cursor Composer veya Chat ekranında çalışırken, ajanın GraphMCP araçlarını listelediğinden emin olabilirsiniz.

### C) VS Code + Roo Code / Cline Kullanıyorsanız
Roo Code veya Cline, projenin kökündeki `.mcp.json` dosyasını otomatik olarak tanıyabilir. 

1. Ekranda MCP sekmesine gidin.
2. `graph-mcp` sunucusunun yeşil renkli ve aktif olduğunu doğrulayın.
3. Eğer görünmüyorsa, küresel ayarlar dosyanıza (`~/Library/Application Support/Claude/claude_desktop_config.json`) sunucuyu manuel olarak ekleyebilirsiniz:
   ```json
   {
     "mcpServers": {
       "graph-mcp-vendoris": {
         "type": "stdio",
         "command": "/usr/local/bin/docker",
         "args": [
           "exec", "-i",
           "-e", "DEFAULT_COLLECTION=Vendoris",
           "graph-mcp",
           "python", "-m", "src.mcp_server"
         ]
       }
     }
   }
   ```

---

## 🚀 En İyi Verim İçin Doğru İletişim Formülü

Ajanınızla çalışmaya başlarken komutları şu şekilde vermeniz, onun doğrudan GraphMCP entegrasyonu üzerinden işlem yapmasını sağlar:

* ❌ **Yanlış İstek:** `@AGENTS.md okuyup hazır hale gelirmisin bekleyen görevlerin nelerdir`
  *(Bu istek ajanı dosyayı doğrudan satır satır okumaya zorlar.)*
*  **Doğru İstek:** `"Lütfen execute_agent_task aracını kullanarak projedeki bekleyen görevleri listele ve sıradaki görevi başlat."`
*  **Doğru İstek:** `"Projeyi semantik olarak analiz etmek istiyorum. index_project aracını çalıştırarak verileri Neo4j ve Qdrant'a yükler misin?"`

Bu adımlar ve yeni eklediğimiz kurallar sayesinde ajanınız artık dosyaları manuel okumak yerine **GraphMCP'yi en verimli şekilde kullanmaya başlayacaktır.**
