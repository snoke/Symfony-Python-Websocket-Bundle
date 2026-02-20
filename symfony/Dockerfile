FROM php:8.4-cli
WORKDIR /app
RUN apt-get update && apt-get install -y git unzip && rm -rf /var/lib/apt/lists/*
COPY symfony /app
COPY bundle /bundle
RUN if [ -L /app/vendor/snoke/ws-bundle ] || [ ! -d /app/vendor/snoke/ws-bundle ]; then \
      rm -rf /app/vendor/snoke/ws-bundle; \
      mkdir -p /app/vendor/snoke; \
      cp -R /bundle /app/vendor/snoke/ws-bundle; \
    fi
EXPOSE 8000
CMD ["php", "-S", "0.0.0.0:8000", "-t", "public", "public/index.php"]
