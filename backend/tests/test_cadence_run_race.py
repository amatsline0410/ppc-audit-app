"""Two concurrent opens of the same (year, month, audit_type) cadence run must not
500: the flag audit inside get_or_create_run is slow, so both requests can pass
the initial SELECT and race the INSERT — UNIQUE keeps one, the loser must return
the winner's row instead of raising IntegrityError."""
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models as md
from app.pipeline import cadence as cad
from app.pipeline import audit as audit_stage, sales as sales_stage


def test_run_create_race_returns_winner(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s1, s2 = S(), S()

    monkeypatch.setattr(audit_stage, "active_snapshot", lambda db: date(2026, 7, 1))
    monkeypatch.setattr(sales_stage, "total_ad", lambda db: {"spend": 1.0, "sales": 2.0})

    def audit_with_competitor(db, th):
        # while "our" request is still auditing, a concurrent request wins the insert
        s2.add(md.CadenceRun(year=2026, month=7, audit_type="full_month",
                             flags=99, ad_spend=9.0, ad_sales=18.0))
        s2.commit()
        return []

    monkeypatch.setattr(audit_stage, "audit", audit_with_competitor)

    out = cad.get_or_create_run(s1, 2026, 7, "full_month", 0.3)

    assert out is not None and out["flags"] == 99          # winner's row came back
    assert s2.query(md.CadenceRun).count() == 1            # no duplicate row

    s1.close(); s2.close()
