"""Configuration management for ticket processing pipeline."""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class AWSConfig:
    """AWS service configuration."""

    region: str = "us-east-1"
    endpoint_url: Optional[str] = None
    use_localstack: bool = False

    @classmethod
    def from_env(cls) -> "AWSConfig":
        """Load configuration from environment variables."""
        use_localstack = os.getenv("USE_LOCALSTACK", "false").lower() == "true"
        endpoint_url = os.getenv("AWS_ENDPOINT_URL") if use_localstack else None

        return cls(
            region=os.getenv("AWS_REGION", "us-east-1"),
            endpoint_url=endpoint_url,
            use_localstack=use_localstack,
        )


@dataclass
class S3Config:
    """S3 bucket configuration."""

    raw_bucket: str = "tickets-raw"
    enriched_bucket: str = "tickets-enriched"

    @classmethod
    def from_env(cls) -> "S3Config":
        """Load S3 configuration from environment."""
        return cls(
            raw_bucket=os.getenv("S3_BUCKET_RAW", "tickets-raw"),
            enriched_bucket=os.getenv("S3_BUCKET_ENRICHED", "tickets-enriched"),
        )


@dataclass
class SQSConfig:
    """SQS queue configuration."""

    queue_name: str = "ticket-processing-queue"
    poll_interval: int = 20  # Long polling wait time
    max_messages: int = 10  # Max messages per receive
    visibility_timeout: int = 300  # 5 minutes

    @classmethod
    def from_env(cls) -> "SQSConfig":
        """Load SQS configuration from environment."""
        return cls(
            queue_name=os.getenv("SQS_QUEUE_NAME", "ticket-processing-queue"),
            poll_interval=int(os.getenv("SQS_POLL_INTERVAL", "20")),
            max_messages=int(os.getenv("SQS_MAX_MESSAGES", "10")),
            visibility_timeout=int(os.getenv("SQS_VISIBILITY_TIMEOUT", "300")),
        )


@dataclass
class DynamoDBConfig:
    """DynamoDB table configuration."""

    table_name: str = "tickets"

    @classmethod
    def from_env(cls) -> "DynamoDBConfig":
        """Load DynamoDB configuration from environment."""
        return cls(
            table_name=os.getenv("DYNAMODB_TABLE", "tickets"),
        )


@dataclass
class ModelConfig:
    """ML model configuration."""

    cache_dir: str
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    classifier_model: str = "distilbert-base-uncased-finetuned-sst-2-english"
    summarizer_model: str = "sshleifer/distilbart-cnn-6-6"
    max_summary_length: int = 50

    @classmethod
    def from_env(cls) -> "ModelConfig":
        """Load model configuration from environment."""
        return cls(
            cache_dir=os.getenv("MODEL_CACHE_DIR", os.path.expanduser("~/.cache/models")),
            embedding_model=os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
            classifier_model=os.getenv("CLASSIFIER_MODEL", "distilbert-base-uncased-finetuned-sst-2-english"),
            summarizer_model=os.getenv("SUMMARIZER_MODEL", "sshleifer/distilbart-cnn-6-6"),
            max_summary_length=int(os.getenv("MAX_SUMMARY_LENGTH", "50")),
        )


@dataclass
class ProcessorConfig:
    """Complete processor configuration."""

    aws: AWSConfig
    s3: S3Config
    sqs: SQSConfig
    dynamodb: DynamoDBConfig
    model: ModelConfig

    @classmethod
    def from_env(cls) -> "ProcessorConfig":
        """Load complete configuration from environment."""
        return cls(
            aws=AWSConfig.from_env(),
            s3=S3Config.from_env(),
            sqs=SQSConfig.from_env(),
            dynamodb=DynamoDBConfig.from_env(),
            model=ModelConfig.from_env(),
        )

    def __repr__(self) -> str:
        """String representation (safe for logging)."""
        return (
            f"ProcessorConfig("
            f"region={self.aws.region}, "
            f"localstack={self.aws.use_localstack}, "
            f"queue={self.sqs.queue_name}, "
            f"table={self.dynamodb.table_name})"
        )
