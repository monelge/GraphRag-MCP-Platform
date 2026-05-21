#!/bin/bash
# Host makineden Docker içindeki Unified Orchestration V2 doğrulamayı tetikleyen launcher

CONTAINER_NAME="graph-mcp"

echo "=========================================================="
echo "🎯 Unified Orchestration V2 - Full System Verification"
echo "=========================================================="

# Konteyner içinde PYTHONPATH ayarı ve V2 Python script icrası
docker exec -it $CONTAINER_NAME /bin/bash -c "export PYTHONPATH=\$PYTHONPATH:/app && python3 /app/scripts/verification/mcp_server_full_orchestration_verification.py"

echo "=========================================================="
