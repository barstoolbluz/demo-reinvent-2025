"""Model loading and caching utilities.

This module provides lazy-loaded, cached access to ML models:
- Sentence transformers for embeddings
- Classification models for sentiment/intent
- Summarization models

All models are cached using @lru_cache to avoid reloading.
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from functools import lru_cache

import torch
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    AutoModelForSeq2SeqLM,
    pipeline,
)
from sentence_transformers import SentenceTransformer

from src.common.config import ModelConfig

logger = logging.getLogger(__name__)


# Model configurations
MODEL_CONFIGS = {
    "embeddings": {
        "name": "sentence-transformers/all-MiniLM-L6-v2",
        "size_mb": 22,
        "dim": 384,
        "type": "sentence-transformer"
    },
    "classifier": {
        "name": "distilbert-base-uncased-finetuned-sst-2-english",
        "size_mb": 255,
        "type": "sequence-classification"
    },
    "summarizer": {
        "name": "sshleifer/distilbart-cnn-6-6",
        "size_mb": 315,
        "type": "seq2seq"
    }
}


def get_model_cache_dir() -> Path:
    """Get model cache directory from environment or config."""
    cache_dir = os.getenv("MODEL_CACHE_DIR")
    if cache_dir:
        path = Path(cache_dir)
    else:
        config = ModelConfig.from_env()
        path = Path(config.cache_dir)

    path.mkdir(parents=True, exist_ok=True)
    return path


def get_device() -> str:
    """
    Get device for model inference.

    Returns:
        "cpu" - We only use CPU in this project
    """
    return "cpu"


@lru_cache(maxsize=1)
def load_embedding_model() -> SentenceTransformer:
    """
    Load sentence embedding model (cached).

    Returns:
        SentenceTransformer model for generating 384-dim embeddings

    Note:
        This function is cached - model is loaded only once per process.
    """
    config = MODEL_CONFIGS["embeddings"]
    cache_dir = get_model_cache_dir()

    logger.info(f"Loading embedding model: {config['name']}")
    logger.info(f"Cache directory: {cache_dir}")

    try:
        model = SentenceTransformer(
            config["name"],
            cache_folder=str(cache_dir),
            device=get_device()
        )
        logger.info(f"✓ Embedding model loaded ({config['size_mb']}MB)")
        return model
    except Exception as e:
        logger.error(f"Failed to load embedding model: {e}")
        raise


@lru_cache(maxsize=1)
def load_classifier_pipeline():
    """
    Load sentiment classification pipeline (cached).

    Returns:
        HuggingFace pipeline for text classification

    Note:
        Used for sentiment analysis. For intent/urgency, we use
        keyword-based classification (see classifier.py).
    """
    config = MODEL_CONFIGS["classifier"]
    cache_dir = get_model_cache_dir()

    logger.info(f"Loading classifier: {config['name']}")

    try:
        classifier = pipeline(
            "text-classification",
            model=config["name"],
            device=-1,  # CPU only
            model_kwargs={"cache_dir": str(cache_dir)}
        )
        logger.info(f"✓ Classifier loaded ({config['size_mb']}MB)")
        return classifier
    except Exception as e:
        logger.error(f"Failed to load classifier: {e}")
        raise


@lru_cache(maxsize=1)
def load_summarizer_pipeline():
    """
    Load summarization pipeline (cached).

    Returns:
        HuggingFace pipeline for text summarization

    Note:
        Uses DistilBART for generating concise summaries.
    """
    config = MODEL_CONFIGS["summarizer"]
    cache_dir = get_model_cache_dir()

    logger.info(f"Loading summarizer: {config['name']}")

    try:
        summarizer = pipeline(
            "summarization",
            model=config["name"],
            device=-1,  # CPU only
            model_kwargs={"cache_dir": str(cache_dir)}
        )
        logger.info(f"✓ Summarizer loaded ({config['size_mb']}MB)")
        return summarizer
    except Exception as e:
        logger.error(f"Failed to load summarizer: {e}")
        raise


def preload_all_models():
    """
    Preload all models at startup.

    Useful for:
    - Container warm-up (Lambda, K8s)
    - Ensuring models are cached before processing
    - Detecting model loading errors early

    Raises:
        Exception if any model fails to load
    """
    logger.info("Preloading all models...")

    try:
        load_embedding_model()
        load_classifier_pipeline()
        load_summarizer_pipeline()
        logger.info("✓ All models preloaded successfully")
    except Exception as e:
        logger.error(f"Failed to preload models: {e}")
        raise


def get_model_info() -> Dict[str, Any]:
    """
    Get information about models and runtime environment.

    Returns:
        Dictionary with model configs, PyTorch version, device info
    """
    cache_dir = get_model_cache_dir()

    info = {
        "cache_dir": str(cache_dir),
        "device": get_device(),
        "pytorch_version": torch.__version__,
        "cpu_threads": torch.get_num_threads(),
        "models": MODEL_CONFIGS,
        "total_size_mb": sum(m["size_mb"] for m in MODEL_CONFIGS.values())
    }

    return info


def clear_model_cache():
    """
    Clear LRU cache to force model reload.

    Warning:
        This will cause models to be reloaded on next use.
        Only use for testing or if models need updating.
    """
    logger.warning("Clearing model cache...")
    load_embedding_model.cache_clear()
    load_classifier_pipeline.cache_clear()
    load_summarizer_pipeline.cache_clear()
    logger.info("Model cache cleared")


def check_model_availability() -> Dict[str, bool]:
    """
    Check if models can be loaded without errors.

    Returns:
        Dict mapping model name to availability status

    Example:
        >>> check_model_availability()
        {'embeddings': True, 'classifier': True, 'summarizer': True}
    """
    results = {}

    # Check embeddings
    try:
        model = load_embedding_model()
        results["embeddings"] = model is not None
    except Exception as e:
        logger.error(f"Embeddings unavailable: {e}")
        results["embeddings"] = False

    # Check classifier
    try:
        model = load_classifier_pipeline()
        results["classifier"] = model is not None
    except Exception as e:
        logger.error(f"Classifier unavailable: {e}")
        results["classifier"] = False

    # Check summarizer
    try:
        model = load_summarizer_pipeline()
        results["summarizer"] = model is not None
    except Exception as e:
        logger.error(f"Summarizer unavailable: {e}")
        results["summarizer"] = False

    return results


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)

    print("Model Information:")
    print("-" * 60)
    info = get_model_info()
    for key, value in info.items():
        if key != "models":
            print(f"{key}: {value}")

    print("\nChecking model availability...")
    print("-" * 60)
    availability = check_model_availability()
    for model, available in availability.items():
        status = "✓" if available else "✗"
        print(f"{status} {model}: {'Available' if available else 'Failed'}")

    print("\nPreloading all models...")
    print("-" * 60)
    preload_all_models()
    print("Done!")
