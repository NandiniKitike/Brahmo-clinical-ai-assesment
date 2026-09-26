"""
Regulatory status engine — event-sourced, never a boolean.

Binding law §7: Status derives from effective-dated regulatory events.
A plain `banned = True/False` boolean is a design failure.

Every status derivation returns:
  - current_action: the most recent applicable RegulatoryAction
  - notification_id: the gazette notification that produced this status
  - effective_date: when the status took effect
  - supersession_chain: ordered list of events that led here
  - data_as_of: when we last checked (for DATA_EXPIRED detection)

The check_regulatory_status() function is called by the safety rail and
returns a CheckResult (one of the 8 CheckState values).
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.models import (
    RegulatoryEvent, ProductRegulatoryEvent, DrugProduct, ActiveIngredient,
    FDCComponent, RegulatoryAction, CheckState, CheckSeverity
)
from app.config import settings
import logging
import re

logger = logging.getLogger(__name__)

# Maximum age of regulatory data before we return DATA_EXPIRED
DATA_EXPIRY_DAYS = 365  # configurable via settings in future


class RegulatoryStatus:
    """Structured regulatory status — never a boolean."""
    def __init__(
        self,
        check_state: CheckState,
        current_action: Optional[str],
        notification_id: Optional[str],
        effective_date: Optional[datetime],
        supersession_chain: list,
        evidence: str,
        severity: CheckSeverity,
        data_as_of: Optional[datetime] = None,
    ):
        self.check_state = check_state
        self.current_action = current_action
        self.notification_id = notification_id
        self.effective_date = effective_date
        self.supersession_chain = supersession_chain
        self.evidence = evidence
        self.severity = severity
        self.data_as_of = data_as_of or datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "check_state": self.check_state.value,
            "current_action": self.current_action,
            "notification_id": self.notification_id,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "supersession_chain": self.supersession_chain,
            "evidence": self.evidence,
            "severity": self.severity.value,
            "data_as_of": self.data_as_of.isoformat(),
        }


def _build_supersession_chain(
    db: Session, event: RegulatoryEvent, depth: int = 0
) -> list[dict]:
    """Walk the supersession chain backwards from the given event."""
    if depth > 10:  # safety cap
        return [{"event_id": event.id, "notification_id": event.notification_id, "note": "chain_depth_limit"}]

    chain = [{
        "event_id": event.id,
        "notification_id": event.notification_id,
        "action": event.action.value,
        "effective_date": event.effective_date.isoformat(),
    }]

    if event.supersedes_notification_id:
        prior = db.query(RegulatoryEvent).filter_by(
            notification_id=event.supersedes_notification_id
        ).first()
        if prior:
            chain += _build_supersession_chain(db, prior, depth + 1)

    return chain


def get_latest_event_for_product(db: Session, product: DrugProduct) -> Optional[RegulatoryEvent]:
    """
    Find the latest applicable regulatory event for a product.
    Checks both product-level and ingredient-pattern-level events.
    """
    # Check product-specific events
    product_events = (
        db.query(RegulatoryEvent)
        .join(ProductRegulatoryEvent, ProductRegulatoryEvent.event_id == RegulatoryEvent.id)
        .filter(ProductRegulatoryEvent.product_id == product.id)
        .filter(RegulatoryEvent.effective_date <= datetime.utcnow())
        .order_by(RegulatoryEvent.effective_date.desc())
        .all()
    )
    if product_events:
        return product_events[0]

    # Check ingredient-pattern events (FDC patterns)
    # Get canonical ingredient names for this product
    ingredients = (
        db.query(ActiveIngredient)
        .join(FDCComponent, FDCComponent.ingredient_id == ActiveIngredient.id)
        .filter(FDCComponent.product_id == product.id)
        .all()
    )
    ingredient_names = {i.name.lower() for i in ingredients}

    # Get all pattern events and match manually
    pattern_events = (
        db.query(RegulatoryEvent)
        .join(ProductRegulatoryEvent, ProductRegulatoryEvent.event_id == RegulatoryEvent.id)
        .filter(ProductRegulatoryEvent.ingredient_pattern.isnot(None))
        .filter(RegulatoryEvent.effective_date <= datetime.utcnow())
        .order_by(RegulatoryEvent.effective_date.desc())
        .all()
    )

    for event in pattern_events:
        pev = db.query(ProductRegulatoryEvent).filter_by(event_id=event.id).first()
        if pev and pev.ingredient_pattern:
            # Match pattern: check if all pattern ingredients are in this product
            pattern_ingredients = {
                p.strip().lower()
                for p in re.split(r"[+&,]", pev.ingredient_pattern)
                if p.strip()
            }
            if pattern_ingredients and pattern_ingredients.issubset(ingredient_names):
                # All required ingredients present → this event applies
                return event

    return None


def check_regulatory_status(db: Session, product: DrugProduct, data_as_of: datetime = None) -> RegulatoryStatus:
    """
    Derive regulatory status for a product from event history.
    Returns a RegulatoryStatus with full evidence.
    Missing data NEVER renders as safe (binding law §5).
    """
    data_as_of = data_as_of or datetime.utcnow()

    try:
        latest_event = get_latest_event_for_product(db, product)

        if latest_event is None:
            # No regulatory event found — NOT safe, just not checked
            return RegulatoryStatus(
                check_state=CheckState.CHECKED_NO_HIT,
                current_action=None,
                notification_id=None,
                effective_date=None,
                supersession_chain=[],
                evidence="No regulatory events found for this product in the gazette register.",
                severity=CheckSeverity.INFO,
                data_as_of=data_as_of,
            )

        # Check data freshness
        age_days = (data_as_of - latest_event.effective_date).days
        if age_days > DATA_EXPIRY_DAYS:
            return RegulatoryStatus(
                check_state=CheckState.DATA_EXPIRED,
                current_action=latest_event.action.value,
                notification_id=latest_event.notification_id,
                effective_date=latest_event.effective_date,
                supersession_chain=_build_supersession_chain(db, latest_event),
                evidence=f"Last gazette event is {age_days} days old (threshold: {DATA_EXPIRY_DAYS}). Data may be stale.",
                severity=CheckSeverity.MEDIUM,
                data_as_of=data_as_of,
            )

        # Map action to check state
        action = latest_event.action
        if action in (RegulatoryAction.BANNED, RegulatoryAction.PROHIBITED):
            return RegulatoryStatus(
                check_state=CheckState.HIT,
                current_action=action.value,
                notification_id=latest_event.notification_id,
                effective_date=latest_event.effective_date,
                supersession_chain=_build_supersession_chain(db, latest_event),
                evidence=f"Product is PROHIBITED per notification {latest_event.notification_id}, effective {latest_event.effective_date.date()}. {latest_event.summary or ''}",
                severity=CheckSeverity.HIGH,
                data_as_of=data_as_of,
            )
        elif action == RegulatoryAction.RESTRICTED:
            return RegulatoryStatus(
                check_state=CheckState.HIT,
                current_action=action.value,
                notification_id=latest_event.notification_id,
                effective_date=latest_event.effective_date,
                supersession_chain=_build_supersession_chain(db, latest_event),
                evidence=f"Product is RESTRICTED per notification {latest_event.notification_id}, effective {latest_event.effective_date.date()}. {latest_event.summary or ''}",
                severity=CheckSeverity.MEDIUM,
                data_as_of=data_as_of,
            )
        elif action == RegulatoryAction.STAY_GRANTED:
            return RegulatoryStatus(
                check_state=CheckState.PARTIAL_COVERAGE,
                current_action=action.value,
                notification_id=latest_event.notification_id,
                effective_date=latest_event.effective_date,
                supersession_chain=_build_supersession_chain(db, latest_event),
                evidence=f"Regulatory stay in effect per {latest_event.notification_id}. A prior prohibition exists but is currently stayed by court order. Legal status is contested.",
                severity=CheckSeverity.MEDIUM,
                data_as_of=data_as_of,
            )
        elif action in (RegulatoryAction.APPROVED, RegulatoryAction.BAN_LIFTED):
            return RegulatoryStatus(
                check_state=CheckState.CHECKED_NO_HIT,
                current_action=action.value,
                notification_id=latest_event.notification_id,
                effective_date=latest_event.effective_date,
                supersession_chain=_build_supersession_chain(db, latest_event),
                evidence=f"No active prohibition. Latest event: {action.value} per {latest_event.notification_id}, effective {latest_event.effective_date.date()}.",
                severity=CheckSeverity.INFO,
                data_as_of=data_as_of,
            )
        else:
            return RegulatoryStatus(
                check_state=CheckState.PARTIAL_COVERAGE,
                current_action=action.value,
                notification_id=latest_event.notification_id,
                effective_date=latest_event.effective_date,
                supersession_chain=_build_supersession_chain(db, latest_event),
                evidence=f"Regulatory action '{action.value}' noted per {latest_event.notification_id}. Manual review recommended.",
                severity=CheckSeverity.MEDIUM,
                data_as_of=data_as_of,
            )

    except Exception as e:
        logger.error(f"Regulatory check error for product {product.id}: {e}")
        return RegulatoryStatus(
            check_state=CheckState.SERVICE_UNAVAILABLE,
            current_action=None,
            notification_id=None,
            effective_date=None,
            supersession_chain=[],
            evidence=f"Regulatory check could not complete: {str(e)}",
            severity=CheckSeverity.HIGH,
        )
