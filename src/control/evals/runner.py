import time
import logging
from typing import List, Dict, Any
from src.control.evals.dataset_manager import EvalCase

logger = logging.getLogger(__name__)

class EvalRunner:
    def __init__(self, search_func):
        self.search_func = search_func

    async def run_eval(self, dataset: List[EvalCase], collection: str) -> Dict[str, Any]:
        results = []
        t0 = time.monotonic()
        
        hits_at_1 = 0
        hits_at_3 = 0
        hits_at_5 = 0
        mrr = 0.0
        
        for case in dataset:
            # Aramayı çalıştır
            # Not: search_func asenkron olmalı
            search_results_raw = await self.search_func(case.question, collection=collection)
            
            # Sonuçları işle (Basitçe dosya yollarını çıkar)
            # Not: Gerçek sistemde search_code string döner, onu parse etmek veya 
            # ham liste dönen bir iç fonksiyon kullanmak daha iyidir.
            retrieved_files = self._extract_files_from_output(search_results_raw)
            
            # Metrikleri hesapla
            found_idx = -1
            for i, f in enumerate(retrieved_files):
                if any(expected in f for expected in case.expected_files):
                    found_idx = i
                    break
            
            if found_idx == 0: hits_at_1 += 1
            if 0 <= found_idx < 3: hits_at_3 += 1
            if 0 <= found_idx < 5: hits_at_5 += 1
            if found_idx >= 0:
                mrr += 1.0 / (found_idx + 1)
                
            results.append({
                "question": case.question,
                "found_at": found_idx,
                "retrieved": retrieved_files[:5]
            })
            
        total = len(dataset)
        duration = time.monotonic() - t0
        
        return {
            "summary": {
                "total_cases": total,
                "hit_at_1": hits_at_1 / total if total > 0 else 0,
                "hit_at_3": hits_at_3 / total if total > 0 else 0,
                "hit_at_5": hits_at_5 / total if total > 0 else 0,
                "mrr": mrr / total if total > 0 else 0,
                "avg_latency_sec": duration / total if total > 0 else 0
            },
            "details": results
        }

    def _extract_files_from_output(self, output: str) -> List[str]:
        """Arama çıktısından dosya yollarını ayıklar."""
        import re
        # Örn: 📄 `/projects/GraphRagMCP/src/storage/neo4j_store.py`
        matches = re.findall(r"📄 `(.*?)`", output)
        return matches
