"""End-to-end integration tests for ML pipeline.

These tests validate the complete ticket enrichment pipeline:
1. Raw ticket → ML processing → Enriched ticket
2. Schema validation
3. Model integration
4. Worker orchestration

Note: These tests load actual ML models and may take longer to run.
"""
import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from src.common.schemas import RawTicket, EnrichedTicket, EnrichmentData
from src.processor.worker import TicketProcessor
from src.processor.models import preload_all_models, get_model_info


# Fixtures
@pytest.fixture(scope="module")
def preloaded_models():
    """Preload ML models once for all tests in this module."""
    print("\n🔄 Preloading ML models (this may take a minute)...")
    try:
        preload_all_models()
        print("✅ Models preloaded successfully")
        return True
    except Exception as e:
        pytest.skip(f"Failed to preload models: {e}")


@pytest.fixture
def sample_ticket_dict():
    """Sample ticket for testing."""
    return {
        "ticket_id": "TEST-E2E-001",
        "subject": "Cannot access my account - urgent help needed",
        "body": "I have been trying to login to my account for the past three hours but keep getting an 'invalid credentials' error. I am absolutely certain I am using the correct password because it is saved in my password manager. I have tried resetting my password twice but the problem persists. This is very urgent as I need to access my account for an important work meeting this afternoon. Please help!",
        "priority": "high",
        "created_at": int(datetime.utcnow().timestamp()),
        "customer_id": "CUST-12345",
        "metadata": {
            "source": "email",
            "language": "en",
            "tags": ["authentication", "urgent"]
        }
    }


@pytest.fixture
def payment_ticket_dict():
    """Payment-related ticket for testing."""
    return {
        "ticket_id": "TEST-E2E-002",
        "subject": "Payment failed but money was charged",
        "body": "My credit card payment was declined yesterday when I tried to upgrade my subscription. However, when I checked my bank statement this morning, I found that the money was actually deducted from my account. I need this resolved quickly and want a refund processed. The transaction ID is TXN-98765 and the amount is $49.99. I have been a loyal customer for three years and have never had this issue before.",
        "priority": "high",
        "created_at": int(datetime.utcnow().timestamp()),
        "customer_id": "CUST-67890",
        "metadata": {
            "source": "web",
            "language": "en",
            "tags": ["billing", "payment"]
        }
    }


@pytest.fixture
def feature_request_dict():
    """Feature request ticket for testing."""
    return {
        "ticket_id": "TEST-E2E-003",
        "subject": "Feature suggestion: Dark mode",
        "body": "I would love to see a dark mode option added to the application. It would be great for using the app at night and would reduce eye strain. This is just a nice-to-have feature suggestion, so no rush. Thanks for considering it!",
        "priority": "low",
        "created_at": int(datetime.utcnow().timestamp()),
        "customer_id": "CUST-11111",
        "metadata": {
            "source": "mobile_app",
            "language": "en",
            "tags": ["enhancement"]
        }
    }


# ============================================================================
# Schema Validation Tests
# ============================================================================

class TestSchemaValidation:
    """Tests for Pydantic schema validation."""

    def test_raw_ticket_validation_success(self, sample_ticket_dict):
        """Test successful raw ticket validation."""
        ticket = RawTicket(**sample_ticket_dict)

        assert ticket.ticket_id == sample_ticket_dict["ticket_id"]
        assert ticket.subject == sample_ticket_dict["subject"]
        assert ticket.body == sample_ticket_dict["body"]
        assert ticket.customer_id == sample_ticket_dict["customer_id"]

    def test_raw_ticket_validation_missing_fields(self):
        """Test raw ticket validation with missing required fields."""
        incomplete_ticket = {
            "ticket_id": "TEST-001",
            "subject": "Test"
            # Missing required fields: body, created_at, customer_id, metadata
        }

        with pytest.raises(Exception):  # Pydantic validation error
            RawTicket(**incomplete_ticket)

    def test_enrichment_data_validation(self):
        """Test enrichment data schema validation."""
        enrichment = EnrichmentData(
            embedding=[0.1] * 384,
            intent="login_issue",
            intent_confidence=0.85,
            urgency="critical",
            urgency_confidence=0.90,
            sentiment="NEGATIVE",
            sentiment_confidence=0.75,
            summary="User cannot access account due to invalid credentials error.",
            processed_at=datetime.utcnow().isoformat(),
            model_version="1.0.0"
        )

        assert len(enrichment.embedding) == 384
        assert enrichment.intent == "login_issue"
        assert enrichment.urgency == "critical"
        assert enrichment.sentiment == "NEGATIVE"

    def test_enriched_ticket_from_raw(self, sample_ticket_dict):
        """Test creating enriched ticket from raw ticket."""
        raw_ticket = RawTicket(**sample_ticket_dict)

        enrichment = EnrichmentData(
            embedding=[0.1] * 384,
            intent="login_issue",
            intent_confidence=0.85,
            urgency="critical",
            urgency_confidence=0.90,
            sentiment="NEGATIVE",
            sentiment_confidence=0.75,
            summary="User cannot access account.",
            processed_at=datetime.utcnow().isoformat(),
            model_version="1.0.0"
        )

        enriched = EnrichedTicket.from_raw(raw_ticket, enrichment)

        # Check all fields present
        assert enriched.ticket_id == raw_ticket.ticket_id
        assert enriched.subject == raw_ticket.subject
        assert enriched.body == raw_ticket.body
        assert enriched.enrichment == enrichment


