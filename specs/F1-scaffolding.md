## F1 — Monorepo scaffolding, config & dev environment

**Goal:** A running skeleton — FastAPI serving `GET /api/health`, a dark React app shell with sidebar, Postgres in Docker, and green CI — that every later feature builds on without re-scaffolding.

**Depends on:** none (first feature)

### Context digest

Contracts and principles from the shared context (CLAUDE.md) that this feature is bound by — use these exact names/paths/values:

- **Repo layout (§4):** monorepo root holds `docker-compose.yml`, `.github/workflows/ci.yml`, `backend/`, `frontend/`. Backend package root is `backend/app/` with subpackages `api/`, `graph/` (+ `graph/nodes/`), `tools/`, `llm/`, `persistence/`, plus `backend/evals/` and `backend/tests/`. Frontend is `frontend/src/` with `api/`, `stores/`, `styles/`, `components/{ui,run,approval,report}/`, `pages/`, and files `main.tsx`, `App.tsx`, `types.ts`. **F1 creates every file/dir in §4 as an empty stub** (module docstring or one-line placeholder) so later features only fill them in.
- **API contract (§7):** `GET /api/health → 200 {status:"ok"}`. This is the only route F1 implements. All API paths are under the `/api` prefix. Do not implement any other §7 route (they belong to F6+).
- **Tech stack (§3):** Python 3.12 managed with `uv`; FastAPI + Uvicorn; Pydantic v2 + `pydantic-settings`; PostgreSQL 16 (Docker). Frontend: React 19 + TypeScript + Vite (SPA, **no Next.js**); Tailwind CSS v4; TanStack Query v5 (server state) + Zustand (UI state); `lucide-react` icons only; `react-markdown` + `remark-gfm`. CI: GitHub Actions.
- **Design system (§8) — exact tokens for `styles/theme.css`:** background `#0B0E14`, surface `#131722`, raised surface `#1A2030`, border `#232B3D`; text primary `#E6EAF2`, secondary `#8A94A8`; accent `#6E9FFF`, success `#4ADE80`, warn `#FBBF24`, danger `#F87171`. Fonts: Inter (UI) + JetBrains Mono (code/costs/ids). Radius 10px cards / 8px controls. 8-pt spacing grid. Dark-first. **No component library** — `components/ui/` is hand-built. Icons: `lucide-react` only. No default Vite splash, no lorem ipsum, no emoji-as-icons (principle §2.10).
- **Env vars this feature must expose in `Settings` (from feature step 2):** `OPENAI_API_KEY`, `TAVILY_API_KEY`, `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`, `LANGSMITH_PROJECT`, `DATABASE_URL`, `CHECKPOINT_BACKEND` (`"sqlite"|"postgres"`, default `"sqlite"`), `CORS_ORIGINS`. OpenAI is the sole LLM provider — no `ANTHROPIC_API_KEY`.
- **Principles that bite in F1:** §2.8 12-factor config — all config via env through `pydantic-settings`; commit `.env.example`, never `.env`. §2.9 observability — LangSmith env vars present (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT=atlas`) even though tracing isn't wired until later. §2.10 no-AI-boilerplate frontend. §9 definition of done — typecheck (`mypy`/`tsc --noEmit`) + lint (`ruff`/`eslint`) + tests (`pytest`/`vitest`) + `.env.example` updated + README section + Verify command runs.

### Context deltas

- **`specs/` directory (new, non-conforming to §4):** this spec lives in `specs/F1-scaffolding.md`. §4 does not list a `specs/` dir (it references a single `SPEC.md`). This is a docs-only addition and does not affect code. No action needed unless the team wants §4 updated to mention `specs/`.
- **`CORS_ORIGINS` env format:** decided as a comma-separated string parsed into `list[str]` (see Implementation notes). This is a concrete refinement of §2 step 2, not a change to any code contract. No shared-context edit required.
- Otherwise **none** — F1 introduces no new state fields (§5), routes (§7), or graph nodes (§6).

### Scope

1. **Root files.**
   - `docker-compose.yml` — Postgres only (backend/frontend containers arrive in F13).
   - `.github/workflows/ci.yml` — two jobs (backend, frontend).
   - `.gitignore` covering `.env`, `__pycache__/`, `.venv/`, `*.db`, `node_modules/`, `dist/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`.
   - `.env.example` at repo root with every var from step 2 + Postgres creds, dummy values.
   - `README.md` with an F1 section (how to run backend, frontend, and Postgres; how to verify).

2. **Backend project (`backend/`).** Run `uv init` (or hand-write). `backend/pyproject.toml` with:
   - `requires-python = ">=3.12"`.
   - Runtime deps (pinned per §3, resolve exact patch at install): `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `pydantic-settings`, `sse-starlette`, `langgraph>=1.0,<2.0`, `langchain>=1.0,<2.0`, `langchain-openai`, `langchain-tavily`, `langgraph-checkpoint-sqlite`, `langgraph-checkpoint-postgres`. (Install now so the lockfile is stable; F2+ import them. Do **not** import graph/LLM libs in F1 code.)
   - Dev deps group: `ruff`, `mypy`, `pytest`, `httpx` (for FastAPI `TestClient`).
   - `[tool.ruff]` (line-length 100, target py312, select `E,F,I,UP,B`), `[tool.mypy]` relaxed-strict (`python_version = "3.12"`, `disallow_untyped_defs = true`, `warn_unused_ignores = true`, `ignore_missing_imports = true`), `[tool.pytest.ini_options]` (`testpaths = ["tests"]`).

3. **`backend/app/config.py` — `Settings`.** `pydantic-settings` `BaseSettings` reading from env / `.env`. Required (no default) → fail-fast; optional → default.
   ```python
   from pydantic import Field, field_validator
   from pydantic_settings import BaseSettings, SettingsConfigDict

   class Settings(BaseSettings):
       model_config = SettingsConfigDict(
           env_file=".env", env_file_encoding="utf-8", extra="ignore"
       )
       # required — missing → ValidationError at construction (fail fast)
       OPENAI_API_KEY: str
       TAVILY_API_KEY: str
       # optional
       LANGSMITH_API_KEY: str | None = None
       LANGSMITH_TRACING: bool = False
       LANGSMITH_PROJECT: str = "atlas"
       DATABASE_URL: str = "postgresql://atlas:atlas@localhost:5432/atlas"
       CHECKPOINT_BACKEND: Literal["sqlite", "postgres"] = "sqlite"
       CORS_ORIGINS: list[str] = ["http://localhost:5173"]

       @field_validator("CORS_ORIGINS", mode="before")
       @classmethod
       def _split_csv(cls, v):
           if isinstance(v, str):
               return [o.strip() for o in v.split(",") if o.strip()]
           return v

   def get_settings() -> Settings:
       return Settings()
   ```
   Expose a module-level `settings = get_settings()` **and** keep `get_settings()` callable (tests construct `Settings()` under a patched env to exercise fail-fast without tripping the import-time singleton). Import `Literal` from `typing`.

4. **`backend/app/main.py` — app factory.**
   ```python
   def create_app() -> FastAPI:
       app = FastAPI(title="Atlas API")
       app.add_middleware(
           CORSMiddleware,
           allow_origins=settings.CORS_ORIGINS,
           allow_credentials=True,
           allow_methods=["*"],
           allow_headers=["*"],
       )
       @app.get("/api/health")
       def health() -> dict[str, str]:
           return {"status": "ok"}
       return app

   app = create_app()
   ```

5. **Backend stub modules.** Create every §4 backend path as an importable stub with a one-line module docstring stating which feature fills it in — e.g. `app/graph/state.py` → `"""ResearchState graph state — implemented in F2."""`. Add `__init__.py` to every package dir (`app`, `app/api`, `app/graph`, `app/graph/nodes`, `app/tools`, `app/llm`, `app/persistence`, `tests`). Create `evals/benchmark_topics.jsonl` (empty), `evals/report_template.md` (placeholder), `evals/{run_benchmark,graders}.py` (stubs). **No graph/LLM/tool logic** (§ Out of scope).

6. **Frontend project (`frontend/`).** Scaffold Vite React-TS (`npm create vite@latest . -- --template react-ts` inside `frontend/`), React 19. Then:
   - Install: `@tanstack/react-query`, `zustand`, `lucide-react`, `react-markdown`, `remark-gfm`. Dev: `tailwindcss`, `@tailwindcss/vite`, `prettier`, plus the eslint/vitest deps below.
   - `vite.config.ts` — add `@tailwindcss/vite` and `@vitejs/plugin-react`; set `test` (vitest) config with `environment: "jsdom"`, `globals: true`, `setupFiles: "./src/test/setup.ts"`.
   - `src/styles/theme.css` — `@import "tailwindcss";` then `@theme { ... }` mapping the §8 tokens to Tailwind v4 CSS variables (see skeleton in Implementation notes). Import Inter + JetBrains Mono. Set the dark background on `body`.
   - `src/main.tsx` — mount `<App/>` wrapped in `QueryClientProvider` (a single `QueryClient`); import `styles/theme.css`.
   - `src/App.tsx` — **sidebar shell**: left sidebar with "Atlas" wordmark and nav items "New Run" and "History" (each a `lucide-react` icon + label; active state styled), and an empty main panel with a real empty-state (text + one action, no illustration, per §8). No routing library required in F1 (nav can be non-functional buttons or local state); do not add react-router. No default Vite splash/logo/counter.
   - `src/types.ts` — stub with a comment: mirrors backend contracts, filled from F6.
   - Create empty stub dirs/files for the rest of §4 frontend layout (`api/`, `stores/`, `components/{ui,run,approval,report}/` with a `.gitkeep` or index stub, `pages/{NewRunPage,RunPage,HistoryPage}.tsx` as placeholder components).

7. **Frontend tooling.**
   - ESLint **flat config** `eslint.config.js` (typescript-eslint + react-hooks + react-refresh, matching the Vite template's flat-config output). `prettier` config `.prettierrc` (or `prettier` key in package.json).
   - `package.json` scripts: `dev`, `build` (`tsc -b && vite build`), `preview`, `lint` (`eslint .`), `typecheck` (`tsc --noEmit`), `format` (`prettier --write .`), `test` (`vitest run`).
   - Vitest deps: `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom`, `@vitejs/plugin-react`. `src/test/setup.ts` imports `@testing-library/jest-dom`.

8. **`docker-compose.yml` (DB-only).**
   ```yaml
   services:
     postgres:
       image: postgres:16
       environment:
         POSTGRES_USER: atlas
         POSTGRES_PASSWORD: atlas
         POSTGRES_DB: atlas
       ports: ["5432:5432"]
       volumes: ["atlas_pgdata:/var/lib/postgresql/data"]
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U atlas -d atlas"]
         interval: 5s
         timeout: 5s
         retries: 5
   volumes:
     atlas_pgdata:
   ```
   Credentials must match the `DATABASE_URL` default in `Settings`.

9. **`.github/workflows/ci.yml`** — trigger on `pull_request` and `push` to `main`. Two jobs:
   - **backend** (`working-directory: backend`): `astral-sh/setup-uv`, `uv sync`, then `uv run ruff check .`, `uv run mypy app`, `uv run pytest`. Set dummy required env (`OPENAI_API_KEY`, `TAVILY_API_KEY`) at the job/step level so import-time `Settings()` succeeds.
   - **frontend** (`working-directory: frontend`): `actions/setup-node` (Node 20+), `npm ci`, then `npm run lint`, `npm run typecheck`, `npm run test`.

10. **`.env.example`** — every var from step 2 with dummy values, plus a comment that `CORS_ORIGINS` is comma-separated. Include Postgres-matching `DATABASE_URL`.

### Out of scope

- Any graph code — nodes, `state.py` logic, `builder.py`, routing (F2+).
- LLM router logic (F9; stubbed file only here).
- Checkpointer/runs-repo implementations (F2/F6; stub files only).
- Any real API route beyond `/api/health` (F6 owns run lifecycle + SSE).
- Any real page content / routing / data fetching (F10–F12); F1 only renders the static shell.
- Backend/frontend Dockerfiles and their compose services (F13). `docker-compose.yml` is Postgres-only here.

### Implementation notes

- **Verify installed versions before writing library-specific code** (§2.11): after `uv sync` / `npm install`, run `uv run python -c "import fastapi, pydantic_settings"` and `npm ls tailwindcss @tailwindcss/vite` and trust the installed versions over this spec.
- **Tailwind v4 is CSS-first** — no `tailwind.config.js`, no PostCSS/`content` array. Use the `@tailwindcss/vite` plugin and define tokens in CSS via `@theme`. Skeleton for `src/styles/theme.css`:
  ```css
  @import "tailwindcss";
  @theme {
    --color-background: #0B0E14;
    --color-surface: #131722;
    --color-raised: #1A2030;
    --color-border: #232B3D;
    --color-text-primary: #E6EAF2;
    --color-text-secondary: #8A94A8;
    --color-accent: #6E9FFF;
    --color-success: #4ADE80;
    --color-warn: #FBBF24;
    --color-danger: #F87171;
    --font-sans: "Inter", ui-sans-serif, system-ui, sans-serif;
    --font-mono: "JetBrains Mono", ui-monospace, monospace;
    --radius-card: 10px;
    --radius-control: 8px;
  }
  body { background: var(--color-background); color: var(--color-text-primary); font-family: var(--font-sans); }
  ```
  These generate utilities like `bg-background`, `text-text-secondary`, `border-border`, `font-mono`. Load Inter/JetBrains Mono via an `@import`/`<link>` from a font source or a self-hosted `@font-face`; a `google fonts` `<link>` in `index.html` is acceptable for F1.
- **pydantic-settings v2 list parsing gotcha:** a bare `list[str]` field makes pydantic-settings attempt **JSON** decoding of the env value, so `CORS_ORIGINS=http://localhost:5173` (non-JSON) raises `SettingsError`. The `mode="before"` `field_validator` that splits on commas fixes this — keep it. Alternatively store as `str` and split in `main.py`; the validator approach is preferred so the typed field stays `list[str]`.
- **Fail-fast semantics:** required fields have no default, so `Settings()` raises `pydantic.ValidationError` listing the missing keys when they're absent from both env and `.env`. Because `config.py` builds a module-level `settings` singleton at import, the fail-fast test must patch the environment (e.g. `monkeypatch.delenv(...)` for the two keys) and construct `Settings()` directly, not import the singleton.
- **CI env for pytest:** importing `app.main` triggers `create_app()` → touches `settings`, so the backend CI job (and local `pytest`) needs the two required keys present. Provide them as dummy values via a `tests/conftest.py` that sets `os.environ` defaults before import **and** as job-level `env:` in CI, so `pytest` passes on a fresh clone without a real `.env`.
- **ESLint flat config:** the current Vite `react-ts` template already emits `eslint.config.js` (flat). Keep that format; do not create a legacy `.eslintrc`.
- **Determinism/idempotency:** N/A for F1 (no graph nodes / interrupts).
- **No secrets committed** (§9): only `.env.example` with dummies; `.env` is gitignored.

### Test plan

- **backend `tests/test_health.py`** — FastAPI `TestClient(create_app())`: `GET /api/health` → `200` and body `{"status": "ok"}`.
- **backend `tests/test_config.py`** — (a) with the two required keys set (via conftest/monkeypatch), `Settings()` constructs and `CHECKPOINT_BACKEND == "sqlite"`, `CORS_ORIGINS == ["http://localhost:5173"]` by default; (b) `CORS_ORIGINS="http://a.com,http://b.com"` parses to a 2-item list; (c) **fail-fast:** with `OPENAI_API_KEY` (and the other required key) removed from the env, `Settings()` raises `pydantic.ValidationError`.
- **frontend `src/App.test.tsx`** — render `<App/>` with `@testing-library/react`; assert the "Atlas" wordmark and both nav labels ("New Run", "History") are in the document.

### Verify

```bash
# DB
docker compose up -d postgres
docker compose ps            # postgres shows "healthy"

# backend (from backend/)
cp ../.env.example ../.env    # or export the 2 required keys
uv sync
uv run ruff check . && uv run mypy app && uv run pytest
uv run uvicorn app.main:app --reload &
curl -s localhost:8000/api/health      # → {"status":"ok"}

# frontend (from frontend/)
npm install
npm run lint && npm run typecheck && npm run test
npm run dev                   # open http://localhost:5173 → dark shell, "Atlas" sidebar, New Run / History nav
```

Expected: health returns `{"status":"ok"}`; the dev server shows the dark (`#0B0E14`) shell with the Atlas sidebar and Inter font; all lint/typecheck/test commands exit 0; `docker compose ps` reports Postgres healthy.

### Acceptance criteria

- [ ] Repo tree matches §4 (every listed backend + frontend path exists, stubs where later features fill in), plus root `docker-compose.yml`, `.github/workflows/ci.yml`, `.env.example`.
- [ ] `GET /api/health` returns `200 {"status":"ok"}` (`test_health` passes).
- [ ] `Settings` fails fast with a clear `ValidationError` naming the missing key when a required key is absent (`test_config` fail-fast case passes); defaults resolve as specified; `CORS_ORIGINS` parses comma-separated env values.
- [ ] `npm run dev` renders the dark shell using §8 tokens (background `#0B0E14`, Inter loaded) with the "Atlas" wordmark and New Run / History nav; no default Vite splash (`App.test.tsx` passes).
- [ ] `docker compose up -d postgres` brings up `postgres:16` with a passing healthcheck and a named volume.
- [ ] CI (`ci.yml`) has backend (ruff + mypy + pytest) and frontend (eslint + tsc + vitest) jobs on PR and push to `main`, and passes green on a fresh clone (no real secrets required — dummy env in CI).
- [ ] No `.env` committed; `.env.example` contains every step-2 var with dummy values.
