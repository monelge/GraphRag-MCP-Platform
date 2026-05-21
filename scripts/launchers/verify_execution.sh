#!/bin/bash
# Host makineden Docker içindeki Execution Plane doğrulamayı tetikleyen launcher

CONTAINER_NAME="graph-mcp"

echo "[*] Docker konteyneri ($CONTAINER_NAME) üzerinde Execution Plane testi başlatılıyor..."

# Konteyner içinde PYTHONPATH ayarı ve Python script icrası
docker exec -it $CONTAINER_NAME /bin/bash -c "export PYTHONPATH=\$PYTHONPATH:/app && python3 /app/scripts/verification/execution_plane_verification.py"