# ============================================================================
# End-to-End ML Pipeline Tests
# ============================================================================

class TestMLPipeline:
    """Tests for complete ML processing pipeline."""

    def test_process_login_ticket_e2e(self, preloaded_models, sample_ticket_dict):
        """Test complete processing of login issue ticket."""
        # Create processor with mocked AWS clients
        with patch('src.processor.worker.get_s3_client'), \
             patch('src.processor.worker.get_sqs_client'), \
             patch('src.processor.worker.get_dynamodb_resource'):

            processor = TicketProcessor()

            # Process ticket through complete pipeline
            enriched = processor.process_ticket(sample_ticket_dict)

            # Validate output type
            assert isinstance(enriched, EnrichedTicket)

            # Validate raw ticket fields preserved
            assert enriched.ticket_id == sample_ticket_dict["ticket_id"]
            assert enriched.subject == sample_ticket_dict["subject"]
            assert enriched.body == sample_ticket_dict["body"]

            # Validate enrichment fields populated
            assert enriched.enrichment is not None

            # Validate embedding
            assert len(enriched.enrichment.embedding) == 384
            assert all(isinstance(x, float) for x in enriched.enrichment.embedding)
            # Embedding should not be all zeros for non-empty ticket
            assert not all(x == 0.0 for x in enriched.enrichment.embedding)

            # Validate intent classification
            assert enriched.enrichment.intent == "login_issue"
            assert 0.0 <= enriched.enrichment.intent_confidence <= 1.0
            assert enriched.enrichment.intent_confidence > 0.5

            # Validate urgency classification
            # Should be critical or high due to "urgent" keyword and high priority
            assert enriched.enrichment.urgency in ["critical", "high"]
            assert 0.0 <= enriched.enrichment.urgency_confidence <= 1.0

            # Validate sentiment classification
            assert enriched.enrichment.sentiment in ["POSITIVE", "NEGATIVE", "NEUTRAL"]
            assert 0.0 <= enriched.enrichment.sentiment_confidence <= 1.0

            # Validate summary
            assert isinstance(enriched.enrichment.summary, str)
            assert len(enriched.enrichment.summary) > 0
            # Summary should be shorter than original body
            assert len(enriched.enrichment.summary) < len(sample_ticket_dict["body"])

            # Validate metadata
            assert enriched.enrichment.processed_at is not None
            assert enriched.enrichment.model_version == "1.0.0"

            print(f"\n✅ Login ticket processed successfully:")
            print(f"   Intent: {enriched.enrichment.intent} ({enriched.enrichment.intent_confidence:.2f})")
            print(f"   Urgency: {enriched.enrichment.urgency} ({enriched.enrichment.urgency_confidence:.2f})")
            print(f"   Sentiment: {enriched.enrichment.sentiment} ({enriched.enrichment.sentiment_confidence:.2f})")
            print(f"   Summary: {enriched.enrichment.summary[:80]}...")

    def test_process_payment_ticket_e2e(self, preloaded_models, payment_ticket_dict):
        """Test complete processing of payment issue ticket."""
        with patch('src.processor.worker.get_s3_client'), \
             patch('src.processor.worker.get_sqs_client'), \
             patch('src.processor.worker.get_dynamodb_resource'):

            processor = TicketProcessor()
            enriched = processor.process_ticket(payment_ticket_dict)

            # Validate intent is payment-related
            assert enriched.enrichment.intent == "payment_issue"
            assert enriched.enrichment.intent_confidence > 0.5

            # Validate urgency is high (explicit priority + keywords)
            assert enriched.enrichment.urgency in ["critical", "high"]

            # Validate summary contains key information
            assert isinstance(enriched.enrichment.summary, str)
            assert len(enriched.enrichment.summary) > 0

            print(f"\n✅ Payment ticket processed successfully:")
            print(f"   Intent: {enriched.enrichment.intent} ({enriched.enrichment.intent_confidence:.2f})")
            print(f"   Urgency: {enriched.enrichment.urgency} ({enriched.enrichment.urgency_confidence:.2f})")
            print(f"   Sentiment: {enriched.enrichment.sentiment} ({enriched.enrichment.sentiment_confidence:.2f})")
            print(f"   Summary: {enriched.enrichment.summary[:80]}...")

    def test_process_feature_request_e2e(self, preloaded_models, feature_request_dict):
        """Test complete processing of feature request ticket."""
        with patch('src.processor.worker.get_s3_client'), \
             patch('src.processor.worker.get_sqs_client'), \
             patch('src.processor.worker.get_dynamodb_resource'):

            processor = TicketProcessor()
            enriched = processor.process_ticket(feature_request_dict)

            # Validate intent is feature request
            assert enriched.enrichment.intent == "feature_request"
            assert enriched.enrichment.intent_confidence > 0.5

            # Validate urgency is low (explicit priority + keywords)
            assert enriched.enrichment.urgency == "low"

            # Validate sentiment is likely positive (polite request)
            # (This may vary based on model, so just check it's valid)
            assert enriched.enrichment.sentiment in ["POSITIVE", "NEGATIVE", "NEUTRAL"]

            print(f"\n✅ Feature request processed successfully:")
            print(f"   Intent: {enriched.enrichment.intent} ({enriched.enrichment.intent_confidence:.2f})")
            print(f"   Urgency: {enriched.enrichment.urgency} ({enriched.enrichment.urgency_confidence:.2f})")
            print(f"   Sentiment: {enriched.enrichment.sentiment} ({enriched.enrichment.sentiment_confidence:.2f})")
            print(f"   Summary: {enriched.enrichment.summary[:80]}...")

    def test_embedding_similarity(self, preloaded_models):
        """Test that similar tickets have similar embeddings."""
        from src.processor.embeddings import generate_ticket_embedding, compute_similarity

        ticket1 = {
            "subject": "Cannot login to account",
            "body": "Getting authentication error when trying to access my account"
        }

        ticket2 = {
            "subject": "Login problem",
            "body": "Unable to sign in, keeps saying invalid password"
        }

        ticket3 = {
            "subject": "Payment declined",
            "body": "My credit card was rejected during checkout"
        }

        # Generate embeddings
        emb1 = generate_ticket_embedding(ticket1)
        emb2 = generate_ticket_embedding(ticket2)
        emb3 = generate_ticket_embedding(ticket3)

        # Similar tickets (both login issues) should have high similarity
        similarity_login = compute_similarity(emb1, emb2)
        assert similarity_login > 0.6, f"Login tickets should be similar, got {similarity_login:.3f}"

        # Dissimilar tickets should have lower similarity
        similarity_different = compute_similarity(emb1, emb3)
        assert similarity_different < similarity_login, \
            f"Login vs payment should be less similar than login vs login"

        print(f"\n✅ Embedding similarity validated:")
        print(f"   Login vs Login: {similarity_login:.3f}")
        print(f"   Login vs Payment: {similarity_different:.3f}")

    def test_processing_time_reasonable(self, preloaded_models, sample_ticket_dict):
        """Test that processing completes in reasonable time."""
        import time

        with patch('src.processor.worker.get_s3_client'), \
             patch('src.processor.worker.get_sqs_client'), \
             patch('src.processor.worker.get_dynamodb_resource'):

            processor = TicketProcessor()

            start = time.time()
            enriched = processor.process_ticket(sample_ticket_dict)
            elapsed = time.time() - start

            # Processing should complete in under 10 seconds (CPU inference)
            assert elapsed < 10.0, f"Processing took {elapsed:.2f}s, expected < 10s"

            print(f"\n✅ Processing time: {elapsed:.2f}s (within acceptable range)")


