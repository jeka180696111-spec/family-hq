FROM python:3.11-slim

WORKDIR /app

# Fonts: Cyrillic for body text + Symbola/Noto for unicode symbols/emoji
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        fonts-liberation \
        fonts-noto-core \
        fonts-symbola \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "src.main"]
