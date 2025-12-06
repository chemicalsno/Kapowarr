FROM python:3.13-slim-bookworm

STOPSIGNAL SIGTERM

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp

COPY . .

RUN pip install --no-cache-dir .

RUN useradd -d /app --create-home kapowarr

WORKDIR /app

USER kapowarr

EXPOSE 5656

CMD ["python3", "/tmp/Kapowarr.py"]
