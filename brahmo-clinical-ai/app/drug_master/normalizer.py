"""
Normalization pipeline for the India Drug Master.

Ingests the provided CSV files and maps each product to:
  - Canonical active ingredient(s) in the active_ingredients table
  - FDCComponent rows (one per ingredient in the product)
  - NormalizationRecord tracking every mapping decision
  - ReviewQueue entries for any ambiguous/uncertain resolution

Design decisions:
  D-003: CDCI data already has parsed ingredient columns — we use them directly
         with EXACT_MATCH at confidence=1.0. This is not "auto-resolve" because
         the data is already structured. Truly ambiguous cases (pharmacy_stock)
         go through LLM-assisted + fuzzy match with lower confidence.
  D-004: Ingredient name normalization uses lowercase + stripped whitespace as
         the canonical form stored in active_ingredients. Aliases array captures
         variants seen in source data.
"""

import pandas as pd
import re
import uuid
import hashlib
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from app.models import (
    ActiveIngredient, DrugProduct, FDCComponent, NormalizationRecord,
    ReviewQueue, NormalizationMethod, AmbiguityReasonCode
)
from app.config import settings
import logging

logger = logging.getLogger(__name__)


def _normalize_ingredient_name(raw: str) -> str:
    """Canonical form: stripped, lowercase."""
    return raw.strip().lower() if raw else ""


def _generate_batch_id(prefix: str) -> str:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    return f"{prefix}-{ts}"


def _get_or_create_ingredient(
    db: Session, raw_name: str, source: str, source_version: str, load_batch: str
) -> tuple[ActiveIngredient, bool]:
    """
    Get existing ingredient by canonical name, or create a new one.
    Returns (ingredient, created).
    """
    canonical = _normalize_ingredient_name(raw_name)
    if not canonical:
        return None, False

    ingredient = db.query(ActiveIngredient).filter_by(name=canonical).first()
    if ingredient:
        # Add alias if raw_name not already there
        if raw_name not in ingredient.aliases:
            aliases = list(ingredient.aliases)
            aliases.append(raw_name)
            ingredient.aliases = aliases
        return ingredient, False

    ingredient = ActiveIngredient(
        id=str(uuid.uuid4()),
        name=canonical,
        aliases=[raw_name] if raw_name != canonical else [],
        source=source,
        source_version=source_version,
        load_batch=load_batch,
    )
    db.add(ingredient)
    db.flush()  # Flush immediately so next query sees this row
    return ingredient, True


def ingest_cdci(db: Session, filepath: str, load_batch: str) -> dict:
    """
    Ingest the CDCI drug subset CSV.
    The CDCI data has structured ingredient columns (ingredient_1, strength_1_mg, ...).
    These are treated as EXACT_MATCH at confidence=1.0 because the source has
    already decomposed them — we are not making an inference here.
    """
    df = pd.read_csv(filepath)
    stats = {"products": 0, "ingredients_created": 0, "components": 0, "ambiguous": 0, "errors": 0}

    SOURCE = "CDCI-SUBSET"
    INGREDIENT_COLS = [
        ("ingredient_1", "strength_1_mg"),
        ("ingredient_2", "strength_2_mg"),
        ("ingredient_3", "strength_3_mg"),
    ]

    for idx, row in df.iterrows():
        try:
            source_version = str(row.get("source_version", "CDCI-SUBSET-2026Q2")).strip()
            effective_from = str(row.get("effective_from", "")).strip()

            # Determine if FDC
            ingredient_names = []
            for ing_col, _ in INGREDIENT_COLS:
                val = row.get(ing_col)
                if pd.notna(val) and str(val).strip():
                    ingredient_names.append(str(val).strip())
            is_fdc = len(ingredient_names) > 1

            # Skip if this brand already exists (idempotent reload)
            existing = db.query(DrugProduct).filter_by(
                brand_name=str(row["brand_name"]).strip(),
                source=SOURCE
            ).first()
            if existing:
                continue

            product = DrugProduct(
                id=str(uuid.uuid4()),
                brand_name=str(row["brand_name"]).strip(),
                manufacturer=str(row.get("manufacturer", "")).strip() or None,
                formulation=str(row.get("dose_form", "")).strip() or None,
                pack_description=str(row.get("strength_text", "")).strip() or None,
                is_fdc=is_fdc,
                cdci_code=str(row.get("product_id", "")).strip() or None,
                source=SOURCE,
                source_version=source_version,
                load_batch=load_batch,
            )
            db.add(product)
            db.flush()  # Flush so ingredient FK lookups see this product
            stats["products"] += 1

            for ing_col, str_col in INGREDIENT_COLS:
                ing_raw = row.get(ing_col)
                str_raw = row.get(str_col)

                if pd.isna(ing_raw) or not str(ing_raw).strip():
                    continue

                ing_name = str(ing_raw).strip()
                ingredient, created = _get_or_create_ingredient(
                    db, ing_name, SOURCE, source_version, load_batch
                )
                if ingredient is None:
                    continue
                if created:
                    stats["ingredients_created"] += 1

                # Parse strength
                strength_value = None
                strength_unit = "mg"  # CDCI uses mg column
                try:
                    if pd.notna(str_raw):
                        strength_value = float(str_raw)
                except (ValueError, TypeError):
                    pass

                component = FDCComponent(
                    id=str(uuid.uuid4()),
                    product_id=product.id,
                    ingredient_id=ingredient.id,
                    strength_value=strength_value,
                    strength_unit=strength_unit,
                    strength_raw=str(str_raw) if pd.notna(str_raw) else None,
                    confidence_score=1.0,
                    normalization_method=NormalizationMethod.EXACT_MATCH,
                    verification_note="Source CDCI provides pre-parsed ingredient columns",
                    source=SOURCE,
                    source_version=source_version,
                    load_batch=load_batch,
                )
                db.add(component)
                stats["components"] += 1

                norm_record = NormalizationRecord(
                    id=str(uuid.uuid4()),
                    product_id=product.id,
                    raw_input=ing_name,
                    resolved_value=ingredient.name,
                    confidence_score=1.0,
                    normalization_method=NormalizationMethod.EXACT_MATCH,
                    is_ambiguous=False,
                    source_file=filepath,
                    source_row_index=int(idx),
                    load_batch=load_batch,
                )
                db.add(norm_record)

        except Exception as e:
            logger.error(f"Error at row {idx}: {e}")
            stats["errors"] += 1

    db.commit()
    logger.info(f"CDCI ingest complete: {stats}")
    return stats


