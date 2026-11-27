FROM python:3.13-slim

ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf \
    USE_TF=0 \
    TRANSFORMERS_NO_TF=1 \
    TOKENIZERS_PARALLELISM=false

WORKDIR /app

# CPU-only PyTorch first (the default Linux wheel pulls ~2 GB of CUDA libraries we don't need)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model into the image: containers never call Hugging Face at runtime
RUN python -c "import sys; from sentence_transformers import SentenceTransformer; SentenceTransformer(sys.argv[1])" "$EMBEDDING_MODEL"

COPY app ./app
COPY ui ./ui
COPY scripts ./scripts
COPY data/docs ./data/docs

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app /opt/hf
USER appuser

ENV HF_HUB_OFFLINE=1
EXPOSE 8000 8501

# One worker on purpose: the session lock and metrics live in process memory.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]