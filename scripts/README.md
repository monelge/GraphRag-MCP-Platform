# 🛠️ GraphRagMCP V2 - Script Kataloğu

Bu rehber, GraphRagMCP Platformunda yer alan tüm otomasyon, test, indeksleme ve doğrulama betiklerinin (script'lerinin) ne işe yaradığını, nasıl kullanılacağını ve hangi mimari katmana (plane) karşılık geldiğini detaylandırır.

---

## 🗺️ Mimari Harita & Script İlişkisi

Platformumuz **5 Ana Düzlem (Plane)** ve **1 Birleşik Orkestratör (Unified Orchestrator)** üzerine kuruludur. Script'ler bu düzlemlerin doğruluğunu, performansını ve veri akışını yönetir:

```mermaid
graph TD
    classDef plane fill:#1d212a,stroke:#3b82f6,stroke-width:2px,color:#fff;
    classDef index fill:#0f172a,stroke:#10b981,stroke-width:1px,color:#a7f3d0;
    classDef verify fill:#0f172a,stroke:#f59e0b,stroke-width:1px,color:#fef3c7;
    classDef launcher fill:#0f172a,stroke:#8b5cf6,stroke-width:1px,color:#ddd6fe;

    KP["Knowledge Plane V2"]:::plane
    MP["Memory Plane V2"]:::plane
    EP["Execution Plane V2"]:::plane
    CP["Control Plane V2"]:::plane
    AP["Agent Plane V2"]:::plane
    UO["Unified Orchestration V2"]:::plane

    subgraph İndeksleme Araçları
        I1["index_v2.py"]:::index
        I2["reindex_v2_auto.py"]:::index
    end

    subgraph Doğrulama Testleri
        T1["knowledge_plane_v2_verification.py"]:::verify
        T2["memory_plane_v2_verification.py"]:::verify
        T3["execution_plane_v2_verification.py"]:::verify
        T4["control_plane_v2_verification.py"]:::verify
        T5["agent_plane_v2_verification.py"]:::verify
        T6["mcp_server_full_orchestration_verification.py"]:::verify
    end

    subgraph Shell Başlatıcılar (Launchers)
        L1["verify_full_system_v2.sh"]:::launcher
        L2["verify_kp_v2.sh"]:::launcher
    end

    I1 & I2 --> KP
    T1 --> KP
    T2 --> MP
    T3 --> EP
    T4 --> CP
    T5 --> AP
    T6 --> UO
    L2 --> T1
    L1 --> T6
```

---

## 📁 1. Doğrulama Testleri (`/scripts/verification/`)

Bu klasör, sistemin farklı katmanlarının ve Master MCP sunucusunun yeteneklerini doğrulamak için yazılmış entegrasyon ve birim testlerini barındırır.

| Script Adı | Katman (Plane) | Kısa Açıklama | Konteyner İçi Çalıştırma Komutu |
| :--- | :--- | :--- | :--- |
| 🛡️ [agent_plane_v2_verification.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/agent_plane_v2_verification.py) | **Agent Plane (V2)** | Ajanın karar verme sürecini, `Verifier` geri besleme mekanizmasını ve **Reflection Loop** özelliğini doğrular. | `python3 /app/scripts/verification/agent_plane_v2_verification.py` |
| 🛡️ [agent_plane_verification.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/agent_plane_verification.py) | **Agent Plane (V1)** | V1 ajanın temel araç çağırma ve komut icra etme yeteneklerini test eder. | `python3 /app/scripts/verification/agent_plane_verification.py` |
| ⚖️ [control_plane_v2_verification.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/control_plane_v2_verification.py) | **Control Plane (V2)** | Sistem yönetişimini (Governance), bütçe aşım limitlerini (Strict Failure Limit) ve token yönetimini test eder. | `python3 /app/scripts/verification/control_plane_v2_verification.py` |
| ⚖️ [control_plane_verification.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/control_plane_verification.py) | **Control Plane (V1)** | Temel görev takibi ve işlem izleme (Tracing) akışlarını doğrular. | `python3 /app/scripts/verification/control_plane_verification.py` |
| 🚀 [execution_plane_v2_verification.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/execution_plane_v2_verification.py) | **Execution Plane (V2)** | Komut çalıştırma öncesi güvenlik analizlerini (Pre-flight Checks) ve güvenli ortam sınırlarını doğrular. | `python3 /app/scripts/verification/execution_plane_v2_verification.py` |
| 🚀 [execution_plane_verification.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/execution_plane_verification.py) | **Execution Plane (V1)** | Terminal komutlarının temel çalıştırılma süreçlerini ve çıktı yakalama mekanizmasını test eder. | `python3 /app/scripts/verification/execution_plane_verification.py` |
| 🌐 [knowledge_plane_v2_verification.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/knowledge_plane_v2_verification.py) | **Knowledge Plane (V2)** | Qdrant ve Neo4j üzerindeki gelişmiş veri çıkarma, anlamsal arama ve RAG zenginleştirme süreçlerini test eder. | `python3 /app/scripts/verification/knowledge_plane_v2_verification.py` |
| 🌐 [knowledge_plane_verification.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/knowledge_plane_verification.py) | **Knowledge Plane (V1)** | Temel Neo4j ve Qdrant entegrasyonlarını ve ilk düzey veri yükleme operasyonlarını test eder. | `python3 /app/scripts/verification/knowledge_plane_verification.py` |
| 🧠 [memory_plane_v2_verification.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/memory_plane_v2_verification.py) | **Memory Plane (V2)** | **Semantic Facts** (kalıcı anlamsal doğrular) biriktirme, periyodik hafıza sıkıştırma (`compact_memory`) ve varlık çıkarma mekanizmalarını doğrular. | `python3 /app/scripts/verification/memory_plane_v2_verification.py` |
| 🧠 [memory_plane_verification.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/memory_plane_verification.py) | **Memory Plane (V1)** | Temel kısa ve uzun vadeli bellek okuma/yazma süreçlerini test eder. | `python3 /app/scripts/verification/memory_plane_verification.py` |
| 🎯 [mcp_server_full_orchestration_verification.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/mcp_server_full_orchestration_verification.py) | **Unified Orchestrator (V2)** | 5 Düzlemin bir araya gelerek tek bir istek üzerinden tam otonom akışla sonuç üretmesini test eder. (End-to-End Test) | `python3 /app/scripts/verification/mcp_server_full_orchestration_verification.py` |
| 🎯 [mcp_server_full_verification.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/mcp_server_full_verification.py) | **Unified Orchestrator (V1)** | V1 Master orkestratörün tüm bileşenlerinin entegrasyonunu doğrular. | `python3 /app/scripts/verification/mcp_server_full_verification.py` |
| 🔌 [knowledge_plane_demo.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/knowledge_plane_demo.py) | **Knowledge Plane (Demo)** | Knowledge Plane API'lerini kullanarak arama ve sorgulama yeteneklerini interaktif olarak gösteren demo betiği. | `python3 /app/scripts/verification/knowledge_plane_demo.py` |
| 🧪 [test_all_tools.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/test_all_tools.py) | **Integration Testing** | MCP sunucusu tarafından dış dünyaya sunulan tüm araçları (tools) hızlıca test eder. | `python3 /app/scripts/verification/test_all_tools.py` |
| 🧪 [test_all_tools_deep.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/test_all_tools_deep.py) | **Integration Testing** | Tüm araçları en derin parametreleri, istisnai durumları ve sınır koşulları ile test eden derin doğrulama script'i. | `python3 /app/scripts/verification/test_all_tools_deep.py` |
| 🧪 [test_audit.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/test_audit.py) | **Integration Testing** | Platform içi denetim ve governance mekanizmalarının yetkilendirme katmanını doğrular. | `python3 /app/scripts/verification/test_audit.py` |
| 🧪 [test_steps.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/verification/test_steps.py) | **Integration Testing** | Control Plane üzerindeki işlem adımlarının (Steps) durum geçişlerini ve takibini test eder. | `python3 /app/scripts/verification/test_steps.py` |

---

## 🗂️ 2. İndeksleme Araçları (`/scripts/indexing/`)

Platformun kod tabanını Neo4j grafik veritabanı ve Qdrant vektör veritabanına aktararak RAG yeteneklerini besleyen zekayı oluşturan script'lerdir.

| Script Adı | Sürüm | Kısa Açıklama | Konteyner İçi Çalıştırma Komutu |
| :--- | :--- | :--- | :--- |
| ⚡ [index_v2.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/indexing/index_v2.py) | **V2 (SOTA)** | PageRank ve topluluk algılama (Community Detection) analizi ile kod tabanını zenginleştirerek indeksleyen ana script. | `python3 /app/scripts/indexing/index_v2.py` |
| ⚡ [index.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/indexing/index.py) | **V1** | Kod tabanının dosyalarını, fonksiyonlarını ve sınıflarını hiyerarşik olarak çıkaran standart indeksleyici. | `python3 /app/scripts/indexing/index.py` |
| 🔄 [reindex_v2_auto.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/indexing/reindex_v2_auto.py) | **V2 (SOTA)** | Değişen dosyaları otomatik olarak tespit eden ve grafik ile vektör veritabanını incremental olarak güncelleyen akıllı re-indeksleyici. | `python3 /app/scripts/indexing/reindex_v2_auto.py` |
| 🔄 [reindex.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/indexing/reindex.py) | **V1** | Kod tabanında yapılan değişiklikleri algılayıp veritabanını manuel tetikleme ile güncelleyen re-indeksleyici. | `python3 /app/scripts/indexing/reindex.py` |
| 🐛 [debug_indexing.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/indexing/debug_indexing.py) | **Debug** | İndeksleme sırasında oluşan Neo4j ve Qdrant bağlantı hatalarını ve veri format uyuşmazlıklarını analiz eden yardımcı araç. | `python3 /app/scripts/indexing/debug_indexing.py` |
| 🏢 [index_vendoris.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/indexing/index_vendoris.py) | **Domain Specific** | Vendoris alanına (domain) özgü verilerin indekslenmesini sağlayan özel konfigürasyon çalıştırıcısı. | `python3 /app/scripts/indexing/index_vendoris.py` |
| 🏢 [index_ware.py](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/indexing/index_ware.py) | **Domain Specific** | Ware alanına (domain) özgü lojistik verilerinin grafik şemaya dönüştürülüp indekslenmesini sağlayan betik. | `python3 /app/scripts/indexing/index_ware.py` |

---

## 🚀 3. Shell Başlatıcılar (`/scripts/launchers/`)

Host makineden Docker konteyneri içerisindeki testleri ve doğrulamaları hızlıca tetiklemek için kullanılan, kök dizinden `/scripts/launchers/` altına taşınmış kullanıcı dostu arayüz betikleridir.

> [!NOTE]
> Bu başlatıcılar doğrudan **Host makinede** (`Cwd: /Volumes/MacBook/RiderProjects/GraphRagMCP`) çalıştırılmak üzere tasarlanmıştır.

| Başlatıcı Script | Tetiklenen Test Katmanı | Host Üzerinde Çalıştırma Komutu |
| :--- | :--- | :--- |
| 🎯 **[verify_full_system_v2.sh](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/launchers/verify_full_system_v2.sh)** | **Unified Orchestrator V2 (SOTA)** | `bash scripts/launchers/verify_full_system_v2.sh` |
| 🎯 **[verify_full_system.sh](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/launchers/verify_full_system.sh)** | Unified Orchestrator V1 | `bash scripts/launchers/verify_full_system.sh` |
| 🛡️ **[verify_agent_v2.sh](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/launchers/verify_agent_v2.sh)** | Agent Plane V2 (Reflection Loop) | `bash scripts/launchers/verify_agent_v2.sh` |
| 🛡️ **[verify_agent.sh](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/launchers/verify_agent.sh)** | Agent Plane V1 | `bash scripts/launchers/verify_agent.sh` |
| ⚖️ **[verify_control_v2.sh](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/launchers/verify_control_v2.sh)** | Control Plane V2 (Governance) | `bash scripts/launchers/verify_control_v2.sh` |
| ⚖️ **[verify_control.sh](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/launchers/verify_control.sh)** | Control Plane V1 | `bash scripts/launchers/verify_control.sh` |
| 🚀 **[verify_execution_v2.sh](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/launchers/verify_execution_v2.sh)** | Execution Plane V2 (Safety) | `bash scripts/launchers/verify_execution_v2.sh` |
| 🚀 **[verify_execution.sh](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/launchers/verify_execution.sh)** | Execution Plane V1 | `bash scripts/launchers/verify_execution.sh` |
| 🌐 **[verify_kp_v2.sh](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/launchers/verify_kp_v2.sh)** | Knowledge Plane V2 (Search) | `bash scripts/launchers/verify_kp_v2.sh` |
| 🌐 **[verify_kp.sh](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/launchers/verify_kp.sh)** | Knowledge Plane V1 (Neo4j/Qdrant) | `bash scripts/launchers/verify_kp.sh` |
| 🧠 **[verify_memory_v2.sh](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/launchers/verify_memory_v2.sh)** | Memory Plane V2 (Semantic Facts) | `bash scripts/launchers/verify_memory_v2.sh` |
| 🧠 **[verify_memory.sh](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/launchers/verify_memory.sh)** | Memory Plane V1 | `bash scripts/launchers/verify_memory.sh` |
| 🧪 **[verify_all_tools_v2.sh](file:///Volumes/MacBook/RiderProjects/GraphRagMCP/scripts/launchers/verify_all_tools_v2.sh)** | MCP Tools Integration Deep Test | `bash scripts/launchers/verify_all_tools_v2.sh` |

---

## ⚡ Pratik Kullanım İpuçları & Hızlı Başlangıç

> [!TIP]
> **Tüm Sistemi V2 Standartlarında Doğrulamak İçin:**
> Host makinenizde projenin kök dizinindeyken şu komutu çalıştırmanız yeterlidir:
> ```bash
> bash scripts/launchers/verify_full_system_v2.sh
> ```

> [!IMPORTANT]
> **Güvenlik & Yetkilendirme Uyarısı:**
> Başlatıcıları ilk kez taşındıktan sonra çalıştırırken executable iznine ihtiyaç duyabilirsiniz. İzin vermek için:
> ```bash
> chmod +x scripts/launchers/*.sh
> ```

> [!WARNING]
> **Konteynerin Çalışır Durumda Olduğundan Emin Olun:**
> Doğrulama script'leri Docker içerisindeki `graph-mcp` konteyneri ile iletişim kurarak çalışır. Çalıştırma öncesinde `docker ps` komutu ile `graph-mcp` isimli servisinizin ayakta olduğunu kontrol edin.
