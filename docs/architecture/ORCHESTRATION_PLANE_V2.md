# Orchestration Plane V2 Mimari Tasarımı

## 1. Amaç
Orchestration Plane, Knowledge, Memory, Agent, Execution ve Control katmanlarını tek bir kusursuz iş akışında birleştiren "Beyin" katmanıdır. Hibrit bir **State Machine + Blackboard** mimarisi kullanarak, ajanın karmaşık yazılım görevlerini otonom ve güvenli bir şekilde tamamlamasını sağlar.

## 2. Mimari Yapı (Hybrid Approach)

### A. Blackboard (Shared Context)
Tüm katmanların ortaklaşa yazdığı ve okuduğu merkezi bir bellek alanıdır.
*   **Knowledge Data:** Proje haritası, AST ilişkileri.
*   **Memory Data:** Geçmiş deneyimler, çıkarılmış kurallar (Atomic Facts).
*   **Execution Data:** Sandbox çıktıları, test sonuçları.
*   **Control Data:** Güncel bütçe durumu, verimlilik skoru.

### B. State Machine (Flow Orchestrator)
Görevin hangi aşamada olduğunu yöneten deterministik akış.
1.  **[RESEARCH PHASE]:** Knowledge Plane (Repo Map) + Memory Plane (Past Lessons) ile Blackboard doldurulur.
2.  **[STRATEGY PHASE]:** Agent Plane (Planner) Blackboard'daki veriye göre bir plan çıkarır.
3.  **[EXECUTION PHASE]:** Agent Plane (Editor) kod üretir -> Execution Plane (Pre-flight) denetler -> Sandbox çalıştırır.
4.  **[VALIDATION PHASE]:** Agent Plane (Reviewer/Verifier) sonucu denetler. 
    *   *FAIL* -> Control Plane (Yield Analysis) bütçeyi kontrol eder -> **Reflection Loop** ile başa döner.
    *   *PASS* -> Görev tamamlanır.

## 3. Temel Özellikler

*   **Zero-Shot to Agentic:** Artık MCP üzerinden sadece "dosya oku" denmiyor. `execute_agent_task` aracıyla tüm bu orkestrasyon tetikleniyor.
*   **Self-Healing Context:** Eğer `Research` aşamasında eksik bilgi varsa, ajan otomatik olarak `Knowledge Plane`'den daha derin (3-hop) graph genişletmesi talep eder.
*   **Cost-Aware Thinking:** Her aşama geçişinde `Control Plane` verim analizi yaparak "bu görev daha fazla bütçeyi hak ediyor mu?" sorusunu yanıtlar.

## 4. MCP Entegrasyonu (Unified Tool)
Aşağıdaki ana araç tüm bu orkestrasyonu tetikleyen tek giriş noktasıdır:
*   `execute_agent_task(goal: str, project_path: str)`
    *   İçeride: Research -> Strategy -> Execution -> Validation döngüsünü koşturur.
    *   Dışarıda: Sadece final raporu ve yapılan değişiklikleri sunar.
