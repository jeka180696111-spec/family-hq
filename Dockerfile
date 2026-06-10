FROM python:3.11-slim

WORKDIR /app

# Fonts: Cyrillic body + multiple emoji coverage paths.
# - fonts-symbola = monochrome emoji (best coverage for our needs)
# - fonts-ancient-scripts = Symbola_hint.ttf path
# - fonts-noto-color-emoji = color emoji as final fallback
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        fonts-liberation \
        fonts-noto-core \
        fonts-symbola \
        fonts-ancient-scripts \
        fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "src.main"]
