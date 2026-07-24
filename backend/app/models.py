"""Star-ish schema = the ERD from the skill.

Dimensions hold structure (slow-changing). One fact table holds raw metrics
stamped with snapshot_date (grows each upload -> enables trends + ML features).

RULE: never store derived rates (ACoS/CTR/...). Compute them in metrics.py.
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import (Column, String, Float, Integer, Boolean, Date, DateTime, ForeignKey, Index)
from sqlalchemy.orm import relationship
from .database import Base


class DimProduct(Base):
    __tablename__ = "dim_product"
    asin = Column(String, primary_key=True)
    sku = Column(String, nullable=True)
    title = Column(String, nullable=True)
    break_even_acos = Column(Float, nullable=True)  # per-product margin override (optional)
    ads = relationship("DimAd", back_populates="product",
                       cascade="all, delete-orphan", passive_deletes=True)


class DimCampaign(Base):
    __tablename__ = "dim_campaign"
    campaign_id = Column(String, primary_key=True)
    name = Column(String)
    targeting_type = Column(String, nullable=True)   # auto | manual
    state = Column(String, nullable=True)            # enabled | paused | archived
    daily_budget = Column(Float, nullable=True)
    portfolio_id = Column(String, nullable=True)
    ad_groups = relationship("DimAdGroup", back_populates="campaign",
                             cascade="all, delete-orphan", passive_deletes=True)


class DimAdGroup(Base):
    __tablename__ = "dim_ad_group"
    ad_group_id = Column(String, primary_key=True)
    campaign_id = Column(String, ForeignKey("dim_campaign.campaign_id", ondelete="CASCADE"))
    name = Column(String, nullable=True)
    default_bid = Column(Float, nullable=True)
    state = Column(String, nullable=True)
    campaign = relationship("DimCampaign", back_populates="ad_groups")
    ads = relationship("DimAd", back_populates="ad_group",
                       cascade="all, delete-orphan", passive_deletes=True)
    targets = relationship("DimTarget", back_populates="ad_group",
                           cascade="all, delete-orphan", passive_deletes=True)


class DimAd(Base):
    __tablename__ = "dim_ad"
    ad_id = Column(String, primary_key=True)
    ad_group_id = Column(String, ForeignKey("dim_ad_group.ad_group_id", ondelete="CASCADE"))
    asin = Column(String, ForeignKey("dim_product.asin", ondelete="CASCADE"), nullable=True)
    sku = Column(String, nullable=True)
    state = Column(String, nullable=True)
    ad_group = relationship("DimAdGroup", back_populates="ads")
    product = relationship("DimProduct", back_populates="ads")


class DimTarget(Base):
    __tablename__ = "dim_target"
    target_id = Column(String, primary_key=True)
    ad_group_id = Column(String, ForeignKey("dim_ad_group.ad_group_id", ondelete="CASCADE"))
    target_type = Column(String)                 # keyword | product_target
    keyword_text = Column(String, nullable=True)
    match_type = Column(String, nullable=True)   # exact | phrase | broad
    expression = Column(String, nullable=True)   # product target expression
    bid = Column(Float, nullable=True)
    state = Column(String, nullable=True)
    ad_group = relationship("DimAdGroup", back_populates="targets")


class FactPerformance(Base):
    __tablename__ = "fact_performance"
    perf_id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String)   # campaign | ad_group | ad | target
    entity_id = Column(String)
    snapshot_date = Column(Date)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    sales = Column(Float, default=0.0)
    orders = Column(Integer, default=0)
    units = Column(Integer, default=0)


class FactDaily(Base):
    """One row per calendar day for the Daily SALES & PPC Tracker (Monitoring).

    Consolidates two daily Amazon exports keyed by Date: the Business Report
    (Sales & Traffic by Date) + the Sponsored Products campaign report (aggregated
    to a daily total). Upserted by `date` so re-ingesting a file never duplicates,
    and a business-only or ppc-only upload just fills its own columns (the rest stay
    NULL -> rendered as "-"). Percent fields are stored as plain numbers (24.03, not
    0.2403) — consistent everywhere. Derived values (deltas, rolling avgs, alerts,
    health score) are computed at read time in monitoring.py, never stored.
    """
    __tablename__ = "fact_daily"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, unique=True, index=True, nullable=False)
    # --- Business Report: sales & traffic ---
    ordered_sales = Column(Float, nullable=True)        # Ordered Product Sales ($)
    units_ordered = Column(Integer, nullable=True)
    total_order_items = Column(Integer, nullable=True)
    asp = Column(Float, nullable=True)                  # Average Selling Price ($)
    page_views = Column(Integer, nullable=True)
    sessions = Column(Integer, nullable=True)
    buy_box_pct = Column(Float, nullable=True)          # Featured Offer (Buy Box) %
    unit_session_pct = Column(Float, nullable=True)     # = CVR (primary conversion metric)
    units_refunded = Column(Integer, nullable=True)
    refund_rate = Column(Float, nullable=True)          # %
    shipped_sales = Column(Float, nullable=True)
    units_shipped = Column(Integer, nullable=True)
    orders_shipped = Column(Integer, nullable=True)
    # --- B2B twins (for the B2B vs B2C split) ---
    ordered_sales_b2b = Column(Float, nullable=True)
    units_ordered_b2b = Column(Integer, nullable=True)
    unit_session_pct_b2b = Column(Float, nullable=True)
    # --- Sponsored Products, aggregated to a daily total ---
    ppc_impressions = Column(Integer, nullable=True)
    ppc_clicks = Column(Integer, nullable=True)
    ppc_spend = Column(Float, nullable=True)
    ppc_sales = Column(Float, nullable=True)
    ppc_orders = Column(Integer, nullable=True)


class DailyWatchFact(Base):
    """Daily Watch's OWN time-series table — deliberately separate from
    FactPerformance so daily spike-tracking never shifts the audit's 'latest
    snapshot' that the Weekly/Mid/Full/Pause cadences read. One row per campaign
    per day; upserted by (date, campaign_id) so re-uploading a day replaces it.
    Raw counts only — deltas/anomalies are computed at read time in dailywatch.py."""
    __tablename__ = "daily_watch_fact"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    campaign_id = Column(String, nullable=False)
    name = Column(String, nullable=True)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    sales = Column(Float, default=0.0)
    orders = Column(Integer, default=0)
    units = Column(Integer, default=0)
    __table_args__ = (Index("ix_dwf_day_camp", "date", "campaign_id", unique=True),)


class WatchedCampaign(Base):
    """Daily Watch monitor list — campaigns the user flagged with the Monitor
    button. Lives in the SAME per-cadence db as DailyWatchFact (daily file), so
    the watchlist is isolated to the Daily cadence. One ACTIVE row per campaign;
    each new daily upload auto-clears watches whose day ACoS is at/under the
    goal (status -> 'cleared', kept for history)."""
    __tablename__ = "watched_campaign"
    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=True)
    status = Column(String, default="active")   # active | cleared
    added_date = Column(Date, nullable=True)    # latest uploaded day when added
    added_acos = Column(Float, nullable=True)   # % number (24.03), like Daily Watch KPIs
    cleared_date = Column(Date, nullable=True)
    cleared_acos = Column(Float, nullable=True)


class WeeklyTermFact(Base):
    """Weekly Optimization's OWN table — one row per line of the bulk's SP Search
    Term Report. Carries the *real entity IDs* the report exposes (Campaign / Ad
    Group / Keyword / Product Targeting ID) plus the customer search term and raw
    counts, so the Weekly cadence can emit bid-update + harvest bulk rows that point
    at exactly the right Amazon entities. Deliberately separate from FactPerformance
    so a Weekly bulk only ever drives the Weekly cadence. Tagged by `week` (Week 1..N,
    calendar-style panels) and upserted per week — re-uploading a week replaces it, so
    weeks accumulate into a trend exactly like Daily Watch accumulates days."""
    __tablename__ = "weekly_term_fact"
    id = Column(Integer, primary_key=True, autoincrement=True)
    week = Column(Integer, nullable=False, default=1, index=True)   # Week 1..N panel
    campaign_id = Column(String, nullable=False)
    ad_group_id = Column(String, nullable=False)
    keyword_id = Column(String, nullable=True)
    product_targeting_id = Column(String, nullable=True)
    campaign_name = Column(String, nullable=True)
    ad_group_name = Column(String, nullable=True)
    state = Column(String, nullable=True)
    bid = Column(Float, nullable=True)
    keyword_text = Column(String, nullable=True)
    match_type = Column(String, nullable=True)
    expression = Column(String, nullable=True)        # product targeting expression
    is_auto = Column(Boolean, default=False)          # auto-campaign clause row?
    search_term = Column(String, nullable=False)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    sales = Column(Float, default=0.0)
    orders = Column(Integer, default=0)
    units = Column(Integer, default=0)
    __table_args__ = (Index("ix_wtf_week_camp", "week", "campaign_id"),
                      Index("ix_wtf_adgroup", "ad_group_id"))


class MidMonthTermFact(Base):
    """Mid-Month Check's OWN table — same shape as WeeklyTermFact (one row per SP
    Search Term Report line, real entity IDs as exact strings) but a **single
    snapshot** (one panel, no weeks): replaced wholesale on each upload. Drives the
    Mid-Month cadence's bid-adjustment + heavy-negative-targeting plan. Separate
    table so a Mid-Month bulk only ever drives the Mid-Month cadence."""
    __tablename__ = "mid_month_term_fact"
    id = Column(Integer, primary_key=True, autoincrement=True)
    period = Column(Integer, nullable=False, default=0, index=True)   # 0 = current, 1 = previous (for compare)
    campaign_id = Column(String, nullable=False)
    ad_group_id = Column(String, nullable=False)
    keyword_id = Column(String, nullable=True)
    product_targeting_id = Column(String, nullable=True)
    campaign_name = Column(String, nullable=True)
    ad_group_name = Column(String, nullable=True)
    state = Column(String, nullable=True)
    bid = Column(Float, nullable=True)
    keyword_text = Column(String, nullable=True)
    match_type = Column(String, nullable=True)
    expression = Column(String, nullable=True)
    is_auto = Column(Boolean, default=False)
    search_term = Column(String, nullable=False)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    sales = Column(Float, default=0.0)
    orders = Column(Integer, default=0)
    units = Column(Integer, default=0)
    __table_args__ = (Index("ix_mmtf_camp", "campaign_id"),
                      Index("ix_mmtf_adgroup", "ad_group_id"))


class FullMonthTermFact(Base):
    """Full Month Audit's OWN table — same shape as MidMonthTermFact (one row per SP
    Search Term Report line, real entity IDs as exact strings), single snapshot
    replaced per upload. Drives the Full Month cadence's **full optimization** plan
    (bid adjustments + harvest promote + negatives + bleeders, all at once).
    Separate table so a Full Month bulk only ever drives the Full Month cadence."""
    __tablename__ = "full_month_term_fact"
    id = Column(Integer, primary_key=True, autoincrement=True)
    period = Column(Integer, nullable=False, default=0, index=True)   # 0 = current, 1 = previous (for compare)
    campaign_id = Column(String, nullable=False)
    ad_group_id = Column(String, nullable=False)
    keyword_id = Column(String, nullable=True)
    product_targeting_id = Column(String, nullable=True)
    campaign_name = Column(String, nullable=True)
    ad_group_name = Column(String, nullable=True)
    state = Column(String, nullable=True)
    bid = Column(Float, nullable=True)
    keyword_text = Column(String, nullable=True)
    match_type = Column(String, nullable=True)
    expression = Column(String, nullable=True)
    is_auto = Column(Boolean, default=False)
    search_term = Column(String, nullable=False)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    sales = Column(Float, default=0.0)
    orders = Column(Integer, default=0)
    units = Column(Integer, default=0)
    __table_args__ = (Index("ix_fmtf_camp", "campaign_id"),
                      Index("ix_fmtf_adgroup", "ad_group_id"))


class PauseScaleTermFact(Base):
    """Pause/Scale Audit's OWN table — same shape as the other cadence STR tables
    (one row per SP Search Term Report line, real entity IDs as exact strings),
    single 60-day snapshot replaced per upload. Drives the cut/scale decisions
    (pause dead targets/campaigns, scale winners). Separate table so a Pause/Scale
    bulk only ever drives the Pause/Scale cadence."""
    __tablename__ = "pause_scale_term_fact"
    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(String, nullable=False)
    ad_group_id = Column(String, nullable=False)
    keyword_id = Column(String, nullable=True)
    product_targeting_id = Column(String, nullable=True)
    campaign_name = Column(String, nullable=True)
    ad_group_name = Column(String, nullable=True)
    state = Column(String, nullable=True)
    bid = Column(Float, nullable=True)
    keyword_text = Column(String, nullable=True)
    match_type = Column(String, nullable=True)
    expression = Column(String, nullable=True)
    is_auto = Column(Boolean, default=False)
    search_term = Column(String, nullable=False)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    sales = Column(Float, default=0.0)
    orders = Column(Integer, default=0)
    units = Column(Integer, default=0)
    __table_args__ = (Index("ix_pstf_camp", "campaign_id"),
                      Index("ix_pstf_adgroup", "ad_group_id"))


class ProductAdFact(Base):
    """Product Ads' OWN table — **separate from the PPC Audit star schema**
    (DimAd/FactPerformance). One row per Product Ad line of the bulk's Sponsored
    Products Campaigns sheet (Entity='Product Ad'): ASIN + SKU + the real Ad/Campaign
    /Ad-Group IDs (exact strings) and the row's own metrics. Replaced wholesale on
    each upload. Lets the Product Ads tab run off its own dedicated bulk upload,
    independent of the audit pipeline."""
    __tablename__ = "product_ad_fact"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ad_id = Column(String, nullable=True)
    asin = Column(String, nullable=True, index=True)
    sku = Column(String, nullable=True)
    campaign_id = Column(String, nullable=True)
    campaign_name = Column(String, nullable=True)
    ad_group_id = Column(String, nullable=True)
    ad_group_name = Column(String, nullable=True)
    state = Column(String, nullable=True)
    # this ad's campaign targeting kind, classified from the bulk's Campaign
    # "Targeting Type" + Keyword / Product Targeting entity rows:
    # 'auto' | 'keyword' | 'product' | 'manual' (manual, type unknown) | None
    campaign_type = Column(String, nullable=True)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    sales = Column(Float, default=0.0)
    orders = Column(Integer, default=0)
    units = Column(Integer, default=0)
    __table_args__ = (Index("ix_paf_asin", "asin"),)


class WaterfallRun(Base):
    """One generated Waterfall Restructure plan (RAF funnel). Lives in the BASE
    project db (restructure is account-level, not per-cadence). Items live in
    WaterfallItem; status advances as the user marks each phase applied."""
    __tablename__ = "waterfall_run"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="draft")   # draft|a_applied|b_applied|c_applied|d_applied|done
    naming_template = Column(String, nullable=True)
    heroes_json = Column(String, nullable=True)    # JSON list of hero SKUs
    params_json = Column(String, nullable=True)    # JSON: thresholds used + day-0 benchmark rows


class WaterfallItem(Base):
    """One planned Waterfall action (rename / bid cut / create / negative / pause),
    grouped by phase A-D. payload_json carries everything the bulk emitter needs."""
    __tablename__ = "waterfall_item"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("waterfall_run.id", ondelete="CASCADE"), index=True)
    phase = Column(String, nullable=False)     # 'A'|'B'|'C'|'D'
    action = Column(String, nullable=False)    # rename|rename_adgroup|bid_cut|create_campaign|
                                               # create_adgroup|create_ad|create_keyword|create_pt|
                                               # negative|pause
    sku = Column(String, nullable=True)
    slot = Column(String, nullable=True)       # AT|KWT-BROAD|KWT-PHRASE|KWT-EXACT|PT
    campaign_id = Column(String, nullable=True)   # exact string (real ID or temp name for creates)
    ad_group_id = Column(String, nullable=True)
    target_id = Column(String, nullable=True)
    payload_json = Column(String, nullable=True)
    selected = Column(Boolean, default=True)
    __table_args__ = (Index("ix_wfi_run_phase", "run_id", "phase"),)


class BidLedger(Base):
    """Effective-bid overlay: every exported bid/state change is recorded here so
    the NEXT export computes from what was already exported, not the stale snapshot
    (consecutive exports double-apply otherwise). Lives in the BASE project db.
    `applied` flips when the user confirms the upload to Amazon (or automatically
    when a new bulk snapshot matches the exported value)."""
    __tablename__ = "bid_ledger"
    id = Column(Integer, primary_key=True, autoincrement=True)
    target_id = Column(String, index=True, nullable=False)
    campaign_id = Column(String, nullable=True)
    exported_bid = Column(Float, nullable=True)
    exported_state = Column(String, nullable=True)
    run_id = Column(Integer, nullable=True)
    source = Column(String, nullable=False)    # waterfall|weekly|bidopt|midmonth|pausescale
    exported_at = Column(DateTime, default=datetime.utcnow)
    applied = Column(Boolean, default=False)
    applied_at = Column(DateTime, nullable=True)


class SBFact(Base):
    """Sponsored Brands — Channels' OWN table (own upload, separate from the SP
    star schema). One row per entity per snapshot from the bulk's **SB Multi Ad
    Group Campaigns** sheet ONLY (the legacy 'Sponsored Brands Campaigns' sheet
    duplicates the same campaigns — reading both double-counts). Plus one row per
    SB Search Term Report line (entity='str'). Replaced wholesale per upload.
    v1 = audit visibility (no SB bulk generation)."""
    __tablename__ = "sb_fact"
    id = Column(Integer, primary_key=True, autoincrement=True)
    entity = Column(String, nullable=False, index=True)  # campaign|ad group|keyword|...|str
    campaign_id = Column(String, nullable=True)
    ad_group_id = Column(String, nullable=True)
    keyword_id = Column(String, nullable=True)
    campaign_name = Column(String, nullable=True)
    ad_group_name = Column(String, nullable=True)
    state = Column(String, nullable=True)
    ad_format = Column(String, nullable=True)   # video | product_collection | store_spotlight
    keyword_text = Column(String, nullable=True)
    match_type = Column(String, nullable=True)
    expression = Column(String, nullable=True)
    search_term = Column(String, nullable=True)  # entity='str' rows
    bid = Column(Float, nullable=True)
    budget = Column(Float, nullable=True)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    sales = Column(Float, default=0.0)
    orders = Column(Integer, default=0)
    units = Column(Integer, default=0)


class SDFact(Base):
    """Sponsored Display — Channels' OWN table (own upload). One row per entity
    per snapshot from the bulk's 'Sponsored Display Campaigns' sheet. Replaced
    wholesale per upload. v1 = audit visibility only."""
    __tablename__ = "sd_fact"
    id = Column(Integer, primary_key=True, autoincrement=True)
    entity = Column(String, nullable=False, index=True)  # campaign|ad group|product ad|contextual targeting|audience targeting
    campaign_id = Column(String, nullable=True)
    ad_group_id = Column(String, nullable=True)
    targeting_id = Column(String, nullable=True)
    campaign_name = Column(String, nullable=True)
    ad_group_name = Column(String, nullable=True)
    state = Column(String, nullable=True)
    tactic = Column(String, nullable=True)
    sku = Column(String, nullable=True)
    asin = Column(String, nullable=True)
    expression = Column(String, nullable=True)   # targeting expression
    bid = Column(Float, nullable=True)
    budget = Column(Float, nullable=True)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    sales = Column(Float, default=0.0)
    orders = Column(Integer, default=0)
    units = Column(Integer, default=0)


class SPChannelFact(Base):
    """Sponsored Products campaign totals for the Channels mix card — captured
    from the SAME upload as SBFact/SDFact so SP vs SB vs SD compare like-for-like
    (the audit star schema may hold a different upload/cadence). One row per SP
    campaign; replaced wholesale per upload."""
    __tablename__ = "sp_channel_fact"
    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(String, nullable=True)
    campaign_name = Column(String, nullable=True)
    state = Column(String, nullable=True)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    sales = Column(Float, default=0.0)
    orders = Column(Integer, default=0)


class OverlapFinding(Base):
    """Cannibalization / keyword-ownership finding. Two kinds:
    'duplicate_target' — same keyword_text+match_type (or PT expression) enabled
    in 2+ campaigns (splits data, budgets compete); 'cross_product' — same
    customer search term selling for 2+ different SKUs (Amazon may serve the
    worse converter). Regenerated wholesale on each run (idempotent re-review).
    Lives in the BASE project db."""
    __tablename__ = "overlap_finding"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String, nullable=False)      # duplicate_target | cross_product
    term = Column(String, nullable=False)
    match_type = Column(String, nullable=True)
    owner_sku = Column(String, nullable=True)
    owner_campaign_id = Column(String, nullable=True)
    verdict = Column(String, nullable=False)   # resolve | coexist | insufficient_data
    candidates_json = Column(String, nullable=True)   # per-candidate metrics (drill-down)
    actions_json = Column(String, nullable=True)      # precomputed bulk actions for losers
    selected = Column(Boolean, default=False)


class CadenceRun(Base):
    """A saved audit-cadence run for a (year, month, audit_type) — the monthly
    rhythm record. Carries the headline numbers captured at run time; its SOP
    effort checklist lives in CadenceTask. Unique per (year, month, audit_type)."""
    __tablename__ = "cadence_run"
    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    audit_type = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    flags = Column(Integer, default=0)            # snapshot of flag count at run time
    ad_spend = Column(Float, default=0.0)
    ad_sales = Column(Float, default=0.0)
    note = Column(String, nullable=True)
    __table_args__ = (Index("ix_cadence_run_key", "year", "month", "audit_type", unique=True),)


class CadenceTask(Base):
    """One SOP effort line for a cadence run (seeded from the preset; check off as done)."""
    __tablename__ = "cadence_task"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("cadence_run.id", ondelete="CASCADE"), index=True)
    text = Column(String, nullable=False)
    done = Column(Boolean, default=False)


class MonthSalesOverride(Base):
    """Manual total-sales figure for a calendar month, for the Monitoring overview's
    'vs last month' / 'vs last year' comparison when that month has no daily data
    uploaded (e.g. historical totals you only know as a single number)."""
    __tablename__ = "month_sales_override"
    year = Column(Integer, primary_key=True)
    month = Column(Integer, primary_key=True)
    sales = Column(Float, nullable=False)


class ProductBenchmark(Base):
    """Per-ASIN break-even data for PPC. break_even_acos = the ACoS at which an
    extra ad sale nets zero profit (= gross margin fraction). Above it you lose
    money on each ad sale. Uploaded ('Product Benchmark') or derived from costs.
    """
    __tablename__ = "product_benchmark"
    asin = Column(String, primary_key=True)
    sale_price = Column(Float, nullable=True)
    break_even_acos = Column(Float, nullable=True)   # fraction (0.42 = 42%)
    target_acos = Column(Float, nullable=True)        # optional per-ASIN goal override


class FactPlacement(Base):
    """Per-campaign placement performance + current bid-adjustment %, from the
    bulk 'Bidding Adjustment' rows. Drives placement bid optimization
    (Top of Search / Product page / Rest of search)."""
    __tablename__ = "fact_placement"
    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(String)
    placement = Column(String)
    snapshot_date = Column(Date)
    percentage = Column(Float, default=0.0)   # current bid adjustment (0 = +0%)
    strategy = Column(String, nullable=True)  # campaign Bidding Strategy (same bulk row)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    sales = Column(Float, default=0.0)
    orders = Column(Integer, default=0)


class ChangeLog(Base):
    """Audit trail — every action written to a bulk export is logged here, so the
    operator (and the weekly report) can see what changed, why, old -> new value.
    Scoped per audit like everything else."""
    __tablename__ = "change_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=datetime.utcnow)
    asin = Column(String, nullable=True)
    campaign_id = Column(String, nullable=True)
    entity_type = Column(String)            # keyword | product_target | placement | negative
    entity_id = Column(String, nullable=True)
    label = Column(String, nullable=True)   # keyword text / expression / placement
    field = Column(String)                  # bid | state | percentage | create
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    action = Column(String)                 # trim_bid | scale | pause | negate | promote | placement
    reason = Column(String, nullable=True)
    source = Column(String)                 # audit_bulk | bid_optimizer | placement | harvest
    status = Column(String, default="exported")


class MinedKeyword(Base):
    """Consolidated keyword research, deduped by normalized phrase. Merges Amazon
    Brand Analytics Search Query Performance + Helium10 Cerebro uploads."""
    __tablename__ = "mined_keyword"
    keyword = Column(String, primary_key=True)   # normalized lowercase phrase
    display = Column(String)
    words = Column(Integer, default=1)
    search_volume = Column(Integer, default=0)   # max across sources
    src_sqp = Column(Boolean, default=False)
    src_cerebro = Column(Boolean, default=False)
    sqp_impressions = Column(Integer, default=0)
    sqp_clicks = Column(Integer, default=0)
    sqp_purchases = Column(Integer, default=0)
    cerebro_organic_rank = Column(Integer, nullable=True)
    cerebro_sponsored_rank = Column(Integer, nullable=True)
    cerebro_competing = Column(Integer, nullable=True)
    cerebro_sales = Column(Float, nullable=True)
    # Search Term Report (harvest bulk upload) — third source; impressions feed
    # the Impression Share metric (STR impressions ÷ search volume × 100)
    src_str = Column(Boolean, default=False)
    str_impressions = Column(Integer, default=0)
    str_clicks = Column(Integer, default=0)
    str_orders = Column(Integer, default=0)


class ChecklistItem(Base):
    """Manual task on a per-audit checklist (auto items are computed, not stored)."""
    __tablename__ = "checklist_item"
    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(String)
    done = Column(Boolean, default=False)
    created = Column(DateTime, default=datetime.utcnow)


# ---- Competitor Research / Indexed Keywords / SEO tracker (base db, cadence-
# agnostic — like Monitoring). Schema per research_tracker/MAPPING.md: replaces
# the "Project Snore x Competitor Research" Google Sheet. Snapshots append-only.
class TrackerProject(Base):
    """One per client product line (e.g. 'Project Snore')."""
    __tablename__ = "tracker_project"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)
    primary_asin = Column(String)                 # exact string, never numeric
    created_at = Column(DateTime, default=datetime.utcnow)


class TrackedCompetitor(Base):
    """Competitor (or the primary, is_primary=True) product attributes — X-ray
    import + the manual listing-health audit block from the sheet's Main tab."""
    __tablename__ = "tracked_competitor"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("tracker_project.id", ondelete="CASCADE"), index=True)
    asin = Column(String)
    brand = Column(String, nullable=True)
    title = Column(String, nullable=True)
    is_primary = Column(Boolean, default=False)
    active = Column(Boolean, default=True)        # competitors rotate in/out
    # X-ray attributes (imported)
    price = Column(Float, nullable=True)
    sales = Column(Integer, nullable=True)
    revenue = Column(Float, nullable=True)
    bsr = Column(Integer, nullable=True)
    seller_country = Column(String, nullable=True)
    fba_fees = Column(Float, nullable=True)
    active_sellers = Column(Integer, nullable=True)
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, nullable=True)
    images = Column(Integer, nullable=True)
    review_velocity = Column(Integer, nullable=True)
    buy_box = Column(String, nullable=True)
    category = Column(String, nullable=True)
    size_tier = Column(String, nullable=True)
    fulfillment = Column(String, nullable=True)
    dimensions = Column(String, nullable=True)
    weight = Column(Float, nullable=True)
    creation_date = Column(String, nullable=True)  # ISO date string from export
    image_url = Column(String, nullable=True)
    bullet_points = Column(String, nullable=True)  # copy text (BP Comparison row 1)
    # manual listing-health audit (Main rows 19-27): None = unchecked
    listing_health_score = Column(Float, nullable=True)
    pdp_images = Column(Boolean, nullable=True)
    pdp_videos = Column(Boolean, nullable=True)
    brand_story = Column(Boolean, nullable=True)
    aplus = Column(Boolean, nullable=True)
    crawlable_text = Column(Boolean, nullable=True)
    alt_text = Column(Boolean, nullable=True)
    comparison_table = Column(Boolean, nullable=True)
    amazon_badge = Column(Boolean, nullable=True)


