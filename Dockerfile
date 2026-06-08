FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends     build-essential git tzdata     && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Istanbul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt .

# 1. CPU-only torch (arm64/amd64 uyumlu en son kararlı sürüm)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# 2. transformers
RUN pip install --no-cache-dir transformers

# 3. Geri kalan paketler
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
RUN mkdir -p /app/data

RUN groupadd -r mcpuser && useradd -r -g mcpuser mcpuser &&     mkdir -p /home/mcpuser/.cache &&     chown -R mcpuser:mcpuser /home/mcpuser
USER mcpuser

ENV TRANSFORMERS_CACHE=/app/data/.cache/huggingface
ENV HF_HOME=/app/data/.cache/huggingface

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s   CMD python3 -c "import src.mcp_server" || exit 1

CMD ["tail", "-f", "/dev/null"]
