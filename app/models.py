"""Data model, SPEC section 4.

Timestamps are timezone-aware UTC; always create them with utcnow().
Fields beyond the spec are marked "extra" and exist so imports round-trip without loss.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


LEGAL_ROUTES = ("call", "dm", "group_reply", "consented_email", "ad_disclosed")
DRAFT_KINDS = ("first_touch", "followup_1", "followup_2", "reply", "offer", "call_script")
CHANNELS = ("email", "whatsapp", "instagram_dm", "call")
DRAFT_STATUSES = ("pending", "approved", "rejected", "sent", "failed", "superseded")
ACTORS = ("human", "system", "claude", "openai")

LEAD_STATUSES = (
    "new",
    "researched",
    "drafted",
    "awaiting_approval",
    "contacted",
    "replied",
    "call_booked",
    "proposal_sent",
    "won",
    "lost",
    "no_reply",
    "archived",
    "suppressed",
)

# Lead state machine. Any state may move to "suppressed", and nothing leaves it.
LEAD_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "new": ("researched",),
    "researched": ("drafted",),
    "drafted": ("awaiting_approval",),
    "awaiting_approval": ("contacted",),
    "contacted": ("replied", "no_reply"),
    "replied": ("call_booked",),
    "call_booked": ("proposal_sent",),
    "proposal_sent": ("won", "lost"),
    "no_reply": ("archived",),
    "won": (),
    "lost": (),
    "archived": (),
    "suppressed": (),
}


def can_transition(current: str, target: str) -> bool:
    if current == "suppressed":
        return False
    if target == "suppressed":
        return True
    return target in LEAD_TRANSITIONS.get(current, ())


class Lead(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company: str
    company_norm: str = Field(default="", index=True)  # extra: dedup key
    segment: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None  # extra: CSV "region" / "state"
    website: Optional[str] = None
    domain: Optional[str] = Field(default=None, index=True)  # extra: dedup key
    instagram: Optional[str] = None
    facebook_page: Optional[str] = None
    score: Optional[int] = Field(default=None, index=True)
    score_breakdown: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    evidence_url: Optional[str] = None
    evidence_type: Optional[str] = None
    signal_notes: Optional[str] = None
    angle: Optional[str] = None
    legal_route: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="new", index=True)
    owner_notes: Optional[str] = None
    suggested_package: Optional[str] = None  # extra
    source_channel: Optional[str] = None  # extra: CSV "channel" (where the lead was found)
    date_found: Optional[str] = None  # extra
    source_file: Optional[str] = None  # extra: first file the lead was imported from
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Contact(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int = Field(foreign_key="lead.id", index=True)
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = Field(default=None, index=True)
    phone: Optional[str] = None
    phone_norm: Optional[str] = Field(default=None, index=True)  # extra: dedup key
    whatsapp: Optional[str] = None
    whatsapp_norm: Optional[str] = Field(default=None, index=True)  # extra: dedup key
    is_mobile_only: bool = False
    dnc_checked_at: Optional[datetime] = None
    needs_manual: bool = False


class Profile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int = Field(foreign_key="lead.id", index=True)
    # Spec calls this column "json"; that name shadows a pydantic method, so it is "data" here.
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    sources: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    model: Optional[str] = None


class Draft(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int = Field(foreign_key="lead.id", index=True)
    contact_id: Optional[int] = Field(default=None, foreign_key="contact.id")
    kind: str
    channel: str
    subject: Optional[str] = None
    body: str
    generated_by: str  # "openai:<model>" | "human"
    lint_report: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    status: str = Field(default="pending", index=True)
    parent_message_id: Optional[int] = Field(default=None, foreign_key="message.id")
    source: Optional[str] = None  # extra: "import:<file>" for drafts that came from a CSV
    created_at: datetime = Field(default_factory=utcnow)  # extra
    updated_at: datetime = Field(default_factory=utcnow)  # extra


class Approval(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    draft_id: int = Field(foreign_key="draft.id", index=True)
    body_sha256: str
    approved_at: datetime = Field(default_factory=utcnow)
    approved_by: str
    expires_at: datetime


class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int = Field(foreign_key="lead.id", index=True)
    contact_id: Optional[int] = Field(default=None, foreign_key="contact.id")
    direction: str  # "out" | "in"
    channel: str
    body: str
    provider_message_id: Optional[str] = None
    sent_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    status: Optional[str] = None


class Consent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    contact_id: int = Field(foreign_key="contact.id", index=True)
    channel: str  # "email" | "whatsapp"
    source: str
    evidence: Optional[str] = None
    recorded_at: datetime = Field(default_factory=utcnow)
    recorded_by: str


class Suppression(SQLModel, table=True):
    """Checked on every send, by each field. Values are stored normalized."""

    id: Optional[int] = Field(default=None, primary_key=True)
    email: Optional[str] = Field(default=None, index=True)
    phone: Optional[str] = Field(default=None, index=True)
    company: Optional[str] = Field(default=None, index=True)
    reason: Optional[str] = None
    added_at: datetime = Field(default_factory=utcnow)


class AuditEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=utcnow, index=True)
    actor: str
    action: str
    entity: str
    entity_id: Optional[int] = None
    details: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
