# Backend image for Hugging Face Spaces (Docker SDK). Serves app/main.py
# (FastAPI) on the port Spaces expects; the Next.js frontend (web/) is
# deployed separately on Vercel and is not part of this image.
#
# Runs as a non-root uid 1000 user, per HF Spaces' Docker requirements
# (the platform mounts the container filesystem non-root).

FROM python:3.11-slim

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR /code

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Pre-download the embedding and reranking models into the image so
# startup never depends on the network — matches HF_LOCAL_FILES_ONLY=true,
# which rag/config.py expects in production, and avoids a slow first
# request after every cold start.
RUN python -c "from langchain_huggingface import HuggingFaceEmbeddings; HuggingFaceEmbeddings(model_name='sentence-transformers/all-MiniLM-L6-v2')" \
    && python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

COPY --chown=user app/ app/
COPY --chown=user rag/ rag/

EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
