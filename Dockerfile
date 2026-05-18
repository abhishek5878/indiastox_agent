# IndiaStox substrate API — FastAPI gateway over DuckDB + tools layer.
#
# Single-stage image. The build context includes the pre-seeded warehouse and
# raw event NDJSONs (force-added at deploy time) so the container starts with
# the same state the local demo has. Sim state lives in-process, so a restart
# wipes the world — that is intentional for a free-tier demo.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
