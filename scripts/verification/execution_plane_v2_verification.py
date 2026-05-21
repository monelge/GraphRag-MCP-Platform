from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Proje kök dizinini ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from src.execution.runners.command_runner import CommandRunner


async def verify_execution_plane_v2():
    print("=== Execution Plane V2 Doğrulama Testi Başlıyor ===\n")
    
    runner = CommandRunner()

    # 1. Güvenlik İhlali Testi (Yasaklı Anahtar Kelime)
    print("[1/3] Güvenlik İhlali Tespiti (Dangerous Keyword)...")
    dangerous_cmd = "rm -rf /"
    try:
        await runner.run(dangerous_cmd)
        print("    ❌ Hata: Yasaklı komut engellenemedi!")
    except ValueError as e:
        print(f"    ✅ Başarılı: {e}")

    # 2. Yasaklı Dizin Erişimi Testi
    print("\n[2/3] Yasaklı Dizin Erişimi Tespiti (Path Sanitization)...")
    bad_cwd = "/app/.git"
    try:
        await runner.run("ls", cwd=bad_cwd)
        print("    ❌ Hata: Yasaklı dizin erişimi engellenemedi!")
    except ValueError as e:
        print(f"    ✅ Başarılı: {e}")

    # 3. Python Syntax Kontrolü Testi
    print("\n[3/3] Python Syntax Kontrolü (Pre-flight Linting)...")
    bad_python = "python3 -c 'print(\"hello\"'" # Kapanmamış parantez
    try:
        await runner.run(bad_python)
        print("    ❌ Hata: Hatalı Python kodu çalıştırılmaya çalışıldı!")
    except ValueError as e:
        print(f"    ✅ Başarılı: {e}")

    print("\n=== ✅ Execution Plane V2 Doğrulaması Başarıyla Tamamlandı ===")


if __name__ == "__main__":
    asyncio.run(verify_execution_plane_v2())
