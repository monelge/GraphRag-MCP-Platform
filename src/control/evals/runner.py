import re
import time
from typing import Any, Dict, List

from src.control.evals.dataset_manager import EvalCase
from src.control.evals.scoring.metrics import faithfulness_score, hit_at_k, mrr


class EvalRunner:
    def __init__(self, search_func):
        self.search_func = search_func

    async def run_eval(self, dataset: List[EvalCase], collection: str) -> Dict[str, Any]:
        results = []
        t0 = time.monotonic()
        total_hit1 = 0.0
        total_hit3 = 0.0
        total_hit5 = 0.0
        total_mrr = 0.0
        total_faithfulness = 0.0
        for case in dataset:
            search_results_raw = await self.search_func(case.question, collection=collection)
            retrieved_files = self._extract_files_from_output(search_results_raw)
            total_hit1 += hit_at_k(retrieved_files, case.expected_files, 1)
            total_hit3 += hit_at_k(retrieved_files, case.expected_files, 3)
            total_hit5 += hit_at_k(retrieved_files, case.expected_files, 5)
            total_mrr += mrr(retrieved_files, case.expected_files)
            total_faithfulness += faithfulness_score(search_results_raw, case.expected_files)
            results.append({"question": case.question, "retrieved": retrieved_files[:5]})
        total = len(dataset)
        duration = time.monotonic() - t0
        return {
            "summary": {
                "total_cases": total,
                "hit_at_1": total_hit1 / total if total else 0.0,
                "hit_at_3": total_hit3 / total if total else 0.0,
                "hit_at_5": total_hit5 / total if total else 0.0,
                "mrr": total_mrr / total if total else 0.0,
                "faithfulness": total_faithfulness / total if total else 0.0,
                "avg_latency_sec": duration / total if total else 0.0,
            },
            "details": results,
        }

    def _extract_files_from_output(self, output: str) -> List[str]:
        return re.findall(r"📄 `(.*?)`", output)
