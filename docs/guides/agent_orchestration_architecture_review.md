# 📋 GraphRAG-Augmented Coding Agent — Mimari İnceleme ve İyileştirme Önerileri

**Tarih:** 2026-06-07

---

## Genel Değerlendirme

Plan genel olarak oldukça güçlü bir vizyon sunuyor.

Öne çıkan güçlü yönler:

- GraphRAG merkezli bağlam yönetimi
- Test-driven agent yaklaşımı
- Model routing (Tier sistemi)
- Reflection loop mimarisi
- Memory katmanlarının düşünülmüş olması
- Production odaklı yapı
- Modüler tasarım

Genel mimari seviyesi yüksek olsa da, uzun vadeli sürdürülebilirlik açısından bazı noktalar sadeleştirilmeli ve bazı eksik parçalar eklenmelidir.

---

## 1. Fazla Katmanlaşma Riski

### Mevcut Yapı

- Knowledge Plane
- Memory Plane
- Agent Plane
- Execution Plane
- Control Plane
- Unified Orchestrator
- Agent API

Bu kadar fazla düzlem zamanla:

- sorumluluk karmaşasına,
- bakım maliyetine,
- katmanlar arası bağımlılıkların artmasına

neden olabilir.

### Risk

Bir görev başarısız olduğunda:

- Agent mı karar verecek?
- Escalation Manager mı?
- CodeAct Runner mı?
- Control Plane mi?

Bu belirsizlik sistem büyüdükçe teknik borca dönüşebilir.

### Öneri

Gerçek runtime mimarisi şu seviyeye indirilebilir:

```text
Knowledge Layer
Execution Layer
Control Layer
```

#### Birleştirilebilecek Yapılar

| Mevcut | Öneri |
|--------|-------|
| Memory Plane | Knowledge Layer içine alınabilir |
| Agent Plane | Ayrı plane olmaktan çıkarılabilir |
| Orchestrator | Control Layer altında çalışabilir |

---

## 2. Complexity Router Fazla Karmaşık

Şu anda:

- 30+ sinyal
- onlarca ağırlık
- manuel puanlama sistemi

bulunuyor.

Bu yapı zamanla:

- açıklanamaz hale gelir,
- bakım zorlaşır,
- ağırlıkların neden seçildiği unutulur.

### Öneri

İlk sürüm için yalnızca dört sinyal:

```python
score = (
    0.4 * file_count +
    0.3 * stacktrace_exists +
    0.2 * architecture_keywords +
    0.1 * token_count
)
```

Sonrasında telemetry verileri ile sistem geliştirilmeli.

---

## 3. Reflection Döngüsü Genişletilmeli

Mevcut yapı:

```text
max_reflections = 3
```

### Önerilen Aşamalı Akış

| Aşama | Eylem | Deneme |
|-------|-------|--------|
| 1 | Aynı model ile tekrar | 2 deneme |
| 2 | Tier yükselt | 2 deneme |
| 3 | Context genişlet | 1 deneme |
| 4 | Human review | — |

### Sebep

Başarısızlıkların büyük bölümü:

- eksik context,
- yanlış test,
- eski memory

kaynaklıdır. Doğrudan tier yükseltmek yerine önce context kalitesini artırmak daha ekonomik ve isabetlidir.

---

## 4. Eksik: Patch Memory

Şu anda mevcut:

- Episodic Memory
- Semantic Memory
- Decision Memory

Ancak aşağıdaki yapı eksik:

```json
{
  "problem": "N+1 query",
  "files": ["UserRepository.cs"],
  "patch_hash": "...",
  "tests": ["UserTests"],
  "successful": true
}
```

### Önerilen Yeni Katman: Patch Memory

Benzer problemler tekrar oluştuğunda geçmiş çözümleri örnek olarak kullanmak.

```text
Yeni görev: "N+1 problemi var"
       ↓
recall_patch("N+1")
       ↓
Önceki başarılı patch prompt içine eklenir
```

---

## 5. Retrieval Evaluation Dataset Eksik

`run_retrieval_eval` tool'u mevcut, ancak bir benchmark veri seti tanımlanmamış.

### Öneri

```text
evals/
└── retrieval/
    ├── case001.json
    ├── case002.json
    └── case003.json
```

Örnek vaka formatı:

```json
{
  "query": "N+1 problemi nerede?",
  "expected_files": [
    "UserRepository.cs",
    "OrderRepository.cs"
  ]
}
```

