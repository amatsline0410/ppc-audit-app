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

### 1. Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # tweak TARGET_ACOS / LLM_PROVIDER if you want

python -m app.main              # one-time: seed the bundled ZValves bulk file
uvicorn app.main:app --reload   # serve on http://localhost:8000  (docs at /docs)
```

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