#!/bin/bash
# Host makineden Docker içindeki TÜM SİSTEMİ (mcp_server.py) doğrulayan launcher

CONTAINER_NAME="graph-mcp"

echo "=========================================================="
echo "🌟 GraphRagMCP V2 - Full System Verification"
echo "=========================================================="

# Konteyner içinde PYTHONPATH ayarı ve Master Python script icrası
docker exec -it $CONTAINER_NAME /bin/bash -c "export PYTHONPATH=\$PYTHONPATH:/app && python3 /app/scripts/verification/mcp_server_full_verification.py"

echo "=========================================================="
