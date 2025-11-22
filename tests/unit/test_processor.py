"""Unit tests for ML processor components.

Tests cover:
- Model loading and caching
- Embedding generation
- Classification (intent, urgency, sentiment)
- Summarization
- Worker orchestration components
"""
import json
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from typing import Dict, Any

import numpy as np

from src.processor.models import (
    get_model_info,
    check_model_availability,
    MODEL_CONFIGS
)
from src.processor.embeddings import (
    generate_ticket_embedding,
    batch_generate_embeddings,
    compute_similarity,
    find_similar_tickets,
    get_embedding_stats
)
from src.processor.classifier import (
    classify_intent,
    classify_urgency,
    classify_sentiment,
    get_classification_summary
)
from src.processor.summarizer import (
    generate_summary,
    generate_summaries_batch,
    get_summary_stats,
    summarize_for_display
)


# Test fixtures
@pytest.fixture
def sample_ticket():
    """Standard test ticket."""
    return {
        "ticket_id": "TEST-001",
        "subject": "Cannot login to account",
        "body": "I've been trying to login for hours but keep getting an error message. This is urgent!",
        "priority": "high",
        "created_at": 1234567890,
        "customer_id": "CUST-123",
        "metadata": {
            "source": "email",
            "language": "en",
            "tags": []
        }
    }


@pytest.fixture
def short_ticket():
    """Short ticket for edge case testing."""
    return {
        "ticket_id": "TEST-002",
        "subject": "Quick question",
        "body": "How do I reset password?",
        "created_at": 1234567890,
        "customer_id": "CUST-456",
        "metadata": {"source": "web", "language": "en", "tags": []}
    }


@pytest.fixture
def empty_ticket():
    """Empty ticket for edge case testing."""
    return {
        "ticket_id": "TEST-003",
        "subject": "",
        "body": "",
        "created_at": 1234567890,
        "customer_id": "CUST-789",
        "metadata": {"source": "api", "language": "en", "tags": []}
    }


@pytest.fixture
def mock_embedding_model():
    """Mock SentenceTransformer model."""
    mock = MagicMock()
    # Return realistic 384-dim embedding
    mock.encode.return_value = np.random.randn(384).astype(np.float32)
    return mock


@pytest.fixture
def mock_classifier_pipeline():
    """Mock HuggingFace classification pipeline."""
    mock = MagicMock()
    mock.return_value = [{"label": "POSITIVE", "score": 0.85}]
    return mock


@pytest.fixture
def mock_summarizer_pipeline():
    """Mock HuggingFace summarization pipeline."""
    mock = MagicMock()
    mock.return_value = [{"summary_text": "User cannot login to account due to error."}]
    return mock


# ============================================================================
# Model Loading Tests
# ============================================================================

class TestModelLoading:
    """Tests for model loading utilities."""

    def test_get_model_info(self):
        """Test model info retrieval."""
        info = get_model_info()

        assert "cache_dir" in info
        assert "device" in info
        assert "pytorch_version" in info
        assert "models" in info
        assert "total_size_mb" in info

        # Check device is CPU
        assert info["device"] == "cpu"

        # Check models are present
        assert "embeddings" in info["models"]
        assert "classifier" in info["models"]
        assert "summarizer" in info["models"]

        # Check total size calculation
        expected_size = sum(m["size_mb"] for m in MODEL_CONFIGS.values())
        assert info["total_size_mb"] == expected_size

    @patch('src.processor.models.load_embedding_model')
    @patch('src.processor.models.load_classifier_pipeline')
    @patch('src.processor.models.load_summarizer_pipeline')
    def test_check_model_availability_success(self, mock_summ, mock_class, mock_emb):
        """Test successful model availability check."""
        mock_emb.return_value = MagicMock()
        mock_class.return_value = MagicMock()
        mock_summ.return_value = MagicMock()

        results = check_model_availability()

        assert results["embeddings"] is True
        assert results["classifier"] is True
        assert results["summarizer"] is True

    @patch('src.processor.models.load_embedding_model')
    def test_check_model_availability_failure(self, mock_emb):
        """Test model availability check with failure."""
        mock_emb.side_effect = Exception("Download failed")

        results = check_model_availability()

        assert results["embeddings"] is False


