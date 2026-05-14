"""Uygulama genelinde paylaşılan özel hata tipleri."""


class GraphRagError(Exception):
    """Tüm uygulama hatalarının temel sınıfı."""


class IndexingError(GraphRagError):
    """İndeksleme akışı sırasında oluşan hataları temsil eder."""


class RetrievalError(GraphRagError):
    """Retrieval ve arama süreci hatalarını temsil eder."""


class MemoryError(GraphRagError):
    """Hafıza katmanı işlemlerindeki hataları temsil eder."""


class TaskError(GraphRagError):
    """Task orchestration ve checkpoint hatalarını temsil eder."""


class ExecutionError(GraphRagError):
    """Sandbox ve komut yürütme hatalarını temsil eder."""


class StorageError(GraphRagError):
    """Veri depolama ve sorgu katmanı hatalarını temsil eder."""


class OntologyError(GraphRagError):
    """Ontology parse ve yazım hatalarını temsil eder."""
