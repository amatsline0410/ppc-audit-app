# PPC Audit Console

Turn Amazon Sponsored Products **bulk file** into audit, ASIN-rooted tree, ready-to-upload **automation bulk file** — with live **goal-ACoS** knob, optional **local-LLM** narration (Ollama / LM Studio / OpenClaw / any OpenAI-compatible server).

```
bulk .xlsx ─▶ ingest ─▶ split ─▶ clean ─▶ load(SQLite) ─▶ audit(flags) ─▶ automate(bulk file)
                                                              │
                                              React + Tailwind console (target-ACoS slider)
                                                              │
                                              optional: local LLM narration / client email
```

## Stack
- **Backend:** FastAPI + SQLAlchemy + Pydantic + pandas/openpyxl, SQLite (Postgres-portable schema).
- **Frontend:** React (Vite) + Tailwind, dark "ops console" theme.
- **LLM layer:** provider-agnostic adapter; default `none` (app 100% functional without LLM).

## Quick start

Runs the same on Linux/macOS and Windows 10/11. Needs Python 3.11+, Node 18+.

### 1. Backend — Linux / macOS
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run.sh                        # copies .env, seeds on first run, serves :8000
```

### 1. Backend — Windows
```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
run.bat                         :: or  .\run.ps1  from PowerShell
```

If PowerShell blocks `run.ps1` ("running scripts is disabled"), either use `run.bat`
or allow local scripts once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

The run scripts activate `backend/.venv` themselves when no venv is already active,
so the venv only has to be *created* once — you don't have to activate it every time.

Doing it by hand instead of via the run script:
```bash
cp .env.example .env            # Windows: copy .env.example .env
python -m app.main              # one-time: seed the bundled ZValves bulk file
uvicorn app.main:app --reload   # serve on http://localhost:8000  (docs at /docs)
```

First login: **SAdmin** / **RootPass** (override with `SUPERUSER_NAME` / `SUPERUSER_PASS`).

### 2. Frontend
```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173  (proxies /api -> :8000)
```

Open console, drag in bulk `.xlsx`, slide **Goal ACoS**, review flags, tick wanted bid changes, download **automation bulk file**, re-upload to Amazon.

## The goal-ACoS knob
Target ACoS threshold flows through three layers, request always wins:
1. `config.py` default (`TARGET_ACOS`, env-overridable)
2. API query param: `POST /upload?target_acos=`, `GET /audit?target_acos=`
3. Frontend slider → re-runs audit live.

Drives `HIGH_ACOS` flag + every target-ACoS bid recommendation:
`new_bid = bid × (target ÷ observed_acos)`, capped **−50% / +25%** per pass, floored.

## Enabling a local LLM (optional)
Narration (analyst summary or client email) additive. Turn on in `.env`:
```bash
LLM_PROVIDER=ollama          # or lmstudio | openclaw | openai_compat
LLM_MODEL=llama3.1
# LLM_BASE_URL=              # blank = provider default localhost
# LLM_USE_LANGCHAIN=true     # route through LangChain (pip install langchain-core)
```
Restart backend. `GET /config` reports provider reachability; UI shows ●/○ status dot. Provider down or dependency missing → app degrades graceful — audit + bulk files keep working.

## API
| Method | Path | Purpose |
|---|---|---|
| POST | `/upload?target_acos=&snapshot_date=` | bulk `.xlsx` → run pipeline → summary |
| GET | `/asins?target_acos=` | ASINs with roll-up metrics + flag counts |
| GET | `/asins/{asin}/tree` | full ASIN-rooted tree |
| GET | `/audit?target_acos=&flag=&severity=` | flags |
| POST | `/automate` | chosen flags → bulk upload file |
| POST | `/narrate` | flags → LLM summary/email |
| GET | `/config` | defaults + LLM status |

## Tests
```bash
cd backend && pytest -q        # pure metrics + rules + threshold-override behavior
```

## Notes / v1 scope
- One bulk file in, manual re-upload out (no Amazon Ads API).
- `fact_performance` snapshot-stamped → re-upload weekly, build trends + ML features.
- Money stored as float for v1 (use Decimal/cents if this ever bills).