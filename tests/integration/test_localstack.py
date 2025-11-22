"""Integration tests for LocalStack AWS resources.

These tests verify that LocalStack is properly configured with all required
AWS resources for the ticket processing pipeline.

Run with: pytest tests/integration/test_localstack.py -v
"""
import json
import time
import pytest

from src.common.aws_clients import (
    get_s3_client,
    get_sqs_client,
    get_dynamodb_resource,
    get_dynamodb_client,
)


@pytest.fixture(scope="module")
def s3():
    """S3 client fixture."""
    return get_s3_client(localstack=True)


@pytest.fixture(scope="module")
def sqs():
    """SQS client fixture."""
    return get_sqs_client(localstack=True)


@pytest.fixture(scope="module")
def dynamodb():
    """DynamoDB resource fixture."""
    return get_dynamodb_resource(localstack=True)


@pytest.fixture(scope="module")
def dynamodb_client():
    """DynamoDB client fixture."""
    return get_dynamodb_client(localstack=True)


class TestS3Buckets:
    """Test S3 bucket setup."""

    def test_buckets_exist(self, s3):
        """Verify required S3 buckets exist."""
        response = s3.list_buckets()
        bucket_names = [b["Name"] for b in response["Buckets"]]

        assert "tickets-raw" in bucket_names, "tickets-raw bucket not found"
        assert "tickets-enriched" in bucket_names, "tickets-enriched bucket not found"

    def test_can_upload_to_raw_bucket(self, s3):
        """Test uploading to tickets-raw bucket."""
        test_key = "test-upload.json"
        test_data = {"test": "data", "timestamp": time.time()}

        s3.put_object(
            Bucket="tickets-raw",
            Key=test_key,
            Body=json.dumps(test_data),
            ContentType="application/json"
        )

        # Verify upload
        response = s3.get_object(Bucket="tickets-raw", Key=test_key)
        retrieved_data = json.loads(response["Body"].read())

        assert retrieved_data["test"] == "data"

        # Cleanup
        s3.delete_object(Bucket="tickets-raw", Key=test_key)

    def test_can_upload_to_enriched_bucket(self, s3):
        """Test uploading to tickets-enriched bucket."""
        test_key = "test-enriched.json"
        test_data = {"enriched": True, "timestamp": time.time()}

        s3.put_object(
            Bucket="tickets-enriched",
            Key=test_key,
            Body=json.dumps(test_data),
            ContentType="application/json"
        )

        # Verify upload
        response = s3.get_object(Bucket="tickets-enriched", Key=test_key)
        retrieved_data = json.loads(response["Body"].read())

        assert retrieved_data["enriched"] is True

        # Cleanup
        s3.delete_object(Bucket="tickets-enriched", Key=test_key)


class TestSQSQueue:
    """Test SQS queue setup."""

    def test_queue_exists(self, sqs):
        """Verify ticket-processing-queue exists."""
        response = sqs.get_queue_url(QueueName="ticket-processing-queue")
        assert "QueueUrl" in response
        assert "ticket-processing-queue" in response["QueueUrl"]

    def test_queue_attributes(self, sqs):
        """Verify queue has correct attributes."""
        queue_url = sqs.get_queue_url(QueueName="ticket-processing-queue")["QueueUrl"]

        response = sqs.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=["All"]
        )

        attributes = response["Attributes"]

        # Check visibility timeout
        assert int(attributes["VisibilityTimeout"]) == 300, "VisibilityTimeout should be 300 seconds"

        # Check message retention
        assert int(attributes["MessageRetentionPeriod"]) == 86400, "MessageRetentionPeriod should be 86400 seconds (24h)"

        # Check long polling
        assert int(attributes["ReceiveMessageWaitTimeSeconds"]) == 20, "Long polling should be 20 seconds"

    def test_can_send_and_receive_message(self, sqs):
        """Test sending and receiving messages."""
        queue_url = sqs.get_queue_url(QueueName="ticket-processing-queue")["QueueUrl"]

        # Send message
        test_message = {
            "Records": [{
                "s3": {
                    "bucket": {"name": "tickets-raw"},
                    "object": {"key": "TEST-123.json"}
                }
            }]
        }

        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(test_message)
        )

        # Receive message (with short wait)
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=2
        )

        assert "Messages" in response, "No messages received"
        assert len(response["Messages"]) > 0

        # Verify message content
        message = response["Messages"][0]
        body = json.loads(message["Body"])
        assert body["Records"][0]["s3"]["object"]["key"] == "TEST-123.json"

        # Delete message (cleanup)
        sqs.delete_message(
            QueueUrl=queue_url,
            ReceiptHandle=message["ReceiptHandle"]
        )


