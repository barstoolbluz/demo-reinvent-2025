"""Data schemas for ticket processing pipeline."""
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class TicketMetadata(BaseModel):
    """Ticket metadata."""

    source: str = Field(..., description="Source of the ticket (email, web, api)")
    language: str = Field(default="en", description="Language code")
    tags: List[str] = Field(default_factory=list, description="User-defined tags")


class RawTicket(BaseModel):
    """Raw ticket data from S3."""

    ticket_id: str = Field(..., description="Unique ticket identifier")
    subject: str = Field(..., description="Ticket subject line")
    body: str = Field(..., description="Full ticket body text")
    priority: Optional[str] = Field(None, description="Explicit priority (critical/high/medium/low)")
    created_at: int = Field(..., description="Unix timestamp of creation")
    customer_id: str = Field(..., description="Customer identifier")
    metadata: TicketMetadata = Field(default_factory=lambda: TicketMetadata(source="unknown"))

    class Config:
        json_schema_extra = {
            "example": {
                "ticket_id": "TKT-001",
                "subject": "Cannot login to account",
                "body": "I've been trying to login for an hour but keep getting 'invalid credentials' error.",
                "priority": "high",
                "created_at": 1700000000,
                "customer_id": "CUST-12345",
                "metadata": {
                    "source": "email",
                    "language": "en"
                }
            }
        }


class EnrichmentData(BaseModel):
    """ML enrichment results."""

    # Embedding (384-dim for all-MiniLM-L6-v2)
    embedding: List[float] = Field(..., description="Semantic embedding vector")

    # Classification
    intent: str = Field(..., description="Classified intent category")
    intent_confidence: float = Field(..., ge=0.0, le=1.0, description="Intent confidence score")

    urgency: str = Field(..., description="Classified urgency level")
    urgency_confidence: float = Field(..., ge=0.0, le=1.0, description="Urgency confidence score")

    sentiment: str = Field(..., description="Sentiment (POSITIVE/NEGATIVE)")
    sentiment_confidence: float = Field(..., ge=0.0, le=1.0, description="Sentiment confidence score")

    # Summary
    summary: str = Field(..., description="Generated summary")

    # Metadata
    processed_at: str = Field(..., description="ISO timestamp of processing")
    model_version: str = Field(default="1.0.0", description="Model version identifier")

    class Config:
        json_schema_extra = {
            "example": {
                "embedding": [0.123, -0.456, 0.789],  # Truncated for example
                "intent": "login_issue",
                "intent_confidence": 0.92,
                "urgency": "high",
                "urgency_confidence": 0.88,
                "sentiment": "NEGATIVE",
                "sentiment_confidence": 0.95,
                "summary": "Customer unable to login after password reset",
                "processed_at": "2024-01-15T10:30:00Z",
                "model_version": "1.0.0"
            }
        }


class EnrichedTicket(BaseModel):
    """Complete enriched ticket (raw + enrichment)."""

    # Raw ticket fields (flattened)
    ticket_id: str
    subject: str
    body: str
    priority: Optional[str]
    created_at: int
    customer_id: str
    metadata: TicketMetadata

    # Enrichment data
    enrichment: EnrichmentData

    @classmethod
    def from_raw(cls, raw: RawTicket, enrichment: EnrichmentData) -> "EnrichedTicket":
        """Create enriched ticket from raw ticket and enrichment data."""
        return cls(
            ticket_id=raw.ticket_id,
            subject=raw.subject,
            body=raw.body,
            priority=raw.priority,
            created_at=raw.created_at,
            customer_id=raw.customer_id,
            metadata=raw.metadata,
            enrichment=enrichment,
        )


class DynamoDBTicket(BaseModel):
    """Ticket record for DynamoDB (without embedding due to size)."""

    ticket_id: str = Field(..., description="Partition key")
    created_at: int = Field(..., description="Sort key")

    # Core fields
    subject: str
    customer_id: str

    # Enrichment (no embedding)
    intent: str
    urgency: str
    sentiment: str
    summary: str

    # Metadata
    processed_at: str
    s3_key: str = Field(..., description="S3 key for full enriched data")

    @classmethod
    def from_enriched(cls, enriched: EnrichedTicket) -> "DynamoDBTicket":
        """Create DynamoDB record from enriched ticket."""
        return cls(
            ticket_id=enriched.ticket_id,
            created_at=enriched.created_at,
            subject=enriched.subject,
            customer_id=enriched.customer_id,
            intent=enriched.enrichment.intent,
            urgency=enriched.enrichment.urgency,
            sentiment=enriched.enrichment.sentiment,
            summary=enriched.enrichment.summary,
            processed_at=enriched.enrichment.processed_at,
            s3_key=f"{enriched.ticket_id}.json",
        )


class S3Event(BaseModel):
    """S3 event notification structure."""

    class S3Object(BaseModel):
        """S3 object details."""
        key: str
        size: int

    class S3Bucket(BaseModel):
        """S3 bucket details."""
        name: str

    class S3(BaseModel):
        """S3 event data."""
        bucket: "S3Event.S3Bucket"
        object: "S3Event.S3Object"

    s3: S3
    eventName: str


class SQSMessage(BaseModel):
    """SQS message structure."""

    Records: List[S3Event] = Field(..., description="S3 event records")


# For DynamoDB composite key queries
class TicketKey(BaseModel):
    """DynamoDB table key."""

    ticket_id: str
    created_at: int