# ============================================================================
# Embedding Tests
# ============================================================================

class TestEmbeddings:
    """Tests for embedding generation."""

    @patch('src.processor.embeddings.load_embedding_model')
    def test_generate_ticket_embedding(self, mock_load, sample_ticket, mock_embedding_model):
        """Test single ticket embedding generation."""
        mock_load.return_value = mock_embedding_model

        embedding = generate_ticket_embedding(sample_ticket)

        # Check output format
        assert isinstance(embedding, list)
        assert len(embedding) == 384
        assert all(isinstance(x, float) for x in embedding)

        # Check model was called with combined text
        mock_embedding_model.encode.assert_called_once()
        call_text = mock_embedding_model.encode.call_args[0][0]
        assert sample_ticket["subject"] in call_text
        assert sample_ticket["body"] in call_text

    @patch('src.processor.embeddings.load_embedding_model')
    def test_generate_embedding_empty_ticket(self, mock_load, empty_ticket, mock_embedding_model):
        """Test embedding generation for empty ticket."""
        mock_load.return_value = mock_embedding_model

        embedding = generate_ticket_embedding(empty_ticket)

        # Should return zero vector for empty text
        assert len(embedding) == 384
        assert all(x == 0.0 for x in embedding)

    @patch('src.processor.embeddings.load_embedding_model')
    def test_batch_generate_embeddings(self, mock_load, sample_ticket, short_ticket):
        """Test batch embedding generation."""
        mock_model = MagicMock()
        # Return batch of embeddings
        mock_model.encode.return_value = np.random.randn(2, 384).astype(np.float32)
        mock_load.return_value = mock_model

        tickets = [sample_ticket, short_ticket]
        embeddings = batch_generate_embeddings(tickets)

        assert len(embeddings) == 2
        assert all(len(emb) == 384 for emb in embeddings)

        # Check batch processing was used
        mock_model.encode.assert_called_once()
        call_kwargs = mock_model.encode.call_args[1]
        assert call_kwargs["batch_size"] == 32

    def test_compute_similarity_identical(self):
        """Test cosine similarity for identical vectors."""
        embedding = [1.0] * 384
        similarity = compute_similarity(embedding, embedding)

        assert similarity == pytest.approx(1.0, abs=1e-6)

    def test_compute_similarity_orthogonal(self):
        """Test cosine similarity for orthogonal vectors."""
        emb1 = [1.0] + [0.0] * 383
        emb2 = [0.0, 1.0] + [0.0] * 382

        similarity = compute_similarity(emb1, emb2)

        assert similarity == pytest.approx(0.0, abs=1e-6)

    def test_compute_similarity_opposite(self):
        """Test cosine similarity for opposite vectors."""
        emb1 = [1.0] * 384
        emb2 = [-1.0] * 384

        similarity = compute_similarity(emb1, emb2)

        assert similarity == pytest.approx(-1.0, abs=1e-6)

    def test_find_similar_tickets(self):
        """Test finding similar tickets."""
        query_emb = [1.0] * 384

        # Create ticket embeddings with varying similarity
        tickets = [
            {"ticket_id": "T1", "embedding": [0.9] * 384},  # High similarity
            {"ticket_id": "T2", "embedding": [0.5] * 384},  # Medium similarity
            {"ticket_id": "T3", "embedding": [-1.0] * 384},  # Opposite (low)
            {"ticket_id": "T4", "embedding": [0.1] * 384},  # Low similarity
        ]

        similar = find_similar_tickets(query_emb, tickets, top_k=2, min_similarity=0.5)

        # Should return top 2 above threshold
        assert len(similar) <= 2
        assert all("similarity" in t for t in similar)
        assert all(t["similarity"] >= 0.5 for t in similar)

        # Should be sorted by similarity (highest first)
        if len(similar) == 2:
            assert similar[0]["similarity"] >= similar[1]["similarity"]

    def test_get_embedding_stats(self):
        """Test embedding statistics calculation."""
        embeddings = [
            [1.0] * 384,
            [2.0] * 384,
            [3.0] * 384
        ]

        stats = get_embedding_stats(embeddings)

        assert stats["count"] == 3
        assert stats["dimension"] == 384
        assert "norm_mean" in stats
        assert "norm_std" in stats
        assert stats["norm_min"] <= stats["norm_max"]

    def test_get_embedding_stats_empty(self):
        """Test embedding statistics for empty list."""
        stats = get_embedding_stats([])

        assert stats["count"] == 0
        assert stats["dimension"] == 0
        assert stats["norm_mean"] == 0.0