class TrackedKeyword(Base):
    """Master keyword list per project (the sheet's Main grid rows)."""
    __tablename__ = "tracked_keyword"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("tracker_project.id", ondelete="CASCADE"), index=True)
    keyword = Column(String)
    search_volume = Column(Integer, nullable=True)
    relevancy = Column(Integer, nullable=True)     # manual tag (sheet used 0/1/2/4)
    keyword_sales = Column(Integer, nullable=True) # Cerebro "Keyword Sales"
    source = Column(String, default="cerebro")     # cerebro | search_terms | manual | ppc_str


class RankSnapshot(Base):
    """Keyword x ASIN organic rank at a date. Append-only: re-import of the same
    date replaces that date only. rank None = not ranked ('-' or 0 in exports)."""
    __tablename__ = "rank_snapshot"
    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword_id = Column(Integer, ForeignKey("tracked_keyword.id", ondelete="CASCADE"), index=True)
    asin = Column(String)
    checked_at = Column(Date)
    organic_rank = Column(Integer, nullable=True)
    method = Column(String, default="cerebro")     # cerebro | manual | migrate


class KeywordUsage(Base):
    """Where OUR listing/campaigns use a keyword (sheet's Listing Audit markers).
    One row per marker; absence of a row = not used."""
    __tablename__ = "keyword_usage"
    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword_id = Column(Integer, ForeignKey("tracked_keyword.id", ondelete="CASCADE"), index=True)
    element = Column(String)   # title|bullet_points|aplus|description|search_terms|alt_text|sp_broad|sp_phrase|sp_exact|sb_broad|sb_phrase|sb_exact
    match = Column(String)     # exact | broad


