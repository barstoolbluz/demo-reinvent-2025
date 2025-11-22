"""Ticket intent and urgency classification.

This module classifies tickets using:
1. Keyword-based intent detection (login, payment, bug, etc.)
2. Keyword-based urgency detection (critical, high, medium, low)
3. ML-based sentiment analysis (positive, negative, neutral)
"""
import logging
import re
from typing import Dict, Any, Tuple

from src.processor.models import load_classifier_pipeline

logger = logging.getLogger(__name__)


# Intent classification keywords
INTENT_KEYWORDS = {
    "login_issue": [
        "login", "log in", "sign in", "signin", "password", "credentials",
        "authentication", "auth", "access denied", "locked out", "2fa", "mfa"
    ],
    "payment_issue": [
        "payment", "charge", "charged", "refund", "billing", "invoice",
        "transaction", "credit card", "debit", "declined", "failed payment"
    ],
    "bug_report": [
        "bug", "error", "crash", "broken", "not working", "doesn't work",
        "issue", "problem", "glitch", "freeze", "hang", "exception"
    ],
    "feature_request": [
        "feature", "request", "enhancement", "add", "support for", "would love",
        "suggestion", "improve", "could you add", "wish"
    ],
    "account_management": [
        "account", "profile", "settings", "update", "change", "delete",
        "deactivate", "email address", "phone number", "password reset"
    ],
    "performance_issue": [
        "slow", "performance", "loading", "timeout", "lag", "delay",
        "hanging", "speed", "takes too long"
    ],
    "security_concern": [
        "security", "hack", "hacked", "unauthorized", "breach", "suspicious",
        "fraud", "scam", "phishing", "malware", "virus"
    ],
    "data_request": [
        "data", "export", "download", "gdpr", "privacy", "information",
        "personal data", "data protection"
    ],
    "integration_help": [
        "integration", "api", "webhook", "oauth", "sdk", "plugin",
        "third party", "connect", "sync"
    ]
}


# Urgency classification keywords
URGENCY_KEYWORDS = {
    "critical": [
        "urgent", "critical", "emergency", "asap", "immediately", "right now",
        "down", "outage", "broken", "can't access", "unable to", "blocked",
        "losing money", "production", "hacked", "security breach"
    ],
    "high": [
        "important", "need help", "problem", "issue", "can't", "cannot",
        "doesn't work", "not working", "error", "failing", "soon",
        "business impact"
    ],
    "medium": [
        "question", "how to", "how do i", "help", "assistance",
        "wondering", "clarify", "explain"
    ],
    "low": [
        "suggestion", "feature", "enhancement", "when possible",
        "sometime", "eventually", "minor", "nice to have"
    ]
}


def classify_intent(ticket: Dict[str, Any]) -> Tuple[str, float]:
    """
    Classify ticket intent using keyword matching.

    Args:
        ticket: Ticket dict with 'subject' and 'body'

    Returns:
        Tuple of (intent_label, confidence_score)
        intent_label: One of the INTENT_KEYWORDS keys or 'general_inquiry'
        confidence_score: Float between 0.0 and 1.0

    Example:
        >>> ticket = {"subject": "Cannot login", "body": "Getting error"}
        >>> intent, conf = classify_intent(ticket)
        >>> intent
        'login_issue'
        >>> conf > 0.5
        True
    """
    # Combine subject and body, lowercase for matching
    subject = ticket.get("subject", "")
    body = ticket.get("body", "")
    text = f"{subject} {body}".lower()

    if not text.strip():
        return "general_inquiry", 0.0

    # Score each intent category
    intent_scores = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            # Use word boundaries for more accurate matching
            pattern = r'\b' + re.escape(keyword) + r'\b'
            matches = len(re.findall(pattern, text))
            score += matches

        if score > 0:
            intent_scores[intent] = score

    if not intent_scores:
        return "general_inquiry", 0.5

    # Best intent is the one with highest score
    best_intent = max(intent_scores, key=intent_scores.get)
    best_score = intent_scores[best_intent]

    # Normalize confidence: cap at 1.0, scale by number of keyword matches
    # More matches = higher confidence
    confidence = min(best_score / 3.0, 1.0)

    logger.debug(f"Intent: {best_intent} (confidence: {confidence:.2f}, matches: {best_score})")

    return best_intent, confidence


