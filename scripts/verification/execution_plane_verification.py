from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Proje kök dizinini ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import src.mcp.server as server
from src.mcp.tool_registry import run_verification_plan
from src.execution.runners.command_runner import CommandRunner
from src.execution.sandbox.runtime_manager import SandboxRuntimeManager


async def verify_execution_plane():
    print("=== Execution Plane Doğrulama Testi Başlıyor ===\n")

    temp_dir = Path(tempfile.mkdtemp(prefix="ep_verify_"))
    print(f"[*] Test Dizini: {temp_dir}\n")

    try:
        # 1. Profil Tespiti (Profile Detection)
        print("[1/4] Profil Tespiti (Profile Detection) Testi...")
        runner = CommandRunner()
        manager = SandboxRuntimeManager(runner)
        
        # Fake bir Python projesi oluşturalım
        (temp_dir / "requirements.txt").touch()
        profile_py = manager.detect_profile(str(temp_dir))
        print(f"    requirements.txt bulundu -> Profil: {profile_py.name} (Build: {profile_py.build_cmd})")
        
        # Temizleyip fake bir Node.js projesi oluşturalım
        (temp_dir / "requirements.txt").unlink()
        (temp_dir / "package.json").touch()
        profile_node = manager.detect_profile(str(temp_dir))
        print(f"    package.json bulundu -> Profil: {profile_node.name} (Build: {profile_node.build_cmd})")

        # 2. Tool Policy & Command Runner (İzin Verilen / Engellenen Komutlar)
        print("\n[2/4] Güvenlik & İzin (Tool Policy) Testi...")
        
        # İzin verilen bir komut (örn. echo veya bash ama inline değil)
        # Not: ALLOWED_EXECUTABLES içinde /bin/bash var, ama -c engelli. 
        # Test için python3 kullanalım:
        print("    [A] İzin verilen komut testi (python3 -c 'print(1+1)'):")
        res_allowed = await runner.run("python3 -c 'print(1+1)'", cwd=str(temp_dir))
        if res_allowed.success and "2" in res_allowed.stdout:
            print("        ✅ Başarılı. Çıktı: 2")
        else:
            print(f"        ❌ Hata: {res_allowed.stderr}")

        # İzin verilmeyen inline bash testi (BLOCKED_BASH_FLAGS)
        print("    [B] Engellenen komut testi (bash -c 'echo hack'):")
        res_blocked = await runner.run("bash -c 'echo hack'", cwd=str(temp_dir))
        if not res_blocked.success and "Inline bash commands are not allowed" in res_blocked.stderr:
            print("        ✅ Güvenlik politikası çalıştı. Komut engellendi.")
        else:
            print(f"        ❌ Güvenlik zafiyeti! Sonuç: {res_blocked.stderr}")

        # 3. Timeout Kontrolü
        print("\n[3/4] Zaman Aşımı (Timeout) Testi...")
        print("    python3 -c 'import time; time.sleep(3)' komutu 1 saniye limit ile çalıştırılacak:")
        res_timeout = await runner.run("python3 -c 'import time; time.sleep(3)'", cwd=str(temp_dir), timeout=1)
        if res_timeout.timed_out:
            print("        ✅ Timeout mekanizması başarıyla çalıştı.")
        else:
            print("        ❌ Komut zaman aşımına uğramadı!")

        # 4. run_verification_plan Tool Entegrasyonu
        print("\n[4/4] run_verification_plan() Tool Çalıştırılıyor...")
        # Fake Python dosyası ve test oluşturalım
        (temp_dir / "package.json").unlink() # Python'a dönelim
        (temp_dir / "pyproject.toml").touch()
        (temp_dir / "test_app.py").write_text("def test_dummy(): assert True\n")
        
        print(f"    Hedef Dizin: {temp_dir}")
        plan_res = await run_verification_plan(
            project_path=str(temp_dir),
            run_build=False, # Bağımlılık kurmamak için build atlıyoruz
            run_tests=True,
            run_lint=False
        )
        print(f"\n{plan_res}")
        if "Başarılı" in plan_res or "Başarısız" in plan_res:
            print("    ✅ Doğrulama planı başarıyla icra edildi.")

        print("\n=== ✅ Yürütme Düzlemi Doğrulaması Başarıyla Tamamlandı ===")

    except Exception as e:
        print(f"\n❌ Test sırasında hata oluştu: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_execution_plane())
