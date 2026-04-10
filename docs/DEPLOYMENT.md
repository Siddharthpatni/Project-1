# Deployment

## Local development

```bash
git clone <repo> vergabepilot-ai
cd vergabepilot-ai
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY
docker compose up --build
```

Services:
- Frontend → http://localhost:3000
- API docs → http://localhost:8000/docs
- MinIO    → http://localhost:9001 (`minioadmin` / `minioadmin`)
- Postgres → localhost:5432

To run tests:
```bash
docker compose run --rm api pytest -q
```

## Working without Docker (backend only)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
export DATABASE_URL=sqlite:///./vergabepilot.db
export REDIS_URL=redis://localhost:6379/0
uvicorn app.main:app --reload
# in a second shell:
celery -A app.workers.celery_app worker --loglevel=info
```

## Frontend only

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

## Production notes

- Build the frontend with `npm run build` and serve via `next start` behind nginx.
- Run multiple Celery workers with `--concurrency` tuned to CPU count.
- Use an external Postgres + S3 bucket; never run MinIO single-node in prod.
- Set `LOG_LEVEL=INFO` (or `WARNING`) and ship logs to your aggregator.
