"""Keyword intake into a Listing Optimizer project (from mined/harvest/n-gram)
+ the AI relevancy prompt built from current vs proposed listing copy."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models as md
from app.pipeline import tracker as tk


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


@pytest.fixture()
def project(db):
    return tk.create_project(db, "Ice Sleeve", "B0TEST0001")["project_id"]


def test_add_keywords_dedupes_and_backfills(db, project):
    r = tk.add_keywords(db, project, [
        {"keyword": "ice sleeve", "search_volume": 1200, "source": "cerebro"},
        {"keyword": "Ice Sleeve"},                     # dup (case-insensitive)
        {"keyword": "pitcher ice pack"},               # no SV yet
        {"keyword": ""},                               # ignored
    ], source="harvest")
    assert r["added"] == 2 and r["duplicates"] == 1 and r["total"] == 2

    # second push: dup backfills the missing search volume, keeps existing rows
    r2 = tk.add_keywords(db, project, [
        {"keyword": "PITCHER ICE PACK", "search_volume": 800, "source": "sqp"},
        {"keyword": "arm ice wrap"},
    ])
    assert r2["added"] == 1 and r2["duplicates"] == 1 and r2["total"] == 3
    kw = db.query(md.TrackedKeyword).filter(md.TrackedKeyword.keyword == "pitcher ice pack").one()
    assert kw.search_volume == 800
    assert kw.source == "harvest"      # original source kept


def test_add_keywords_unknown_project(db):
    with pytest.raises(ValueError):
        tk.add_keywords(db, 999, [{"keyword": "x"}])


def test_relevancy_prompt_covers_current_and_proposed(db, project):
    tk.add_keywords(db, project, [{"keyword": "ice sleeve", "search_volume": 1200}])
    db.add(md.ListingCopy(project_id=project, variant="current", element="title",
                          text="Pro Ice Pitcher Sleeve for Baseball"))
    db.add(md.ListingCopy(project_id=project, variant="proposed", element="title",
                          text="Ice Sleeve Arm Wrap, Youth Pitchers"))
    db.add(md.ListingCopy(project_id=project, variant="current", element="bullet_points",
                          text="Keeps arm cold after games"))
    db.commit()

    out = tk.relevancy_prompt(db, project)
    p = out["prompt"]
    assert out["keywords"] == 1 and out["truncated"] == 0
    assert "B0TEST0001" in p
    assert "CURRENT LISTING DATA" in p and "PROPOSED LISTING DATA" in p
    assert "Pro Ice Pitcher Sleeve for Baseball" in p
    assert "Ice Sleeve Arm Wrap, Youth Pitchers" in p
    assert "ice sleeve (search volume 1,200)" in p
    assert "| Keyword | Relevancy (1-5) | In Current? | In Proposed? | Best Placement | Reason |" in p
    # empty elements are labeled, not dropped
    assert "Backend Search Terms:\n(empty)" in p


def test_primary_seo_before_after_push(db, project):
    from datetime import date
    # primary competitor row + one ranked keyword -> indexed 100%
    db.add(md.TrackedCompetitor(project_id=project, asin="B0TEST0001", is_primary=True, active=True))
    db.commit()
    tk.add_keywords(db, project, [{"keyword": "ice sleeve"}])
    kid = db.query(md.TrackedKeyword).filter(md.TrackedKeyword.keyword == "ice sleeve").one().id
    db.add(md.RankSnapshot(keyword_id=kid, asin="B0TEST0001",
                           checked_at=date(2026, 7, 1), organic_rank=5))
    db.commit()

    before = tk.primary_seo(db, project)
    assert before["indexed"] == 1.0 and before["tracked"] == 1 and before["page1"] == 1

    # push 3 new (unranked) keywords -> denominator grows, indexed drops to 25%
    tk.add_keywords(db, project, [{"keyword": f"kw {i}"} for i in range(3)])
    after = tk.primary_seo(db, project)
    assert after["tracked"] == 4 and after["ranked"] == 1
    assert after["indexed"] == 0.25
    assert after["page1"] == before["page1"]      # rank counts untouched by the push
