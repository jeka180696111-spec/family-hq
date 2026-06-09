FROM python:3.11-slim

WORKDIR /app

# Cyrillic fonts for chronicle PDF generation
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "src.main"]
