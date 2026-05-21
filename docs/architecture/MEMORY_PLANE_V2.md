# Memory Plane V2 Mimari Tasarımı

## 1. Amaç
Memory Plane V2, ajanın geçmiş konuşmaları ve deneyimlerini "çöplüğe" dönüşmeden yönetmesini hedefler. Sektördeki **Mem0** (Atomic Fact Extraction) ve **MemGPT / Letta** (Active Context Paging) mimarilerinden ilham alarak, hafızayı **hiyerarşik, token verimli ve deduplike edilmiş** bir yapıya kavuşturur.

## 2. Ana Bileşenler (SOTA Entegrasyonları)

### A. Atomic Fact Extraction (Mem0 Yaklaşımı)
*   **Sorun:** Geleneksel RAG, tüm konuşma loglarını (Episodik) doğrudan vektör veritabanına atar. Bu da aynı bilginin ("Kullanıcı Python sever") 10 kere tekrar etmesine ve LLM context'ini şişirmesine neden olur.
*   **V2 Çözümü:** Ajan bir görevi bitirdiğinde, ham loglar yerine küçük bir LLM (gpt-4o-mini) çağrısı ile **"Kalıcı ve Atomik Gerçekler" (Durable Atomic Facts)** çıkarılır. "User prefers explicit typings" gibi net cümleler olarak `semantic` katmana kaydedilir.

### B. Hiyerarşik Bellek (H-MEM / Semantic Routing)
*   **Sorun:** Hafıza büyüdükçe vektör araması yanlış sonuçlar (False Positives) getirmeye başlar.
*   **V2 Çözümü:** Bellekler sadece metin olarak değil, `Domain -> Category -> Fact` hiyerarşisinde saklanır.
    *   *Domain:* Örn. "Architecture", "User Preferences", "Bug Fixes"
    *   Sorgu atıldığında LLM önce doğru "Domain"i seçer, sadece o kategorideki anıları arar. (Context Builder önceliklendirir).

### C. Active Compaction (Otomatik Birleştirme)
*   Mevcut `compact_memory` komutu geliştirildi. Artık sadece "benzer metinleri birleştirmek" yerine, eski `episodic` logları alıp tek bir `procedural` (Kural) veya `semantic` (Bilgi) kaydına dönüştürüp, eskileri arşivliyor.

## 3. Yeni Veri Akışı

1.  **Episodik Kayıt:** Ajan görev sırasında `store_memory(type="episodic")` ile ham notlarını yazar.
2.  **Extraction (Trigger):** Görev bittiğinde (veya `compact_memory` çağrıldığında), sistem son N episodik kaydı alır.
3.  **LLM Consolidation:** LLM, bu karmaşık loglardan 3-4 tane net "Kural" veya "Gerçek" (Atomic Fact) çıkarır.
4.  **Semantic Yazım:** Yeni çıkarılan net bilgiler `semantic` veya `decision` katmanına kalıcı olarak yazılırken, eski logların `status`'ü "archived" yapılarak silinir.

## 4. Başarı Kriterleri
*   Ajanın "Hafıza" klasöründe birbirini tekrar eden kayıtların (Duplicate Memories) olmaması.
*   Geçmişte çözülen bir bug sorulduğunda, 10 sayfalık log yerine "X hatası Y yapılarak çözülür" şeklinde 1 cümlelik net bilginin (Atomic Fact) gelmesi.
*   Arama maliyetlerinin (Token Budget) %50 oranında düşmesi.