class ListingCopy(Base):
    """Listing copy per element (Listing Copy tab). asin NULL = our listing
    (current vs proposed); asin set = a competitor's copy, pasted manually for
    the Listing Audit comparison (no search_terms for competitors)."""
    __tablename__ = "listing_copy"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("tracker_project.id", ondelete="CASCADE"), index=True)
    variant = Column(String)   # current | proposed
    element = Column(String)   # title|bullet_points|aplus|description|search_terms|alt_text
    asin = Column(String, nullable=True)   # NULL = ours; else competitor ASIN
    text = Column(String, nullable=True)


class BannedKeyword(Base):
    """Amazon banned/restricted keyword list (user-maintained, shared across
    tracker projects in this db). The Listing Sanitizer flags any of these
    appearing in OUR listing copy — competitors are never scanned."""
    __tablename__ = "banned_keyword"
    id = Column(Integer, primary_key=True, autoincrement=True)
    phrase = Column(String, nullable=False)


# polymorphic fact lookups + idempotent replace key
Index("ix_fact_entity", FactPerformance.entity_type, FactPerformance.entity_id)
Index("ix_fact_snap", FactPerformance.entity_type, FactPerformance.entity_id, FactPerformance.snapshot_date)
Index("ix_placement_camp_snap", FactPlacement.campaign_id, FactPlacement.snapshot_date)
Index("ix_changelog_ts", ChangeLog.ts)
Index("ix_rank_kw_asin_date", RankSnapshot.keyword_id, RankSnapshot.asin, RankSnapshot.checked_at)


# project-level economics defaults (refund rate, default referral) live in _meta;
# see database.get_project_meta / settings helpers.
