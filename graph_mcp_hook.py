#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess

# ── KONFİGÜRASYON ──────────────────────────────────────────────────────────
# Docker konteyner ismi
CONTAINER_NAME = "graph-mcp"
# Proje kök dizini (Host üzerindeki yol)
PROJECT_PATH = os.getcwd()
HOST_PROJECTS_ROOT = Path("/Volumes/MacBook/RiderProjects").resolve()
CONTAINER_PROJECTS_ROOT = Path("/projects")


def to_container_path(path_str):
    """Host path'ini container içindeki /projects mount'una çevir."""
    path = Path(path_str).resolve()
    try:
        relative = path.relative_to(HOST_PROJECTS_ROOT)
    except ValueError:
        return None
    return str(CONTAINER_PROJECTS_ROOT / relative)

def get_changed_files():
    """Git diff kullanarak son commit ile değişen dosyaları bulur."""
    try:
        # Son commit'teki değişiklikleri al
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        files = result.stdout.splitlines()
        # Sadece desteklenen uzantıları ve mevcut dosyaları al
        valid_extensions = {".py", ".ts", ".tsx", ".cs", ".go", ".rs"}
        changed = []
        for f in files:
            absolute = os.path.join(PROJECT_PATH, f)
            if not any(f.endswith(ext) for ext in valid_extensions):
                continue
            if not os.path.exists(absolute):
                continue

            container_path = to_container_path(absolute)
            if container_path is not None:
                changed.append(container_path)

        return changed
    except Exception as e:
        print(f"❌ Git hatası: {e}")
        return []

def trigger_incremental_index(changed_files):
    """Docker içindeki GraphMCP sunucusuna artımlı indeksleme komutu gönderir."""
    if not changed_files:
        print("✅ Değişen dosya yok, indeksleme atlandı.")
        return

    container_project_path = to_container_path(PROJECT_PATH)
    if container_project_path is None:
        print("❌ Proje yolu /Volumes/MacBook/RiderProjects altında değil, container path üretilemedi.")
        return

    print(f"🔄 {len(changed_files)} dosya için artımlı indeksleme başlatılıyor...")
    
    # Dosya listesini JSON string yap
    files_json = json.dumps(changed_files)
    
    # Docker exec ile komutu çalıştır
    cmd = [
        "docker", "exec", CONTAINER_NAME,
        "python", "-c",
        f"import asyncio; from src.mcp_server import incremental_index_project; "
        f"print(asyncio.run(incremental_index_project('{container_project_path}', {files_json})))"
    ]
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ İndeksleme tetiklenemedi: {e}")

if __name__ == "__main__":
    changed = get_changed_files()
    trigger_incremental_index(changed)
