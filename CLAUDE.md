# CLAUDE.md — Agent Onboarding

## Project Summary

Ctrl+Apply is a semi-automated job application tool. A **Python FastAPI backend** (port 8765) orchestrates form analysis via `claude-agent-sdk`, serves a WebSocket bridge, and drives browser automation through Playwright's CDP connection to the user's Chrome. A **Chrome Extension** (Manifest V3) provides a side panel UI and read-only DOM extraction of job application forms. The extension never modifies the DOM — all form filling is done by Playwright via CDP on port 9222.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, uvicorn, Pydantic v2, DuckDB, Polars, claude-agent-sdk, Playwright, rapidfuzz
- **Extension:** Vanilla JS (no build step, no framework), Chrome MV3 Side Panel API
- **Build system:** hatchling (pyproject.toml)
- **Linter:** ruff (line-length=100, target py310, rules: E, F, I)

## Environment Setup

All commands **must** be run inside the `ctrl-apply` micromamba environment. Always prefix commands with `micromamba run -n ctrl-apply` or activate the environment first.

```bash
# 1. Create env from environment.yml (once)
micromamba create -f environment.yml -y

# 2. Install Playwright Chromium browser (once, ~110 MB)
micromamba run -n ctrl-apply playwright install chromium
```

If the environment already exists and you need to reinstall after dependency changes:
```bash
micromamba run -n ctrl-apply pip install -e ".[dev]"
```

## Commands

| Action | Command |
|---|---|
| **Install deps** | `micromamba create -f environment.yml -y` |
| **Run server** | `micromamba run -n ctrl-apply python -m backend.main` |
| **Lint check** | `micromamba run -n ctrl-apply ruff check backend/` |
| **Lint fix** | `micromamba run -n ctrl-apply ruff check --fix backend/` |
| **Format check** | `micromamba run -n ctrl-apply ruff format --check backend/` |
| **Format fix** | `micromamba run -n ctrl-apply ruff format backend/` |
| **Import check** | `micromamba run -n ctrl-apply python -c "from backend.main import app"` |
| **Health check** | `curl http://127.0.0.1:8765/health` (server must be running) |

Always run `ruff check` and `ruff format --check` before committing Python changes. Fix any issues with `--fix` / `ruff format`.

There is no test suite yet. When tests are added, they will use `pytest` and `pytest-asyncio` (already in dev dependencies).

## Project Layout

```
backend/                    # Python FastAPI backend (the only Python package)
  main.py                   # FastAPI app entry point, lifespan, router registration
  config.py                 # Settings via pydantic-settings (env prefix: CTRL_APPLY_)
  db.py                     # DuckDB connection, table schemas (jobs, applications)
  models/                   # Pydantic v2 data models
    profile.py              # UserProfile — loaded from data/profile.yaml
    form.py                 # FormField, FormAnalysis, ExtractedForm
    job.py                  # JobListing with status enum
    application.py          # Application tracking record
  services/                 # Business logic (all async)
    llm_service.py          # claude-agent-sdk query() wrapper, cloud/local routing
    playwright_service.py   # CDP connection, form filling, dropdown matching
    form_service.py         # Orchestrates: extraction → LLM analysis → fill
    profile_service.py      # Load YAML profile, serialize to LLM prompt context
  routers/                  # FastAPI route handlers
    ws.py                   # WebSocket /ws — main extension ↔ backend bridge
    profile.py              # GET/POST /api/profile
    form.py                 # POST /api/form/analyze, /api/form/fill
extension/                  # Chrome MV3 extension (vanilla JS, no build step)
  manifest.json             # Permissions: sidePanel, activeTab, storage
  service-worker.js         # WebSocket client to ws://127.0.0.1:8765/ws
  content/
    detector.js             # ATS platform detection from URL patterns
    extractor.js            # Read-only DOM form field extraction
  sidepanel/
    index.html, panel.js, panel.css  # Side panel UI
data/                       # User data (not in version control)
  profile.template.yaml     # Template — copy to profile.yaml and fill out
  profile.yaml              # User's actual profile (gitignored)
  jobs.duckdb               # DuckDB database (auto-created on first run)
  cover_letters/            # Generated cover letters
scripts/
  launch-chrome.sh          # Launch Chrome with --remote-debugging-port=9222
pyproject.toml              # Dependencies, build config, ruff config
environment.yml             # Micromamba env specification
```

## Architecture

**Data flow:** Content script extracts form fields → service worker relays via WebSocket → backend sends fields + profile to Claude via `claude-agent-sdk` `query()` → Claude returns field-to-profile mappings → side panel shows mappings for user review → user clicks Fill → Playwright fills form via CDP.

**LLM integration** (`backend/services/llm_service.py`): Uses `claude-agent-sdk`'s `query()` async iterator with `ClaudeAgentOptions`. Cloud mode uses Claude Max subscription (default). Local mode sets `ANTHROPIC_BASE_URL` to point at Ollama — same code path, only env vars differ.

**Playwright** (`backend/services/playwright_service.py`): Connects to the user's real Chrome browser via `connect_over_cdp()`. Uses `page.fill()`, `page.select_option()`, `page.set_input_files()`, `page.check()`. Dropdown matching uses `rapidfuzz` with WRatio scorer (threshold: 70).

**DuckDB** (`backend/db.py`): Two tables — `jobs` and `applications`. Auto-initialized on first connection. File at `data/jobs.duckdb`.

## Key Conventions

- **Always use Polars** for DataFrame operations. Never use pandas.
- **Always use DuckDB** for SQL/database operations. Never use SQLite.
- **Pydantic v2** for all data models. Use `model_validate()`, `model_dump()`. Never use Pydantic v1 API.
- All Python files start with `from __future__ import annotations`.
- All backend services are async. Use `async def` for service methods.
- Singleton service instances at module level (e.g., `llm_service = LLMService()`).
- Extension content scripts are **read-only** — they never modify the DOM.
- All Python scripts in this repository must be run in the `ctrl-apply` micromamba environment.

## Configuration

Settings in `backend/config.py` use `pydantic-settings` with env prefix `CTRL_APPLY_`. Key settings:

| Setting | Default | Env var override |
|---|---|---|
| `host` | `127.0.0.1` | `CTRL_APPLY_HOST` |
| `port` | `8765` | `CTRL_APPLY_PORT` |
| `llm_mode` | `cloud` | `CTRL_APPLY_LLM_MODE` |
| `cdp_url` | `http://localhost:9222` | `CTRL_APPLY_CDP_URL` |
| `data_dir` | `data/` | `CTRL_APPLY_DATA_DIR` |

## Known Issues

- **CDP connection fails at startup** if Chrome isn't running with `--remote-debugging-port=9222`. This is non-fatal — the backend logs a warning and retries on demand.
- **`pyproject.toml` requires** the `[tool.hatch.build.targets.wheel] packages = ["backend"]` entry. Without it, `pip install -e .` fails with "Unable to determine which files to ship inside the wheel."
- The `EmailStr` import in `backend/models/profile.py` is currently unused (kept as a placeholder).
- No `.gitignore` exists yet. The `data/` directory contains user-specific files (profile.yaml, resume.pdf, jobs.duckdb) that should not be committed.
- No CI/CD pipeline or GitHub Actions workflows exist yet.

## Trust These Instructions

These instructions are validated against the actual repository. Only perform additional codebase exploration if information here is incomplete or found to be incorrect.
