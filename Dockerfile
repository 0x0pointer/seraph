FROM python:3.11-slim@sha256:9358444059ed78e2975ada2c189f1c1a3144a5dab6f35bff8c981afb38946634

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch CPU-only first (avoids NVIDIA CUDA packages that
# are unavailable on ARM / non-GPU hosts)
RUN pip install --no-cache-dir torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu

# Install project dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi==0.135.2" \
    "uvicorn[standard]==0.30.1" \
    "pydantic==2.12.5" \
    "pyyaml==6.0.3" \
    "httpx==0.27.0" \
    "aiosqlite==0.20.0" \
    "sentence-transformers==5.4.0" \
    "nemoguardrails==0.21.0" \
    "langgraph==1.1.3" \
    "langchain-core==1.2.28" \
    "langchain-openai==1.1.12"

COPY . .

RUN useradd --create-home --shell /bin/bash seraph \
    && mkdir -p /data && chown seraph:seraph /data
USER seraph

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
