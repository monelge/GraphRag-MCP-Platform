# Execution Plane V2 Mimari Tasarımı

## 1. Amaç
Execution Plane V2, kodun sadece "izole bir kapta" (Docker/Sandbox) çalışmasını değil, çalışmadan önce **niyet, güvenlik ve kaynak** açısından denetlenmesini hedefler. SOTA sistemlerdeki (E2B, Modal) "Pre-flight Validation" ve "Intent Alignment" prensiplerini temel alır.

## 2. Ana Bileşenler (SOTA Entegrasyonları)

### A. Pre-flight Validation (Uçuş Öncesi Kontrol)
*   **Sorun:** Ajan bazen yanlış path'lerde komut koşturmaya çalışıyor veya eksik bağımlılıklar nedeniyle hata alıyor.
*   **V2 Çözümü:** Komut sandbox'a gönderilmeden önce bir "Validation Gate" (Denetim Kapısı) tarafından kontrol edilir:
    *   **Syntax Check:** Python/Node kodları için `ast.parse` veya `tsc --noEmit` ile hızlı sözdizimi kontrolü.
    *   **Path Sanitization:** Komutun `.git`, `node_modules` gibi yasaklı dizinlere erişimi engellenir.
    *   **Dependency Check:** Gerekli kütüphanelerin yüklü olup olmadığı `pip check` veya `npm list` ile doğrulanır.

### B. Intent Alignment (Niyet Doğrulaması)
*   **Sorun:** Ajan, "Testleri çalıştır" dendiğinde yanlışlıkla veritabanını sıfırlayan bir komut (örn. `dropdb`) yazabilir.
*   **V2 Çözümü:** Kritik komutlar (silme, ağ erişimi, paket yükleme) çalıştırılmadan önce, komutun ajanın mevcut **Görev Tanımı (Task Description)** ile uyumlu olup olmadığı küçük bir "Judge" LLM veya kural motoru tarafından doğrulanır.

### C. Resource Quotas & Timeouts (Kaynak Limitleri)
*   **Sorun:** Sonsuz döngüye giren veya çok fazla bellek tüketen kodlar tüm sistemi kilitleyebilir.
*   **V2 Çözümü:** 
    *   Her işlem için katı CPU/Memory limitleri (`docker update --cpus`).
    *   Kademeli zaman aşımı (örn. okuma işlemleri 5sn, derleme işlemleri 30sn).

## 3. Yeni Veri Akışı

1.  **PROPOSAL:** Agent bir komut veya script önerir.
2.  **PRE-FLIGHT (Yeni):**
    *   Statik Analiz (Lint/Syntax).
    *   Güvenlik Taraması (Yasaklı anahtar kelimeler/pathler).
3.  **INTENT CHECK (Yeni):** Komut, Task Store'daki hedefle kıyaslanır.
4.  **EXECUTION:** Sandbox (Docker/Firecracker) içinde işlem yürütülür.
5.  **POST-FLIGHT:** Çıktı formatı ve yan etkiler denetlenir.

## 4. Başarı Kriterleri
*   Ajanın yazdığı ve bariz syntax hatası içeren kodların sandbox'a gitmeden "Reflect" aşamasına geri gönderilmesi.
*   Yanlış path kullanımı (Path Traversal) hatalarının %100 engellenmesi.
*   Sonsuz döngülerin sistem kaynaklarını tüketmeden 10 saniye içinde sonlandırılması.
