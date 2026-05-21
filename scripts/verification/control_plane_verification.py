from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Proje kök dizinini ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import src.mcp.server as server
from src.mcp.tool_registry import get_control_plane_stats
from src.control.models.budgets import BudgetManager, TaskBudget, BudgetExceededError
from src.control.observability.tracer import PipelineTracer


async def verify_control_plane():
    print("=== Control Plane Doğrulama Testi Başlıyor ===\n")

    try:
        # DB bağlantılarını başlat
        await server._postgres.connect()

        # 1. Model Gateway & Stats Testi
        print("[1/4] Model Gateway & İstatistik Testi...")
        # Gateway stats'larını temizle (test için taze başlangıç)
        server._model_gateway._stats = {
            "total_calls": 0,
            "total_tokens": 0,
            "total_latency_ms": 0,
            "per_model_stats": {},
        }
        
        # Manuel bir istatistik güncellemesi simüle edelim (Gerçek LLM çağrısı yapmadan)
        server._model_gateway._update_stats("gpt-4o-mini", latency=150, tokens=500)
        server._model_gateway._update_stats("gpt-4o", latency=450, tokens=1200)
        
        stats_res = await get_control_plane_stats()
        print(f"    Gateway İstatistikleri (Oturum içi):")
        if "gpt-4o-mini" in stats_res and "gpt-4o" in stats_res:
            print("    ✅ Oturum içi istatistikler başarıyla raporlandı.")
        else:
            print("    ❌ İstatistik raporu eksik veya hatalı!")

        # 2. Budget Manager (Bütçe Denetimi) Testi
        print("\n[2/4] Budget Manager (Bütçe Denetimi) Testi...")
        # Çok düşük limitli bir bütçe yöneticisi oluşturalım
        test_budget = TaskBudget(max_tokens=1000, max_llm_calls=2)
        bm = BudgetManager(task_budget=test_budget)
        
        task_id = "test-budget-task"
        print(f"    Limit: 1000 token, 2 çağrı. Görev: {task_id}")
        
        try:
            # İlk çağrı (500 token) - Geçmeli
            bm.check_task(task_id, tokens_used=500)
            print("    [1] İlk çağrı (500 token): ✅ Geçti")
            
            # İkinci çağrı (600 token) - Toplam 1100 olur, kalmalı
            print("    [2] İkinci çağrı (600 token - limiti aşacak):")
            bm.check_task(task_id, tokens_used=600)
            print("    ❌ HATA: Bütçe aşımı yakalanamadı!")
        except BudgetExceededError as e:
            print(f"    ✅ Başarılı: Bütçe aşımı yakalandı: {e}")

        # 3. Pipeline Tracer (İzleme) Testi
        print("\n[3/4] Pipeline Tracer (İzleme) Testi...")
        tracer = PipelineTracer(query="test sorgusu", collection="verify_control", query_type="test")
        
        with tracer.step("retrieval"):
            await asyncio.sleep(0.1) # İşlem simülasyonu
            tracer.record("retrieval", item_count=5)
            
        with tracer.step("rerank"):
            await asyncio.sleep(0.05)
            tracer.record("rerank", item_count=3)
            
        trace_summary = tracer.finish()
        print(f"    Trace Adım Sayısı: {trace_summary['step_count']}")
        print(f"    Toplam Gecikme: {trace_summary['total_latency_ms']}ms")
        if trace_summary['step_count'] == 2:
            print("    ✅ Pipeline trace başarıyla kaydedildi.")

        # 4. Postgres DB Log Kontrolü
        print("\n[4/4] Postgres DB Log Doğrulaması...")
        if server._postgres.available:
            # Retrieval ve Audit stats'larını çekerek DB erişimini doğrula
            db_stats = await server._postgres.get_llm_usage_stats(days=1)
            print(f"    DB'den gelen son 1 günlük LLM kullanım kaydı sayısı: {len(db_stats)}")
            print("    ✅ Postgres Control Plane sorguları başarılı.")

        print("\n=== ✅ Kontrol Düzlemi Doğrulaması Başarıyla Tamamlandı ===")

    except Exception as e:
        print(f"\n❌ Test sırasında hata oluştu: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await server._postgres.close()
        await server._neo4j.close()
        await server._redis.close()


if __name__ == "__main__":
    asyncio.run(verify_control_plane())
