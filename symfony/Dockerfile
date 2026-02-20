FROM php:8.4-cli
WORKDIR /app
RUN apt-get update && apt-get install -y git unzip && rm -rf /var/lib/apt/lists/*
COPY . /app
EXPOSE 8000
CMD ["php", "-S", "0.0.0.0:8000", "-t", "public"]
