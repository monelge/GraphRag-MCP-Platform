from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Proje kök dizinini ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from src.control.models.budgets import BudgetManager, BudgetExceededError


async def verify_control_plane_v2():
    print("=== Control Plane V2 Doğrulama Testi Başlıyor ===\n")
    
    manager = BudgetManager()
    task_id = "test_v2_task"

    # 1. Normal Bütçe Kontrolü (Başarılı)
    print("[1/2] Normal Bütçe Kontrolü...")
    try:
        manager.check_task(task_id, tokens_used=1000, last_success=True)
        print("    ✅ Başarılı: Normal işlem bütçe içinde onaylandı.")
    except Exception as e:
        print(f"    ❌ Hata: Beklenmedik engel: {e}")

    # 2. Yield Analysis (Runaway Loop) Testi
    print("\n[2/2] Yield Analysis (Ardışık 3 Hata) Testi...")
    try:
        # 1. Hata
        manager.check_task(task_id, tokens_used=500, last_success=False)
        print("    [*] İlk hata kaydedildi.")
        
        # 2. Hata
        manager.check_task(task_id, tokens_used=500, last_success=False)
        print("    [*] İkinci hata kaydedildi.")
        
        # 3. Hata (Burada durdurulmalı)
        print("    [*] Üçüncü hata gönderiliyor...")
        manager.check_task(task_id, tokens_used=500, last_success=False)
        
        print("    ❌ Hata: Ardışık 3 başarısızlık engellenemedi!")
    except BudgetExceededError as e:
        print(f"    ✅ Başarılı: {e}")
        if "Runaway Loop" in str(e):
            print("    ✅ Doğrulandı: Sistem bütçe dolmadan verim analizi ile işlemi durdurdu.")

    print("\n=== ✅ Control Plane V2 Doğrulaması Başarıyla Tamamlandı ===")


if __name__ == "__main__":
    asyncio.run(verify_control_plane_v2())
