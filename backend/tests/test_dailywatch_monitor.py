"""Daily Watch campaign monitor: isolate via Monitor button, auto-clear when a
new day's upload shows the campaign aligned to goal ACoS."""
from datetime import date
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, DailyWatchFact, WatchedCampaign
from app.pipeline import dailywatch as dw


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _day(db, d, cid, name, spend, sales, orders=1):
    db.add(DailyWatchFact(date=d, campaign_id=cid, name=name, impressions=1000,
                          clicks=50, spend=spend, sales=sales, orders=orders))
    db.commit()


def test_monitor_add_and_idempotent(db):
    _day(db, date(2026, 7, 19), "111", "bleeder", 50.0, 100.0)   # 50% ACoS
    r = dw.monitor(db, "111", "bleeder")
    assert r["added"] is True
    assert dw.monitor(db, "111", "bleeder")["added"] is False    # already active
    m = dw.monitors(db, 0.25)
    assert len(m["active"]) == 1
    w = m["active"][0]
    assert w["added_acos"] == 50.0 and w["aligned"] is False


def test_upload_clears_aligned_watch(db):
    _day(db, date(2026, 7, 19), "111", "bleeder", 50.0, 100.0)   # 50% — over 25% goal
    dw.monitor(db, "111", "bleeder")
    # next day upload: aligned (20% ACoS)
    _day(db, date(2026, 7, 20), "111", "bleeder", 20.0, 100.0)
    cleared = dw.evaluate_monitors(db, date(2026, 7, 20), 0.25)
    assert len(cleared) == 1 and cleared[0]["campaign_id"] == "111"
    m = dw.monitors(db, 0.25)
    assert m["active"] == []
    assert m["cleared"][0]["cleared_acos"] == 20.0


def test_not_cleared_when_over_goal_or_no_sales(db):
    _day(db, date(2026, 7, 19), "111", "still bad", 50.0, 100.0)
    _day(db, date(2026, 7, 19), "222", "no sales", 30.0, 0.0, orders=0)
    dw.monitor(db, "111", "still bad")
    dw.monitor(db, "222", "no sales")
    # next day: 111 still 40% (over goal), 222 spends with zero sales (acos None)
    _day(db, date(2026, 7, 20), "111", "still bad", 40.0, 100.0)
    _day(db, date(2026, 7, 20), "222", "no sales", 30.0, 0.0, orders=0)
    assert dw.evaluate_monitors(db, date(2026, 7, 20), 0.25) == []
    assert len(dw.monitors(db, 0.25)["active"]) == 2


def test_missing_campaign_day_keeps_watch(db):
    _day(db, date(2026, 7, 19), "111", "gone", 50.0, 100.0)
    dw.monitor(db, "111", "gone")
    _day(db, date(2026, 7, 20), "999", "other", 10.0, 100.0)     # 111 absent that day
    assert dw.evaluate_monitors(db, date(2026, 7, 20), 0.25) == []
    assert len(dw.monitors(db, 0.25)["active"]) == 1


def test_unmonitor(db):
    _day(db, date(2026, 7, 19), "111", "x", 50.0, 100.0)
    dw.monitor(db, "111", "x")
    assert dw.unmonitor(db, "111") == 1
    assert dw.monitors(db, 0.25)["active"] == []
