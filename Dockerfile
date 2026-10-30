# ---------------------------------------------------------------------------
# CivicSense - production image
#
# A two stage build: the first stage compiles the Python wheels (mysqlclient
# needs a C compiler), the second stage copies only the installed packages, so
# the shipped image carries no build tools.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential default-libmysqlclient-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=civicsense.settings
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        default-mysql-client curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash civic

COPY --from=builder /install /usr/local
COPY . .

RUN mkdir -p /app/staticfiles /app/media && chown -R civic:civic /app
USER civic

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "civicsense.wsgi:application", \
     "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", \
     "--access-logfile", "-"]
