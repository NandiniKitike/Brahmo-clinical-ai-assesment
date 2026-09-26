"""
SQLAlchemy ORM models for the BRAHMO India Drug Master.

Design notes:
- Every row carries source, source_version, and load_batch for full provenance.
- Regulatory status is event-sourced (RegulatoryEvent table), never a boolean.
- Ambiguous resolutions go to ReviewQueue, never silently auto-resolved.
- FDC decompositions carry confidence scores and method tags.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, Text,
    ForeignKey, UniqueConstraint, Index, Enum as SAEnum
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.dialects.postgresql import JSONB
import enum
import uuid


class Base(DeclarativeBase):
    pass


def new_uuid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NormalizationMethod(str, enum.Enum):
    EXACT_MATCH = "EXACT_MATCH"
    LLM_ASSISTED = "LLM_ASSISTED"
    FUZZY_MATCH = "FUZZY_MATCH"
    MANUAL = "MANUAL"


class AmbiguityReasonCode(str, enum.Enum):
    BRAND_NOT_FOUND = "BRAND_NOT_FOUND"
    MULTIPLE_MATCHES = "MULTIPLE_MATCHES"
    STRENGTH_MISMATCH = "STRENGTH_MISMATCH"
    FORMULATION_AMBIGUOUS = "FORMULATION_AMBIGUOUS"
    FDC_DECOMPOSITION_UNCERTAIN = "FDC_DECOMPOSITION_UNCERTAIN"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class RegulatoryAction(str, enum.Enum):
    BANNED = "BANNED"
    RESTRICTED = "RESTRICTED"
    APPROVED = "APPROVED"
    STAY_GRANTED = "STAY_GRANTED"
    BAN_LIFTED = "BAN_LIFTED"
    UNDER_REVIEW = "UNDER_REVIEW"


class CheckState(str, enum.Enum):
    HIT = "HIT"
    CHECKED_NO_HIT = "CHECKED_NO_HIT"
    PARTIAL_COVERAGE = "PARTIAL_COVERAGE"
    UNVERIFIED_INPUT = "UNVERIFIED_INPUT"
    NOT_CHECKED = "NOT_CHECKED"
    DATA_EXPIRED = "DATA_EXPIRED"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class CheckSeverity(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


# ---------------------------------------------------------------------------
# Drug Master Tables
# ---------------------------------------------------------------------------

class ActiveIngredient(Base):
    """
    Canonical salt/molecule record.
    Example: paracetamol, amoxicillin, metformin
    """
    __tablename__ = "active_ingredients"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(String(255), nullable=False, unique=True)  # normalized canonical name
    aliases = Column(JSONB, default=list)                     # known synonyms/spellings
    atc_code = Column(String(50))                             # ATC code if available

    # Provenance
    source = Column(String(100), nullable=False)
    source_version = Column(String(100), nullable=False)
    load_batch = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    fdc_components = relationship("FDCComponent", back_populates="ingredient")
    interaction_pairs_a = relationship("InteractionPair", foreign_keys="InteractionPair.ingredient_a_id", back_populates="ingredient_a")
    interaction_pairs_b = relationship("InteractionPair", foreign_keys="InteractionPair.ingredient_b_id", back_populates="ingredient_b")


class DrugProduct(Base):
    """
    Brand-level product (e.g., Dolo 650, Augmentin 625).
    Maps to one or more active ingredients via FDCComponent.
    """
    __tablename__ = "drug_products"

    id = Column(String, primary_key=True, default=new_uuid)
    brand_name = Column(String(255), nullable=False)
    manufacturer = Column(String(255))
    formulation = Column(String(100))              # tablet, syrup, injection, etc.
    pack_description = Column(Text)                # raw pack string from source
    is_fdc = Column(Boolean, default=False)        # True if fixed-dose combination

    # CDCI / source codes
    cdci_code = Column(String(100))
    nlem_listed = Column(Boolean)
    jan_aushadhi_listed = Column(Boolean)

    # Provenance (binding law §8: every row traceable)
    source = Column(String(100), nullable=False)
    source_version = Column(String(100), nullable=False)
    load_batch = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    fdc_components = relationship("FDCComponent", back_populates="product", cascade="all, delete-orphan")
    normalization_records = relationship("NormalizationRecord", back_populates="product")
    regulatory_events = relationship("ProductRegulatoryEvent", back_populates="product")

    __table_args__ = (
        Index("ix_drug_products_brand_name", "brand_name"),
        Index("ix_drug_products_cdci_code", "cdci_code"),
    )


class FDCComponent(Base):
    """
    Decomposition of an FDC product into individual salts + strengths.
    A non-FDC product has exactly one component.
    Confidence score + method tag required on every row.
    """
    __tablename__ = "fdc_components"

    id = Column(String, primary_key=True, default=new_uuid)
    product_id = Column(String, ForeignKey("drug_products.id"), nullable=False)
    ingredient_id = Column(String, ForeignKey("active_ingredients.id"), nullable=False)

    strength_value = Column(Float)                # numeric strength
    strength_unit = Column(String(50))            # mg, mcg, IU, etc.
    strength_raw = Column(String(100))            # original string from source

    # Quality signal (binding law §6: no silent ambiguity)
    confidence_score = Column(Float, nullable=False)
    normalization_method = Column(SAEnum(NormalizationMethod), nullable=False)
    verification_note = Column(Text)

    # Provenance
    source = Column(String(100), nullable=False)
    source_version = Column(String(100), nullable=False)
    load_batch = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    product = relationship("DrugProduct", back_populates="fdc_components")
    ingredient = relationship("ActiveIngredient", back_populates="fdc_components")


class NormalizationRecord(Base):
    """
    Tracks every normalization decision made during ingestion.
    Ambiguous ones are flagged and queued.
    """
    __tablename__ = "normalization_records"

    id = Column(String, primary_key=True, default=new_uuid)
    product_id = Column(String, ForeignKey("drug_products.id"))
    raw_input = Column(Text, nullable=False)       # original string from source file
    resolved_value = Column(Text)                  # what we resolved it to (if resolved)

    confidence_score = Column(Float, nullable=False)
    normalization_method = Column(SAEnum(NormalizationMethod), nullable=False)
    is_ambiguous = Column(Boolean, default=False)  # True → goes to review queue
    review_queue_id = Column(String, ForeignKey("review_queue.id"))

    # Provenance
    source_file = Column(String(255), nullable=False)
    source_row_index = Column(Integer)
    load_batch = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    product = relationship("DrugProduct", back_populates="normalization_records")
    review_item = relationship("ReviewQueue", back_populates="normalization_records")


class ReviewQueue(Base):
    """
    Ambiguous resolutions that could not be auto-resolved.
    Binding law §6: never silently auto-resolve uncertain mappings.
    """
    __tablename__ = "review_queue"

    id = Column(String, primary_key=True, default=new_uuid)
    raw_input = Column(Text, nullable=False)
    reason_code = Column(SAEnum(AmbiguityReasonCode), nullable=False)
    reason_detail = Column(Text)
    candidates = Column(JSONB)                     # possible matches with scores
    status = Column(String(50), default="PENDING") # PENDING | RESOLVED | DISMISSED
    resolved_by = Column(String(100))
    resolved_at = Column(DateTime)
    resolution_note = Column(Text)

    # Provenance
    source_file = Column(String(255), nullable=False)
    load_batch = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    normalization_records = relationship("NormalizationRecord", back_populates="review_item")


# ---------------------------------------------------------------------------
# Regulatory Event Tables (event-sourced, never boolean)
# ---------------------------------------------------------------------------

class RegulatoryEvent(Base):
    """
    A single gazette notification event.
    Binding law §7: status derives from effective-dated events, not booleans.
    """
    __tablename__ = "regulatory_events"

    id = Column(String, primary_key=True, default=new_uuid)
    notification_id = Column(String(200), nullable=False, unique=True)
    action = Column(SAEnum(RegulatoryAction), nullable=False)
    published_date = Column(DateTime, nullable=False)
    effective_date = Column(DateTime, nullable=False)
    supersedes_notification_id = Column(String(200))   # links to earlier event it overrides
    gazette_reference = Column(String(500))
    summary = Column(Text)

    # Provenance
    source = Column(String(100), nullable=False)
    source_version = Column(String(100), nullable=False)
    load_batch = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    product_events = relationship("ProductRegulatoryEvent", back_populates="event")


class ProductRegulatoryEvent(Base):
    """
    Links a regulatory event to specific drug products (or ingredient patterns).
    """
    __tablename__ = "product_regulatory_events"

    id = Column(String, primary_key=True, default=new_uuid)
    product_id = Column(String, ForeignKey("drug_products.id"))
    event_id = Column(String, ForeignKey("regulatory_events.id"), nullable=False)
    ingredient_pattern = Column(Text)   # e.g., FDC pattern string from gazette

    product = relationship("DrugProduct", back_populates="regulatory_events")
    event = relationship("RegulatoryEvent", back_populates="product_events")


# ---------------------------------------------------------------------------
# Safety Interaction Table
# ---------------------------------------------------------------------------

class InteractionPair(Base):
    """
    Severe drug-drug interaction pairs (ingredient-level).
    """
    __tablename__ = "interaction_pairs"

    id = Column(String, primary_key=True, default=new_uuid)
    ingredient_a_id = Column(String, ForeignKey("active_ingredients.id"), nullable=False)
    ingredient_b_id = Column(String, ForeignKey("active_ingredients.id"), nullable=False)
    severity = Column(SAEnum(CheckSeverity), nullable=False, default=CheckSeverity.HIGH)
    mechanism = Column(Text)
    clinical_consequence = Column(Text)
    management = Column(Text)

    # Provenance
    source = Column(String(100), nullable=False)
    source_version = Column(String(100), nullable=False)
    load_batch = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    ingredient_a = relationship("ActiveIngredient", foreign_keys=[ingredient_a_id], back_populates="interaction_pairs_a")
    ingredient_b = relationship("ActiveIngredient", foreign_keys=[ingredient_b_id], back_populates="interaction_pairs_b")

    __table_args__ = (
        UniqueConstraint("ingredient_a_id", "ingredient_b_id", name="uq_interaction_pair"),
    )


# ---------------------------------------------------------------------------
# Pharmacy Stock Ingestion Tracking
# ---------------------------------------------------------------------------

class PharmacyStockRow(Base):
    """
    Raw pharmacy stock rows after ingestion. Treated as untrusted input.
    Tracks resolution status for every row.
    """
    __tablename__ = "pharmacy_stock_rows"

    id = Column(String, primary_key=True, default=new_uuid)
    raw_billing_string = Column(Text, nullable=False)
    resolved_product_id = Column(String, ForeignKey("drug_products.id"))
    resolution_confidence = Column(Float)
    resolution_method = Column(SAEnum(NormalizationMethod))
    resolution_status = Column(String(50), nullable=False)  # RESOLVED | AMBIGUOUS | UNRESOLVED
    review_queue_id = Column(String, ForeignKey("review_queue.id"))

    source_row_index = Column(Integer)
    load_batch = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# RAG Corpus Tables
# ---------------------------------------------------------------------------

class CorpusChunk(Base):
    """
    A clinically meaningful decision unit from the STW corpus.
    Never a blind token slice.
    """
    __tablename__ = "corpus_chunks"

    id = Column(String, primary_key=True, default=new_uuid)
    source_file = Column(String(255), nullable=False)   # e.g., STW_GP_01_Acute_Pharyngitis.pdf
    stw_code = Column(String(100))                      # e.g., STW-GP-01
    stw_version = Column(String(50))
    effective_date = Column(String(50))
    specialty = Column(String(100))                     # GP, Pediatrics, Gynaecology, etc.
    condition = Column(String(255))
    page_anchor = Column(String(100))                   # page number or section ref
    chunk_type = Column(String(100))                    # recommendation, contraindication, workflow_step, etc.
    is_local_protocol = Column(Boolean, default=False)  # True for local_protocol_acute_fever.md

    content = Column(Text, nullable=False)
    embedding = Column(JSONB)                            # embedding stored as JSON array (768 floats)

    # Provenance
    load_batch = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_corpus_chunks_source_file", "source_file"),
        Index("ix_corpus_chunks_specialty", "specialty"),
        Index("ix_corpus_chunks_condition", "condition"),
    )
