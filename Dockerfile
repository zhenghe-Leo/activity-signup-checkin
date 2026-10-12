# 多阶段构建：先用 Node 构建前端，再由 Python 运行后端并托管前端产物。
# 用法见 README「Docker 启动」：docker compose up --build

# ---- 第一阶段：构建前端 ----
FROM node:24-slim AS frontend
WORKDIR /build
COPY src/frontend/package.json src/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY src/frontend/ ./
RUN npm run build

# ---- 第二阶段：运行 ----
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/app.db
COPY src/backend/requirements.txt src/backend/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r src/backend/requirements.txt
COPY src/backend/ src/backend/
COPY scripts/ scripts/
COPY .env.example ./
COPY --from=frontend /build/dist/ src/frontend/dist/
# 数据库放在数据卷中，重建容器不丢数据；首次启动时 init 导入演示数据，已有数据库时跳过
VOLUME ["/app/data"]
EXPOSE 8000
CMD ["sh", "-c", "python scripts/manage.py init && python scripts/manage.py serve --host 0.0.0.0"]
