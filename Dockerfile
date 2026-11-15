# PackTherm: the API and the web app. Build: docker build -t packtherm .   Run: docker run -p 8000:8000 packtherm

# Build the web app (Node is needed only here, not in the image that runs).
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npx vite build --outDir /web-dist

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 PACKTHERM_JOBS_DIR=/data/jobs
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=web /web-dist ./src/packtherm/web_static
RUN pip install --no-cache-dir ".[api]" \
    && useradd --create-home --uid 10001 packtherm \
    && mkdir -p /data/jobs && chown -R packtherm /data
USER packtherm
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request, os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"
CMD ["sh", "-c", "packtherm serve --host 0.0.0.0 --port ${PORT}"]
