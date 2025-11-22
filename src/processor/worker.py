"""Main ticket processing worker.

This module orchestrates the complete ML pipeline:
1. Poll SQS for new ticket notifications
2. Fetch ticket data from S3
3. Run ML models (embeddings, classification, summarization)
4. Store enriched data in DynamoDB and S3
"""
import json
import logging
import time
import sys
from typing import Dict, Any, Optional
from datetime import datetime

from src.common.aws_clients import get_s3_client, get_sqs_client, get_dynamodb_resource
from src.common.config import ProcessorConfig
from src.common.schemas import RawTicket, EnrichmentData, EnrichedTicket, DynamoDBTicket

from src.processor.models import preload_all_models, get_model_info
from src.processor.embeddings import generate_ticket_embedding
from src.processor.classifier import get_classification_summary
from src.processor.summarizer import generate_summary

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TicketProcessor:
    """Processes support tickets from SQS queue."""

    def __init__(self, config: Optional[ProcessorConfig] = None):
        """
        Initialize ticket processor.

        Args:
            config: Processor configuration (loads from env if None)
        """
        self.config = config or ProcessorConfig.from_env()

        logger.info(f"Initializing TicketProcessor: {self.config}")

        # Initialize AWS clients
        self.s3 = get_s3_client(self.config.aws.use_localstack)
        self.sqs = get_sqs_client(self.config.aws.use_localstack)
        self.dynamodb = get_dynamodb_resource(self.config.aws.use_localstack)

        # Get SQS queue URL
        self.queue_url = self.sqs.get_queue_url(
            QueueName=self.config.sqs.queue_name
        )["QueueUrl"]
        logger.info(f"SQS Queue URL: {self.queue_url}")

        # Get DynamoDB table
        self.table = self.dynamodb.Table(self.config.dynamodb.table_name)
        logger.info(f"DynamoDB Table: {self.config.dynamodb.table_name}")

        # Statistics
        self.stats = {
            "tickets_processed": 0,
            "tickets_failed": 0,
            "start_time": datetime.utcnow()
        }

    def fetch_ticket_from_s3(self, bucket: str, key: str) -> Dict[str, Any]:
        """
        Fetch ticket JSON from S3.

        Args:
            bucket: S3 bucket name
            key: S3 object key

        Returns:
            Ticket dict

        Raises:
            Exception if fetch fails
        """
        logger.info(f"Fetching ticket from s3://{bucket}/{key}")

        try:
            response = self.s3.get_object(Bucket=bucket, Key=key)
            ticket_json = response["Body"].read().decode("utf-8")
            ticket = json.loads(ticket_json)

            logger.info(f"✓ Fetched ticket: {ticket.get('ticket_id', 'unknown')}")
            return ticket

        except Exception as e:
            logger.error(f"Failed to fetch ticket from S3: {e}")
            raise

    def process_ticket(self, raw_ticket: Dict[str, Any]) -> EnrichedTicket:
        """
        Run complete ML pipeline on ticket.

        Args:
            raw_ticket: Raw ticket dict from S3

        Returns:
            Enriched ticket with ML predictions

        Pipeline:
            1. Validate ticket schema
            2. Generate embedding (384-dim)
            3. Classify intent, urgency, sentiment
            4. Generate summary
            5. Package enrichment data
        """
        ticket_id = raw_ticket.get("ticket_id", "unknown")
        logger.info(f"Processing ticket: {ticket_id}")

        start_time = time.time()

        try:
            # Validate schema
            ticket = RawTicket(**raw_ticket)
            logger.debug(f"✓ Schema validated")

            # Generate embedding
            logger.debug("Generating embedding...")
            embedding = generate_ticket_embedding(raw_ticket)
            logger.debug(f"✓ Embedding generated: {len(embedding)} dims")

            # Classify
            logger.debug("Running classification...")
            classification = get_classification_summary(raw_ticket)
            logger.debug(f"✓ Classification complete: {classification['intent']}, {classification['urgency']}")

            # Summarize
            logger.debug("Generating summary...")
            summary = generate_summary(raw_ticket)
            logger.debug(f"✓ Summary generated: {len(summary)} chars")

            # Package enrichment
            enrichment = EnrichmentData(
                embedding=embedding,
                intent=classification["intent"],
                intent_confidence=classification["intent_confidence"],
                urgency=classification["urgency"],
                urgency_confidence=classification["urgency_confidence"],
                sentiment=classification["sentiment"],
                sentiment_confidence=classification["sentiment_confidence"],
                summary=summary,
                processed_at=datetime.utcnow().isoformat(),
                model_version="1.0.0"
            )

            # Create enriched ticket
            enriched = EnrichedTicket.from_raw(ticket, enrichment)

            elapsed = time.time() - start_time
            logger.info(f"✓ Ticket {ticket_id} processed in {elapsed:.2f}s")

            return enriched

        except Exception as e:
            logger.error(f"Failed to process ticket {ticket_id}: {e}", exc_info=True)
            raise

    def store_results(self, enriched_ticket: EnrichedTicket):
        """
        Store enriched ticket in DynamoDB and S3.

        Args:
            enriched_ticket: Enriched ticket with ML predictions

        DynamoDB:
            Stores metadata without embedding (size limits)

        S3:
            Stores complete enriched data including embedding
        """
        ticket_id = enriched_ticket.ticket_id
        logger.info(f"Storing results for ticket: {ticket_id}")

        try:
            # Store in DynamoDB (without embedding)
            dynamo_item = DynamoDBTicket.from_enriched(enriched_ticket)
            self.table.put_item(Item=dynamo_item.dict())
            logger.debug(f"✓ Stored in DynamoDB")

            # Store full enriched data in S3 (includes embedding)
            enriched_json = enriched_ticket.model_dump_json(indent=2)
            self.s3.put_object(
                Bucket=self.config.s3.enriched_bucket,
                Key=f"{ticket_id}.json",
                Body=enriched_json,
                ContentType="application/json"
            )
            logger.debug(f"✓ Stored in S3: {self.config.s3.enriched_bucket}/{ticket_id}.json")

            logger.info(f"✓ Results stored for ticket: {ticket_id}")

        except Exception as e:
            logger.error(f"Failed to store results for {ticket_id}: {e}")
            raise

    def poll_and_process(self) -> int:
        """
        Poll SQS queue and process available tickets.

        Returns:
            Number of messages processed

        Note:
            Uses long polling (configured wait time) for efficiency.
        """
        logger.debug(f"Polling queue (wait={self.config.sqs.poll_interval}s, max={self.config.sqs.max_messages})")

        try:
            response = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=self.config.sqs.max_messages,
                WaitTimeSeconds=self.config.sqs.poll_interval,
                MessageAttributeNames=["All"]
            )

            messages = response.get("Messages", [])

            if not messages:
                logger.debug("No messages received")
                return 0

            logger.info(f"Received {len(messages)} messages")

            for message in messages:
                try:
                    # Parse S3 event notification
                    body = json.loads(message["Body"])

                    # Handle S3 events (or manually sent messages)
                    if "Records" in body:
                        for record in body["Records"]:
                            # Extract S3 bucket and key
                            if "s3" in record:
                                bucket = record["s3"]["bucket"]["name"]
                                key = record["s3"]["object"]["key"]
                            else:
                                # Manually sent message format
                                bucket = self.config.s3.raw_bucket
                                key = record.get("key", record.get("Key"))

                            # Fetch and process
                            raw_ticket = self.fetch_ticket_from_s3(bucket, key)
                            enriched = self.process_ticket(raw_ticket)
                            self.store_results(enriched)

                            self.stats["tickets_processed"] += 1

                    # Delete message from queue
                    self.sqs.delete_message(
                        QueueUrl=self.queue_url,
                        ReceiptHandle=message["ReceiptHandle"]
                    )
                    logger.debug("Message deleted from queue")

                except Exception as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)
                    self.stats["tickets_failed"] += 1
                    # Don't delete message - it will be retried after visibility timeout

            return len(messages)

        except Exception as e:
            logger.error(f"Error polling queue: {e}", exc_info=True)
            return 0

    def run_forever(self, delay_between_polls: float = 1.0):
        """
        Run worker continuously.

        Args:
            delay_between_polls: Seconds to wait between polls (if no messages)

        Note:
            Runs until interrupted (Ctrl+C).
        """
        logger.info("Starting worker (press Ctrl+C to stop)")
        logger.info(f"Queue: {self.config.sqs.queue_name}")
        logger.info(f"Poll interval: {self.config.sqs.poll_interval}s")

        try:
            while True:
                messages_processed = self.poll_and_process()

                # If no messages, wait before next poll
                if messages_processed == 0:
                    time.sleep(delay_between_polls)

        except KeyboardInterrupt:
            logger.info("\nShutting down worker...")
            self.print_stats()

    def print_stats(self):
        """Print processing statistics."""
        elapsed = (datetime.utcnow() - self.stats["start_time"]).total_seconds()
        processed = self.stats["tickets_processed"]
        failed = self.stats["tickets_failed"]

        logger.info("=" * 60)
        logger.info("Worker Statistics")
        logger.info("=" * 60)
        logger.info(f"Runtime: {elapsed:.1f}s")
        logger.info(f"Tickets processed: {processed}")
        logger.info(f"Tickets failed: {failed}")
        if elapsed > 0:
            logger.info(f"Throughput: {processed / elapsed:.2f} tickets/sec")
        logger.info("=" * 60)


def main():
    """Main entry point for worker."""
    logger.info("=" * 60)
    logger.info("Ticket Processing Worker")
    logger.info("=" * 60)

    # Load configuration
    config = ProcessorConfig.from_env()
    logger.info(f"Configuration: {config}")

    # Print model info
    logger.info("\nModel Information:")
    model_info = get_model_info()
    for key, value in model_info.items():
        if key != "models":
            logger.info(f"  {key}: {value}")

    # Preload models
    logger.info("\nPreloading ML models...")
    try:
        preload_all_models()
        logger.info("✓ All models loaded successfully")
    except Exception as e:
        logger.error(f"Failed to preload models: {e}")
        logger.error("Worker cannot start without models")
        sys.exit(1)

    # Initialize worker
    logger.info("\nInitializing worker...")
    worker = TicketProcessor(config)

    # Run
    logger.info("")
    worker.run_forever()


if __name__ == "__main__":
    main()
