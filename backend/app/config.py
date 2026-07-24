"""Central settings. Everything tunable lives here or via env vars.

The headline knob is TARGET_ACOS — the goal threshold. It has a default here,
but every audit/automate request can override it (so the frontend input wins).
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field, asdict


@dataclass
class Thresholds:
    """Flag thresholds. All overridable per-request from the API/frontend."""
    target_acos: float = float(os.getenv("TARGET_ACOS", "0.25"))   # goal ACoS (headline knob)
    min_spend: float = float(os.getenv("MIN_SPEND", "5.0"))        # ignore noise below this $ spend
    min_clicks: int = int(os.getenv("MIN_CLICKS", "5"))           # min clicks for CVR/bid significance
    min_impressions: int = int(os.getenv("MIN_IMPR", "1000"))     # min impressions for CTR significance
    low_ctr: float = float(os.getenv("LOW_CTR", "0.0025"))        # 0.25%
    low_cvr: float = float(os.getenv("LOW_CVR", "0.05"))          # 5%
    overbid_multiplier: float = float(os.getenv("OVERBID_MULT", "1.5"))
    # scale-winners (offensive): raise bid when ACoS sits well under goal with real orders
    scale_min_orders: int = int(os.getenv("SCALE_MIN_ORDERS", "3"))     # min orders to trust the signal
    scale_acos_frac: float = float(os.getenv("SCALE_ACOS_FRAC", "0.75"))  # only scale if ACoS <= goal*frac
    # bid-change safety caps (one pass)
    max_bid_cut: float = float(os.getenv("MAX_BID_CUT", "0.50"))  # never cut more than 50% in one pass
    max_bid_up: float = float(os.getenv("MAX_BID_UP", "1.25"))    # never raise more than 25%
    bid_floor: float = float(os.getenv("BID_FLOOR", "0.20"))

    def merged(self, **overrides) -> "Thresholds":
        """Return a copy with non-None overrides applied (request wins over default)."""
        data = asdict(self)
        for k, v in overrides.items():
            if v is not None and k in data:
                data[k] = v
        return Thresholds(**data)


@dataclass
class Settings:
    db_url: str = os.getenv("DB_URL", "sqlite:///./ppc_audit.db")
    seed_file: str = os.getenv("SEED_FILE", "./data/zvalves_bulk.xlsx")
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"])

    # ---- LLM (all optional; default provider 'none' = app runs fully without any LLM) ----
    llm_provider: str = os.getenv("LLM_PROVIDER", "none")   # none | ollama | lmstudio | openclaw | openai_compat
    llm_model: str = os.getenv("LLM_MODEL", "llama3.1")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")        # provider default used if blank
    llm_use_langchain: bool = os.getenv("LLM_USE_LANGCHAIN", "false").lower() == "true"
    llm_timeout: int = int(os.getenv("LLM_TIMEOUT", "120"))


settings = Settings()
default_thresholds = Thresholds()
