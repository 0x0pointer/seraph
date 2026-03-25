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
    "llm-guard==0.3.16" \
    "onnxruntime==1.18.1" \
    "optimum==1.27.0" \
    "sentence-transformers==2.7.0"

# Patch transitive dependencies pinned by llm-guard 0.3.16 to fix CVEs:
# - transformers 4.51.3 → 4.53.0 (ReDoS in tokenizers)
# - cryptography 44.0.3 → 46.0.5 (subgroup attack on SECT curves)
# - presidio-anonymizer 2.2.358 → 2.2.362 (unblocks cryptography >=46)
RUN pip install --no-cache-dir --force-reinstall --no-deps \
    transformers==4.53.0 \
    cryptography==46.0.5 \
    presidio-anonymizer==2.2.362

COPY . .

RUN useradd --create-home --shell /bin/bash seraph
USER seraph

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
