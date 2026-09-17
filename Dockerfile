# syntax=docker/dockerfile:1.7

FROM node:24-slim AS frontend-build

WORKDIR /app/frontend

RUN npm install -g pnpm@10.34.5

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/index.html frontend/postcss.config.js frontend/tailwind.config.js frontend/vite.config.js frontend/.eslintrc.cjs ./
COPY frontend/src ./src
COPY frontend/tests ./tests
RUN pnpm test \
    && pnpm lint \
    && pnpm build


FROM python:3.13-slim AS backend-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend \
    GJALLAR_FRONTEND_DIST=/app/frontend-dist

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates iputils-ping \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.lock /app/backend/requirements.lock
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/backend/requirements.lock


FROM backend-base AS backend-test

COPY backend/requirements-dev.lock /app/backend/requirements-dev.lock
RUN pip install --no-cache-dir -r /app/backend/requirements-dev.lock

COPY . /workspace
WORKDIR /workspace
RUN PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/workspace/backend \
    python -m pytest -q -p no:cacheprovider /workspace/backend/tests


FROM python:3.13-slim AS client-test

WORKDIR /workspace/client
COPY client/requirements.lock client/requirements-dev.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock -r requirements-dev.lock
COPY client/ ./
RUN python -m pytest -q -p no:cacheprovider tests


FROM backend-base AS runtime

WORKDIR /app

COPY backend/app /app/backend/app
COPY backend/alembic /app/backend/alembic
COPY backend/alembic.ini /app/backend/alembic.ini
COPY docker/entrypoint.sh /app/entrypoint.sh
COPY --from=frontend-build /app/frontend/dist /app/frontend-dist

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