# ============================================================================
# Classification Tests
# ============================================================================

class TestClassification:
    """Tests for ticket classification."""

    def test_classify_intent_login_issue(self):
        """Test intent classification for login issues."""
        ticket = {
            "subject": "Cannot login",
            "body": "Getting authentication error when trying to access my account"
        }

        intent, confidence = classify_intent(ticket)

        assert intent == "login_issue"
        assert 0.0 <= confidence <= 1.0
        assert confidence > 0.5  # Should have high confidence

    def test_classify_intent_payment_issue(self):
        """Test intent classification for payment issues."""
        ticket = {
            "subject": "Payment failed",
            "body": "My credit card was declined but money was charged. Need refund!"
        }

        intent, confidence = classify_intent(ticket)

        assert intent == "payment_issue"
        assert confidence > 0.5

    def test_classify_intent_bug_report(self):
        """Test intent classification for bug reports."""
        ticket = {
            "subject": "Application crash",
            "body": "The app keeps crashing when I try to open it. Getting error code 500."
        }

        intent, confidence = classify_intent(ticket)

        assert intent == "bug_report"
        assert confidence > 0.5

    def test_classify_intent_feature_request(self):
        """Test intent classification for feature requests."""
        ticket = {
            "subject": "Feature suggestion",
            "body": "Would love to see dark mode added. Nice to have enhancement."
        }

        intent, confidence = classify_intent(ticket)

        assert intent == "feature_request"
        assert confidence > 0.5

    def test_classify_intent_general(self):
        """Test intent classification for general inquiry."""
        ticket = {
            "subject": "Hello",
            "body": "I have a question about your service."
        }

        intent, confidence = classify_intent(ticket)

        assert intent == "general_inquiry"
        assert confidence >= 0.5

    def test_classify_intent_empty(self):
        """Test intent classification for empty ticket."""
        ticket = {"subject": "", "body": ""}

        intent, confidence = classify_intent(ticket)

        assert intent == "general_inquiry"
        assert confidence == 0.0

    def test_classify_urgency_critical(self):
        """Test urgency classification for critical tickets."""
        ticket = {
            "subject": "URGENT: System down",
            "body": "Our production system is completely down! Emergency!"
        }

        urgency, confidence = classify_urgency(ticket)

        assert urgency == "critical"
        assert confidence >= 0.8

    def test_classify_urgency_high(self):
        """Test urgency classification for high priority."""
        ticket = {
            "subject": "Important issue",
            "body": "This is a problem that needs help soon."
        }

        urgency, confidence = classify_urgency(ticket)

        assert urgency in ["critical", "high"]
        assert confidence > 0.5

    def test_classify_urgency_low(self):
        """Test urgency classification for low priority."""
        ticket = {
            "subject": "Feature suggestion",
            "body": "Nice to have when possible. No rush."
        }

        urgency, confidence = classify_urgency(ticket)

        assert urgency == "low"
        assert confidence >= 0.7

    def test_classify_urgency_explicit_priority(self):
        """Test urgency classification with explicit priority field."""
        ticket = {
            "subject": "Question",
            "body": "Just wondering about something",
            "priority": "critical"
        }

        urgency, confidence = classify_urgency(ticket)

        assert urgency == "critical"
        assert confidence == 1.0  # Explicit priority has full confidence

    def test_classify_urgency_default(self):
        """Test urgency classification default to medium."""
        ticket = {
            "subject": "Question",
            "body": "I have a question about features"
        }

        urgency, confidence = classify_urgency(ticket)

        # Should default to medium or match keyword
        assert urgency in ["medium", "low"]
        assert confidence >= 0.6

    @patch('src.processor.classifier.load_classifier_pipeline')
    def test_classify_sentiment_positive(self, mock_load, mock_classifier_pipeline):
        """Test sentiment classification for positive ticket."""
        mock_classifier_pipeline.return_value = [{"label": "POSITIVE", "score": 0.95}]
        mock_load.return_value = mock_classifier_pipeline

        ticket = {
            "subject": "Great service!",
            "body": "Thank you for the excellent support!"
        }

        sentiment, confidence = classify_sentiment(ticket)

        assert sentiment == "POSITIVE"
        assert confidence == pytest.approx(0.95)

    @patch('src.processor.classifier.load_classifier_pipeline')
    def test_classify_sentiment_negative(self, mock_load, mock_classifier_pipeline):
        """Test sentiment classification for negative ticket."""
        mock_classifier_pipeline.return_value = [{"label": "NEGATIVE", "score": 0.88}]
        mock_load.return_value = mock_classifier_pipeline

        ticket = {
            "subject": "Terrible experience",
            "body": "Very disappointed with the service."
        }

        sentiment, confidence = classify_sentiment(ticket)

        assert sentiment == "NEGATIVE"
        assert confidence == pytest.approx(0.88)

    @patch('src.processor.classifier.load_classifier_pipeline')
    def test_classify_sentiment_neutral_threshold(self, mock_load, mock_classifier_pipeline):
        """Test sentiment classification maps near 0.5 to neutral."""
        mock_classifier_pipeline.return_value = [{"label": "POSITIVE", "score": 0.51}]
        mock_load.return_value = mock_classifier_pipeline

        ticket = {
            "subject": "Question",
            "body": "I have a question."
        }

        sentiment, confidence = classify_sentiment(ticket)

        assert sentiment == "NEUTRAL"
        assert confidence == 0.5

    @patch('src.processor.classifier.load_classifier_pipeline')
    def test_classify_sentiment_empty(self, mock_load):
        """Test sentiment classification for empty ticket."""
        mock_load.return_value = MagicMock()

        ticket = {"subject": "", "body": ""}

        sentiment, confidence = classify_sentiment(ticket)

        assert sentiment == "NEUTRAL"
        assert confidence == 0.5

    @patch('src.processor.classifier.load_classifier_pipeline')
    def test_get_classification_summary(self, mock_load, mock_classifier_pipeline, sample_ticket):
        """Test complete classification summary."""
        mock_classifier_pipeline.return_value = [{"label": "NEGATIVE", "score": 0.75}]
        mock_load.return_value = mock_classifier_pipeline

        summary = get_classification_summary(sample_ticket)

        # Check all fields present
        assert "intent" in summary
        assert "intent_confidence" in summary
        assert "urgency" in summary
        assert "urgency_confidence" in summary
        assert "sentiment" in summary
        assert "sentiment_confidence" in summary

        # Check types
        assert isinstance(summary["intent"], str)
        assert isinstance(summary["intent_confidence"], float)
        assert isinstance(summary["urgency"], str)
        assert isinstance(summary["urgency_confidence"], float)
        assert isinstance(summary["sentiment"], str)
        assert isinstance(summary["sentiment_confidence"], float)

        # Check intent is login_issue (from "Cannot login" subject)
        assert summary["intent"] == "login_issue"


