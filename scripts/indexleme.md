# GraphMCP — İndeksleme Kılavuzu

## Genel Bakış

`scripts/` klasöründe iki generic indeksleme scripti bulunur:

| Script | Davranış |
|--------|----------|
| `index.py` | **Incremental** — zaten indekslenmiş dosyaları atlar, kaldığı yerden devam eder |
| `reindex.py` | **Sıfırdan** — Qdrant + Neo4j'deki mevcut veriyi siler, tümünü yeniden indeksler |

Her iki script de:
- Hem **Qdrant** (vektör arama) hem **Neo4j** (graph ilişkileri) indeksler
- `.agent/` dizini varsa **agent docs** (markdown) da indekslenir
- Gizli veri içeren chunk'lar (`secret_scanner`) otomatik atlanır
- Detaylı **Rich progress** konsolu gösterir

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
   Scriptleri düzenledikten sonra `docker exec` ile anında kullanılabilir, rebuild gerekmez.

3. Proje dizinleri host'tan container'a `/projects/` altında görünür:
   ```yaml
   - /Volumes/MacBook/RiderProjects:/projects:ro
   ```

---

## index.py — Incremental İndeksleme

Kaldığı yerden devam eder. Zaten indekslenmiş dosyalar atlanır.

```bash
docker exec graph-mcp python3 /app/scripts/index.py \
    --project Vendoris \
    --path /projects/Vendoris
```

```bash
docker exec graph-mcp python3 /app/scripts/index.py \
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

## reindex.py — Sıfırdan Yeniden İndeksleme

> **⚠ DİKKAT:** Mevcut koleksiyon verisini **kalıcı olarak siler**.  
> Zorunlu kullanıcı onayı vardır — atlatılamaz, `--yes` bayrağı **kaldırılmıştır**.

```bash
# -it zorunlu — script klavye girişi bekler
docker exec -it graph-mcp python3 /app/scripts/reindex.py \
    --project Vendoris \
    --path /projects/Vendoris
```

Script çalışmadan önce **koleksiyon adını birebir yazdırmanızı** zorunlu kılar:

```
╭─ reindex.py — Kullanıcı Onayı Zorunlu ──────────────────────────────────╮
│ ⚠ UYARI — Sıfırdan Yeniden İndeksleme                                   │
│                                                                           │
│   Koleksiyon : Vendoris                                                   │
│   Proje yolu : /projects/Vendoris                                         │
│                                                                           │
│ Bu işlem:                                                                 │
│   • Qdrant'taki 'Vendoris' koleksiyonunu tamamen siler                    │
│   • Neo4j'deki 'Vendoris' node'larını tamamen siler                       │
│   • Tüm dosyaları sıfırdan indeksler                                      │
│                                                                           │
│ Onaylamak için koleksiyon adını tam olarak yazın: Vendoris                │
╰───────────────────────────────────────────────────────────────────────── ╯

Koleksiyon adını yazın (Vendoris): _
```

Yanlış isim girilirse script **iptal edilir**, hiçbir veri silinmez.  
CI/otomasyon ortamlarında `reindex.py` kullanılmamalıdır — bunun yerine `index.py` tercih edin.

### Parametreler

| Parametre | Zorunlu | Açıklama | Örnek |
|-----------|---------|----------|-------|
| `--project` | ✅ | Koleksiyon adı | `Vendoris` |
| `--path` | ✅ | Container içindeki proje dizini | `/projects/Vendoris` |
| `--batch` | ❌ | Embedding batch boyutu (varsayılan: 32) | `16` |

---

## Konsol Çıktısı Örneği

```
╭─ GraphMCP İndeksleme ─────────────────────────────────╮
│ 🗂  Vendoris  ·  /projects/Vendoris                    │
│ Mod: Incremental (kaldığı yerden devam)                │
╰───────────────────────────────────────────────────────╯

──────────────── Kaynak Kod İndeksleme ────────────────

⠸ [1/3] AST Parçalama    245/819  ████░░░░  30%  0:00:12  0:00:28
  [2/3] Graph ilişkileri Neo4j'ye yazılıyor...
⠸ [3/3] Embedding + Qdrant  1240/2800  ███░░░░  44%  0:01:02  0:01:18

──────────────── Agent Docs İndeksleme ────────────────

⠸ [📚] Agent Docs  3/8  ████░░░░  37%  0:00:04

┌─────────────────────── İndeksleme Özeti ───────────────────────┐
│ Koleksiyon           │ Vendoris                                 │
│ Toplam dosya         │ 819                                      │
│ Atlanan (zaten ind.) │ 574                                      │
│ İşlenen dosya        │ 245                                      │
│ Qdrant chunk         │ 1240                                     │
│ Gizli veri (atlandı) │ 2                                        │
│ Agent doc dosya      │ 8                                        │
│ Agent chunk upsert   │ 47                                       │
│ Süre                 │ 142.3s                                   │
└──────────────────────────────────────────────────────────────── ┘
```

---

## İzolasyon Garantisi

Her proje **tamamen izole** tutulur:

- **Qdrant**: Her proje ayrı bir collection'da (`Vendoris`, `WareLogisticcBYS`)
- **Neo4j**: Her node `{collection: "Vendoris"}` property'si taşır; sorgular bu filtreden geçer
- **Redis cache**: Collection bazlı key prefix ile izole edilmiştir

Farklı projelerdeki aynı isimli class/fonksiyon birbirine karışmaz.

---

## Desteklenen Dosya Uzantıları

| Uzantı | Dil |
|--------|-----|
| `.py` | Python |
| `.ts` | TypeScript |
| `.tsx` | TypeScript (React) |
| `.cs` | C# |

Hariç tutulan dizinler: `node_modules`, `bin`, `obj`, `dist`, `.next`, `__pycache__`, `.venv`, `venv`, `migrations`

---

## Ne Zaman Hangisini Kullanmalı?

| Durum | Script |
|-------|--------|
| Yeni dosyalar eklendi / değişiklikler var | `index.py` |
| İlk kez indeksleme | `index.py` |
| Index bozuldu / tutarsız sonuçlar | `reindex.py` |
| Proje kodu büyük ölçüde yeniden yapılandırıldı | `reindex.py` |
| İnkremental indeks yanlış sonuç veriyor | `reindex.py` |