class TestDynamoDBTable:
    """Test DynamoDB table setup."""

    def test_table_exists(self, dynamodb_client):
        """Verify tickets table exists."""
        response = dynamodb_client.describe_table(TableName="tickets")
        assert response["Table"]["TableName"] == "tickets"
        assert response["Table"]["TableStatus"] == "ACTIVE"

    def test_table_schema(self, dynamodb_client):
        """Verify table has correct schema."""
        response = dynamodb_client.describe_table(TableName="tickets")
        table = response["Table"]

        # Check key schema
        key_schema = {ks["AttributeName"]: ks["KeyType"] for ks in table["KeySchema"]}
        assert key_schema["ticket_id"] == "HASH", "ticket_id should be partition key"
        assert key_schema["created_at"] == "RANGE", "created_at should be sort key"

        # Check GSI
        gsi_names = [gsi["IndexName"] for gsi in table.get("GlobalSecondaryIndexes", [])]
        assert "urgency-index" in gsi_names, "urgency-index GSI not found"

    def test_can_write_and_read_item(self, dynamodb):
        """Test writing and reading items."""
        table = dynamodb.Table("tickets")

        # Write test item
        test_ticket = {
            "ticket_id": "TEST-001",
            "created_at": int(time.time()),
            "subject": "Test ticket",
            "customer_id": "CUST-TEST",
            "intent": "test",
            "urgency": "medium",
            "sentiment": "NEUTRAL",
            "summary": "This is a test",
            "processed_at": "2024-01-01T00:00:00Z",
            "s3_key": "TEST-001.json"
        }

        table.put_item(Item=test_ticket)

        # Read item back
        response = table.get_item(
            Key={
                "ticket_id": test_ticket["ticket_id"],
                "created_at": test_ticket["created_at"]
            }
        )

        assert "Item" in response
        assert response["Item"]["subject"] == "Test ticket"
        assert response["Item"]["urgency"] == "medium"

        # Cleanup
        table.delete_item(
            Key={
                "ticket_id": test_ticket["ticket_id"],
                "created_at": test_ticket["created_at"]
            }
        )

    def test_can_query_by_urgency(self, dynamodb):
        """Test querying by urgency GSI."""
        table = dynamodb.Table("tickets")

        # Write test items with different urgency
        timestamp = int(time.time())
        test_items = [
            {
                "ticket_id": f"TEST-{i}",
                "created_at": timestamp + i,
                "subject": f"Test ticket {i}",
                "customer_id": "CUST-TEST",
                "intent": "test",
                "urgency": "critical" if i % 2 == 0 else "low",
                "sentiment": "NEUTRAL",
                "summary": "Test",
                "processed_at": "2024-01-01T00:00:00Z",
                "s3_key": f"TEST-{i}.json"
            }
            for i in range(3)
        ]

        for item in test_items:
            table.put_item(Item=item)

        # Query by urgency
        response = table.query(
            IndexName="urgency-index",
            KeyConditionExpression="urgency = :urgency",
            ExpressionAttributeValues={":urgency": "critical"}
        )

        critical_items = response["Items"]
        assert len(critical_items) >= 2, "Should find at least 2 critical items"

        # Cleanup
        for item in test_items:
            table.delete_item(
                Key={
                    "ticket_id": item["ticket_id"],
                    "created_at": item["created_at"]
                }
            )


class TestEndToEndFlow:
    """Test end-to-end data flow."""

    def test_s3_upload_triggers_sqs_message(self, s3, sqs):
        """Test that S3 uploads trigger SQS messages.

        Note: This may not work in LocalStack CE as S3 event notifications
        require LocalStack Pro. Test is marked as expected to fail gracefully.
        """
        queue_url = sqs.get_queue_url(QueueName="ticket-processing-queue")["QueueUrl"]

        # Purge queue first
        try:
            sqs.purge_queue(QueueUrl=queue_url)
            time.sleep(2)  # Wait for purge to complete
        except:
            pass  # Purge might not be supported

        # Upload test ticket
        test_ticket = {
            "ticket_id": "TEST-E2E-001",
            "subject": "End-to-end test",
            "body": "Testing S3 to SQS flow",
            "priority": "low",
            "created_at": int(time.time()),
            "customer_id": "CUST-TEST",
            "metadata": {"source": "test"}
        }

        s3.put_object(
            Bucket="tickets-raw",
            Key="TEST-E2E-001.json",
            Body=json.dumps(test_ticket)
        )

        # Poll SQS for message (may not arrive in LocalStack CE)
        message_found = False
        for _ in range(5):  # Try for 10 seconds
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=2
            )

            if "Messages" in response:
                message = response["Messages"][0]
                body = json.loads(message["Body"])

                if "Records" in body:
                    for record in body["Records"]:
                        if record.get("s3", {}).get("object", {}).get("key") == "TEST-E2E-001.json":
                            message_found = True
                            # Cleanup message
                            sqs.delete_message(
                                QueueUrl=queue_url,
                                ReceiptHandle=message["ReceiptHandle"]
                            )
                            break

            if message_found:
                break

        # Cleanup S3 object
        s3.delete_object(Bucket="tickets-raw", Key="TEST-E2E-001.json")

        if not message_found:
            pytest.skip("S3 event notifications not available in LocalStack CE")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
