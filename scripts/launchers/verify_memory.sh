#!/bin/bash
# Host makineden Docker içindeki Memory Plane doğrulamayı tetikleyen launcher

CONTAINER_NAME="graph-mcp"

echo "[*] Docker konteyneri ($CONTAINER_NAME) üzerinde Memory Plane testi başlatılıyor..."

# Konteyner içinde PYTHONPATH ayarı ve Python script icrası
docker exec -it $CONTAINER_NAME /bin/bash -c "export PYTHONPATH=\$PYTHONPATH:/app && python3 /app/scripts/verification/memory_plane_verification.py"