def ingest_pharmacy_stock(db: Session, filepath: str, load_batch: str) -> dict:
    """
    Ingest the pharmacy stock file — real-world messy, untrusted input.
    Every row treated as untrusted. Billing strings are normalized:
      1. Try exact match against known brand_names in drug_products table
      2. If confidence < threshold → queue for review (NEVER silent resolution)
    
    Note: LLM-assisted normalization for pharmacy stock is handled in a separate
    pass (pharmacy_stock_llm_pass.py) — this pass does structural normalization only.
    """
    df = pd.read_csv(filepath)
    stats = {"rows": 0, "resolved": 0, "ambiguous": 0, "unresolved": 0, "errors": 0}

    SOURCE = "PHARMACY-STOCK"

    # Build a lookup dict of known brand names (lowercase → product_id)
    known_brands: dict[str, list[str]] = {}
    for product in db.query(DrugProduct).all():
        key = product.brand_name.lower().strip()
        known_brands.setdefault(key, []).append(product.id)

    for idx, row in df.iterrows():
        try:
            raw_string = str(row.iloc[0]).strip()  # First col = billing string
            stats["rows"] += 1

            # Try exact match first
            normalized = _clean_billing_string(raw_string)
            matches = known_brands.get(normalized.lower(), [])

            if len(matches) == 1:
                # Exact unique match
                from app.models import PharmacyStockRow
                stock_row = PharmacyStockRow(
                    id=str(uuid.uuid4()),
                    raw_billing_string=raw_string,
                    resolved_product_id=matches[0],
                    resolution_confidence=1.0,
                    resolution_method=NormalizationMethod.EXACT_MATCH,
                    resolution_status="RESOLVED",
                    source_row_index=int(idx),
                    load_batch=load_batch,
                )
                db.add(stock_row)
                db.flush()
                stats["resolved"] += 1

            elif len(matches) > 1:
                # Multiple matches — ambiguous
                review = ReviewQueue(
                    id=str(uuid.uuid4()),
                    raw_input=raw_string,
                    reason_code=AmbiguityReasonCode.MULTIPLE_MATCHES,
                    reason_detail=f"Multiple brand matches for '{normalized}': {matches}",
                    candidates=[{"product_id": m, "confidence": 0.8} for m in matches],
                    source_file=filepath,
                    load_batch=load_batch,
                )
                db.add(review)
                db.flush()  # Must flush so FK exists

                from app.models import PharmacyStockRow
                stock_row = PharmacyStockRow(
                    id=str(uuid.uuid4()),
                    raw_billing_string=raw_string,
                    resolution_status="AMBIGUOUS",
                    review_queue_id=review.id,
                    source_row_index=int(idx),
                    load_batch=load_batch,
                )
                db.add(stock_row)
                db.flush()
                stats["ambiguous"] += 1

            else:
                # No match — flag as unresolved for LLM pass
                review = ReviewQueue(
                    id=str(uuid.uuid4()),
                    raw_input=raw_string,
                    reason_code=AmbiguityReasonCode.BRAND_NOT_FOUND,
                    reason_detail=f"No exact match for normalized string '{normalized}'",
                    candidates=[],
                    source_file=filepath,
                    load_batch=load_batch,
                )
                db.add(review)
                db.flush()  # Must flush so FK exists

                from app.models import PharmacyStockRow
                stock_row = PharmacyStockRow(
                    id=str(uuid.uuid4()),
                    raw_billing_string=raw_string,
                    resolution_status="UNRESOLVED",
                    review_queue_id=review.id,
                    source_row_index=int(idx),
                    load_batch=load_batch,
                )
                db.add(stock_row)
                db.flush()
                stats["unresolved"] += 1

        except Exception as e:
            logger.error(f"Error at pharmacy row {idx}: {e}")
            db.rollback()
            stats["errors"] += 1

    db.commit()
    logger.info(f"Pharmacy stock ingest complete: {stats}")
    return stats



def _clean_billing_string(raw: str) -> str:
    """
    Basic cleaning of a pharmacy billing string.
    Strips pack tokens (e.g., "1X10", "10TAB", "STRIP OF 10"), trailing numbers, etc.
    Returns a cleaned brand-name-like string.
    """
    # Remove common pack tokens
    patterns = [
        r'\b\d+\s*X\s*\d+\b',      # 10X10, 1X15
        r'\b\d+\s*TAB\b',           # 10TAB
        r'\bSTRIP\s*OF\s*\d+\b',    # STRIP OF 10
        r'\bPCS\b',
        r'\bMG\b',
        r'\d+\s*ML\b',
        r'\bINJ\b',
        r'\bSYR?\b',
        r'\bCAP\b',
        r'\bTAB\b',
    ]
    result = raw.upper()
    for pat in patterns:
        result = re.sub(pat, '', result, flags=re.IGNORECASE)
    return result.strip(' -./,')
