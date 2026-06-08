# 🧠 GraphRAG-Augmented Coding Agent — Mimari Değerlendirme ve Üretim (Production) İyileştirme Raporu

**GraphRagMCP V2** platformunun sunduğu AST, PageRank ve semantik topluluk analizi gibi güçlü altyapı, **TDAD (Test-Driven Agentic Development)** döngüsü ve **Complexity Router** mekanizması ile birleştirilerek bir üretim (production) planına dönüştürülmüştür. 2026 SOTA bulgularına dayanan bu yaklaşım, bağlam kalitesini optimize ederek yüksek başarı elde etmeyi hedeflemektedir.

Sistemin üretim ortamlarında ölçeklenebilir, güvenli ve hatasız çalışabilmesi için tespit edilen kritik noktalar, mimari durumlar ve iyileştirme önerileri aşağıda yapılandırılmış olarak sunulmuştur.

---

## 🛠️ Üretim Ortamı İçin Tespit Edilen Noktalar ve Çözüm Önerileri

### 1. Eşzamanlılık ve Kirli Çalışma Alanı (Dirty Workspace) Yönetimi
* Mevcut plan, ajanın doğrudan ana `project_path` üzerinde çalışacağını varsaymaktadır.
* Birden fazla ajan aynı proje üzerinde farklı görevler yürüttüğünde veya tek bir ajan ardışık yansıma (reflection) döngülerinde kod yazarken yarış durumu (race condition) oluşabilir.
* Çözüm olarak, görev tetiklendiği an `Execution Plane` projenin geçici bir kopyasını (ephemeral clone) veya sandbox alanını izole olarak kullanmalıdır. Tüm TDAD döngüsü bu izole alanda koşturulmalı ve yalnızca **Adım ⑦ (COMMIT)** aşamasında onay alındıktan sonra ana depoya aktarılmalıdır.

### 2. Durumsal Kalıcılık ve Çökme Toleransı (Crash Recovery)
* TDAD döngüsündeki adımlar ve özellikle insan onayı bekleyen süreçler zaman alabilir.
* Tasarlanan FastAPI mimarisinde bu CodeAct akışı bellek içi bir döngü olarak kurgulanırsa, `agent-api` konteynerinin olası kesintilerinde süreçler etkilenebilir.
* Çözüm olarak, ajanın adımları (`SPEC` ➔ `TEST` ➔ `EDIT` vb.) birer durum (state) olarak PostgreSQL üzerinde audit logları ve state tabloları ile kayıt altına alınmalıdır. Arka planda çalışan bir worker kuyruğu kullanılarak, son checkpoint'ten görevin geri yüklenmesi sağlanmalıdır.

### 3. Sandbox İzolasyon Sınırları ve Güvenlik
* Plan dahilinde `Execution Plane` içerisinde `Mount Policy` ve `Tool Policy` katmanları ile izole sandbox ve komut güvenlik taraması bulunmaktadır.
* `run_verification_plan` aracının komutları tam olarak hangi katmanda ve nasıl çalıştıracağı netleştirilmelidir.
* Çözüm olarak, `run_verification_plan` aracı test ve derleme komutlarını ağ erişimi kısıtlı ve izole edilmiş geçici test konteynerleri kullanarak yürütmelidir.

### 4. TDAD Döngüsünde Test Doğrulama Stratejisi
* Adım ② kapsamında projede test bulunmuyorsa test önerisi alınması veya ajanın test yazması planlanmaktadır.
* Ajan hem kodu hem de testi kurguladığında halüsinasyon riskini önlemek kritik bir öneme sahiptir.
* Çözüm olarak, ajan yeni bir test dosyası oluşturduğunda, kod değişikliği (patch) uygulanmadan önce bu test çalıştırılmalı ve işlev henüz geliştirilmediği için ilk aşamada başarısız (FAIL) olduğu doğrulanmalıdır.

