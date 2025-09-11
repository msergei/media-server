FROM debian:stable-slim
ENV DEBIAN_FRONTEND=noninteractive
ENV UID=1000
ENV GID=200

# Системные оптимизации и установка базовых пакетов
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y \
        procps \
        iproute2 \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Системные лимиты для производительности
RUN echo "* soft nofile 65536" >> /etc/security/limits.conf && \
    echo "* hard nofile 1048576" >> /etc/security/limits.conf && \
    echo "root soft nofile 65536" >> /etc/security/limits.conf && \
    echo "root hard nofile 1048576" >> /etc/security/limits.conf
