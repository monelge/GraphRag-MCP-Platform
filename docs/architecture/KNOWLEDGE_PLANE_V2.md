# Knowledge Plane V2 Mimari Tasarımı

## 1. Amaç
Knowledge Plane V2, sistemin sadece kod parçalarını (snippets) değil, projenin **mimari omurgasını, mantıksal topluluklarını ve kritiklik derecelerini** anlamasını hedefler. Sektördeki GraphRAG (Microsoft) ve Repo Map (Aider) yaklaşımlarının en iyi yönlerini birleştirir.

## 2. Ana Bileşenler

### A. Mimari Önem Derecesi (PageRank & Centrality)
*   **Mantık:** Neo4j üzerindeki tüm fonksiyon ve sınıflar için bağlantı yoğunluğuna göre bir "Önem Skoru" (PageRank) hesaplanır.
*   **Kullanım:** Retrieval sırasında, benzer semantik skora sahip iki kod parçasından mimari açıdan daha merkezi olan (örn: bir Utility fonksiyonu yerine ana Business Logic) önceliklendirilir.

### B. Mantıksal Topluluklar (Community Detection)
*   **Mantık:** Klasör yapısından bağımsız olarak, kodun birbirini çağırma sıklığına göre mantıksal gruplar (Louvain/Clustering) belirlenir.
*   **Kullanım:** Ajan "Auth akışı nasıl?" diye sorduğunda, sadece klasörleri değil, birbirine bağlı "Auth Topluluğu"ndaki tüm dosyaları görebilir.

### C. Repo Map (Sıkıştırılmış Proje Haritası)
*   **Mantık:** Tüm projenin dosya yapısı, sınıfları ve fonksiyon imzalarından oluşan (gövde hariç) 1000-2000 token'lık bir iskelet haritası.
*   **Kullanım:** Ajan göreve başladığında ilk olarak bu haritayı okuyarak "nerede ne var" bilgisine saniyeler içinde sahip olur.

### D. Semantik İlişki Çıkarımı (Relationship Inference)
*   **Mantık:** `CALLS` veya `DEPENDS_ON` gibi ham ilişkilerin ötesine geçerek, bu ilişkinin amacı (örn: `VALIDATES`, `PERSISTS`, `ORCHESTRATES`) belirlenir.
*   **Kullanım:** Ajanın kodun niyetini (intent) anlaması kolaylaşır.

## 3. Veri Akışı

1.  **Extraction:** AST Chunker ile kod parçalanır ve temel graph ilişkileri (Neo4j) kurulur.
2.  **Enrichment:**
    *   Neo4j üzerinde PageRank ve Clustering algoritmaları koşturulur.
    *   Repo Map (Skelet) metni üretilir ve Qdrant'ta "global context" olarak saklanır.
3.  **Retrieval:** 
    *   Arama sonuçları (Vector Score) + (PageRank Score) + (Recency) formülü ile normalize edilir.
    *   Arama sonucuna ilgili "Community Report" (Topluluk Özeti) eklenir.

## 4. Başarı Kriterleri
*   Arama sonuçlarında projenin ana omurgasını oluşturan dosyaların daha üstte çıkması.
*   Ajanın hiç bilmediği bir projede entrypoint'leri %30 daha hızlı tespit edebilmesi.
*   Geniş kapsamlı mimari sorularda (Global Search) daha tutarlı cevaplar üretilmesi.
