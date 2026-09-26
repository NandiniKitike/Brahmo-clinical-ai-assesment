"""
Master data loading script.
Loads all provided datasets into the database in correct dependency order.
Run: python scripts/load_all_data.py
"""

import sys
import os
import uuid
import pandas as pd
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal, init_db
from app.models import (
    RegulatoryEvent, ProductRegulatoryEvent, DrugProduct,
    ActiveIngredient, FDCComponent, InteractionPair,
    NormalizationMethod, RegulatoryAction, CheckSeverity
)
from app.drug_master.normalizer import ingest_cdci, ingest_pharmacy_stock
from app.config import settings
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LOAD_BATCH = f"BATCH-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}"

DATA_DIR = Path(__file__).parent.parent / "data"
CORPUS_DIR = Path(__file__).parent.parent / "corpus"


def load_gazette_events(db):
    """Load regulatory_gazette_events.csv into RegulatoryEvent table."""
    filepath = DATA_DIR / "regulatory_gazette_events.csv"
    logger.info(f"Loading gazette events from {filepath}")
    df = pd.read_csv(filepath)

    ACTION_MAP = {
        "PROHIBITED": RegulatoryAction.BANNED,
        "RESTRICTED": RegulatoryAction.RESTRICTED,
        "STAY_GRANTED": RegulatoryAction.STAY_GRANTED,
        "WITHDRAWN": RegulatoryAction.BANNED,
        "APPROVED": RegulatoryAction.APPROVED,
    }

    event_rows = {}  # event_id (CSV) → RegulatoryEvent DB object

    for _, row in df.iterrows():
        event_id_csv = str(row["event_id"]).strip()
        action_str = str(row["action"]).strip()
        action = ACTION_MAP.get(action_str, RegulatoryAction.RESTRICTED)

        event = RegulatoryEvent(
            id=str(uuid.uuid4()),
            notification_id=str(row["notification_id"]).strip(),
            action=action,
            published_date=pd.to_datetime(row["date_published"]),
            effective_date=pd.to_datetime(row["effective_date"]),
            supersedes_notification_id=str(row["supersedes_event_id"]).strip() if pd.notna(row.get("supersedes_event_id")) and str(row.get("supersedes_event_id")).strip() else None,
            gazette_reference=str(row["notification_id"]).strip(),
            summary=str(row.get("note", "")).strip() or None,
            source="GAZETTE-PROVIDED",
            source_version="2026Q3",
            load_batch=LOAD_BATCH,
        )
        db.add(event)
        event_rows[event_id_csv] = event

    db.flush()

    # Now resolve supersedes_event_id to notification_id
    for _, row in df.iterrows():
        sup_id_csv = str(row.get("supersedes_event_id", "")).strip()
        if sup_id_csv and sup_id_csv != "nan":
            # supersedes_event_id in CSV refers to another event_id in CSV
            if sup_id_csv in event_rows:
                prior_event = event_rows[sup_id_csv]
                current_event = event_rows[str(row["event_id"]).strip()]
                current_event.supersedes_notification_id = prior_event.notification_id

    db.commit()

    # Link gazette events to products via target_description pattern matching
    _link_events_to_products(db, df, event_rows)

    logger.info(f"Gazette events loaded: {len(event_rows)} events")


def _link_events_to_products(db, df, event_rows):
    """
    Link gazette events to products via ingredient pattern matching.
    For FDC prohibitions, stores the ingredient pattern so the regulatory engine
    can match products that contain all those ingredients.
    """
    for _, row in df.iterrows():
        event_id_csv = str(row["event_id"]).strip()
        event = event_rows.get(event_id_csv)
        if not event:
            continue

        target_type = str(row.get("target_type", "")).strip()
        target_desc = str(row.get("target_description", "")).strip()

        if target_type == "FDC":
            # Extract ingredient pattern from description
            # e.g. "Nimesulide + Paracetamol (all strengths)" → "Nimesulide + Paracetamol"
            pattern = target_desc.split("(")[0].strip()
            pev = ProductRegulatoryEvent(
                id=str(uuid.uuid4()),
                event_id=event.id,
                ingredient_pattern=pattern,
            )
            db.add(pev)

        elif target_type == "INGREDIENT":
            # Extract ingredient name, link to all products containing it
            ing_name = target_desc.split("(")[0].strip().lower()
            ingredient = db.query(ActiveIngredient).filter_by(name=ing_name).first()
            if ingredient:
                products_with_ing = (
                    db.query(DrugProduct)
                    .join(FDCComponent, FDCComponent.product_id == DrugProduct.id)
                    .filter(FDCComponent.ingredient_id == ingredient.id)
                    .all()
                )
                for product in products_with_ing:
                    pev = ProductRegulatoryEvent(
                        id=str(uuid.uuid4()),
                        product_id=product.id,
                        event_id=event.id,
                    )
                    db.add(pev)
            else:
                # Store as pattern anyway for future products
                pev = ProductRegulatoryEvent(
                    id=str(uuid.uuid4()),
                    event_id=event.id,
                    ingredient_pattern=target_desc.split("(")[0].strip(),
                )
                db.add(pev)

    db.commit()


