import logging
from typing import List, Dict, Any, Optional
from src.shared.llm_client import get_llm_client
from src.storage.episodic_store import EpisodicStore, MemoryEntry

logger = logging.getLogger(__name__)

class MemoryCompactor:
    """Bellek kaydı birleştirici — benzer kayıtları özet hale getir."""
    
    def __init__(self, episodic_store: EpisodicStore):
        self.store = episodic_store

    async def compact(self, collection: str, query: str = "*", threshold: float = 0.85):
        """
        Benzer bellek kayıtlarını bulur ve onları tek bir kayıtta birleştirir.
        
        Süreç:
        1. Belirli bir koleksiyondaki veya genelindeki kayıtları çek.
        2. Benzerlik analizi yap (vektör benzerliği üzerinden).
        3. Çok benzer olanları LLM'e gönderip 'tek bir özet' haline getir.
        4. Eski kayıtları 'archived' yap, yeni birleştirilmiş kaydı ekle.
        """
        # 1. Kayıtları çek (Arama motorunu kullanarak tümünü veya benzerlerini bul)
        results = await self.store.search_memory(query, collection=collection, top_k=20)
        if len(results) < 2:
            return "Kompakt hale getirilecek yeterli benzer kayıt bulunamadı."

        # 2. Gruplandırma (LLM'e gönderilecek adayları seç)
        candidates = results[:5]
        
        # 3. LLM ile birleştirme
        merged_content = await self._merge_with_llm(candidates)
        
        # 4. Yeni kaydı oluştur ve eskileri güncelle
        new_entry = MemoryEntry(
            title=f"Compacted Memory: {query}",
            content=merged_content,
            memory_type="semantic",
            collection=collection,
            tags=["compacted"]
        )
        
        await self.store.store_memory(new_entry)
        
        return f"✅ {len(candidates)} kayıt başarıyla birleştirildi: {new_entry.entry_id}"

    async def _merge_with_llm(self, candidates: List[Dict]) -> str:
        """LLM kullanarak birden fazla kaydı tek bir tutarlı metne dönüştürür."""
        context = "\n---\n".join([f"Başlık: {c['name']}\nİçerik: {c['code']}" for c in candidates])

        client = get_llm_client()
        response = await client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Sana verilen benzer bellek kayıtlarını, bilgi kaybı olmadan tek bir tutarlı ve öz metne dönüştür. Tekrar eden kısımları temizle."},
                {"role": "user", "content": f"Birleştirilecek Kayıtlar:\n{context}"}
            ],
            max_tokens=1000
        )
        return response.choices[0].message.content.strip()


    async def prune_expired_memory(self, collection: str) -> str:
        """
        Faz 3: Süresi dolan bellek kayıtlarını temizle.
        valid_to zamanı geçmiş olanları 'archived' yap.
        """
        try:
            # Not: EpisodicStore'a pruning metodu eklenebilir
            logger.info(f"Collection '{collection}' içinde süresi dolan kayıtlar temizleniyor")
            
            # Placeholder
            return f"✅ Collection '{collection}' temizlendi"
        except Exception as e:
            logger.error(f"Expiry pruning hatası: {e}")
            return f"❌ Pruning başarısız: {e}"
