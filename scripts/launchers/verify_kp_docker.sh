#!/bin/bash
# =================================================================
# GraphRagMCP - Knowledge Plane Docker Doğrulama Betiği
# =================================================================

# Hata oluşursa dur
set -e

# Betiğin bulunduğu dizini ve proje kökünü bul
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "--------------------------------------------------------"
echo "🚀 Knowledge Plane Doğrulaması Başlatılıyor"
echo "--------------------------------------------------------"

# Eğer Docker içindeysek /app'e geç, değilsek proje köküne geç
if [ -d "/app" ]; then
    cd /app
    echo "[*] Ortam: Docker (/app)"
else
    cd "$PROJECT_ROOT"
    echo "[*] Ortam: Host ($PROJECT_ROOT)"
fi

# PYTHONPATH ayarla
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Python doğrulama scriptini çalıştır (scripts/ prefix'i ile)
python3 scripts/verification/knowledge_plane_verification.py

echo ""
echo "--------------------------------------------------------"
echo "✅ İşlem tamamlandı."
echo "--------------------------------------------------------"
