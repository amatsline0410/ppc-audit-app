"""Per-audit checklist. Auto items are computed from real DB state (so a step
ticks itself the moment you do it — e.g. upload a file); manual items are
user-added tasks persisted per audit.
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from sqlalchemy import func
from .. import models as md


def _count(db: Session, model) -> int:
    return db.query(func.count()).select_from(model).scalar() or 0


def status(db: Session, meta: dict) -> dict:
    """meta = project meta dict (for goal-ACoS detection)."""
    from . import benchmark as bench_stage
    perf = _count(db, md.FactPerformance)
    bench = len(bench_stage._merged_rows(db))   # store-wide benchmark counts too
    changes = _count(db, md.ChangeLog)

    auto = [
        {"key": "bulk", "label": "Upload SP bulk file", "done": perf > 0,
         "hint": "PPC Audit → drop the bulk .xlsx"},
        {"key": "goal", "label": "Set Goal ACoS for this audit", "done": "acos_threshold" in meta,
         "hint": "sidebar / Goal ACoS control"},
        {"key": "benchmark", "label": "Set break-even benchmark", "done": bench > 0,
         "hint": "Uploads → Product Benchmark"},
        {"key": "export", "label": "Export a bulk action", "done": changes > 0,
         "hint": "any engine → download bulk file (logged)"},
    ]
    manual = [{"id": c.id, "text": c.text, "done": bool(c.done)}
              for c in db.query(md.ChecklistItem).order_by(md.ChecklistItem.created).all()]

    items = auto + manual
    done = sum(1 for i in items if i["done"])
    return {"auto": auto, "manual": manual,
            "progress": {"done": done, "total": len(items)}}


def add(db: Session, text: str) -> dict:
    item = md.ChecklistItem(text=text.strip(), done=False)
    db.add(item); db.commit()
    return {"id": item.id, "text": item.text, "done": False}


def toggle(db: Session, item_id: int, done: bool) -> bool:
    item = db.get(md.ChecklistItem, item_id)
    if not item:
        return False
    item.done = done
    db.commit()
    return True


def remove(db: Session, item_id: int) -> bool:
    item = db.get(md.ChecklistItem, item_id)
    if not item:
        return False
    db.delete(item); db.commit()
    return True
