FROM python:3.12-slim
LABEL authors="Misha Opstal"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    libsodium23 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY assets ./assets
COPY models ./models
COPY voice_call ./voice_call
COPY helpers ./helpers
COPY bot.py .
COPY audio.py .
COPY config.py .

ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]