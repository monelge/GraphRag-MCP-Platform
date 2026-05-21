#!/bin/bash
# Host makineden Docker içindeki Control Plane doğrulamayı tetikleyen launcher

CONTAINER_NAME="graph-mcp"

echo "[*] Docker konteyneri ($CONTAINER_NAME) üzerinde Control Plane testi başlatılıyor..."

# Konteyner içinde PYTHONPATH ayarı ve Python script icrası
docker exec -it $CONTAINER_NAME /bin/bash -c "export PYTHONPATH=\$PYTHONPATH:/app && python3 /app/scripts/verification/control_plane_verification.py"
