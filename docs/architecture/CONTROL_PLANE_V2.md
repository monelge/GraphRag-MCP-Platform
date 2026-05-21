# Control Plane V2 Mimari Tasarımı

## 1. Amaç
Control Plane V2, sistemi sadece "bütçe dolunca duran" bir yapıdan çıkarıp, **"maliyet/fayda optimizasyonu yapan ve proaktif denetim sağlayan"** bir yönetim katmanına dönüştürmeyi hedefler. NVIDIA NeMo Guardrails ve AI FinOps (Financial Operations) prensiplerini temel alır.

## 2. Ana Bileşenler (SOTA Entegrasyonları)

### A. Multi-tier Model Routing (Kademeli Model Yönlendirme)
*   **Sorun:** Her görev için en pahalı modeli (GPT-4o) kullanmak gereksiz maliyet yaratıyor.
*   **V2 Çözümü:** Görevler zorluk derecesine göre 3 seviyeye ayrılır:
    *   **Tier 1 (SLM):** Sınıflandırma, formatlama ve basit extraction işlemleri için `gpt-4o-mini` veya `llama-3-8b`.
    *   **Tier 2 (Standard):** Kod yazımı ve standart mantık yürütme için `claude-3-5-sonnet`.
    *   **Tier 3 (Frontier):** Karmaşık mimari kararlar ve final inceleme için `o1-preview` veya `gpt-4o`.

### B. Yield-based Budget Guardrails (Verim Odaklı Bütçe Denetimi)
*   **Sorun:** Ajan bazen bir hatayı düzeltmek için 10 kere üst üste başarısız deneme yaparak bütçeyi tüketiyor.
*   **V2 Çözümü:** "Verim Analizi" mekanizması eklenir. Eğer ajan son 3 adımda "belirsizliği azaltamadıysa" veya "test sonuçlarında ilerleme kaydedemediyse", bütçe dolmasa bile işlem durdurulur ve "Plan Revizyonu" veya "İnsan Onayı" istenir.

### C. Forensic Audit Logging (Adli Denetim Kayıtları)
*   **Sorun:** Bir güvenlik ihlali veya bütçe aşımı olduğunda "neden" olduğunu anlamak zor.
*   **V2 Çözümü:** Her adımın niyet (intent), kullanılan araç, harcanan token ve üretilen sonuç verileri PostgreSQL'de **ilişkisel ve değiştirilemez** bir şekilde saklanır. Bu veriler üzerinden "Maliyet/Başarı" analizi raporları üretilir.

## 3. Yeni Veri Akışı

1.  **REQUEST:** Agent bir işlem yapmak ister.
2.  **ROUTING (Yeni):** Görevin karmaşıklığı analiz edilir ve en ucuz ama yetenekli model seçilir.
3.  **GUARDRAIL (Yeni):** İşlem öncesi "Bütçe Verimi" kontrol edilir.
4.  **LOGGING:** Tüm meta veriler Forensic Log katmanına yazılır.
5.  **FEEDBACK:** Başarı/Maliyet oranı hesaplanarak bir sonraki adım için bütçe tahsisatı güncellenir.

## 4. Başarı Kriterleri
*   Aynı görev setinde toplam maliyetin %30 oranında düşmesi (Model Routing sayesinde).
*   "Runaway Loops" (Kısır döngü) vakalarının 3 denemeden sonra bütçe bitmeden yakalanması.
*   Tüm işlemlerin saniyeler içinde adli (forensic) olarak izlenebilmesi.
