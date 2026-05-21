# Agent Plane V2 Mimari Tasarımı

## 1. Amaç
Agent Plane V2, ajanı "tek seferde doğru yapmaya çalışan bir script" olmaktan çıkarıp, "hata yapabilen, hatasını fark eden ve düzelten bir uzman (Agentic Workflow)" haline getirmeyi hedefler. Andrew Ng tarafından tanımlanan **Reflection (Öz-Eleştiri)** ve **Multi-Agent Collaboration** prensiplerini temel alır.

## 2. Ana Bileşenler (SOTA Entegrasyonları)

### A. Reflection & Self-Correction Loop (Öz-Eleştiri Döngüsü)
*   **Sorun:** Mevcut sistemde `Reviewer` bir hata bulduğunda süreç genellikle durur veya başarısız sayılır.
*   **V2 Çözümü:** Eğer `Reviewer` (Kod inceleme) veya `Verifier` (Test doğrulama) aşaması "Red" (Fail) dönerse, sistem otomatik olarak **"Reflection"** durumuna geçer. Bu aşamada hata mesajı ve eleştiri `Editor`'e geri gönderilir ve süreç `Editor -> Reviewer` döngüsüne girer (Max 3 deneme).

### B. Dynamic Planning (Dinamik Planlama)
*   **Sorun:** Başlangıçta yapılan plan, `Retriever` yeni bir dosya veya bağımlılık bulduğunda geçersiz kalabiliyor.
*   **V2 Çözümü:** `Retriever` aşamasından sonra `Planner` tekrar tetiklenerek "Bulunan yeni bilgilere göre planın güncellenmesi gerekiyor mu?" sorusunu yanıtlar. Gerekirse görev listesi (Task Store) çalışma anında revize edilir.

### C. Persona Specialization (Uzmanlık Ayrımı)
*   **Yapı:** 
    *   **Creator (Editor):** Sadece kodu yazmaya odaklanır.
    *   **Critic (Reviewer):** Sadece hataları bulmaya ve güvenlik açıklarını tespit etmeye odaklanır.
    *   **Verifier (Execution):** Sadece testleri koşturup ampirik kanıt sunar.
*   Bu üç persona arasındaki "sağlıklı çatışma", kod kalitesini %40-60 oranında artırır.

## 3. Yeni Durum Makinesi (State Machine) Akışı

1.  **START:** Görev alınır.
2.  **PLAN:** Başlangıç planı oluşturulur.
3.  **RETRIEVE:** İlgili context toplanır.
4.  **DYNAMIC RE-PLAN (Yeni):** Context'e göre plan güncellenir.
5.  **EDIT (ACT):** Kod değişikliği yapılır.
6.  **REVIEW (REFLECT):** Başka bir model/persona kodu inceler.
    *   *FAIL* -> **Loop back to EDIT** (Kritik geri bildirimle birlikte).
    *   *PASS* -> **Go to VERIFY**.
7.  **VERIFY (TEST):** Testler çalıştırılır.
    *   *FAIL* -> **Loop back to EDIT** (Test hatasıyla birlikte).
    *   *PASS* -> **FINISH**.

## 4. Başarı Kriterleri
*   Ajanın kendi yazdığı syntax hatalarını kullanıcıya sormadan otomatik düzeltmesi.
*   Testlerin başarısız olduğu durumlarda ajanın hatayı analiz edip "Kodu şu yüzden düzelttim" diyerek ikinci bir commit/versiyon sunması.
*   Karmaşık, çok dosyalı değişikliklerde (Refactoring) tutarlılığın artması.
