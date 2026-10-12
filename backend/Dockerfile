FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app/backend
COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/app ./app
COPY --from=frontend /build/dist /app/frontend/dist
RUN useradd --create-home hookscope && mkdir -p /app/backend/data && chown -R hookscope:hookscope /app
USER hookscope
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8787/api/ready', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "100", "--backlog", "256", "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "30"]
