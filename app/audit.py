"""AuditEvent writer (SPEC section 11: every action is recorded)."""

from typing import Any

from sqlmodel import Session

from app.models import AuditEvent


def audit(
    session: Session,
    actor: str,
    action: str,
    entity: str,
    entity_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(actor=actor, action=action, entity=entity, entity_id=entity_id, details=details)
    session.add(event)
    return event
