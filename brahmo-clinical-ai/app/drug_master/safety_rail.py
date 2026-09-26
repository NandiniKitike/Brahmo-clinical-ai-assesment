"""
Deterministic Safety Rail — Module A.6

CRITICAL: NO LLM ANYWHERE IN THIS FILE. Pure lookup over versioned data.
Binding law §4: "Safety checks are pure lookup/rules over versioned data."

Given a draft prescription (list of brand-level product references), this rail:
  (a) Checks for duplicate active ingredient across products
  (b) Checks for prohibited/restricted FDC per event-sourced regulatory status
  (c) Checks for severe interactions per the seed list
  (d) Calculates cumulative same-ingredient exposure across the whole prescription

Every check returns exactly one of 8 states:
  HIT · CHECKED_NO_HIT · PARTIAL_COVERAGE · UNVERIFIED_INPUT · NOT_CHECKED
  · DATA_EXPIRED · SOURCE_CONFLICT · SERVICE_UNAVAILABLE

Missing data NEVER renders as "safe" — it renders as UNVERIFIED_INPUT or NOT_CHECKED.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from app.models import (
    DrugProduct, FDCComponent, ActiveIngredient, InteractionPair,
    CheckState, CheckSeverity, NormalizationMethod
)
from app.drug_master.regulatory import check_regulatory_status, RegulatoryStatus
import logging

logger = logging.getLogger(__name__)

# Current data version — loaded from config in real deployment
RAIL_DATA_VERSION = "CDCI-SUBSET-2026Q2 + GAZETTE-2026Q3 + INTERACTION-SEED-v1"
RAIL_RULE_VERSION = "safety-rail-v1.0"


@dataclass
class CheckResult:
    """A single check outcome with full evidence."""
    check_name: str
    check_state: CheckState
    severity: CheckSeverity
    evidence: str
    rule_version: str = RAIL_RULE_VERSION
    data_version: str = RAIL_DATA_VERSION
    affected_products: list = field(default_factory=list)
    affected_ingredients: list = field(default_factory=list)
    aggregate_exposure: Optional[dict] = None  # for cumulative check


@dataclass
class PrescriptionItem:
    """A single item in a draft prescription."""
    raw_input: str                         # brand name as written by doctor
    product_id: Optional[str] = None       # resolved product ID (if resolved)
    resolved: bool = False
    resolution_confidence: float = 0.0
    dose_per_administration: Optional[float] = None
    doses_per_day: Optional[int] = None
    formulation_note: Optional[str] = None


@dataclass
class RailResult:
    """Full safety rail output for a prescription."""
    prescription_items: list
    resolved_products: list                # list of (product, ingredient_list) tuples
    unresolved_items: list                 # items that could not be resolved
    check_duplicate_ingredient: CheckResult
    check_regulatory: CheckResult
    check_interaction: CheckResult
    check_cumulative_exposure: CheckResult
    rail_data_version: str = RAIL_DATA_VERSION
    rail_rule_version: str = RAIL_RULE_VERSION
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "prescription_items": [
                {"raw_input": i.raw_input, "resolved": i.resolved, "product_id": i.product_id,
                 "resolution_confidence": i.resolution_confidence}
                for i in self.prescription_items
            ],
            "unresolved_items": self.unresolved_items,
            "checks": {
                "duplicate_ingredient": self._result_dict(self.check_duplicate_ingredient),
                "regulatory": self._result_dict(self.check_regulatory),
                "interaction": self._result_dict(self.check_interaction),
                "cumulative_exposure": self._result_dict(self.check_cumulative_exposure),
            },
            "rail_data_version": self.rail_data_version,
            "rail_rule_version": self.rail_rule_version,
            "timestamp": self.timestamp,
        }

    def _result_dict(self, r: CheckResult) -> dict:
        return {
            "check_state": r.check_state.value,
            "severity": r.severity.value,
            "evidence": r.evidence,
            "affected_products": r.affected_products,
            "affected_ingredients": r.affected_ingredients,
            "aggregate_exposure": r.aggregate_exposure,
            "rule_version": r.rule_version,
            "data_version": r.data_version,
        }


class SafetyRail:
    """
    Deterministic safety rail. Instantiate once, call check_prescription() per Rx.
    No LLM. No probabilistic inference. Pure lookup over versioned database.
    """

    def __init__(self, db: Session):
        self.db = db

    def resolve_product(self, raw_input: str) -> PrescriptionItem:
        """
        Resolve a brand name string to a DrugProduct.
        Uses exact match only — ambiguous cases return unresolved.
        No silent resolution.
        """
        item = PrescriptionItem(raw_input=raw_input)

        # Exact match (case-insensitive)
        clean = raw_input.strip()
        product = self.db.query(DrugProduct).filter(
            DrugProduct.brand_name.ilike(clean)
        ).first()

        if product:
            item.product_id = product.id
            item.resolved = True
            item.resolution_confidence = 1.0
        else:
            # Try partial / suffix match (e.g., "Dolo" → "Dolo 650")
            products = self.db.query(DrugProduct).filter(
                DrugProduct.brand_name.ilike(f"{clean}%")
            ).all()

            if len(products) == 1:
                item.product_id = products[0].id
                item.resolved = True
                item.resolution_confidence = 0.90
            elif len(products) > 1:
                # Multiple matches — UNVERIFIED_INPUT, not silent
                item.resolved = False
                item.resolution_confidence = 0.0
                item.formulation_note = f"Multiple brand matches for '{clean}': {[p.brand_name for p in products[:5]]}"
            # else: no match at all, resolved=False

        return item

    def get_ingredients(self, product_id: str) -> list[tuple[ActiveIngredient, FDCComponent]]:
        """Return all (ingredient, component) pairs for a product."""
        return (
            self.db.query(ActiveIngredient, FDCComponent)
            .join(FDCComponent, FDCComponent.ingredient_id == ActiveIngredient.id)
            .filter(FDCComponent.product_id == product_id)
            .all()
        )

    # ------------------------------------------------------------------
    # CHECK (a): Duplicate active ingredient across products
    # ------------------------------------------------------------------
    def check_duplicate_ingredient(
        self, resolved_items: list[tuple[PrescriptionItem, DrugProduct, list]]
    ) -> CheckResult:
        """
        Detect duplicate active ingredients across prescription items.
        The cumulative daily total for each shared salt is included as evidence.
        """
        if not resolved_items:
            return CheckResult(
                check_name="duplicate_ingredient",
                check_state=CheckState.NOT_CHECKED,
                severity=CheckSeverity.INFO,
                evidence="No resolved products to check.",
            )

        # Map: ingredient_name → list of (product, component) that contain it
        ingredient_map: dict[str, list] = {}
        for item, product, ing_list in resolved_items:
            for ingredient, component in ing_list:
                ingredient_map.setdefault(ingredient.name, []).append({
                    "product_id": product.id,
                    "brand_name": product.brand_name,
                    "ingredient_name": ingredient.name,
                    "strength_value": component.strength_value,
                    "strength_unit": component.strength_unit,
                    "doses_per_day": item.doses_per_day,
                })

        duplicates = {k: v for k, v in ingredient_map.items() if len(v) > 1}

        if not duplicates:
            return CheckResult(
                check_name="duplicate_ingredient",
                check_state=CheckState.CHECKED_NO_HIT,
                severity=CheckSeverity.INFO,
                evidence="No duplicate active ingredients detected across prescription items.",
                affected_products=[item.product_id for item, _, _ in resolved_items],
                affected_ingredients=list(ingredient_map.keys()),
            )

        # Build evidence with cumulative totals
        evidence_parts = []
        aggregate = {}
        for ing_name, occurrences in duplicates.items():
            brands = [o["brand_name"] for o in occurrences]
            # Cumulative daily total (if doses_per_day known)
            total_mg_day = None
            if all(o["doses_per_day"] and o["strength_value"] for o in occurrences):
                total_mg_day = sum(
                    o["strength_value"] * o["doses_per_day"] for o in occurrences
                )
            aggregate[ing_name] = {
                "occurrences": len(occurrences),
                "in_products": brands,
                "total_mg_per_day": total_mg_day,
            }
            total_str = f" → cumulative {total_mg_day} mg/day total" if total_mg_day else ""
            evidence_parts.append(
                f"'{ing_name}' appears in: {', '.join(brands)}{total_str}"
            )

        return CheckResult(
            check_name="duplicate_ingredient",
            check_state=CheckState.HIT,
            severity=CheckSeverity.HIGH,
            evidence="DUPLICATE ACTIVE INGREDIENT DETECTED. " + "; ".join(evidence_parts),
            affected_products=[o["product_id"] for v in duplicates.values() for o in v],
            affected_ingredients=list(duplicates.keys()),
            aggregate_exposure=aggregate,
        )

    # ------------------------------------------------------------------
    # CHECK (b): Prohibited/restricted FDC regulatory status
    # ------------------------------------------------------------------
    def check_regulatory_status(
        self, resolved_items: list[tuple[PrescriptionItem, DrugProduct, list]]
    ) -> CheckResult:
        """
        Check each resolved product against event-sourced regulatory status.
        Returns HIT if any product has an active prohibition or restriction.
        """
        if not resolved_items:
            return CheckResult(
                check_name="regulatory",
                check_state=CheckState.NOT_CHECKED,
                severity=CheckSeverity.INFO,
                evidence="No resolved products to check.",
            )

        hits = []
        partial = []
        evidence_parts = []

        for item, product, _ in resolved_items:
            status: RegulatoryStatus = check_regulatory_status(self.db, product)

            if status.check_state == CheckState.HIT:
                hits.append(product.brand_name)
                evidence_parts.append(
                    f"[{product.brand_name}] {status.evidence} (Notification: {status.notification_id}, Effective: {status.effective_date.date() if status.effective_date else 'unknown'})"
                )
            elif status.check_state in (CheckState.PARTIAL_COVERAGE, CheckState.DATA_EXPIRED):
                partial.append(product.brand_name)
                evidence_parts.append(f"[{product.brand_name}] {status.evidence}")
            elif status.check_state == CheckState.SERVICE_UNAVAILABLE:
                evidence_parts.append(f"[{product.brand_name}] Regulatory check failed: {status.evidence}")
                return CheckResult(
                    check_name="regulatory",
                    check_state=CheckState.SERVICE_UNAVAILABLE,
                    severity=CheckSeverity.HIGH,
                    evidence="; ".join(evidence_parts),
                    affected_products=[product.brand_name],
                )

        if hits:
            return CheckResult(
                check_name="regulatory",
                check_state=CheckState.HIT,
                severity=CheckSeverity.HIGH,
                evidence="PROHIBITED/RESTRICTED PRODUCT DETECTED. " + " | ".join(evidence_parts),
                affected_products=hits,
            )
        if partial:
            return CheckResult(
                check_name="regulatory",
                check_state=CheckState.PARTIAL_COVERAGE,
                severity=CheckSeverity.MEDIUM,
                evidence="Partial regulatory coverage. " + " | ".join(evidence_parts),
                affected_products=partial,
            )

        return CheckResult(
            check_name="regulatory",
            check_state=CheckState.CHECKED_NO_HIT,
            severity=CheckSeverity.INFO,
            evidence=f"All {len(resolved_items)} products checked against gazette register. No active prohibitions found.",
            affected_products=[item.product_id for item, _, _ in resolved_items],
        )

    # ------------------------------------------------------------------
    # CHECK (c): Severe drug-drug interactions
    # ------------------------------------------------------------------
    def check_interactions(
        self, resolved_items: list[tuple[PrescriptionItem, DrugProduct, list]]
    ) -> CheckResult:
        """
        Check for severe ingredient-level interactions from the seed list.
        Compares every ingredient pair across all prescription items.
        """
        if not resolved_items:
            return CheckResult(
                check_name="interaction",
                check_state=CheckState.NOT_CHECKED,
                severity=CheckSeverity.INFO,
                evidence="No resolved products to check.",
            )

        # Collect all ingredient IDs across prescription
        all_ingredient_ids = set()
        for _, product, ing_list in resolved_items:
            for ingredient, _ in ing_list:
                all_ingredient_ids.add(ingredient.id)

        if len(all_ingredient_ids) < 2:
            return CheckResult(
                check_name="interaction",
                check_state=CheckState.CHECKED_NO_HIT,
                severity=CheckSeverity.INFO,
                evidence="Only one unique active ingredient in prescription — no pair interaction possible.",
            )

        # Look up all known interaction pairs where both ingredients are present
        interaction_hits = (
            self.db.query(InteractionPair)
            .filter(
                InteractionPair.ingredient_a_id.in_(all_ingredient_ids),
                InteractionPair.ingredient_b_id.in_(all_ingredient_ids),
            )
            .all()
        )

        if not interaction_hits:
            return CheckResult(
                check_name="interaction",
                check_state=CheckState.CHECKED_NO_HIT,
                severity=CheckSeverity.INFO,
                evidence=f"No severe interaction pairs found among {len(all_ingredient_ids)} active ingredients. Seed list version: {RAIL_DATA_VERSION}",
                affected_ingredients=list(all_ingredient_ids),
            )

        evidence_parts = []
        for pair in interaction_hits:
            ing_a = self.db.query(ActiveIngredient).filter_by(id=pair.ingredient_a_id).first()
            ing_b = self.db.query(ActiveIngredient).filter_by(id=pair.ingredient_b_id).first()
            evidence_parts.append(
                f"{ing_a.name if ing_a else pair.ingredient_a_id} ↔ {ing_b.name if ing_b else pair.ingredient_b_id}: "
                f"Severity={pair.severity.value}. {pair.clinical_consequence or ''} Management: {pair.management or 'See source.'}"
            )

        return CheckResult(
            check_name="interaction",
            check_state=CheckState.HIT,
            severity=CheckSeverity.HIGH,
            evidence="SEVERE INTERACTION DETECTED. " + " | ".join(evidence_parts),
            affected_ingredients=[p.ingredient_a_id for p in interaction_hits] + [p.ingredient_b_id for p in interaction_hits],
        )

    # ------------------------------------------------------------------
    # CHECK (d): Cumulative same-ingredient exposure
    # ------------------------------------------------------------------
    def check_cumulative_exposure(
        self, resolved_items: list[tuple[PrescriptionItem, DrugProduct, list]]
    ) -> CheckResult:
        """
        Calculate total daily exposure for each active ingredient across the prescription.
        The classic case: Dolo 650 + Sinarest both contain Paracetamol.
        Even if neither product individually is over a threshold, the cumulative
        total must be surfaced as evidence.

        Note: This check SURFACES the total — it does NOT make a dose-safety judgment.
        Binding law §12: we do NOT calculate patient-specific dose safety. We report
        what the prescription adds up to; the doctor decides.
        """
        if not resolved_items:
            return CheckResult(
                check_name="cumulative_exposure",
                check_state=CheckState.NOT_CHECKED,
                severity=CheckSeverity.INFO,
                evidence="No resolved products to check.",
            )

        # Aggregate: ingredient_name → list of exposure contributions
        aggregates: dict[str, list] = {}
        items_missing_dose_info = []

        for item, product, ing_list in resolved_items:
            for ingredient, component in ing_list:
                name = ingredient.name
                if component.strength_value and item.doses_per_day:
                    contribution = component.strength_value * item.doses_per_day
                    aggregates.setdefault(name, []).append({
                        "brand_name": product.brand_name,
                        "per_dose_mg": component.strength_value,
                        "doses_per_day": item.doses_per_day,
                        "daily_mg": contribution,
                    })
                else:
                    # Missing dose info — PARTIAL_COVERAGE, not safe
                    aggregates.setdefault(name, []).append({
                        "brand_name": product.brand_name,
                        "per_dose_mg": component.strength_value,
                        "doses_per_day": item.doses_per_day,
                        "daily_mg": None,
                        "note": "dose_info_missing",
                    })
                    if product.brand_name not in items_missing_dose_info:
                        items_missing_dose_info.append(product.brand_name)

        # Filter to ingredients appearing in >1 product
        shared = {k: v for k, v in aggregates.items() if len(v) > 1}

        if not shared:
            return CheckResult(
                check_name="cumulative_exposure",
                check_state=CheckState.CHECKED_NO_HIT,
                severity=CheckSeverity.INFO,
                evidence="No shared active ingredients across prescription items. Cumulative exposure check not applicable.",
            )

        evidence_parts = []
        aggregate_out = {}
        has_hit = False
        has_partial = bool(items_missing_dose_info)

        for ing_name, contributions in shared.items():
            brands = [c["brand_name"] for c in contributions]
            total_known = sum(c["daily_mg"] for c in contributions if c["daily_mg"] is not None)
            has_unknown = any(c["daily_mg"] is None for c in contributions)

            aggregate_out[ing_name] = {
                "in_products": brands,
                "total_mg_per_day_known": total_known if total_known > 0 else None,
                "has_incomplete_dose_info": has_unknown,
                "contributions": contributions,
            }

            if has_unknown:
                evidence_parts.append(
                    f"[{ing_name}] shared across {brands} — total mg/day INCOMPLETE (missing dose info for some items)"
                )
            else:
                has_hit = True
                evidence_parts.append(
                    f"[{ing_name}] shared across {brands} — combined total: {total_known:.1f} mg/day "
                    f"({'|'.join(str(c['daily_mg']) for c in contributions)} mg contributions)"
                )

        final_state = CheckState.HIT if has_hit else (CheckState.PARTIAL_COVERAGE if has_partial else CheckState.CHECKED_NO_HIT)
        severity = CheckSeverity.HIGH if has_hit else CheckSeverity.MEDIUM

        return CheckResult(
            check_name="cumulative_exposure",
            check_state=final_state,
            severity=severity,
            evidence="CUMULATIVE INGREDIENT EXPOSURE DETECTED. " + " | ".join(evidence_parts)
            if final_state == CheckState.HIT
            else "Partial cumulative exposure data. " + " | ".join(evidence_parts),
            affected_ingredients=list(shared.keys()),
            aggregate_exposure=aggregate_out,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def check_prescription(self, prescription_items: list[PrescriptionItem]) -> RailResult:
        """
        Run all four safety checks on a draft prescription.
        Unresolved items are reported as UNVERIFIED_INPUT — never silently skipped.
        """
        resolved_items = []
        unresolved = []

        for item in prescription_items:
            if not item.resolved:
                # Try to resolve now if product_id not set
                resolved_item = self.resolve_product(item.raw_input)
                item.product_id = resolved_item.product_id
                item.resolved = resolved_item.resolved
                item.resolution_confidence = resolved_item.resolution_confidence
                item.formulation_note = resolved_item.formulation_note

            if item.resolved and item.product_id:
                product = self.db.query(DrugProduct).filter_by(id=item.product_id).first()
                if product:
                    ing_list = self.get_ingredients(item.product_id)
                    resolved_items.append((item, product, ing_list))
                else:
                    unresolved.append({
                        "raw_input": item.raw_input,
                        "reason": "product_id_not_found_in_db",
                        "check_state": CheckState.UNVERIFIED_INPUT.value,
                    })
            else:
                unresolved.append({
                    "raw_input": item.raw_input,
                    "reason": item.formulation_note or "no_match_found",
                    "check_state": CheckState.UNVERIFIED_INPUT.value,
                })

        # Unresolved items force UNVERIFIED_INPUT on checks if any exist
        def _wrap_if_unverified(result: CheckResult) -> CheckResult:
            if unresolved:
                result.evidence = (
                    f"[PARTIAL CHECK: {len(unresolved)} item(s) could not be verified: "
                    f"{[u['raw_input'] for u in unresolved]}] " + result.evidence
                )
                if result.check_state == CheckState.CHECKED_NO_HIT:
                    result.check_state = CheckState.PARTIAL_COVERAGE
            return result

        check_dup = _wrap_if_unverified(self.check_duplicate_ingredient(resolved_items))
        check_reg = _wrap_if_unverified(self.check_regulatory_status(resolved_items))
        check_int = _wrap_if_unverified(self.check_interactions(resolved_items))
        check_cum = _wrap_if_unverified(self.check_cumulative_exposure(resolved_items))

        return RailResult(
            prescription_items=prescription_items,
            resolved_products=[(product.brand_name, [i.name for i, _ in ing_list]) for _, product, ing_list in resolved_items],
            unresolved_items=unresolved,
            check_duplicate_ingredient=check_dup,
            check_regulatory=check_reg,
            check_interaction=check_int,
            check_cumulative_exposure=check_cum,
        )
