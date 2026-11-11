FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    CHROMA_DIR=/app/chroma_db \
    PORT=8000

WORKDIR /app

# Dependencias primero (aprovecha la cache de capas de Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request as u; u.urlopen(f\"http://localhost:{os.environ.get('PORT','8000')}/salud\", timeout=3)" || exit 1

# API FastAPI. En Render usa $PORT; en compose el servicio api puede sobreescribir el comando.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
