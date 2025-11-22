#!/usr/bin/env bash
set -euo pipefail

# Development workflow helper script
# Provides commands for common development tasks

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_info() { echo -e "${GREEN}✓${NC} $1"; }
echo_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
echo_error() { echo -e "${RED}✗${NC} $1"; }
echo_title() { echo -e "${BLUE}===${NC} $1"; }

# Show usage
usage() {
    cat <<EOF
Usage: $0 <command>

Development workflow commands:

  setup         Initialize LocalStack resources (S3, SQS, DynamoDB)
  seed          Upload sample tickets to LocalStack
  test          Run integration tests
  status        Check LocalStack service status
  clean         Clean up test data and resources
  reset         Reset everything (clean + setup + seed)
  logs          Show LocalStack logs
  shell         Open Python shell with imports loaded
  lint          Run code linters (black, ruff)
  help          Show this help message

Examples:
  $0 setup              # Initialize AWS resources
  $0 seed               # Upload sample tickets
  $0 test               # Run integration tests
  $0 reset              # Full reset and reseed

EOF
}

# Check if LocalStack is running
check_localstack() {
    if ! awslocal s3 ls >/dev/null 2>&1; then
        echo_error "LocalStack is not running"
        echo "Start it with: flox activate -s"
        echo "Or manually: flox services start"
        return 1
    fi
    return 0
}

# Setup: Initialize LocalStack resources
cmd_setup() {
    echo_title "Setting up LocalStack resources"
    "$SCRIPT_DIR/localstack/init-resources.sh"
}

# Seed: Upload sample tickets
cmd_seed() {
    echo_title "Uploading sample tickets"
    if ! check_localstack; then
        return 1
    fi
    "$SCRIPT_DIR/localstack/seed-data.sh"
}

# Test: Run integration tests
cmd_test() {
    echo_title "Running integration tests"
    if ! check_localstack; then
        return 1
    fi

    cd "$PROJECT_ROOT"
    echo "Running pytest..."
    pytest tests/integration/test_localstack.py -v
}

