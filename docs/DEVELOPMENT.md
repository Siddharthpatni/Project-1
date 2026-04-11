# Developer Guide

Welcome to the Vergabepilot.AI development guide. Follow these steps to set up your environment, make changes, and contribute to the project.

## 1. Local Setup

### Prerequisites
- Docker & Docker Compose
- Python 3.12+ (for local linting/testing)
- Node.js 18+ (for frontend development)

### Running the Stack
The easiest way to develop is using Docker Compose:

```bash
cp .env.example .env
# Add your OPENROUTER_API_KEY to .env
docker compose up --build
```

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000/docs
- **MinIO Console**: http://localhost:9001 (minioadmin / minioadmin)

## 2. Making Changes

### Backend (Python/FastAPI)
The backend uses a modular Phase-based architecture:
- `app/api/`: Add or modify REST endpoints.
- `app/phase0_manual/`: Update the manual scraper logic.
- `app/phase1_llm_scraper/`: Modify how scrapers are generated and evaluated.
- `app/phase3_integration/pipeline.py`: Change the scraping cascade logic.

**How to contribute:**
1. Create a new branch: `git checkout -b feature/your-feature-name`.
2. Make your logic changes.
3. Add any new dependencies to `requirements.txt`.
4. Run tests (see section 3).

### Frontend (Next.js/React)
- `app/`: Page-level components and routing.
- `components/`: UI building blocks (Tailwind CSS).
- `lib/api.ts`: API interaction layer.

## 3. Testing

### Backend Testing
We use `pytest` for backend testing. Ensure you have the dependencies installed locally:

```bash
cd backend
pip install -r requirements.txt
pytest
```

### Frontend Testing
```bash
cd frontend
npm install
npm run build # To verify everything compiles correctly
npm run lint  # To check for code style issues
```

## 4. Contributing a New Manual Scraper
If you want to add a manual (Phase 0) scraper for a specific domain:
1. Update `backend/app/phase0_manual/v1_reference.py`.
2. Test it locally: `python backend/app/phase0_manual/v1_reference.py <url>`.
3. If it performs better than general logic, it will automatically be picked up by the `Strategy.MANUAL` pipeline.

## 5. Deployment Readiness Checklist
Before pushing your changes, ensure:
- [ ] Code is linted and type-checked.
- [ ] Tests pass (if applicable).
- [ ] `docker-compose.yml` build succeeds.
- [ ] Any new env variables are added to `.env.example`.

## 6. Git Workflow
- Keep commits small and descriptive.
- Avoid automatic code formatting on existing files to keep diffs clean.
- Push to your dedicated branch and request a review.