# ============================================================================
# Summarization Tests
# ============================================================================

class TestSummarization:
    """Tests for ticket summarization."""

    @patch('src.processor.summarizer.load_summarizer_pipeline')
    def test_generate_summary(self, mock_load, mock_summarizer_pipeline):
        """Test summary generation for standard ticket."""
        mock_load.return_value = mock_summarizer_pipeline

        # Create ticket with >20 words to trigger summarization
        ticket = {
            "ticket_id": "TEST-001",
            "subject": "Cannot login to account",
            "body": "I have been trying to login to my account for several hours now but I keep getting an error message saying invalid credentials. I am certain that I am using the correct password because I have it saved in my password manager. This is very urgent as I need access for an important meeting."
        }

        summary = generate_summary(ticket)

        assert isinstance(summary, str)
        assert len(summary) > 0

        # Check summarizer was called
        mock_summarizer_pipeline.assert_called_once()

        # Check summary ends with punctuation
        assert summary[-1] in ".!?"

    @patch('src.processor.summarizer.load_summarizer_pipeline')
    def test_generate_summary_short_ticket(self, mock_load, short_ticket):
        """Test summary generation for short ticket."""
        mock_load.return_value = MagicMock()

        summary = generate_summary(short_ticket)

        # For short tickets, should return subject
        assert summary == short_ticket["subject"]

        # Summarizer should not be called for very short tickets
        mock_load.return_value.assert_not_called()

    @patch('src.processor.summarizer.load_summarizer_pipeline')
    def test_generate_summary_empty_ticket(self, mock_load, empty_ticket):
        """Test summary generation for empty ticket."""
        mock_load.return_value = MagicMock()

        summary = generate_summary(empty_ticket)

        # Should return empty string for empty ticket
        assert summary == ""

    @patch('src.processor.summarizer.load_summarizer_pipeline')
    def test_generate_summary_custom_length(self, mock_load, mock_summarizer_pipeline):
        """Test summary generation with custom max length."""
        mock_load.return_value = mock_summarizer_pipeline

        # Create ticket with >20 words to trigger summarization
        ticket = {
            "ticket_id": "TEST-001",
            "subject": "Payment issue",
            "body": "I tried to make a payment yesterday but my credit card was declined. However, when I checked my bank statement this morning, I saw that the money was actually deducted from my account. I need this resolved urgently and would like a refund processed as soon as possible."
        }

        generate_summary(ticket, max_length=100, min_length=20)

        # Check max_length was passed to summarizer
        call_kwargs = mock_summarizer_pipeline.call_args[1]
        assert call_kwargs["max_length"] == 100
        assert call_kwargs["min_length"] == 20

    @patch('src.processor.summarizer.load_summarizer_pipeline')
    def test_generate_summary_truncates_long_text(self, mock_load, mock_summarizer_pipeline):
        """Test summary generation truncates very long tickets."""
        mock_load.return_value = mock_summarizer_pipeline

        # Create ticket with >700 words
        long_body = " ".join(["word"] * 1000)
        ticket = {
            "subject": "Long ticket",
            "body": long_body
        }

        generate_summary(ticket)

        # Check text was truncated before passing to summarizer
        call_text = mock_summarizer_pipeline.call_args[0][0]
        assert len(call_text.split()) <= 700

    @patch('src.processor.summarizer.load_summarizer_pipeline')
    def test_generate_summary_fallback_on_error(self, mock_load, sample_ticket):
        """Test summary generation fallback on error."""
        mock_pipeline = MagicMock()
        mock_pipeline.side_effect = Exception("Model error")
        mock_load.return_value = mock_pipeline

        summary = generate_summary(sample_ticket)

        # Should return truncated subject as fallback
        assert summary == sample_ticket["subject"][:100]

    @patch('src.processor.summarizer.load_summarizer_pipeline')
    def test_generate_summaries_batch(self, mock_load, sample_ticket, short_ticket):
        """Test batch summary generation."""
        mock_pipeline = MagicMock()
        mock_pipeline.return_value = [{"summary_text": "Summary text."}]
        mock_load.return_value = mock_pipeline

        tickets = [sample_ticket, short_ticket]
        summaries = generate_summaries_batch(tickets)

        assert len(summaries) == len(tickets)
        assert all(isinstance(s, str) for s in summaries)

    @patch('src.processor.summarizer.load_summarizer_pipeline')
    def test_generate_summaries_batch_with_failures(self, mock_load, sample_ticket):
        """Test batch summary generation handles individual failures."""
        mock_pipeline = MagicMock()
        mock_pipeline.side_effect = Exception("Model error")
        mock_load.return_value = mock_pipeline

        tickets = [sample_ticket]
        summaries = generate_summaries_batch(tickets)

        # Should have fallback summary
        assert len(summaries) == 1
        assert summaries[0] == sample_ticket["subject"][:100]

    def test_get_summary_stats(self):
        """Test summary compression statistics."""
        original = "This is a very long text " * 20
        summary = "Short summary"

        stats = get_summary_stats(original, summary)

        assert stats["original_words"] > stats["summary_words"]
        assert stats["original_chars"] > stats["summary_chars"]
        assert stats["compression_ratio"] > 1.0
        assert stats["word_reduction"] > 0
        assert stats["char_reduction"] > 0

    @patch('src.processor.summarizer.load_summarizer_pipeline')
    def test_summarize_for_display(self, mock_load, mock_summarizer_pipeline, sample_ticket):
        """Test ultra-short summary for display."""
        mock_load.return_value = mock_summarizer_pipeline

        display = summarize_for_display(sample_ticket, max_display_length=50)

        assert len(display) <= 50

        # If truncated, should end with "..."
        if len(display) == 50:
            assert display.endswith("...")

    @patch('src.processor.summarizer.load_summarizer_pipeline')
    def test_summarize_for_display_short_summary(self, mock_load):
        """Test display summary when full summary already fits."""
        mock_pipeline = MagicMock()
        mock_pipeline.return_value = [{"summary_text": "Short."}]
        mock_load.return_value = mock_pipeline

        ticket = {
            "subject": "Test",
            "body": "This is a test ticket with enough words to trigger summarization."
        }

        display = summarize_for_display(ticket, max_display_length=100)

        # Summary should fit without truncation
        assert len(display) <= 100
        assert not display.endswith("...")


