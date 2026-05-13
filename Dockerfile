FROM python:3.11-slim

WORKDIR /app

# Sistem bağımlılıkları (tree-sitter C uzantısı için gerekli)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Python paketlerini önce kopyala — layer cache'den yararlanır
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kaynak kodunu kopyala
COPY src/ ./src/

# V2 registry / metadata için kalıcı app data dizini
RUN mkdir -p /app/data

# Non-root user
RUN groupadd -r mcpuser && useradd -r -g mcpuser mcpuser
USER mcpuser

# MCP server stdio modunda çalışır; docker exec -i ile başlatılır
# Healthcheck: server'ın canlı olduğunu kontrol et
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s \
  CMD python3 -c "import src.mcp_server" || exit 1

# Konteyneri ayakta tut; MCP sunucusu docker exec ile başlatılır
CMD ["tail", "-f", "/dev/null"]
