# GraphRagMCP — Claude Code Kılavuzu

Bu proje bir MCP sunucusudur. Tüm kod analizi, arama ve bellek işlemleri için aşağıdaki MCP araçlarını kullan. Doğrudan dosya okuma yerine önce MCP araçlarını dene.

---

## MCP Sunucusu

- **Adı:** `graph-mcp`
- **Transport:** SSE — `http://deva.adanaekspres.com:8000/sse`
- **Koleksiyon varsayılanı:** `WareLogisticcBYS`

---

## Türkçe → MCP Tool Eşleme Tablosu

Kullanıcı Türkçe yazdığında aşağıdaki tablodan doğru tool'u seç ve çağır. `collection` parametresi belirtilmemişse `WareLogisticcBYS` kullan.

### Arama & Analiz

| Kullanıcı şunu yazdığında | Çağrılacak Tool | Notlar |
|---------------------------|-----------------|--------|
| "… ara", "… bul", "… nerede" | `search_code` | query parametresine kullanıcının metnini ver |
| "… açıkla", "… anlat", "… ne yapıyor" | `explain_code` | query = dosya adı veya konu |
| "mimari", "katman", "genel yapı" | `search_repo_architecture` | query = kullanıcının metni |
| "tam metin", "string ara", "grep" | `grep_exact_string` | query = aranan metin |
| "dokümantasyon ara", "kural ara" | `search_agent_docs` | query = kullanıcının metni |

### İndeksleme

| Kullanıcı şunu yazdığında | Çağrılacak Tool | Notlar |
|---------------------------|-----------------|--------|
| "indeksle", "tara", "kaydet kodu" | `index_project` | project_path zorunlu |
| "sadece değişenleri indeksle", "artımlı" | `incremental_index_project` | project_path zorunlu |
| "dokları indeksle", "AGENTS.md indeksle" | `index_agent_docs` | project_path zorunlu |
| "projeyi kaydet", "sisteme ekle" | `register_project` | project_path zorunlu |
| "projeleri göster", "hangi projeler var" | `list_projects` | parametre yok |
| "repo özetle", "proje özeti" | `summarize_repository` | project_path zorunlu |

### Bellek & Karar

| Kullanıcı şunu yazdığında | Çağrılacak Tool | Notlar |
|---------------------------|-----------------|--------|
| "bunu hatırla", "belleğe kaydet" | `store_memory` | title + content zorunlu |
| "ne hatırlıyorsun", "belleğe bak" | `recall_memory` | query = konu |
| "kararı kaydet", "mimari karar" | `store_decision_memory` | title + content + collection zorunlu |
| "kararları ara", "geçmiş kararlar" | `search_decisions` | query = konu |
| "belleği sıkıştır", "belleği temizle" | `compact_memory` | collection zorunlu |
| "bellek döngüsü çalıştır" | `run_memory_cycle` | collection zorunlu |

### Görev Yönetimi

| Kullanıcı şunu yazdığında | Çağrılacak Tool | Notlar |
|---------------------------|-----------------|--------|
| "görev oluştur", "task aç" | `create_agent_task` | title + description + collection |
| "görev durumu", "task nerede" | `get_task_status` | task_id zorunlu |
| "görevi onayla", "adımı onayla" | `approve_task_step` | task_id zorunlu |
| "görevi tamamla", "kapat" | `complete_task` | task_id zorunlu |
| "göreve devam et", "resume" | `resume_task` | task_id zorunlu |
| "görevleri listele", "açık tasklar" | `list_agent_tasks` | collection opsiyonel |
| "ajan çalıştır", "otomatik yap" | `execute_agent_task` | goal + project_path zorunlu |

### Proje & Kalite

| Kullanıcı şunu yazdığında | Çağrılacak Tool | Notlar |
|---------------------------|-----------------|--------|
| "proje durumu", "ne aşamada" | `get_project_state` | collection zorunlu |
| "aktif faz", "hangi fazda" | `get_active_phase` | collection zorunlu |
| "değişim etkisi", "ne etkilenir" | `analyze_change_impact` | project_path + changed_paths |
| "güvenlik tara", "açık bul" | `security_scan` | project_path zorunlu |
| "refactor öner", "iyileştirme" | `refactor_suggestions` | project_path zorunlu |
| "test öner", "unit test yaz" | `test_suggestion` | project_path + target_file |
| "kopya kod bul", "clone detection" | `code_clone_detection` | collection zorunlu |
| "doğrulama çalıştır", "build test" | `run_verification_plan` | project_path zorunlu |
| "istatistikler", "token kullanımı" | `get_control_plane_stats` | parametre yok |

---

## Öncelik Sırası

1. Önce **MCP araçlarını** kullan — doğrudan dosya okuma ikinci seçenek.
2. `search_code` yetersiz kalırsa (`retrieval yetersiz` uyarısı gelirse) `grep_exact_string` ile dene.
3. `explain_code` için `search_code` sonucu varsa LLM çağrısını atla — kodu kendin analiz et.
4. Collection adı her zaman **lowercase** — `WareLogisticcBYS` değil `warelogisticcbys` olarak geç.

---

## Slash Commands

Tüm toollar `/komut-adı` olarak da kullanılabilir. `.claude/commands/` dizininde tanımlıdır:

```
/g-kod-ara             → search_code
/g-kodu-açıkla         → explain_code
/g-mimari-ara          → search_repo_architecture
/g-metin-ara           → grep_exact_string
/g-dok-ara             → search_agent_docs
/g-indeksle            → index_project
/g-artimli-indeksle    → incremental_index_project
/g-dok-indeksle        → index_agent_docs
/g-proje-kaydet        → register_project
/g-projeleri-listele   → list_projects
/g-repo-ozetle         → summarize_repository
/g-bellek-kaydet       → store_memory
/g-bellek-ara          → recall_memory
/g-bellek-sikistir     → compact_memory
/g-bellek-dongusu      → run_memory_cycle
/g-karar-kaydet        → store_decision_memory
/g-karar-ara           → search_decisions
/g-gorev-olustur       → create_agent_task
/g-gorev-durumu        → get_task_status
/g-gorev-onayla        → approve_task_step
/g-gorev-tamamla       → complete_task
/g-gorev-devam         → resume_task
/g-gorevleri-listele   → list_agent_tasks
/g-ajan-calistir       → execute_agent_task
/g-proje-durumu        → get_project_state
/g-aktif-faz           → get_active_phase
/g-degisim-etkisi      → analyze_change_impact
/g-guvenlik-tara       → security_scan
/g-refactor-oner       → refactor_suggestions
/g-test-oner           → test_suggestion
/g-kopya-kod-bul       → code_clone_detection
/g-dogrulama-calistir  → run_verification_plan
/g-istatistikler       → get_control_plane_stats
/g-retrieval-test      → run_retrieval_eval
```
