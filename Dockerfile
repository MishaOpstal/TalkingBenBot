FROM python:3.13-slim AS build
# git is only needed to install py-cord from GitHub (see requirements.txt)
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.13-slim
LABEL authors="Misha Opstal"

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libopus0 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build /install /usr/local

WORKDIR /app
COPY bot.py ./
COPY ben ./ben
COPY assets ./assets

ENV PYTHONUNBUFFERED=1 \
    MODELS_DIR=/app/models \
    DATA_DIR=/app/data \
    SOUNDS_DIR=/app/assets/sounds

CMD ["python", "bot.py"]
