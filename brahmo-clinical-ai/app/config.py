"""
Application configuration — all values loaded from environment.
No hardcoded constants anywhere in the codebase.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    # API Keys
    gemini_api_key: str = Field(..., env="GEMINI_API_KEY")

    # Database
    database_url: str = Field(..., env="DATABASE_URL")

    # Thresholds
    normalization_confidence_threshold: float = Field(0.85, env="NORMALIZATION_CONFIDENCE_THRESHOLD")
    fdc_decomposition_confidence_threshold: float = Field(0.80, env="FDC_DECOMPOSITION_CONFIDENCE_THRESHOLD")
    ambiguity_review_queue_threshold: float = Field(0.70, env="AMBIGUITY_REVIEW_QUEUE_THRESHOLD")

    # Models
    embedding_model: str = Field("models/text-embedding-004", env="EMBEDDING_MODEL")
    embedding_dimensions: int = Field(768, env="EMBEDDING_DIMENSIONS")
    llm_model: str = Field("gemini-1.5-flash", env="LLM_MODEL")

    # Data versioning
    data_load_batch_prefix: str = Field("BATCH", env="DATA_LOAD_BATCH_PREFIX")

    # File paths
    interaction_seed_path: str = Field("data/severe_interaction_seed.csv", env="INTERACTION_SEED_PATH")
    gazette_events_path: str = Field("data/regulatory_gazette_events.csv", env="GAZETTE_EVENTS_PATH")
    corpus_dir: str = Field("corpus", env="CORPUS_DIR")

    # Chunking
    chunk_max_tokens: int = Field(300, env="CHUNK_MAX_TOKENS")
    chunk_overlap_tokens: int = Field(50, env="CHUNK_OVERLAP_TOKENS")

    # Retrieval
    retrieval_top_k: int = Field(5, env="RETRIEVAL_TOP_K")
    bm25_weight: float = Field(0.4, env="BM25_WEIGHT")
    semantic_weight: float = Field(0.6, env="SEMANTIC_WEIGHT")

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
