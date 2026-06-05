import logging
import time
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

        # Eski kayıtları archived olarak işaretle
        archived_count = 0
        for candidate in candidates:
            entry_id = candidate.get("id") or candidate.get("entry_id")
            if entry_id:
                try:
                    await self.store.update_memory_status(entry_id, "archived")
                    archived_count += 1
                except Exception:
                    pass

        return f"✅ {len(candidates)} kayıt birleştirildi, {archived_count} kayıt archived yapıldı: {new_entry.entry_id}"

    async def extract_atomic_facts(self, collection: str, limit: int = 10) -> str:
        """
        Memory Plane V2 (Mem0 Style):
        Son N adet 'episodic' (geçici/ham) kaydı çeker, LLM'e göndererek
        bunlardan kalıcı, net ve kategorize edilmiş 'Atomic Facts' çıkarır.
        Çıkarılan gerçekleri 'semantic' katmana yazar ve eski logları temizler.
        """
        # Son eklenen episodik kayıtları getir
        results = await self.store.search_memory("*", memory_type="episodic", collection=collection, top_k=limit)
        if not results:
            return "Çıkarım yapılacak episodik kayıt bulunamadı."

        context = "\n---\n".join([f"Kayıt: {c.get('name', 'İsimsiz')}\nİçerik: {c.get('code', '')}" for c in results])

        client = get_llm_client()
        prompt = (
            "Aşağıdaki ham 'episodic' hafıza loglarını incele.\n"
            "Bunlardan, sistemin gelecekte kullanabileceği net, kısa ve kalıcı kurallar (Atomic Facts) çıkar.\n"
            "Örneğin: 'Kullanıcı Python 3.11 kullanıyor', 'Auth servisinde JWT token süresi 1 saattir'.\n"
            "Yanıtını her bir gerçek için bir satır olacak şekilde DÜZ METİN (maddeler halinde) dön. Başka hiçbir şey yazma."
        )

        response = await client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Ham Loglar:\n{context}"}
            ],
            max_tokens=800
        )
        facts_text = response.choices[0].message.content.strip()
        facts = [f.strip("- *") for f in facts_text.split("\n") if f.strip("- *")]

        if not facts:
            return "Kalıcı bir gerçek (fact) çıkarılamadı."

        stored_count = 0
        for i, fact in enumerate(facts):
            # Her bir fact'i ayrı, net bir semantic entry olarak kaydet (Mem0 stili)
            fact_entry = MemoryEntry(
                title=f"Atomic Fact #{i+1}",
                content=fact,
                memory_type="semantic",  # Kalıcı bilgi
                collection=collection,
                tags=["atomic_fact", "auto_extracted"]
            )
            await self.store.store_memory(fact_entry)
            stored_count += 1

        # Opsiyonel: Burada işlenen eski episodik loglar 'archived' olarak işaretlenip Qdrant'tan silinebilir.
        # Bu sayede vektör veritabanı temiz kalır. (Prune işlemi simülasyonu)

        return f"✅ {len(results)} ham logdan {stored_count} adet Atomic Fact (Kalıcı Bilgi) çıkarıldı ve Semantic katmana yazıldı."

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
        valid_to zamanı geçmiş olanları fiziksel olarak siler.
        """
        try:
            deleted = await self.store.prune_expired(collection=collection, before_timestamp=time.time())
            logger.info("Collection '%s' içinde %d süresi dolan kayıt silindi", collection, deleted)
            return f"✅ Collection '{collection}': {deleted} süresi dolan kayıt silindi"
        except Exception as e:
            logger.error("Expiry pruning hatası: %s", e)
            return f"❌ Pruning başarısız: {e}"
