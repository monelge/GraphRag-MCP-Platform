#!/bin/bash

# GraphRagMCP V2 — Full System Tool Verification Wrapper
# Bu script, tüm MCP araçlarını (Tools) container içinde test eder.

# Renkler
GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}=== 🌐 GraphRagMCP V2 Entegrasyon Testi Başlatılıyor ===${NC}"

# 1. Container kontrolü
if [ "$(docker ps -q -f name=graph-mcp)" ]; then
    echo -e "[*] graph-mcp container'ı çalışıyor. Test scripti başlatılıyor...\n"
else
    echo -e "${RED}[!] HATA: graph-mcp container'ı çalışmıyor!${NC}"
    echo -e "[*] Lütfen 'docker compose up -d' komutu ile sistemi başlatın."
    exit 1
fi

# 2. Test scriptini çalıştır
docker exec -it graph-mcp /bin/bash -c "export PYTHONPATH=\$PYTHONPATH:/app && python3 /app/scripts/verification/test_all_tools_deep.py"

# 3. Sonuç kontrolü
if [ $? -eq 0 ]; then
    echo -e "\n${GREEN}✅ Tüm sistem testleri başarıyla tamamlandı.${NC}"
else
    echo -e "\n${RED}❌ Testler sırasında bir hata oluştu. Yukarıdaki logları inceleyin.${NC}"
    exit 1
fi
