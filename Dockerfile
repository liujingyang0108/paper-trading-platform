FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
EXPOSE 8800
CMD ["paper-platform", "--config", "config.docker.json", "--synthetic"]
