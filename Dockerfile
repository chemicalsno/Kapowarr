FROM python:3.13-slim

STOPSIGNAL SIGTERM

ENV S6_OVERLAY_VERSION=3.1.6.2

RUN \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        curl \
        xz-utils \
        bash \
    && curl -L -o /tmp/s6-overlay-noarch.tar.xz \
        https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz \
    && curl -L -o /tmp/s6-overlay.tar.xz \
        https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-x86_64.tar.xz \
    && tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz \
    && tar -C / -Jxpf /tmp/s6-overlay.tar.xz \
    && rm -rf /tmp/s6-overlay*.tar.xz \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --upgrade pip --break-system-packages

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

COPY . .

RUN addgroup --system abc && adduser --system --ingroup abc abc

RUN \
    chown -R abc:abc /app \
    && chmod -R 755 /app

USER root

EXPOSE 5656

ENV PUID=1000 \
    PGID=1000 \
    TZ=UTC

RUN \
    mkdir -p /etc/services.d/kapowarr \
    && echo "#!/usr/bin/with-contenv bash\ncd /app\nexec s6-setuidgid abc python3 /app/Kapowarr.py" \
        > /etc/services.d/kapowarr/run \
    && chmod +x /etc/services.d/kapowarr/run

ENTRYPOINT ["/init"]
