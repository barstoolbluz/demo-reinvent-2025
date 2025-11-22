#!/usr/bin/env bash
set -euo pipefail

# LocalStack AWS Resource Initialization Script
# Creates S3 buckets, SQS queues, and DynamoDB tables for ticket processing pipeline

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${GREEN}✓${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

echo_error() {
    echo -e "${RED}✗${NC} $1"
}

# Check if LocalStack is running
check_localstack() {
    echo "Checking LocalStack availability..."

    local max_retries=30
    local retry_count=0

    while [ $retry_count -lt $max_retries ]; do
        if awslocal s3 ls >/dev/null 2>&1; then
            echo_info "LocalStack is ready"
            return 0
        fi
        retry_count=$((retry_count + 1))
        echo "Waiting for LocalStack... ($retry_count/$max_retries)"
        sleep 2
    done

    echo_error "LocalStack not available after ${max_retries} attempts"
    echo "Make sure LocalStack is running: flox services start"
    return 1
}

# Create S3 buckets
create_s3_buckets() {
    echo ""
    echo "Creating S3 buckets..."

    # Raw tickets bucket
    if awslocal s3 mb s3://tickets-raw 2>/dev/null; then
        echo_info "Created bucket: tickets-raw"
    else
        echo_warn "Bucket tickets-raw already exists"
    fi

    # Enriched tickets bucket
    if awslocal s3 mb s3://tickets-enriched 2>/dev/null; then
        echo_info "Created bucket: tickets-enriched"
    else
        echo_warn "Bucket tickets-enriched already exists"
    fi

    # List buckets
    echo ""
    echo "Available S3 buckets:"
    awslocal s3 ls | awk '{print "  - " $3}'
}

# Create SQS queue
create_sqs_queue() {
    echo ""
    echo "Creating SQS queue..."

    local queue_name="ticket-processing-queue"

    # Check if queue exists
    if awslocal sqs get-queue-url --queue-name "$queue_name" >/dev/null 2>&1; then
        echo_warn "Queue $queue_name already exists"
    else
        awslocal sqs create-queue \
            --queue-name "$queue_name" \
            --attributes '{
                "VisibilityTimeout": "300",
                "MessageRetentionPeriod": "86400",
                "ReceiveMessageWaitTimeSeconds": "20"
            }' >/dev/null
        echo_info "Created queue: $queue_name"
    fi

    # Get queue URL
    local queue_url=$(awslocal sqs get-queue-url --queue-name "$queue_name" --query 'QueueUrl' --output text)
    echo_info "Queue URL: $queue_url"
}

# Create DynamoDB table
create_dynamodb_table() {
    echo ""
    echo "Creating DynamoDB table..."

    local table_name="tickets"

    # Check if table exists
    if awslocal dynamodb describe-table --table-name "$table_name" >/dev/null 2>&1; then
        echo_warn "Table $table_name already exists"
    else
        awslocal dynamodb create-table \
            --table-name "$table_name" \
            --attribute-definitions \
                AttributeName=ticket_id,AttributeType=S \
                AttributeName=created_at,AttributeType=N \
                AttributeName=urgency,AttributeType=S \
            --key-schema \
                AttributeName=ticket_id,KeyType=HASH \
                AttributeName=created_at,KeyType=RANGE \
            --provisioned-throughput \
                ReadCapacityUnits=5,WriteCapacityUnits=5 \
            --global-secondary-indexes '[
                {
                    "IndexName": "urgency-index",
                    "KeySchema": [
                        {"AttributeName": "urgency", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"}
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                    "ProvisionedThroughput": {
                        "ReadCapacityUnits": 5,
                        "WriteCapacityUnits": 5
                    }
                }
            ]' >/dev/null

        echo_info "Created table: $table_name"

        # Wait for table to be active
        echo "Waiting for table to be active..."
        awslocal dynamodb wait table-exists --table-name "$table_name"
        echo_info "Table is active"
    fi

    # Describe table
    echo ""
    echo "Table details:"
    awslocal dynamodb describe-table --table-name "$table_name" \
        --query 'Table.[TableName,TableStatus,ItemCount,TableSizeBytes]' \
        --output text | awk '{printf "  Table: %s\n  Status: %s\n  Items: %s\n  Size: %s bytes\n", $1, $2, $3, $4}'
}

# Configure S3 event notifications
configure_s3_events() {
    echo ""
    echo "Configuring S3 event notifications..."

    # Get SQS queue ARN
    local queue_url=$(awslocal sqs get-queue-url --queue-name "ticket-processing-queue" --query 'QueueUrl' --output text)
    local queue_arn="arn:aws:sqs:us-east-1:000000000000:ticket-processing-queue"

    # Configure S3 bucket notification
    awslocal s3api put-bucket-notification-configuration \
        --bucket tickets-raw \
        --notification-configuration '{
            "QueueConfigurations": [{
                "Id": "ticket-upload-notification",
                "QueueArn": "'"$queue_arn"'",
                "Events": ["s3:ObjectCreated:*"]
            }]
        }' 2>/dev/null || echo_warn "Could not configure S3 events (might not be fully supported in LocalStack CE)"

    echo_info "S3 event notifications configured"
}

# Main execution
main() {
    echo "================================================"
    echo "LocalStack AWS Resource Initialization"
    echo "================================================"

    # Check LocalStack
    if ! check_localstack; then
        exit 1
    fi

    # Create resources
    create_s3_buckets
    create_sqs_queue
    create_dynamodb_table
    configure_s3_events

    echo ""
    echo "================================================"
    echo_info "All resources initialized successfully!"
    echo "================================================"
    echo ""
    echo "Summary:"
    echo "  - S3 buckets: tickets-raw, tickets-enriched"
    echo "  - SQS queue: ticket-processing-queue"
    echo "  - DynamoDB table: tickets (with urgency-index)"
    echo ""
    echo "Next steps:"
    echo "  1. Upload sample tickets: ./scripts/localstack/seed-data.sh"
    echo "  2. Run worker: python -m src.processor.worker"
    echo ""
}

main "$@"
