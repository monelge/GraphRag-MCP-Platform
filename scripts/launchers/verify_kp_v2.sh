#!/bin/bash
# Host makineden Docker içindeki Knowledge Plane V2 doğrulamayı tetikleyen launcher

CONTAINER_NAME="graph-mcp"

echo "=========================================================="
echo "🚀 Knowledge Plane V2 - Enrichment & Search Verification"
echo "=========================================================="

# Konteyner içinde PYTHONPATH ayarı ve V2 Python script icrası
docker exec -it $CONTAINER_NAME /bin/bash -c "export PYTHONPATH=\$PYTHONPATH:/app && python3 /app/scripts/verification/knowledge_plane_v2_verification.py"

echo "=========================================================="