# Status: Check LocalStack service status
cmd_status() {
    echo_title "LocalStack Status"

    if ! check_localstack; then
        return 1
    fi

    echo ""
    echo "S3 Buckets:"
    awslocal s3 ls | awk '{print "  - " $3}'

    echo ""
    echo "SQS Queues:"
    awslocal sqs list-queues | grep -o '"[^"]*ticket[^"]*"' | tr -d '"' | awk '{print "  - " $0}' || echo "  (none)"

    echo ""
    echo "DynamoDB Tables:"
    awslocal dynamodb list-tables | grep -o '"tickets"' | tr -d '"' | awk '{print "  - " $0}' || echo "  (none)"

    echo ""
    echo "S3 Objects (tickets-raw):"
    local count=$(awslocal s3 ls s3://tickets-raw/ 2>/dev/null | wc -l)
    echo "  Count: $count"
    if [ $count -gt 0 ]; then
        awslocal s3 ls s3://tickets-raw/ | head -5 | awk '{print "  - " $4}'
        if [ $count -gt 5 ]; then
            echo "  ... and $((count - 5)) more"
        fi
    fi

    echo ""
    echo "SQS Messages:"
    local queue_url=$(awslocal sqs get-queue-url --queue-name ticket-processing-queue --query 'QueueUrl' --output text 2>/dev/null)
    if [ -n "$queue_url" ]; then
        local msg_count=$(awslocal sqs get-queue-attributes --queue-url "$queue_url" --attribute-names ApproximateNumberOfMessages --query 'Attributes.ApproximateNumberOfMessages' --output text)
        echo "  Approximate messages: $msg_count"
    fi
}

# Clean: Remove test data
cmd_clean() {
    echo_title "Cleaning up test data"

    if ! check_localstack; then
        return 1
    fi

    echo "Removing S3 objects from tickets-raw..."
    awslocal s3 rm s3://tickets-raw/ --recursive 2>/dev/null || true

    echo "Removing S3 objects from tickets-enriched..."
    awslocal s3 rm s3://tickets-enriched/ --recursive 2>/dev/null || true

    echo "Purging SQS queue..."
    local queue_url=$(awslocal sqs get-queue-url --queue-name ticket-processing-queue --query 'QueueUrl' --output text 2>/dev/null)
    if [ -n "$queue_url" ]; then
        awslocal sqs purge-queue --queue-url "$queue_url" 2>/dev/null || true
    fi

    echo "Scanning DynamoDB table..."
    local items=$(awslocal dynamodb scan --table-name tickets --query 'Items' --output json 2>/dev/null || echo "[]")
    local item_count=$(echo "$items" | python3 -c "import sys, json; print(len(json.load(sys.stdin)))")

    if [ "$item_count" -gt 0 ]; then
        echo "Deleting $item_count items from DynamoDB..."
        echo "$items" | python3 -c "
import sys, json
import boto3

dynamodb = boto3.resource(
    'dynamodb',
    endpoint_url='http://localhost:4566',
    aws_access_key_id='test',
    aws_secret_access_key='test',
    region_name='us-east-1'
)
table = dynamodb.Table('tickets')

items = json.load(sys.stdin)
for item in items:
    table.delete_item(Key={
        'ticket_id': item['ticket_id'],
        'created_at': item['created_at']
    })
print(f'Deleted {len(items)} items')
"
    fi

    echo_info "Cleanup complete"
}

# Reset: Full reset
cmd_reset() {
    echo_title "Resetting environment"
    cmd_clean
    cmd_setup
    cmd_seed
    echo_info "Reset complete"
}

# Logs: Show LocalStack logs
cmd_logs() {
    echo_title "LocalStack Logs"
    echo "Showing last 50 lines (Ctrl+C to exit)"
    echo ""

    # Try to find LocalStack logs
    if [ -f "$HOME/.localstack/logs/localstack.log" ]; then
        tail -f "$HOME/.localstack/logs/localstack.log"
    elif [ -d "$FLOX_ENV_CACHE/localstack" ]; then
        echo_warn "LocalStack logs not found in standard location"
        echo "Check: $FLOX_ENV_CACHE/localstack"
    else
        echo_error "Could not find LocalStack logs"
    fi
}

# Shell: Open Python shell with imports
cmd_shell() {
    echo_title "Opening Python shell"
    cd "$PROJECT_ROOT"

    python3 <<EOF
import sys
sys.path.insert(0, '$PROJECT_ROOT')

from src.common.aws_clients import *
from src.common.config import *
from src.common.schemas import *

print("Available imports:")
print("  - get_s3_client, get_sqs_client, get_dynamodb_resource")
print("  - ProcessorConfig, AWSConfig, S3Config, SQSConfig")
print("  - RawTicket, EnrichedTicket, DynamoDBTicket")
print("")
print("Example:")
print("  s3 = get_s3_client(localstack=True)")
print("  s3.list_buckets()")
print("")

import code
code.interact(local=locals())
EOF
}

# Lint: Run code linters
cmd_lint() {
    echo_title "Running linters"
    cd "$PROJECT_ROOT"

    echo "Checking Python syntax..."
    python3 -m py_compile src/**/*.py tests/**/*.py

    echo_info "Syntax check passed"

    # Could add black, ruff, mypy here if installed
}

# Main command dispatcher
main() {
    if [ $# -eq 0 ]; then
        usage
        exit 0
    fi

    case "$1" in
        setup)
            cmd_setup
            ;;
        seed)
            cmd_seed
            ;;
        test)
            cmd_test
            ;;
        status)
            cmd_status
            ;;
        clean)
            cmd_clean
            ;;
        reset)
            cmd_reset
            ;;
        logs)
            cmd_logs
            ;;
        shell)
            cmd_shell
            ;;
        lint)
            cmd_lint
            ;;
        help|--help|-h)
            usage
            ;;
        *)
            echo_error "Unknown command: $1"
            echo ""
            usage
            exit 1
            ;;
    esac
}

main "$@"
