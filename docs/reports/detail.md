  Knowledge Plane Detayları

  1. Temel Dosyalar ve Fonksiyonlar
   * Pipeline Katmanı:
       * src/indexing/pipelines/project_intelligence.py: Projenin "kimliğini" (diller, frameworkler, modüller) belirler ve yüksek seviyeli mimari özetleri (repo_summary, module_summary) üretir.
           * sync_project_intelligence(): Tüm zekayı senkronize eden ana fonksiyon.
           * generate_global_architecture_summary(): Neo4j'den modüller arası CALLS/DEPENDS_ON ilişkilerini çekerek mimari metin üretir.
   * İndeksleme Katmanı:
       * src/handlers/indexing_handler.py: Kodun parçalanması ve depolanması sürecini yönetir.
           * index_project() / incremental_index_project(): AST tabanlı parçalama ve vektörel kayıt sürecini başlatır.
       * src/indexing/chunkers/ast_chunker.py: Kodu fonksiyon, sınıf ve metod bazlı (AST-aware) parçalara böler.
       * src/indexing/extractors/graph_extractor.py: Kod blokları arasındaki semantik ilişkileri çıkarır.
   * Ontoloji Katmanı:
       * src/ontology/schema.py: NodeType (Module, Class, Function, Endpoint vb.) ve EdgeType (CALLS, IMPLEMENTS, USES_CONFIG vb.) tanımlarını tutar.
   * Arama Katmanı:
       * src/handlers/retrieval_handler.py: Bilgiye erişim sağlar.
           * search_repo_architecture(): Mimari özetler arasında arama yapar.
           * search_code(): Hibrit arama ve graph genişletme (expansion) kullanarak kod seviyesinde bilgi getirir.

  2. Nasıl Tetiklenir (Start Points)?
   * İlk Kurulum: register_project veya index_project tool çağrısı ile tüm proje taranır.
   * Değişiklik Anında: incremental_index_project (genellikle git hook'ları üzerinden) sadece değişen dosyaları Knowledge Plane'e dahil eder.
   * Mimarinin Anlaşılması: summarize_repository çağrıldığında Project Intelligence Pipeline çalışarak projenin güncel özetini çıkarır.
   * Sorgulama: search_repo_architecture ile kullanıcı mimari düzeyde (örneğin "auth akışı nasıl?") sorular sorar.

  3. Süreç Akışı (Step-by-Step)
   1. Keşif (Discovery): Proje dizini taranır; kullanılan diller (Python, C#, TS vb.) ve frameworkler tespit edilir.
   2. Parçalama (Chunking): ASTChunker dosyaları anlamlı bloklara böler.
   3. İlişki Çıkarma (Extraction): GraphExtractor fonksiyonların birbirini çağırma (CALLS) ve dosyaların birbirine bağımlılık (DEPENDS_ON) ilişkilerini Neo4j'ye yazar.
   4. Güvenlik Denetimi: Secret Scanner bloklar içindeki API key veya şifreleri temizler (redaction).
   5. Vektörleştirme (Embedding): Temizlenmiş bloklar Dense ve Sparse embedder'lar ile vektör uzayına taşınır.
   6. Özetleme (Summarization): Modül ve repo seviyesinde özetler üretilerek Qdrant'ta source_type="repo_summary" etiketiyle saklanır.
   7. Sorgulama (Retrieval): Kullanıcı bir soru sorduğunda, sistem önce mimari özetlere (search_repo_architecture) bakar, ardından gerekirse kod derinliğine (search_code) iner.

   Memory Plane Detayları

  1. Temel Dosyalar ve Fonksiyonlar
   * Modeller:
       * src/memory/models/memory_models.py: MemoryEntry sınıfı tüm hafıza kayıtlarının (title, content, type, valid_to, tags) şemasını belirler. Toplamda 4 katman (layer) vardır: episodic, semantic, decision, procedural.
   * Handler Katmanı:
       * src/handlers/memory_handler.py: Gelen MCP Tool isteklerini karşılayan ana denetleyicidir.
   * Service Katmanı (İş Mantığı):
       * src/memory/services/memory_writer.py: Yeni bellek kaydı oluşturma işlemlerini yönetir.
       * src/memory/services/memory_recall.py: Sorguya göre hafıza kayıtlarını okuma ve filtreleme işlemlerini yapar.
       * src/memory/services/memory_compaction.py: Benzer anıları LLM kullanarak birleştirir (compact) ve süresi dolmuş (valid_to) geçici kayıtları siler (prune).
   * Store Katmanı (Veri Erişimi):
       * src/memory/stores/episodic_store.py: Temel (Base) store'dur. Tüm kayıtlar aslında burası üzerinden Qdrant'a yazılır (source_type="episodic_memory").
       * src/memory/stores/decision_store.py: Mimari kararlar için EpisodicStore etrafında bir sarmalayıcıdır (wrapper).
       * src/memory/stores/semantic_memory_store.py: Doğrudan semantic katmanlı hafızalar için bir genişletmedir.
       * src/memory/stores/temporal_store.py: Zaman duyarlı (valid_from, valid_to) kayıtları yönetmek için bir wrapper'dır.

  2. Nasıl Tetiklenir (Start Points)?
   * Bilgi Saklama: Ajan, önemli bir işlem yaptığında veya bir mimari kararı kaydetmek istediğinde store_memory veya store_decision_memory çağırır.
   * Bilgi Okuma: Ajan bir konuyu araştırırken, daha önce bu konuda bir olay yaşanıp yaşanmadığını veya mimari kural olup olmadığını görmek için recall_memory veya search_decisions kullanır.
   * Hafıza Bakımı: Zamanla biriken aynı tipteki hafızaları birleştirmek (kompaktlaştırmak) ve süresi dolanları temizlemek için compact_memory tetiklenir.

  3. Süreç Akışı (Step-by-Step)
   1. Yazma (Write):
       * store_memory tetiklenir.
       * MemoryHandler, bellek tipine göre isteği MemoryWriter veya SemanticMemoryStore'a iletir.
       * Veri MemoryEntry modeline dönüşür, Dense ve Sparse embedder'lar tarafından vektörleştirilir.
       * Son olarak EpisodicStore aracılığıyla Qdrant veritabanına payload (memory_layer, valid_to, status=active) ile birlikte kaydedilir.
   2. Okuma (Read):
       * recall_memory tetiklenir.
       * MemoryRecall servisi aranacak katmanı (episodic, decision vb.) filtreler.
       * Qdrant üzerinde hibrit (Hybrid Search) arama yapılır. Süresi dolmamış (status=active) kayıtlar getirilir.
       * Arama istatistikleri ve başarı durumu PostgreSQL'e (retrieval_logs) loglanır.
   3. Bakım (Compaction):
       * compact_memory çağrılır.
       * MemoryCompactor, benzer kayıtları Qdrant'tan çeker.
       * Bu kayıtları birleştirmesi için LLM'e gönderir. LLM tek bir özet metin döner.
       * Eski kayıtlar arşivlenirken, LLM'in ürettiği tekil ve güçlü (semantic) yeni kayıt oluşturulur. Aynı zamanda prune_expired çalışarak miadı dolmuş çöpleri fiziksel olarak siler.
 Agent Plane Detayları

  1. Temel Dosyalar ve Fonksiyonlar
   * Orkestrasyon:
       * src/agent/orchestrator/state_machine.py: Görevin hangi aşamada olduğunu, bir sonraki aşamaya ne zaman geçeceğini ve hata durumlarını yönetir. TaskOrchestrator.run_step() ana motordur.
       * src/agent/orchestrator/checkpoints.py: Görevin her adımında state'i (bağlamı) PostgreSQL'e kaydeder. Bu sayede sistem kapansa bile resume_task ile kalındığı yerden devam edilebilir.
       * src/agent/orchestrator/approvals.py: Kritik adımlardan (kod yazma, komut çalıştırma vb.) önce kullanıcının onayını bekleyen bir bariyer görevi görür.
   * Düğüm (Node) Pipeline'ı:
       * planner.py: Görevi küçük adımlara böler.
       * retriever.py: Knowledge Plane'i kullanarak gerekli kod parçalarını ve dökümanları bulur.
       * explainer.py: Bulunan kodun ne yaptığını analiz eder.
       * editor.py: Kod değişikliklerini hazırlar (Execution Plane'e gönderir).
       * verifier.py: Yapılan değişiklikleri build/test süreçleriyle doğrular.
       * summarizer.py: Sonucu özetler ve elde edilen tecrübeyi Memory Plane'e yazar (_learn_from_step).
   * Görev Modelleri:
       * src/agent/tasks/task_models.py: Task ve TaskStep veri yapılarını tanımlar. Durumlar (planned, executing, waiting_approval, done vb.) burada tutulur.

  2. Nasıl Tetiklenir (Start Points)?
   * Görev Başlatma: create_agent_task tool'u ile bir başlık ve açıklama verilerek tetiklenir.
   * Onay Mekanizması: Eğer ajan WAITING_APPROVAL durumuna gelirse, kullanıcı approve_task_step tool'unu kullanarak devam ettirir.
   * Kaldığı Yerden Devam: Herhangi bir kesinti veya manuel durdurma sonrası resume_task ile son başarılı checkpoint'ten işlem devam eder.

  3. Süreç Akışı (Durum Geçişleri)
   1. Planlama (PLANNED): PlannerNode çalışır, yapılacaklar listesini oluşturur.
   2. Bilgi Toplama (RETRIEVING): RetrieverNode repo içinde ilgili dosyaları bulur.
   3. Analiz (ANALYZING): ExplainerNode bağlamı ajan için anlamlandırır.
   4. Onay Bekleme (WAITING_APPROVAL): Kritik bir adım öncesi ajan durur ve kullanıcıya planı sunar.
   5. Uygulama (EXECUTING): EditorNode (ve Execution Plane) kod değişikliklerini uygular.
   6. Doğrulama (VERIFYING): VerifierNode ve ReviewerNode kodun doğruluğunu ve test başarısını kontrol eder.
   7. Özetleme & Öğrenme (DONE): SummarizerNode sonucu kullanıcıya sunar ve elde edilen yeni bilgiyi Memory Plane'e (episodic/semantic) ekler.
  
  Execution Plane Detayları

  1. Temel Dosyalar ve Fonksiyonlar
   * Yönetim (Management):
       * src/execution/sandbox/runtime_manager.py: Projenin dilini ve framework'ünü tespit ederek (detect_profile) uygun build/test komutlarını seçer.
       * PROFILES: python, node, dotnet ve flutter için varsayılan komutları (örn: pytest, npm test) tanımlar.
   * Politika ve Güvenlik (Guardrails):
       * src/execution/sandbox/mount_policy.py: Ajanın sadece izin verilen dizinlerde (/projects, /tmp vb.) okuma/yazma yapmasını sağlar.
       * src/execution/sandbox/tool_policy.py: Sadece izin verilen komutların (python3, node, bash vb.) çalıştırılmasına izin verir. Inline bash komutlarını (-c flag'i gibi) güvenlik nedeniyle engeller.
   * Yürütücüler (Runners):
       * src/execution/runners/command_runner.py: Düşük seviyeli komut çalıştırma motorudur. Timeout (zaman aşımı), exit code takibi ve output yakalama işlerini yapar.
       * build_runner.py & test_runner.py: CommandRunner üzerine inşa edilmiş, dile özel build ve test süreçlerini yöneten yüksek seviyeli sarmalayıcılardır.

  2. Nasıl Tetiklenir (Start Points)?
   * Doğrulama Planı: Kullanıcı run_verification_plan tool'unu çağırdığında tüm build/test zinciri tetiklenir.
   * Ajan İşlemleri: Ajanın EditorNode veya VerifierNode bileşenleri, kod yazdıktan sonra doğruluğu kontrol etmek için otomatik olarak bu katmanı kullanır.

  3. Süreç Akışı (Step-by-Step)
   1. Profil Tespiti: Proje kök dizinine bakılarak (örn: package.json varsa Node.js) uygun ExecutionProfile seçilir.
   2. Mount Kontrolü: Çalıştırılacak komutun yolu MountPolicy üzerinden kontrol edilir. Yazma izni olmayan bir yere dokunulamaz.
   3. Allowlist Kontrolü: Komutun kendisi (executable) ToolPolicy üzerinden denetlenir. İzin verilmeyen bir binary çalıştırılamaz.
   4. İzolasyonlu Çalıştırma: CommandRunner komutu asenkron olarak başlatır.
   5. Zaman ve Hata Takibi: Komut belirlenen sürede bitmezse öldürülür. Çıktılar (stdout/stderr) yakalanır.
   6. Sonuç Raporlama: ExecutionResult nesnesi oluşturulur; başarı durumu (exit_code == 0) ajana veya kullanıcıya dönülür.

   Control Plane Detayları

  1. Temel Dosyalar ve Fonksiyonlar
   * Model ve Bütçe Yönetimi:
       * src/control/models/gateway.py: Tüm LLM çağrılarını merkezi bir kapıdan geçirir. Hata durumunda yeniden deneme (retry), zaman aşımı (timeout) ve istatistik toplama işlerini yapar.
       * src/control/models/model_router.py: Görev tipine göre (örn: summarize, explain, query_rewrite) en uygun modeli (gpt-4o, gpt-4o-mini vb.) seçer.
       * src/control/models/budgets.py: Hem görev bazlı (max_tokens) hem de günlük bütçe (max_cost_usd) limitlerini in-memory sayaçlarla denetler.
   * Gözlemlenebilirlik (Observability):
       * src/control/observability/tracer.py: Bir retrieval isteğinin hangi aşamalardan (hyde, rerank, graph expand vb.) geçtiğini ve her aşamanın ne kadar sürdüğünü detaylıca (trace) kaydeder.
       * src/control/observability/audit.py: Kritik sistem olaylarını (proje kaydı, onay kararları, hafıza yazımı) PostgreSQL'e audit_events olarak loglar.
       * src/control/observability/metrics.py: Latency, hit ratio ve token kullanımı gibi sayısal metrikleri toplar.
   * Değerlendirme (Eval) Sistemi:
       * src/control/evals/runner.py: Belirlenmiş veri setleri üzerinde sistemi test eder ve "Hit@1, MRR, Faithfulness" gibi kalite puanları üretir.

  2. Nasıl Tetiklenir (Start Points)?
   * Maliyet ve İstatistik Kontrolü: get_control_plane_stats tool'u ile o anki LLM kullanımı ve veritabanı logları sorgulanır.
   * Proje Yönetimi: register_project ile yeni bir repo sisteme tanıtılır ve Control Plane'in registry katmanına eklenir.
   * Etki Analizi: analyze_change_impact çağrıldığında Control Plane, Neo4j üzerindeki ilişkileri kullanarak değişikliğin riskini ölçer.
   * Kalite Ölçümü: run_retrieval_eval ile sistemin arama kalitesi benchmark edilir.

  3. Süreç Akışı (Step-by-Step)
   1. Talep Denetimi: Herhangi bir ajan düğümü (örn: Planner) bir LLM isteği attığında, ModelGateway araya girer.
   2. Bütçe Kontrolü: BudgetManager, bu görevin bütçesinin dolup dolmadığını kontrol eder. Dolduysa işlemi Guardrail üzerinden durdurur.
   3. Yönlendirme: ModelRouter, işlemin karmaşıklığına göre pahalı veya ucuz bir model seçer.
   4. İzleme (Tracing): İşlem sürerken PipelineTracer, arka planda her adımın (retrieval, rerank vb.) performansını ölçer.
   5. Kalıcı Kayıt: İşlem bittiğinde token kullanımı, gecikme ve sonuç kalitesi PostgreSQL'e yazılır.
   6. Raporlama: ControlHandler, tüm bu verileri birleştirerek kullanıcıya bir "Sağlık ve Maliyet Raporu" sunar.

  Control Plane, sistemin sadece çalışmasını değil, verimli ve ekonomik çalışmasını sağlayan "sigorta" ve "analiz" katmanıdır.