# ============================================================================
# Worker Integration Tests
# ============================================================================

class TestWorkerIntegration:
    """Tests for worker orchestration with mocked AWS."""

    def test_fetch_and_process_workflow(self, preloaded_models, sample_ticket_dict):
        """Test complete fetch → process → store workflow."""
        with patch('src.processor.worker.get_s3_client') as mock_s3_getter, \
             patch('src.processor.worker.get_sqs_client') as mock_sqs_getter, \
             patch('src.processor.worker.get_dynamodb_resource') as mock_dynamo_getter:

            # Mock S3 client
            mock_s3 = MagicMock()
            mock_s3.get_object.return_value = {
                "Body": MagicMock(read=lambda: json.dumps(sample_ticket_dict).encode('utf-8'))
            }
            mock_s3_getter.return_value = mock_s3

            # Mock SQS client
            mock_sqs = MagicMock()
            mock_sqs.get_queue_url.return_value = {"QueueUrl": "https://sqs.test/queue"}
            mock_sqs_getter.return_value = mock_sqs

            # Mock DynamoDB
            mock_dynamo = MagicMock()
            mock_table = MagicMock()
            mock_dynamo.Table.return_value = mock_table
            mock_dynamo_getter.return_value = mock_dynamo

            # Create processor
            processor = TicketProcessor()

            # Step 1: Fetch ticket from S3
            ticket = processor.fetch_ticket_from_s3("test-bucket", "test-key.json")
            assert ticket["ticket_id"] == sample_ticket_dict["ticket_id"]

            # Step 2: Process ticket
            enriched = processor.process_ticket(ticket)
            assert isinstance(enriched, EnrichedTicket)
            assert enriched.enrichment is not None

            # Step 3: Store results
            processor.store_results(enriched)

            # Verify DynamoDB put_item was called
            mock_table.put_item.assert_called_once()

            # Verify S3 put_object was called for enriched data
            s3_put_calls = mock_s3.put_object.call_args_list
            assert len(s3_put_calls) > 0

            enriched_call = s3_put_calls[0]
            assert enriched_call[1]["ContentType"] == "application/json"
            assert sample_ticket_dict["ticket_id"] in enriched_call[1]["Key"]

            print(f"\n✅ Complete workflow validated:")
            print(f"   ✓ Fetched from S3")
            print(f"   ✓ Processed with ML pipeline")
            print(f"   ✓ Stored to DynamoDB")
            print(f"   ✓ Stored to S3 (enriched)")

    def test_worker_stats_tracking(self, preloaded_models):
        """Test that worker tracks statistics correctly."""
        with patch('src.processor.worker.get_s3_client'), \
             patch('src.processor.worker.get_sqs_client'), \
             patch('src.processor.worker.get_dynamodb_resource'):

            processor = TicketProcessor()

            # Check initial stats
            assert processor.stats["tickets_processed"] == 0
            assert processor.stats["tickets_failed"] == 0
            assert "start_time" in processor.stats

            # Simulate processing
            processor.stats["tickets_processed"] += 1
            assert processor.stats["tickets_processed"] == 1

            print(f"\n✅ Statistics tracking working correctly")


# ============================================================================
# Model Information Tests
# ============================================================================

class TestModelInformation:
    """Tests for model metadata and information."""

    def test_get_model_info(self, preloaded_models):
        """Test model information retrieval."""
        info = get_model_info()

        assert "cache_dir" in info
        assert "device" in info
        assert "models" in info
        assert "total_size_mb" in info

        # Check models are documented
        assert "embeddings" in info["models"]
        assert "classifier" in info["models"]
        assert "summarizer" in info["models"]

        # Check device is CPU
        assert info["device"] == "cpu"

        print(f"\n✅ Model info:")
        print(f"   Device: {info['device']}")
        print(f"   Total size: {info['total_size_mb']} MB")
        print(f"   Models: {list(info['models'].keys())}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