def load_interaction_seeds(db):
    """Load severe_interaction_seed.csv into InteractionPair table."""
    filepath = DATA_DIR / "severe_interaction_seed.csv"
    logger.info(f"Loading interaction seeds from {filepath}")
    df = pd.read_csv(filepath)
    loaded = 0

    for _, row in df.iterrows():
        ing_a_name = str(row.get("ingredient_a", row.get("drug_a", ""))).strip().lower()
        ing_b_name = str(row.get("ingredient_b", row.get("drug_b", ""))).strip().lower()

        if not ing_a_name or not ing_b_name:
            continue

        ing_a = db.query(ActiveIngredient).filter_by(name=ing_a_name).first()
        ing_b = db.query(ActiveIngredient).filter_by(name=ing_b_name).first()

        if not ing_a:
            ing_a = ActiveIngredient(
                id=str(uuid.uuid4()),
                name=ing_a_name,
                aliases=[],
                source="INTERACTION-SEED",
                source_version="v1",
                load_batch=LOAD_BATCH,
            )
            db.add(ing_a)
            db.flush()

        if not ing_b:
            ing_b = ActiveIngredient(
                id=str(uuid.uuid4()),
                name=ing_b_name,
                aliases=[],
                source="INTERACTION-SEED",
                source_version="v1",
                load_batch=LOAD_BATCH,
            )
            db.add(ing_b)
            db.flush()

        # Check for existing pair (either direction)
        existing = db.query(InteractionPair).filter(
            ((InteractionPair.ingredient_a_id == ing_a.id) & (InteractionPair.ingredient_b_id == ing_b.id)) |
            ((InteractionPair.ingredient_a_id == ing_b.id) & (InteractionPair.ingredient_b_id == ing_a.id))
        ).first()

        if not existing:
            pair = InteractionPair(
                id=str(uuid.uuid4()),
                ingredient_a_id=ing_a.id,
                ingredient_b_id=ing_b.id,
                severity=CheckSeverity.HIGH,
                mechanism=str(row.get("mechanism", "")).strip() or None,
                clinical_consequence=str(row.get("consequence", row.get("clinical_consequence", ""))).strip() or None,
                management=str(row.get("management", "")).strip() or None,
                source="INTERACTION-SEED",
                source_version="v1",
                load_batch=LOAD_BATCH,
            )
            db.add(pair)
            loaded += 1

    db.commit()
    logger.info(f"Interaction seeds loaded: {loaded} pairs")


def main():
    logger.info(f"Starting data load — batch: {LOAD_BATCH}")

    # Initialize DB and create all tables
    init_db()

    db = SessionLocal()
    try:
        # Wipe all tables for clean idempotent reload
        logger.info("Truncating all tables for clean reload...")
        from sqlalchemy import text
        db.execute(text("TRUNCATE TABLE pharmacy_stock_rows, review_queue, normalization_records, fdc_components, product_regulatory_events, regulatory_events, interaction_pairs, drug_products, active_ingredients, corpus_chunks RESTART IDENTITY CASCADE"))
        db.commit()
        logger.info("Tables cleared.")

        # 1. Load CDCI drug subset (foundation of drug master)
        logger.info("=== Step 1: CDCI drug subset ===")
        stats = ingest_cdci(db, str(DATA_DIR / "cdci_drug_subset.csv"), LOAD_BATCH)
        logger.info(f"CDCI stats: {stats}")

        # 2. Load gazette events (must be after drugs so pattern matching works)
        logger.info("=== Step 2: Gazette regulatory events ===")
        load_gazette_events(db)

        # 3. Load interaction seeds
        logger.info("=== Step 3: Interaction seeds ===")
        load_interaction_seeds(db)

        # 4. Load pharmacy stock (messy, untrusted)
        logger.info("=== Step 4: Pharmacy stock (untrusted) ===")
        p_stats = ingest_pharmacy_stock(db, str(DATA_DIR / "pharmacy_stock.csv"), LOAD_BATCH)
        logger.info(f"Pharmacy stock stats: {p_stats}")

        # 5. Ingest Corpus
        logger.info("=== Step 5: Ingest Corpus ===")
        from app.rag.chunker import ingest_corpus
        c_stats = ingest_corpus(db, str(CORPUS_DIR), LOAD_BATCH)
        logger.info(f"Corpus stats: {c_stats}")

        # 6. Embed Corpus Chunks
        logger.info("=== Step 6: Embed Corpus Chunks ===")
        from app.rag.embedder import embed_corpus
        e_stats = embed_corpus(db)
        logger.info(f"Embedding stats: {e_stats}")

        logger.info(f"✅ Data load complete — batch: {LOAD_BATCH}")

    except Exception as e:
        logger.error(f"Data load failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
