# Repository Guidelines

## Project Invariants

HERMES is a 100% local desktop application for monitoring and drafting responses to public tenders. Preserve these invariants: FastAPI binds only to `127.0.0.1`, no telemetry, no cloud or paid API dependency, and no automatic tender submission. HERMION may draft responses, but final submission is always human.

Use the project names consistently in code, logs, comments, and UI: HERMES (app), ARGOS (collection/scraping), KRINOS (document extraction/scoring), HERMION (drafting), MNEMOSYNE (SQLite), PYTHIA (local Ollama LLM).

## Project Structure & Module Organization

- `backend/hermes/main.py` is the FastAPI entry point.
- `backend/hermes/api/` contains one route module per domain (`argos.py`, `krinos.py`, etc.).
- `backend/hermes/agents/` contains ARGOS, KRINOS, and future HERMION implementations.
- `backend/hermes/db/` contains SQLModel models and session setup for MNEMOSYNE.
- `backend/tests/` contains pytest files named `test_*.py`.
- `frontend/src/components/`, `frontend/src/views/`, and `frontend/src/lib/` hold React UI, views, and API/helpers.
- `frontend/src-tauri/` contains the Rust/Tauri wrapper.

Keep backend API modules domain-focused. Keep frontend backend-client logic in `frontend/src/lib/`, not inside components.

## Build, Test, and Development Commands

On this Windows environment, the default `python` is 3.7 and is too old. Use Python 3.12:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn hermes.main:app --host 127.0.0.1 --port 8000 --reload
pytest
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
npm run build
npm run tauri dev
```

Ollama/PYTHIA, when needed:

```powershell
.\scripts\start-pythia.ps1
D:\HermesDeps\ollama\bin\ollama.exe list
```

PYTHIA uses the standalone Ollama binary in `D:\HermesDeps\ollama\bin`, with
models stored in `D:\HermesDeps\ollama\models`.

## Local Storage Constraints

For HERMES setup work, place downloads and heavy caches on `D:` whenever the tool
supports it. This includes installers, Ollama models, Playwright browsers,
npm/pip/Cargo caches, and temporary archives. Avoid filling `C:` with large
dependencies or generated tooling.

## Coding Style & Naming Conventions

Backend uses Python 3.11+ with Ruff (`E`, `F`, `W`, `I`, `B`, `UP`) and 100-character lines. Use `snake_case` for Python modules, functions, and variables. Public business names should be French where appropriate.

Do not add `from __future__ import annotations` to `backend/hermes/db/models.py`; SQLModel/SQLAlchemy need real runtime annotations. Keep SQLModel relationships compatible with the existing style. Use timezone-aware UTC datetimes, never `datetime.utcnow()`.

Frontend uses React 18, TypeScript strict mode, Vite, and Tailwind/CSS. Use PascalCase for components and views (`Sidebar.tsx`, `Accueil.tsx`). Avoid heavy UI libraries unless explicitly justified.

## Testing Guidelines

Backend tests use pytest and pytest-asyncio. Prioritize API routes, agents, parsing, credentials, database access, KRINOS extraction, and ARGOS collection behavior. Run `pytest` from `backend/` before PRs.

No frontend test runner is configured yet. For UI work, run `npm run build` and manually verify the affected screen with Vite or Tauri.

## Security & Configuration Tips

Never commit secrets, credentials, generated databases, `.env`, `data/`, `node_modules/`, or Tauri `target/`. Credentials must remain encrypted in `portails.credentials_chiffres`. Document safe configuration in `.env.example`. Downloaded documents must keep SHA-256 checksums in `documents.checksum_sha256`.

## Commit & Pull Request Guidelines

Commit subjects are concise French, usually phase-based (`Phase 3 — ARGOS : ...`) or scoped (`docs:`, `fix:`), under roughly 70 characters. Claude-generated commits should include the Claude co-author trailer.

PRs should state the changed backend/frontend areas, test results (`pytest`, `npm run build`, manual checks), screenshots for visual changes, and linked phase or issue.
