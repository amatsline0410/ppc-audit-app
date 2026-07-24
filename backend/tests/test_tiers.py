"""Tier Router: band boundaries + catalog-driven suggestion."""
from app.pipeline import tiers


def test_tier_boundaries():
    assert tiers.tier_for(0) is None
    assert tiers.tier_for(-3) is None
    for n, want in [(1, 1), (5, 1), (6, 2), (20, 2), (21, 3), (50, 3),
                    (51, 4), (100, 4), (101, 5), (500, 5), (501, 6),
                    (1000, 6), (1001, 7), (25000, 7)]:
        assert tiers.tier_for(n)["tier"] == want, n


def test_tiers_cover_all_counts_without_gaps():
    prev_hi = 0
    for t in tiers.TIERS:
        assert t["lo"] == prev_hi + 1
        prev_hi = t["hi"] if t["hi"] is not None else prev_hi
    assert tiers.TIERS[-1]["hi"] is None


def test_suggest_counts_parents_plus_standalone(monkeypatch):
    # 2 parents + 4 children + 3 standalone = 5 advertisable units -> Tier 1;
    # children never add structure. 3 product types -> category-portfolio note.
    prods = {}
    for i in range(2):
        prods[f"P{i}"] = {"parentage": "parent", "product_type": f"cat{i}"}
    for i in range(4):
        prods[f"C{i}"] = {"parentage": "child", "parent_sku": f"P{i % 2}", "product_type": f"cat{i % 2}"}
    for i in range(3):
        prods[f"S{i}"] = {"parentage": "", "product_type": "cat2"}
    monkeypatch.setattr(tiers.cat, "read_catalog", lambda sid: {"products": prods})

    class FakeDB:
        info = {"store": "s1"}
    out = tiers.suggest(FakeDB())
    assert out["asin_count"] == 5
    assert out["source"] == "catalog"
    assert out["tier"]["tier"] == 1
    assert out["counts"] == {"units": 5, "parents": 2, "children": 4,
                             "standalone": 3, "total": 9, "categories": 3}
    assert any("Portfolio per" in n for n in out["notes"])
    assert any("child variations" in n for n in out["notes"])


def test_suggest_empty_catalog_no_db():
    # no catalog + no db -> nothing counted, no tier, ladder still returned
    out = tiers.suggest(None)
    assert out["asin_count"] == 0
    assert out["tier"] is None
    assert len(out["tiers"]) == 7
