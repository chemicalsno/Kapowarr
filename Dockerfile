FROM python:3.13-slim-bookworm

STOPSIGNAL SIGTERM

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd kapowarr && chown -R kapowarr:kapowarr /app

USER kapowarr

EXPOSE 5656

CMD ["python3", "Kapowarr.py"]
