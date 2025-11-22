"""Ticket summarization using DistilBART.

This module generates concise summaries of support tickets for:
- Dashboard displays
- Quick triage
- Email notifications
- Search results
"""
import logging
from typing import Dict, Any, Optional

from src.processor.models import load_summarizer_pipeline
from src.common.config import ModelConfig

logger = logging.getLogger(__name__)


def generate_summary(
    ticket: Dict[str, Any],
    max_length: Optional[int] = None,
    min_length: int = 10
) -> str:
    """
    Generate concise summary of ticket.

    Args:
        ticket: Ticket dict with 'subject' and 'body'
        max_length: Maximum summary length in tokens (default from config)
        min_length: Minimum summary length in tokens

    Returns:
        Summary text (single sentence or short paragraph)

    Note:
        - For very short tickets (<20 words), returns subject
        - For longer tickets, generates extractive summary
        - Summary is always shorter than original text

    Example:
        >>> ticket = {
        ...     "subject": "Login issue",
        ...     "body": "I've been trying to login for hours but..."
        ... }
        >>> summary = generate_summary(ticket, max_length=30)
        >>> len(summary) < len(ticket["body"])
        True
    """
    summarizer = load_summarizer_pipeline()

    # Get max_length from config if not specified
    if max_length is None:
        config = ModelConfig.from_env()
        max_length = config.max_summary_length

    # Combine subject and body
    subject = ticket.get("subject", "")
    body = ticket.get("body", "")

    # If no subject or body, return empty
    if not subject and not body:
        return ""

    # If only subject, return it
    if not body:
        return subject

    # If body is very short, just return subject
    word_count = len(body.split())
    if word_count < 20:
        return subject if subject else body[:100]

    # Combine for summarization
    text = f"{subject}. {body}" if subject else body

    # Truncate very long text (DistilBART max is 1024 tokens)
    # Roughly 1 token ≈ 0.75 words, so 1024 tokens ≈ 768 words
    words = text.split()
    if len(words) > 700:
        text = " ".join(words[:700])
        logger.debug(f"Truncated ticket text from {len(words)} to 700 words")

    logger.debug(f"Generating summary for ticket: {ticket.get('ticket_id', 'unknown')}")

    try:
        # Generate summary
        result = summarizer(
            text,
            max_length=max_length,
            min_length=min_length,
            do_sample=False,  # Deterministic output
            truncation=True
        )

        summary = result[0]["summary_text"]

        # Clean up summary
        summary = summary.strip()

        # Ensure it ends with punctuation
        if summary and summary[-1] not in ".!?":
            summary += "."

        logger.debug(f"Summary generated: {len(summary)} chars")

        return summary

    except Exception as e:
        logger.error(f"Failed to generate summary: {e}")
        # Fallback: return truncated subject
        return subject[:100] if subject else body[:100]


def generate_summaries_batch(
    tickets: list[Dict[str, Any]],
    max_length: Optional[int] = None,
    min_length: int = 10
) -> list[str]:
    """
    Generate summaries for multiple tickets.

    Args:
        tickets: List of ticket dicts
        max_length: Maximum summary length in tokens
        min_length: Minimum summary length in tokens

    Returns:
        List of summary strings

    Note:
        Currently processes one-by-one. Could be optimized with
        batch processing in future.

    Example:
        >>> tickets = [
        ...     {"subject": "Issue 1", "body": "..."},
        ...     {"subject": "Issue 2", "body": "..."}
        ... ]
        >>> summaries = generate_summaries_batch(tickets)
        >>> len(summaries) == len(tickets)
        True
    """
    logger.info(f"Generating summaries for {len(tickets)} tickets")

    summaries = []
    for ticket in tickets:
        try:
            summary = generate_summary(ticket, max_length, min_length)
            summaries.append(summary)
        except Exception as e:
            logger.error(f"Failed to summarize ticket {ticket.get('ticket_id')}: {e}")
            # Append fallback summary
            summaries.append(ticket.get("subject", "")[:100])

    return summaries


def get_summary_stats(original_text: str, summary: str) -> Dict[str, Any]:
    """
    Get statistics about summary compression.

    Args:
        original_text: Original ticket text
        summary: Generated summary

    Returns:
        Dict with compression metrics

    Example:
        >>> text = "Long text " * 100
        >>> summary = "Short summary"
        >>> stats = get_summary_stats(text, summary)
        >>> stats["compression_ratio"] > 1.0
        True
    """
    orig_words = len(original_text.split())
    orig_chars = len(original_text)

    summ_words = len(summary.split())
    summ_chars = len(summary)

    return {
        "original_words": orig_words,
        "original_chars": orig_chars,
        "summary_words": summ_words,
        "summary_chars": summ_chars,
        "compression_ratio": orig_chars / summ_chars if summ_chars > 0 else 0.0,
        "word_reduction": orig_words - summ_words,
        "char_reduction": orig_chars - summ_chars
    }


def summarize_for_display(
    ticket: Dict[str, Any],
    max_display_length: int = 100
) -> str:
    """
    Generate ultra-short summary for UI display (dashboard, list view).

    Args:
        ticket: Ticket dict
        max_display_length: Maximum chars for display

    Returns:
        Very short summary suitable for compact display

    Example:
        >>> ticket = {"subject": "Cannot login", "body": "Long explanation..."}
        >>> display = summarize_for_display(ticket, max_display_length=50)
        >>> len(display) <= 50
        True
    """
    # First generate full summary
    summary = generate_summary(ticket, max_length=30)

    # Truncate to display length
    if len(summary) <= max_display_length:
        return summary

    # Truncate and add ellipsis
    truncated = summary[:max_display_length - 3].rsplit(' ', 1)[0]
    return truncated + "..."


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)

    print("Testing summarization...")
    print("-" * 60)

    # Test tickets
    test_tickets = [
        {
            "ticket_id": "TEST-001",
            "subject": "Cannot login to my account",
            "body": "I've been trying to login to my account for the past two hours but I keep getting an 'invalid credentials' error message. I'm absolutely certain that I'm using the correct password because I saved it in my password manager. I've tried resetting my password twice already but the problem persists. This is very urgent as I need to access my account for an important work meeting this afternoon."
        },
        {
            "ticket_id": "TEST-002",
            "subject": "Short ticket",
            "body": "Quick question about pricing."
        },
        {
            "ticket_id": "TEST-003",
            "subject": "Payment issue",
            "body": "My payment was declined yesterday but when I checked my bank statement this morning, the money was actually debited from my account. I need this resolved quickly and want a refund processed. The transaction ID is TXN-12345 and the amount is $99.99. I've been a customer for three years and this has never happened before. Please help!"
        }
    ]

    for ticket in test_tickets:
        print(f"\n{ticket['subject']}")
        print("-" * 60)
        print(f"Original: {len(ticket['body'])} chars")

        # Full summary
        summary = generate_summary(ticket)
        print(f"Summary: {summary}")
        print(f"Summary length: {len(summary)} chars")

        # Display summary
        display = summarize_for_display(ticket, max_display_length=50)
        print(f"Display: {display}")

        # Stats
        stats = get_summary_stats(ticket["body"], summary)
        print(f"Compression: {stats['compression_ratio']:.1f}x")

    print("\nDone!")
