#!/bin/bash
# Host makineden Docker içindeki doğrulamayı tetikleyen launcher

# Konteyner adını kontrol et (Varsayılan: graph-mcp)
CONTAINER_NAME="graph-mcp"

echo "[*] Docker konteyneri ($CONTAINER_NAME) üzerinde test başlatılıyor..."

# Docker komutunu çalıştır
# -it: İnteraktif terminal
# /app/scripts/launchers/verify_kp_docker.sh: Konteyner içindeki hazırladığımız betik
docker exec -it $CONTAINER_NAME /bin/bash /app/scripts/launchers/verify_kp_docker.sh
