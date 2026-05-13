from fastembed import SparseTextEmbedding


class SparseEmbedder:
    """
    Neden sparse (seyrek) vektör?
    "JWT", "bcrypt", "SHA256" gibi teknik token'lar için kesin eşleşme
    gerekir — dense model bunları anlam yerine frekansla yakalar.
    """

    def __init__(self):
        # BM25 modelini indirip yükle (ilk çalıştırmada ~50 MB)
        self.model = SparseTextEmbedding(model_name="Qdrant/bm25")

    def embed_batch(self, texts: list[str]):
        # Qdrant SparseVector formatına uygun indices + values döner
        return list(self.model.embed(texts))
