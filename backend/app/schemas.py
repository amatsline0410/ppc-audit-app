"""Pydantic request/response models."""
from __future__ import annotations
from typing import Optional, Any
from pydantic import BaseModel


class ThresholdOverride(BaseModel):
    target_acos: Optional[float] = None
    min_spend: Optional[float] = None
    min_clicks: Optional[int] = None


class UploadSummary(BaseModel):
    snapshot_date: str
    entity_counts: dict[str, int]
    asins: int
    flags: int
    str_found: bool = False        # bulk carried an SP Search Term Report sheet
    harvest_candidates: list[dict] = []   # promote/negate from that embedded STR


class FlagOut(BaseModel):
    entity_type: str
    entity_id: str
    asin: Optional[str] = None
    flag: str
    severity: str
    observed: Optional[float] = None
    threshold: Optional[float] = None
    suggested_action: str
    new_bid: Optional[float] = None
    label: Optional[str] = None
    stage: Optional[str] = None
    break_even: Optional[float] = None


class AsinSummary(BaseModel):
    asin: str
    spend: float
    sales: float
    orders: int
    acos: Optional[float] = None
    flag_count: int


class AutomateRequest(BaseModel):
    flags: list[FlagOut]


class NarrateRequest(BaseModel):
    target_acos: float = 0.25
    mode: str = "summary"   # summary | email
    flags: list[FlagOut]


class NarrateResponse(BaseModel):
    provider: str
    enabled: bool
    text: str


class TreeNode(BaseModel):
    asin: str
    campaigns: list[dict[str, Any]]


class HarvestCandidate(BaseModel):
    action: str                       # promote | negate
    search_term: str
    campaign_id: str
    ad_group_id: str
    campaign_name: Optional[str] = None
    ad_group_name: Optional[str] = None
    match_type: Optional[str] = None
    impressions: int = 0
    clicks: int = 0
    spend: float = 0.0
    sales: float = 0.0
    orders: int = 0
    acos: Optional[float] = None
    cvr: Optional[float] = None
    suggested_bid: Optional[float] = None
    reason: str = ""
    break_even: Optional[float] = None


class HarvestBulkRequest(BaseModel):
    candidates: list[HarvestCandidate]


class StoreCreate(BaseModel):
    title: str


class ProjectCreate(BaseModel):
    title: str


class ProjectUpdate(BaseModel):
    acos_threshold: float


class RowsRequest(BaseModel):
    rows: list[dict] = []


class ChecklistAdd(BaseModel):
    text: str


class ChecklistToggle(BaseModel):
    done: bool
