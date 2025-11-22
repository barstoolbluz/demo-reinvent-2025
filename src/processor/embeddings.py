"""Ticket embedding generation for semantic search.

This module generates 384-dimensional embeddings using sentence-transformers
for semantic similarity search and ticket routing.
"""
import logging
from typing import List, Dict, Any

import numpy as np

from src.processor.models import load_embedding_model

logger = logging.getLogger(__name__)


def generate_ticket_embedding(ticket: Dict[str, Any]) -> List[float]:
    """
    Generate semantic embedding for a single ticket.

    Args:
        ticket: Ticket dict with 'subject' and 'body' fields

    Returns:
        384-dimensional embedding vector as list of floats

    Example:
        >>> ticket = {"subject": "Login issue", "body": "Cannot access account"}
        >>> embedding = generate_ticket_embedding(ticket)
        >>> len(embedding)
        384
    """
    model = load_embedding_model()

    # Combine subject and body for comprehensive embedding
    subject = ticket.get("subject", "")
    body = ticket.get("body", "")
    text = f"{subject}. {body}" if subject and body else subject or body

    if not text.strip():
        logger.warning(f"Empty text for ticket {ticket.get('ticket_id', 'unknown')}")
        # Return zero vector for empty text
        return [0.0] * 384

    logger.debug(f"Generating embedding for ticket: {ticket.get('ticket_id', 'unknown')}")

    try:
        # Generate embedding
        embedding = model.encode(text, convert_to_numpy=True)

        # Convert to list for JSON serialization
        return embedding.tolist()

    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}")
        raise


def batch_generate_embeddings(
    tickets: List[Dict[str, Any]],
    batch_size: int = 32,
    show_progress: bool = False
) -> List[List[float]]:
    """
    Generate embeddings for multiple tickets (more efficient than one-by-one).

    Args:
        tickets: List of ticket dicts
        batch_size: Number of tickets to process at once
        show_progress: Whether to show progress bar

    Returns:
        List of 384-dimensional embedding vectors

    Note:
        Batch processing is significantly faster than calling
        generate_ticket_embedding() in a loop.

    Example:
        >>> tickets = [
        ...     {"subject": "Issue 1", "body": "Body 1"},
        ...     {"subject": "Issue 2", "body": "Body 2"}
        ... ]
        >>> embeddings = batch_generate_embeddings(tickets)
        >>> len(embeddings)
        2
    """
    model = load_embedding_model()

    # Prepare texts
    texts = []
    for ticket in tickets:
        subject = ticket.get("subject", "")
        body = ticket.get("body", "")
        text = f"{subject}. {body}" if subject and body else subject or body
        texts.append(text if text.strip() else " ")  # Avoid empty strings

    logger.info(f"Generating embeddings for {len(tickets)} tickets")

    try:
        # Batch encode
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            show_progress_bar=show_progress
        )

        # Convert to list of lists
        return [emb.tolist() for emb in embeddings]

    except Exception as e:
        logger.error(f"Failed to generate batch embeddings: {e}")
        raise


def compute_similarity(embedding1: List[float], embedding2: List[float]) -> float:
    """
    Compute cosine similarity between two embeddings.

    Args:
        embedding1: First 384-dim embedding
        embedding2: Second 384-dim embedding

    Returns:
        Cosine similarity score between -1 and 1
        (1 = identical, 0 = orthogonal, -1 = opposite)

    Example:
        >>> emb1 = generate_ticket_embedding({"subject": "Login problem"})
        >>> emb2 = generate_ticket_embedding({"subject": "Cannot login"})
        >>> similarity = compute_similarity(emb1, emb2)
        >>> similarity > 0.8  # Very similar
        True
    """
    # Convert to numpy arrays
    vec1 = np.array(embedding1)
    vec2 = np.array(embedding2)

    # Cosine similarity
    dot_product = np.dot(vec1, vec2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    similarity = dot_product / (norm1 * norm2)
    return float(similarity)


def find_similar_tickets(
    query_embedding: List[float],
    ticket_embeddings: List[Dict[str, Any]],
    top_k: int = 5,
    min_similarity: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Find most similar tickets to a query embedding.

    Args:
        query_embedding: 384-dim embedding of query ticket
        ticket_embeddings: List of dicts with 'ticket_id', 'embedding', etc.
        top_k: Number of similar tickets to return
        min_similarity: Minimum similarity threshold

    Returns:
        List of similar tickets sorted by similarity (highest first)

    Example:
        >>> query_emb = generate_ticket_embedding({"subject": "Payment failed"})
        >>> similar = find_similar_tickets(query_emb, stored_tickets, top_k=3)
        >>> len(similar) <= 3
        True
    """
    similarities = []

    for ticket in ticket_embeddings:
        if "embedding" not in ticket:
            continue

        similarity = compute_similarity(query_embedding, ticket["embedding"])

        if similarity >= min_similarity:
            similarities.append({
                **ticket,
                "similarity": similarity
            })

    # Sort by similarity (highest first)
    similarities.sort(key=lambda x: x["similarity"], reverse=True)

    # Return top k
    return similarities[:top_k]


def get_embedding_stats(embeddings: List[List[float]]) -> Dict[str, Any]:
    """
    Compute statistics about a collection of embeddings.

    Args:
        embeddings: List of embedding vectors

    Returns:
        Dict with statistics (mean, std, min, max of norms)

    Example:
        >>> embeddings = batch_generate_embeddings(tickets)
        >>> stats = get_embedding_stats(embeddings)
        >>> stats.keys()
        dict_keys(['count', 'dimension', 'norm_mean', 'norm_std', 'norm_min', 'norm_max'])
    """
    if not embeddings:
        return {
            "count": 0,
            "dimension": 0,
            "norm_mean": 0.0,
            "norm_std": 0.0,
            "norm_min": 0.0,
            "norm_max": 0.0
        }

    # Convert to numpy array
    embeddings_array = np.array(embeddings)

    # Compute norms (vector lengths)
    norms = np.linalg.norm(embeddings_array, axis=1)

    return {
        "count": len(embeddings),
        "dimension": len(embeddings[0]),
        "norm_mean": float(np.mean(norms)),
        "norm_std": float(np.std(norms)),
        "norm_min": float(np.min(norms)),
        "norm_max": float(np.max(norms))
    }


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)

    print("Testing embedding generation...")
    print("-" * 60)

    # Test single embedding
    test_ticket = {
        "ticket_id": "TEST-001",
        "subject": "Cannot login to my account",
        "body": "I've been trying to login but keep getting errors."
    }

    embedding = generate_ticket_embedding(test_ticket)
    print(f"✓ Single embedding generated: {len(embedding)} dimensions")
    print(f"  Sample values: {embedding[:5]}")

    # Test batch embeddings
    test_tickets = [
        {"subject": "Login issue", "body": "Cannot access account"},
        {"subject": "Payment failed", "body": "Transaction declined"},
        {"subject": "App crash", "body": "Application keeps crashing"}
    ]

    embeddings = batch_generate_embeddings(test_tickets)
    print(f"\n✓ Batch embeddings generated: {len(embeddings)} tickets")

    # Test similarity
    similarity = compute_similarity(embeddings[0], embeddings[1])
    print(f"\n✓ Similarity between ticket 1 and 2: {similarity:.4f}")

    # Test stats
    stats = get_embedding_stats(embeddings)
    print(f"\n✓ Embedding statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("\nDone!")
