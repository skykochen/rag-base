# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Enterprise RAG (Retrieval-Augmented Generation) knowledge base. Monorepo with:
- `backend/` — Python 3.10+ FastAPI service (async SQLAlchemy, pgvector, Tencent COS, Docling, LangChain embeddings)
- `frontend/` — React 19 + TypeScript + Vite SPA (Ant Design, TanStack React Query, Zustand, react-router-dom v7)

## Common Commands

### Infrastructure
```bash
docker compose up -d           # Start PostgreSQL (pgvector/pgvector:pg16)
```

### Backend (from repo root)
```bash
cd backend
uv sync                        # Install deps (uses Aliyun PyPI mirror)
uv run uvicorn app.main:app --reload --port 8000   # Dev server
uv run alembic upgrade head    # Apply migrations
uv run alembic revision --autogenerate -m "msg"    # Generate migration
```

### Frontend (from repo root)
```bash
cd frontend
npm install
npm run dev                    # Dev server on :5173 (proxies /api → :8000)
npm run build                  # Type-check + production build
npm run lint                   # oxlint
npm run gen:api                # Regenerate API client from backend OpenAPI spec (backend must be running on :8000)
```

## Architecture

### Document Ingestion Pipeline
The core flow: upload → parse → split → embed → store.

1. **Upload** (`POST /api/documents`): File → COS → DB row (status=`uploading`) → `BackgroundTasks` schedules `ingest_document`
2. **Parse** (`app/ingestion/parser.py`): Docling `DocumentConverter` (singleton, heavy init) converts to Markdown via `asyncio.to_thread`
3. **Split** (`app/ingestion/splitter.py`): LangChain `RecursiveCharacterTextSplitter` with Chinese-aware separators. Each chunk gets `chunk_index` and MD5 `chunk_hash`
4. **Embed** (`app/ingestion/embedder.py`): DashScope `text-embedding-v3` via OpenAI-compatible protocol. Singleton `OpenAIEmbeddings` instance
5. **Store**: Chunks with `Vector(1024)` embeddings written to `document_chunks` table

Status transitions are committed in independent transactions (`_set_status`) so frontend polling sees intermediate states immediately.

### Data Model
- `Document`: tracks file metadata, COS location, lifecycle status (`uploading`/`parsing`/`indexing`/`ready`/`failed`), deduped by `file_hash` (SHA-256)
- `DocumentChunk`: content + pgvector embedding + page_no/section_path metadata. `chunk_hash` (MD5) enables future incremental indexing

### Key Patterns
- **Idempotent upload**: SHA-256 hash deduplicates both COS objects (key = `documents/{hash}{suffix}`) and DB rows
- **Repository pattern**: `DocumentRepository` / `DocumentChunkRepository` encapsulate SQLAlchemy queries
- **Unified exceptions**: `AppException` hierarchy → `error_handlers.py` maps to JSON responses. Use `NotFoundError`, `ValidationError`, `ConfigurationError`
- **Settings singleton**: `pydantic-settings` reads from root `.env`. Access via `from app.core.config import settings`
- **Async throughout**: `asyncpg` driver, `AsyncSession`, all COS/Docling calls wrapped with `asyncio.to_thread`
- **API client generation**: Frontend uses `@hey-api/openapi-ts` — after changing backend routes, run `npm run gen:api` to regenerate `frontend/src/client/`

### Configuration
All config via environment variables in root `.env` (see `.env.example`). Key groups:
- `DATABASE_URL` — must use `postgresql+asyncpg://` driver
- `COS_*` — Tencent Cloud Object Storage credentials
- `EMBEDDING_*` — DashScope API key, model, dimensions (default 1024, must match `Vector(N)` in migration)
- `CHUNK_SIZE` / `CHUNK_OVERLAP` — text splitter parameters

### Important Constraints
- Embedding dimension (`settings.embedding_dim`) is baked into the Alembic migration's `Vector(N)` column. Changing it requires rebuilding the table
- COS delete failures are logged as warnings but don't fail the request (DB is source of truth; avoids "user thinks deleted but DB still has it" inconsistency)
- `ingest_document` uses its own `AsyncSessionLocal()` sessions separate from the request session, since it runs in a background task
- Frontend dev server proxies `/api` to `localhost:8000`; CORS is also configured in backend settings
