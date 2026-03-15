# Stage 1: React 빌드
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python 백엔드
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY mcp/ ./mcp/
COPY --from=frontend /app/frontend/dist ./frontend/dist

ENV PORT=8585
EXPOSE $PORT
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
