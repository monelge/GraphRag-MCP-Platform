# 🤖 GraphRagMCP V2 Enforced Protocol (SOTA)

Bu dosya, bu çalışma alanındaki tüm ajanlar için **DEĞİŞTİRİLEMEZ** ve **EN ÜST DÜZEY** çalışma protokollerini tanımlar.

## 🛡️ 1. Otonomluk ve Araç Kullanım Protokolü
- **Primary Tool:** Herhangi bir görev, analiz veya düzeltme isteği için **ZORUNLU** olarak `execute_agent_task` kullanılmalıdır. Atomik araçlarla manuel orkestrasyon yapmak (görev oluşturup adım adım koşturmak) verimsizlik ve güvenlik riski nedeniyle yasaklanmıştır.
- **Pre-flight Indexing:** Bir projede çalışmaya başlamadan önce `index_project` ile SOTA (PageRank + Community) analizinin yapıldığından emin olunmalıdır. `execute_agent_task` bunu otomatik denetler.

## 📉 2. Bütçe ve Yield (Verim) Denetimi
- **Strict Failure Limit:** Bir görev sırasında ardışık **2 hata** (failure) alınırsa, Control Plane işlemi runaway loop koruması gereği anında durdurur.
- **Token Efficiency:** Gereksiz context yüklemelerinden kaçınılmalı, Knowledge Plane üzerinden sadece ilgili chunk'lar (`search_code` ile) çağrılmalıdır.

## 🧠 3. Bellek (Memory) ve Reflection
- **Reflection Loop:** `Verifier` hata dönerse, ajan otomatik olarak `Editor` fazına dönerek hatayı düzeltir. Bu döngü maks 3 kez çalışır. Eğer düzelmiyorsa, mimari bir sorun olduğu varsayılır ve `Reviewer` fazına geçilir.
- **Semantic Facts:** Periyodik olarak `compact_memory` çalıştırılarak ham loglar kalıcı "Semantic Fact"lere ( Mem0 yaklaşımı) dönüştürülmelidir.

## 🏗️ 4. Mimari Standartlar
- **Centrality Awareness:** PageRank skoru %15 ve üzeri olan dosyalar "Kritik Bileşen" olarak işaretlenmiştir. Bu dosyalardaki değişiklikler öncesinde `analyze_change_impact` zorunludur.
- **Clean Code:** Tüm üretimler; Clean Architecture, CQRS ve SOLID prensiplerine uygun olmalıdır.

**UYARI:** Bu protokollere uymayan ajan eylemleri sistem tarafından engellenir veya bütçe aşımıyla sonlandırılır.
