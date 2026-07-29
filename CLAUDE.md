# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Proposal Review** — an internal web app that reviews consulting proposals (PPTX/DOCX/PDF) with Claude AI, detecting superlative claims, typos, competitor-comparison language, and blind-evaluation (company-identifying) content.

## Architecture

- **Frontend**: `index.html` at the repo root — a single-file vanilla JS SPA, no build step. Deployed to Vercel. This is the only frontend that is actually live in production.
- **Backend**: `backend/` — FastAPI, deployed to Railway. Business logic lives in `backend/app/routers/jobs.py` (job/file endpoints, Word/PDF export) and `backend/app/routers/auth.py`.
- **Database**: Supabase (PostgreSQL), accessed via `supabase-py` (`backend/app/database.py`). Not SQLAlchemy/Alembic at runtime.
- **Background work**: Celery + Redis for the review pipeline (`backend/app/workers/review_task.py`).
- **AI**: Anthropic Claude (see `backend/app/services/`) — text review in page chunks, vision review per image.

PDF export is built client-side in `index.html` (`buildPdfHtml`, via html2pdf.js) — treat it as the canonical design source when the Word (python-docx) export in `jobs.py` needs to visually match it.

## Notes for Future Sessions

- There is no separate Next.js/React frontend — an earlier `frontend/` (Next.js) directory existed but was never cut over to production and has been removed. If you see references to it in old docs/history, they're stale.
- Deploy workflow: push to `master`, then fast-forward `main` (`git fetch origin && git push origin master:main && git branch -f main origin/main`) — Vercel (frontend) and Railway (backend, manual `railway up --detach` from `backend/`) both build from `main`.
- See `README.md` for local dev setup (backend + Redis + Celery; frontend is just opening/serving `index.html`).