### 5. Complexity Router İçin Donanım Duyarlılığı
* Kural tabanlı deterministik skorlama yaklaşımında Tier 1 (Lokal Ollama) seviyesinde `qwen2.5-coder:32b` kullanımı ve 8K context bütçesi planlanmaktadır.
* Mevcut skorlama sunucu yükünü veya anlık kuyruk durumunu içermemektedir.
* Çözüm olarak, skorlama sistemine anlık donanım metrikleri eklenerek, yoğunluk durumunda istek otomatik olarak Tier 2 (`gemini-2.5-flash`) seviyesine yönlendirilebilmelidir.

### 6. İnsan Katılımı (HITL) İçin Zamanaşımı Politikası
* `CODEACT_HUMAN_APPROVAL` yapılandırmasında, sistem kullanıcıdan onay isteği beklemektedir.
* Kullanıcının uzun süre onay vermemesi durumunda kaynakların askıda kalmaması sağlanmalıdır.
* Çözüm olarak, bekleyen insan onayları için bir zamanaşımı (TTL) süresi tanımlanmalı, süre dolduğunda görev otomatik olarak duraklatılmış (`SUSPENDED`) durumuna çekilerek kaynaklar serbest bırakılmalıdır.

---

## 📂 Güncellenmiş Dosya Yapısı Önerisi

Mevcut dosya yapısı planına uygun olarak **Kuyruk/Worker** ve **Kalıcı Durum (State Machine)** katmanlarının eklenmesi şu şekildedir:

```text
src/
├── agent_api/
│   ├── app.py                           # FastAPI uygulaması
│   ├── endpoints/
│   │   ├── agent_endpoints.py           # /agent/* tüm endpoint'ler
│   │   └── health_endpoints.py          # /health, /ready, /metrics
│   ├── models/
│   │   └── api_models.py                # Pydantic v2 request/response
│   ├── streaming/
│   │   └── sse_handler.py               # SSE canlı event akışı
│   └── workers/                         # Arka plan CodeAct döngü worker'ları
│       └── task_worker.py               # Görevleri kuyruktan tüketir
│
├── agent/
│   ├── codeact_runner.py                # TDAD CodeAct orkestratör
│   ├── state_machine.py                 # Görev checkpoint'lerini DB'ye işleyen yapı
│   ├── spec_builder.py                  # Görev spec oluşturucu
│   └── context_assembler.py             # GraphRAG bağlam optimizörü
│
└── control/
    └── models/
        ├── complexity_router.py         # 30+ sinyal, tier seçici
        ├── escalation_manager.py        # Tier yükseltme + öğrenme
        └── model_router.py              # Mevcut model_router
```

---

## ✅ Üretim Kontrol Listesi

Aşağıdaki maddeler uygulamaya geçilmeden önce tamamlanmış olmalıdır:

| # | Konu | Durum |
|---|------|-------|
| 1 | Ephemeral workspace izolasyonu (`git worktree` veya tmpfs) | ⬜ Bekliyor |
| 2 | PostgreSQL state tablosu + checkpoint kayıt mekanizması | ⬜ Bekliyor |
| 3 | Worker kuyruğu (Redis Streams veya asyncio Queue) | ⬜ Bekliyor |
| 4 | `run_verification_plan` → geçici konteyner izolasyonu | ⬜ Bekliyor |
| 5 | Test-first doğrulama: patch öncesi test FAIL kontrolü | ⬜ Bekliyor |
| 6 | Ollama sunucu yük kontrolü → otomatik tier yükseltme | ⬜ Bekliyor |
| 7 | HITL zamanaşımı (TTL) + SUSPENDED durum geçişi | ⬜ Bekliyor |

---

## 🔗 İlgili Belgeler

- [Orkestrasyon Planı](agent_orchestration_plan.md)
- [Execution Plane V2](../architecture/EXECUTION_PLANE_V2.md)
- [Control Plane V2](../architecture/CONTROL_PLANE_V2.md)
- [Agent Plane V2](../architecture/AGENT_PLANE_V2.md)
