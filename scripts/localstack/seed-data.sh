#!/usr/bin/env bash
set -euo pipefail

# Sample Ticket Generator for LocalStack
# Generates and uploads realistic support tickets to S3

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo_info() {
    echo -e "${GREEN}✓${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Generate a single ticket JSON
generate_ticket() {
    local ticket_id="$1"
    local subject="$2"
    local body="$3"
    local priority="$4"
    local customer_id="${5:-CUST-$(shuf -i 1000-9999 -n 1)}"
    local source="${6:-email}"

    cat <<EOF
{
  "ticket_id": "$ticket_id",
  "subject": "$subject",
  "body": "$body",
  "priority": "$priority",
  "created_at": $(date +%s),
  "customer_id": "$customer_id",
  "metadata": {
    "source": "$source",
    "language": "en",
    "tags": []
  }
}
EOF
}

# Upload ticket to S3
upload_ticket() {
    local ticket_id="$1"
    local ticket_json="$2"

    local temp_file=$(mktemp)
    echo "$ticket_json" > "$temp_file"

    if awslocal s3 cp "$temp_file" "s3://tickets-raw/${ticket_id}.json" 2>/dev/null; then
        echo_info "Uploaded: $ticket_id"
    else
        echo_warn "Failed to upload: $ticket_id"
    fi

    rm -f "$temp_file"
}

# Main execution
main() {
    echo "================================================"
    echo "Sample Ticket Generator"
    echo "================================================"
    echo ""

    # Check LocalStack
    if ! awslocal s3 ls s3://tickets-raw >/dev/null 2>&1; then
        echo_warn "S3 bucket 'tickets-raw' not found"
        echo "Run: ./scripts/localstack/init-resources.sh first"
        exit 1
    fi

    echo "Generating sample tickets..."
    echo ""

    # Ticket 1: Login Issue (High Priority)
    local ticket1=$(generate_ticket \
        "TKT-001" \
        "Cannot login to account" \
        "I've been trying to login for the past hour but keep getting 'invalid credentials' error. I'm sure my password is correct. I've tried resetting it twice but still can't get in. This is urgent as I need to access my account for work." \
        "high" \
        "CUST-1234" \
        "email")
    upload_ticket "TKT-001" "$ticket1"

    # Ticket 2: Payment Issue (Critical)
    local ticket2=$(generate_ticket \
        "TKT-002" \
        "Payment failed but money was debited" \
        "My payment was declined but the money was debited from my account! I need an immediate refund. Transaction ID: TXN-98765. This happened 2 hours ago and I still haven't received any confirmation. Please resolve this ASAP!" \
        "critical" \
        "CUST-5678" \
        "web")
    upload_ticket "TKT-002" "$ticket2"

    # Ticket 3: Feature Request (Low Priority)
    local ticket3=$(generate_ticket \
        "TKT-003" \
        "Feature request: Dark mode" \
        "Would love to see a dark mode option in the app. My eyes hurt after long sessions and it would be great to have a darker theme. I know many other users would appreciate this too. Thanks for considering!" \
        "low" \
        "CUST-2345" \
        "email")
    upload_ticket "TKT-003" "$ticket3"

    # Ticket 4: Bug Report (High Priority)
    local ticket4=$(generate_ticket \
        "TKT-004" \
        "App crashes when uploading files" \
        "The mobile app crashes every time I try to upload a file larger than 10MB. Error message: 'Application has stopped responding'. This is happening on Android 13, Galaxy S23. I've tried reinstalling but the issue persists." \
        "high" \
        "CUST-3456" \
        "mobile")
    upload_ticket "TKT-004" "$ticket4"

    # Ticket 5: Account Management (Medium Priority)
    local ticket5=$(generate_ticket \
        "TKT-005" \
        "How to update email address?" \
        "I need to update my email address on my account but can't find the option in settings. Can you help me change it from old-email@example.com to new-email@example.com? My account ID is ACC-12345." \
        "medium" \
        "CUST-4567" \
        "email")
    upload_ticket "TKT-005" "$ticket5"

    # Ticket 6: Billing Question (Medium Priority)
    local ticket6=$(generate_ticket \
        "TKT-006" \
        "Question about subscription charges" \
        "I was charged \$29.99 this month but I thought my subscription was \$19.99. Can you explain the difference? I don't recall upgrading my plan. Please clarify what I'm being charged for." \
        "medium" \
        "CUST-6789" \
        "web")
    upload_ticket "TKT-006" "$ticket6"

    # Ticket 7: Integration Help (Low Priority)
    local ticket7=$(generate_ticket \
        "TKT-007" \
        "Help integrating with Slack" \
        "I'm trying to integrate your service with our Slack workspace but the OAuth flow keeps failing. I've followed the documentation but getting error 'invalid_redirect_uri'. Any guidance would be appreciated. Not urgent but would like to get this working." \
        "low" \
        "CUST-7890" \
        "api")
    upload_ticket "TKT-007" "$ticket7"

    # Ticket 8: Security Concern (Critical)
    local ticket8=$(generate_ticket \
        "TKT-008" \
        "URGENT: Unauthorized access to account" \
        "I just received notifications about login attempts from unknown locations (Russia, China). I didn't make these attempts! Please lock my account immediately and investigate. I'm changing my password now but very concerned about data breach." \
        "critical" \
        "CUST-8901" \
        "email")
    upload_ticket "TKT-008" "$ticket8"

    # Ticket 9: Data Export Request (Medium Priority)
    local ticket9=$(generate_ticket \
        "TKT-009" \
        "Need to export all my data" \
        "Per GDPR regulations, I'd like to request a full export of all data you have stored about me. Please provide in a machine-readable format (JSON or CSV). My account email is user@example.com." \
        "medium" \
        "CUST-9012" \
        "email")
    upload_ticket "TKT-009" "$ticket9"

    # Ticket 10: Performance Issue (High Priority)
    local ticket10=$(generate_ticket \
        "TKT-010" \
        "Dashboard loading very slow" \
        "The dashboard has been extremely slow for the past 3 days. Takes 30+ seconds to load. My internet is fine (100mbps). Other pages load quickly. Is there an issue with your servers? This is impacting my work significantly." \
        "high" \
        "CUST-0123" \
        "web")
    upload_ticket "TKT-010" "$ticket10"

    echo ""
    echo "================================================"
    echo_info "Generated and uploaded 10 sample tickets"
    echo "================================================"
    echo ""
    echo "Tickets by priority:"
    echo "  - Critical: 2 (TKT-002, TKT-008)"
    echo "  - High: 3 (TKT-001, TKT-004, TKT-010)"
    echo "  - Medium: 4 (TKT-005, TKT-006, TKT-009)"
    echo "  - Low: 2 (TKT-003, TKT-007)"
    echo ""
    echo "Verify uploads:"
    echo "  awslocal s3 ls s3://tickets-raw/"
    echo ""
    echo "Check SQS queue for messages:"
    echo "  awslocal sqs receive-message --queue-url \$(awslocal sqs get-queue-url --queue-name ticket-processing-queue --query 'QueueUrl' --output text)"
    echo ""
}

main "$@"
