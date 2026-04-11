# Project Dependencies

This document provides a comprehensive list of all major libraries and frameworks used in the Vergabepilot.AI project and their specific roles.

## Backend (Python / FastAPI)

These dependencies are managed in `backend/requirements.txt`.

| Category | Library | Purpose |
| :--- | :--- | :--- |
| **Web Framework** | `fastapi` | Core REST API framework for job submission and management. |
| | `uvicorn` | High-performance ASGI server to run the FastAPI app. |
| | `pydantic` | Data validation and settings management using Python type annotations. |
| **Database** | `sqlalchemy` | SQL Toolkit and Object-Relational Mapper (ORM). |
| | `psycopg` | PostgreSQL adapter for Python. |
| | `alembic` | Database migrations management for SQLAlchemy. |
| **Async Jobs** | `celery` | Distributed task queue for asynchronous scraping and processing. |
| | `redis` | Message broker and result backend for Celery. |
| **LLM Integration** | `openai` | Client for OpenAI-compatible APIs (OpenRouter, local LLMs). |
| | `anthropic` | Client for Claude models. |
| | `httpx` | Async HTTP client for interacting with AI services. |
| **Scraping** | `playwright` | Browser automation for Phase 0 (Manual) and Phase 2 (CUA). |
| | `beautifulsoup4` | HTML parsing and data extraction. |
| | `lxml` | Fast XML and HTML parsing (used as a backend for BS4). |
| | `requests` | Synchronous HTTP library for simple page fetches. |
| **Storage** | `boto3` | AWS SDK for Python, used here for S3/MinIO interaction. |
| **Data Processing** | `pandas` | Library for URL extraction from uploaded CSV and Excel files. |
| | `openpyxl` | Engine for reading/writing Excel (.xlsx) files. |
| **Utilities** | `tenacity` | Retrying library for handling transient scraping or API failures. |
| | `structlog` | Structured logging for better observability in production. |
| | `pytest` | Testing framework for unit and integration tests. |

## Frontend (Node.js / Next.js)

These dependencies are managed in `frontend/package.json`.

| Category | Library | Purpose |
| :--- | :--- | :--- |
| **Framework** | `next` | React framework for server-side rendering and static site generation. |
| **UI Library** | `react` | Base UI library for component-based development. |
| **Styling** | `tailwindcss` | Utility-first CSS framework for custom, premium responsive design. |
| **Data Fetching** | `swr` | React Hooks for data fetching, caching, and polling (Jobs/Stats). |
| **Icons** | `lucide-react` | Modern, clean icon set for the dashboard. |
| **Charts** | `recharts` | Composable charting library for dashboard visualizations (Stats). |
| **Utilities** | `clsx` | Utility for constructing `className` strings conditionally. |
| **Language** | `typescript` | Static type checking for improved code quality and developer experience. |

## Infrastructure

| Component | Role |
| :--- | :--- |
| **Docker** | Containerization of all services for consistent environments. |
| **MinIO** | S3-compatible object storage for storing downloaded documents. |
| **PostgreSQL** | Primary relational database for metadata and job history. |
| **Redis** | In-memory data store for the Celery task queue. |
