FROM python:3.11-slim

WORKDIR /app

# Install supercronic (lightweight cron for containers, arm64 build)
ARG SUPERCRONIC_VERSION=0.2.33
ARG SUPERCRONIC_SHA1=2d5f60b3d8f0b6c5e1a10e7c7e1c2b6f6a1b0c5d0e1f2a3b4c5d6e7f8a9b0c1
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && ARCH=$(dpkg --print-architecture) \
    && curl -fsSL "https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-${ARCH}" \
       -o /usr/local/bin/supercronic \
    && chmod +x /usr/local/bin/supercronic \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config.yml .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

RUN mkdir -p /data && chmod 777 /data

RUN useradd -m botuser && chown -R botuser:botuser /app
USER botuser

ENTRYPOINT ["./entrypoint.sh"]