> GraphRAG sistemleri benchmark olmadan optimize edilemez.

---

## 6. Semantic Diff Katmanı Eksik

Şu anda yalnızca `Unified Diff` üretiliyor. Bunun yanında aşağıdaki meta veri de üretilmeli:

```json
{
  "change_type": "refactor",
  "affected_classes": [],
  "risk": "medium"
}
```

### Avantajları

- Explainability (açıklanabilirlik)
- Audit trail
- Memory kalitesi
- Gelecekteki öğrenme mekanizmaları için veri

---

## 7. OpenAI Bridge Ayrı Servis Olmayabilir

Şu anda üç ayrı backend:

- `graph-mcp` (port 8000)
- `openai-bridge` (port 5555)
- `agent-api` (port 8001)

### Öneri: Tek FastAPI Uygulaması

```text
/mcp    → MCP protokol endpoint'i
/v1     → OpenAI uyumlu bridge
/agent  → Agent REST API
```

Böylece auth, logging, telemetry ve configuration tek yerde yönetilir.

---

## 8. Session Context Eksik

Şu anda Episodic ve Semantic Memory mevcut, ancak görev süresince yaşayan kısa ömürlü session context eksik.

### Önerilen Yapı

```python
class TaskSessionContext:
    session_id: str
    opened_files: list[str]
    current_branch: str
    selected_model: str
    reflection_count: int
    last_failures: list[str]
```

Bu veri Redis üzerinde tutulabilir (TTL ile otomatik temizlenir).

---

## 9. PageRank'e Fazla Güvenilmemeli

Etki analizi şu anda ağırlıklı olarak PageRank üzerine kurulmuş. Ancak kod grafı tek boyutlu değildir.

### Önerilen Hibrit Impact Skoru

```text
Impact Score =
  0.4 × call graph
  0.3 × dependency graph
  0.2 × PageRank
  0.1 × git co-change
```

Farklı graph türleri farklı risk sinyalleri taşır; bunları birleştirmek daha isabetli etki analizi sağlar.

---

## 10. Repository Snapshot Sistemi Eksik

Görev başlamadan önce:

```text
snapshot_20260607_1715
```

oluşturulmalı.

Bu sayede:

- rollback
- replay
- karşılaştırma (compare)
- güvenli geri dönüş

mümkün olur.

---

## V3 İçin Öneri: Learning Plane

Mevcut düzlemlere ek olarak `Learning Plane` eklenebilir.

### Sorumlulukları

| Veri Kaynağı | Amaç |
|-------------|------|
| Başarılı patch'ler | Öğrenme kaynağı |
| Başarısız patch'ler | Negatif örnekler |
| Routing sonuçları | Model seçimi optimizasyonu |
| Retrieval sonuçları | Context kalitesinin geliştirilmesi |

Bu katman zaman içinde sistemi gerçek anlamda "öğrenen" hale getirebilir.

---

## Genel Puanlama

| Alan | Puan |
|------|------|
| Mimari Vizyon | 9.5 / 10 |
| Modülerlik | 9 / 10 |
| GraphRAG Yaklaşımı | 9.5 / 10 |
| Production Düşüncesi | 9 / 10 |
| Operasyonel Sadelik | 6 / 10 |
| Bakım Maliyeti | 6.5 / 10 |
| Öğrenebilirlik | 7 / 10 |

**Toplam Puan: 8.7 / 10**

---

## Genel Sonuç

Plan güçlü, ileri görüşlü ve teknik açıdan oldukça olgun.

Ancak uzun vadede asıl tehdit:

> Eksik özellikler değil, kontrol edilemeyen mimari karmaşıklık olacaktır.

Bu nedenle:

- yeni katman eklemek yerine mevcut katmanları sadeleştirmek,
- öğrenme mekanizmalarını güçlendirmek,
- telemetry temelli evrimsel geliştirme yapmak

daha sürdürülebilir bir yol olacaktır.

---

## 🔗 İlgili Belgeler

- [Orkestrasyon Planı](agent_orchestration_plan.md)
- [Production İyileştirme Raporu](agent_orchestration_production_review.md)
- [Agent Plane V2](../architecture/AGENT_PLANE_V2.md)
- [Control Plane V2](../architecture/CONTROL_PLANE_V2.md)
- [Knowledge Plane V2](../architecture/KNOWLEDGE_PLANE_V2.md)