# ============================================================================
# Worker Tests
# ============================================================================

class TestWorker:
    """Tests for worker orchestration components."""

    @patch('src.processor.worker.get_s3_client')
    def test_fetch_ticket_from_s3(self, mock_get_s3, sample_ticket):
        """Test fetching ticket from S3."""
        from src.processor.worker import TicketProcessor

        # Mock S3 client
        mock_s3 = MagicMock()
        mock_response = {
            "Body": MagicMock(read=lambda: json.dumps(sample_ticket).encode('utf-8'))
        }
        mock_s3.get_object.return_value = mock_response
        mock_get_s3.return_value = mock_s3

        # Mock other clients
        with patch('src.processor.worker.get_sqs_client'), \
             patch('src.processor.worker.get_dynamodb_resource'):

            processor = TicketProcessor()
            processor.s3 = mock_s3

            ticket = processor.fetch_ticket_from_s3("test-bucket", "test-key")

            assert ticket["ticket_id"] == sample_ticket["ticket_id"]
            mock_s3.get_object.assert_called_once_with(
                Bucket="test-bucket",
                Key="test-key"
            )

    def test_worker_stats_initialization(self):
        """Test worker statistics initialization."""
        from src.processor.worker import TicketProcessor

        with patch('src.processor.worker.get_s3_client'), \
             patch('src.processor.worker.get_sqs_client'), \
             patch('src.processor.worker.get_dynamodb_resource'):

            processor = TicketProcessor()

            assert processor.stats["tickets_processed"] == 0
            assert processor.stats["tickets_failed"] == 0
            assert "start_time" in processor.stats


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