def classify_urgency(ticket: Dict[str, Any]) -> Tuple[str, float]:
    """
    Classify ticket urgency using keywords and explicit priority field.

    Args:
        ticket: Ticket dict with optional 'priority', 'subject', 'body'

    Returns:
        Tuple of (urgency_level, confidence_score)
        urgency_level: 'critical', 'high', 'medium', or 'low'
        confidence_score: Float between 0.0 and 1.0

    Priority:
        1. Explicit 'priority' field (confidence 1.0)
        2. Keyword matching in subject/body (confidence 0.7-0.9)
        3. Default to 'medium' (confidence 0.6)

    Example:
        >>> ticket = {"subject": "URGENT: System down", "body": "Emergency!"}
        >>> urgency, conf = classify_urgency(ticket)
        >>> urgency
        'critical'
    """
    # Check explicit priority field first
    explicit_priority = ticket.get("priority", "").lower()
    if explicit_priority in ["critical", "high", "medium", "low"]:
        logger.debug(f"Using explicit priority: {explicit_priority}")
        return explicit_priority, 1.0

    # Keyword-based urgency detection
    subject = ticket.get("subject", "")
    body = ticket.get("body", "")
    text = f"{subject} {body}".lower()

    if not text.strip():
        return "medium", 0.6

    # Check urgency levels from highest to lowest
    for urgency_level in ["critical", "high", "medium", "low"]:
        keywords = URGENCY_KEYWORDS[urgency_level]
        for keyword in keywords:
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, text):
                # Higher urgency gets higher confidence
                confidence = {
                    "critical": 0.9,
                    "high": 0.8,
                    "medium": 0.7,
                    "low": 0.7
                }[urgency_level]

                logger.debug(f"Urgency: {urgency_level} (keyword: {keyword})")
                return urgency_level, confidence

    # Default to medium if no keywords match
    return "medium", 0.6


def classify_sentiment(ticket: Dict[str, Any]) -> Tuple[str, float]:
    """
    Classify ticket sentiment using DistilBERT model.

    Args:
        ticket: Ticket dict with 'subject' and 'body'

    Returns:
        Tuple of (sentiment_label, confidence_score)
        sentiment_label: 'POSITIVE', 'NEGATIVE', or 'NEUTRAL'
        confidence_score: Float between 0.0 and 1.0

    Note:
        Uses HuggingFace transformers pipeline for sentiment analysis.
        The model is trained on SST-2 (movie reviews) so may not be
        perfectly calibrated for support tickets, but provides useful signal.

    Example:
        >>> ticket = {"subject": "Great service!", "body": "Thanks for help"}
        >>> sentiment, conf = classify_sentiment(ticket)
        >>> sentiment
        'POSITIVE'
    """
    classifier = load_classifier_pipeline()

    # Combine subject and body
    subject = ticket.get("subject", "")
    body = ticket.get("body", "")
    text = f"{subject}. {body}" if subject and body else subject or body

    if not text.strip():
        return "NEUTRAL", 0.5

    # Truncate to model max length (512 tokens for DistilBERT)
    # Roughly 512 tokens ≈ 400 words
    words = text.split()
    if len(words) > 400:
        text = " ".join(words[:400])

    logger.debug(f"Classifying sentiment for ticket: {ticket.get('ticket_id', 'unknown')}")

    try:
        # Get prediction
        result = classifier(text)[0]

        # DistilBERT returns 'POSITIVE' or 'NEGATIVE'
        # Map labels
        label = result["label"].upper()
        score = float(result["score"])

        # If score is close to 0.5, treat as NEUTRAL
        if 0.45 <= score <= 0.55:
            label = "NEUTRAL"
            score = 0.5

        logger.debug(f"Sentiment: {label} (confidence: {score:.2f})")

        return label, score

    except Exception as e:
        logger.error(f"Failed to classify sentiment: {e}")
        # Return neutral on error
        return "NEUTRAL", 0.5


def get_classification_summary(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run all classification pipelines and return complete summary.

    Args:
        ticket: Ticket dict

    Returns:
        Dict with intent, urgency, sentiment and their confidence scores

    Example:
        >>> ticket = {"subject": "Urgent: Login broken", "body": "..."}
        >>> summary = get_classification_summary(ticket)
        >>> summary.keys()
        dict_keys(['intent', 'intent_confidence', 'urgency', ...])
    """
    intent, intent_conf = classify_intent(ticket)
    urgency, urgency_conf = classify_urgency(ticket)
    sentiment, sentiment_conf = classify_sentiment(ticket)

    return {
        "intent": intent,
        "intent_confidence": intent_conf,
        "urgency": urgency,
        "urgency_confidence": urgency_conf,
        "sentiment": sentiment,
        "sentiment_confidence": sentiment_conf
    }


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)

    print("Testing classification...")
    print("-" * 60)

    # Test tickets
    test_tickets = [
        {
            "ticket_id": "TEST-001",
            "subject": "URGENT: Cannot login to account",
            "body": "I've been trying to login for hours. This is critical!",
        },
        {
            "ticket_id": "TEST-002",
            "subject": "Feature request: Dark mode",
            "body": "Would love to see a dark mode option. Nice to have.",
            "priority": "low"
        },
        {
            "ticket_id": "TEST-003",
            "subject": "Payment failed",
            "body": "Transaction was declined but money was charged. Need refund!",
        }
    ]

    for ticket in test_tickets:
        print(f"\nTicket: {ticket['subject']}")
        print("-" * 60)

        summary = get_classification_summary(ticket)
        for key, value in summary.items():
            if isinstance(value, float):
                print(f"  {key}: {value:.2f}")
            else:
                print(f"  {key}: {value}")

    print("\nDone!")
