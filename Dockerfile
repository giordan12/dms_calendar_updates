FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config.yml .

RUN mkdir -p /data && chmod 777 /data

RUN useradd -m botuser && chown -R botuser:botuser /app
USER botuser

CMD ["python3", "-m", "src.scheduler"]
