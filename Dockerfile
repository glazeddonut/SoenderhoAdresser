# ── Python-runtime til FastAPI-appen ─────────────────────────
FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Installer Python-afhængigheder først (bedre lag-caching ved kodeændringer)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Kopiér kun applikationskoden (ikke .env, venv m.m. — se .dockerignore)
COPY main.py ./
COPY api/ ./api/
COPY static/ ./static/

# Kør som non-root bruger
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Healthcheck mod /api/config (svarer altid 200 med JSON)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8000')+'/api/config')" || exit 1

# --host 0.0.0.0 så containeren kan tilgås udefra
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
