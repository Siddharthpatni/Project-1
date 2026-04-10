#!/usr/bin/env bash
# Convenience script for fresh dev environment.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "creating .env from .env.example"
  cp .env.example .env
fi

echo "building containers..."
docker compose build

echo "starting stack..."
docker compose up -d

echo
echo "Frontend  : http://localhost:3000"
echo "API docs  : http://localhost:8000/docs"
echo "MinIO     : http://localhost:9001  (minioadmin / minioadmin)"
echo
echo "Tail logs : docker compose logs -f api worker"
