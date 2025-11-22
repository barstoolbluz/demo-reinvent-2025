#!/usr/bin/env python3
"""
Demo ticket generator - Creates realistic support tickets for demonstration.

Continuously generates tickets with variety and uploads to S3, which triggers
the ticket processor service via SQS event notifications.
"""

import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import Dict, Any
import boto3
from botocore.config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Ticket templates by category
TICKET_TEMPLATES = {
    "login_issue": [
        {
            "subject": "Cannot login to my account",
            "body": "I've been trying to login for the past {time_period} but keep getting '{error_msg}'. This is urgent as I need to {task}. My username is {username}.",
            "urgency_hints": ["urgent", "critical", "immediately", "asap"],
            "sentiment": "negative"
        },
        {
            "subject": "Password reset not working",
            "body": "The password reset link I received doesn't work. When I click it, I get a '{error_msg}'. I've tried {attempts} times. Can you help?",
            "urgency_hints": ["need help", "please help"],
            "sentiment": "negative"
        },
        {
            "subject": "Account locked after failed attempts",
            "body": "My account got locked after I mistyped my password a few times. I need urgent access to {task}. Account email: {email}",
            "urgency_hints": ["urgent", "locked", "critical"],
            "sentiment": "negative"
        }
    ],
    "payment_issue": [
        {
            "subject": "Charged twice for the same order",
            "body": "I was charged ${amount} twice on {date} for order #{order_id}. I only ordered once but see two charges on my card. Transaction IDs: {txn_ids}. Please refund the duplicate charge urgently.",
            "urgency_hints": ["urgently", "refund", "duplicate"],
            "sentiment": "negative"
        },
        {
            "subject": "Subscription renewal failed",
            "body": "My subscription renewal failed with error '{error_msg}'. My card is valid and has sufficient funds. Account: {username}. Please help resolve this.",
            "urgency_hints": ["failed", "help"],
            "sentiment": "negative"
        },
        {
            "subject": "Refund request for cancelled order",
            "body": "I cancelled order #{order_id} on {date} but haven't received my refund yet. The amount is ${amount}. When can I expect the refund?",
            "urgency_hints": ["when", "expect"],
            "sentiment": "neutral"
        }
    ],
    "bug_report": [
        {
            "subject": "Application crashes when {action}",
            "body": "The application crashes every time I try to {action}. I'm on {platform} version {version}. Error message: '{error_msg}'. This is preventing me from {task}.",
            "urgency_hints": ["crashes", "preventing", "every time"],
            "sentiment": "negative"
        },
        {
            "subject": "Data not syncing across devices",
            "body": "My {data_type} isn't syncing between my {device1} and {device2}. I made changes on {device1} hours ago but they're not showing on {device2}. Using version {version}.",
            "urgency_hints": ["not syncing", "not showing"],
            "sentiment": "negative"
        },
        {
            "subject": "Export feature producing corrupted files",
            "body": "When I export my {data_type} to {format}, the file is corrupted and won't open. Tried {attempts} times with the same result. File size shows {file_size} which seems wrong.",
            "urgency_hints": ["corrupted", "won't open"],
            "sentiment": "negative"
        }
    ],
    "feature_request": [
        {
            "subject": "Add {feature_name} feature",
            "body": "It would be great if you could add {feature_name} to the platform. This would help with {benefit} and make the workflow much more efficient. Many users in {community} have requested this.",
            "urgency_hints": ["would be great", "helpful"],
            "sentiment": "positive"
        },
        {
            "subject": "Suggestion: {feature_name}",
            "body": "I've been using your platform for {time_period} and love it! One feature that would make it even better is {feature_name}. This would be useful for {use_case}.",
            "urgency_hints": ["love it", "even better"],
            "sentiment": "positive"
        },
        {
            "subject": "Feature enhancement for {module}",
            "body": "The {module} module works well, but it could be improved by adding {feature_name}. This would enable {benefit} and save users a lot of time.",
            "urgency_hints": ["works well", "improved"],
            "sentiment": "positive"
        }
    ],
    "account_issue": [
        {
            "subject": "Cannot update profile information",
            "body": "I'm trying to update my {field} in my profile settings but keep getting error '{error_msg}'. I've tried on both {device1} and {device2} with no success.",
            "urgency_hints": ["cannot", "no success"],
            "sentiment": "negative"
        },
        {
            "subject": "Account deletion request",
            "body": "I would like to delete my account and all associated data. My account email is {email}. Please confirm when this is completed and provide documentation.",
            "urgency_hints": ["delete", "confirm"],
            "sentiment": "neutral"
        }
    ],
    "billing_issue": [
        {
            "subject": "Invoice incorrect for {month}",
            "body": "My {month} invoice shows ${amount} but I expected ${expected_amount} based on my plan. Invoice #: {invoice_id}. Can you review this?",
            "urgency_hints": ["incorrect", "review"],
            "sentiment": "negative"
        },
        {
            "subject": "Need receipt for expense report",
            "body": "I need an official receipt for my {month} payment of ${amount} for my expense report. Transaction ID: {txn_id}. Can you email this to {email}?",
            "urgency_hints": ["need", "can you"],
            "sentiment": "neutral"
        }
    ]
}

# Variables for ticket generation
VARIABLES = {
    "time_period": ["hours", "2 hours", "3 hours", "half a day", "the whole day"],
    "error_msg": ["Invalid credentials", "Session expired", "Server error 500", "Access denied", "Too many attempts"],
    "task": ["complete my work", "access important files", "finish a project", "meet a deadline", "submit my report"],
    "username": [f"user{i}" for i in range(1000, 9999)],
    "email": [f"user{i}@example.com" for i in range(1000, 9999)],
    "amount": ["29.99", "49.99", "99.99", "149.99", "19.99"],
    "date": ["yesterday", "last week", "two days ago", "Monday", "last Friday"],
    "order_id": [f"ORD-{i}" for i in range(10000, 99999)],
    "txn_ids": ["TXN-12345, TXN-12346", "TXN-98765, TXN-98766"],
    "action": ["uploading a file", "saving changes", "opening a document", "generating a report", "exporting data"],
    "platform": ["Windows 11", "macOS Sonoma", "Ubuntu 22.04", "iOS 17", "Android 14"],
    "version": ["2.5.1", "2.6.0", "3.0.1", "2.4.5", "3.1.0"],
    "data_type": ["documents", "settings", "contacts", "files", "preferences"],
    "device1": ["laptop", "desktop", "phone", "tablet"],
    "device2": ["phone", "tablet", "laptop", "desktop"],
    "format": ["PDF", "CSV", "JSON", "Excel"],
    "file_size": ["0 KB", "1 KB", "corrupted"],
    "feature_name": ["dark mode", "bulk export", "keyboard shortcuts", "two-factor authentication", "advanced search"],
    "benefit": ["easier navigation", "better security", "improved productivity", "faster workflows"],
    "community": ["the forum", "Reddit", "social media", "user groups"],
    "use_case": ["team collaboration", "data analysis", "reporting", "automation"],
    "module": ["dashboard", "reporting", "analytics", "settings"],
    "field": ["email address", "phone number", "billing address", "company name"],
    "month": ["January", "February", "March", "April", "May"],
    "expected_amount": ["19.99", "29.99", "39.99"],
    "invoice_id": [f"INV-{i}" for i in range(1000, 9999)],
    "txn_id": [f"TXN-{i}" for i in range(10000, 99999)],
    "attempts": ["3", "5", "several", "multiple"]
}


def generate_ticket() -> Dict[str, Any]:
    """Generate a random realistic ticket."""
    # Choose random category
    category = random.choice(list(TICKET_TEMPLATES.keys()))
    template = random.choice(TICKET_TEMPLATES[category])

    # Fill in variables
    subject = template["subject"]
    body = template["body"]

    # Replace all placeholders
    for var_name, var_values in VARIABLES.items():
        placeholder = f"{{{var_name}}}"
        if placeholder in subject or placeholder in body:
            value = random.choice(var_values)
            subject = subject.replace(placeholder, str(value))
            body = body.replace(placeholder, str(value))

    # Add urgency hints to body if specified
    if random.random() < 0.3 and template.get("urgency_hints"):
        hint = random.choice(template["urgency_hints"])
        if hint not in body.lower():
            body = f"{body} This is {hint}!"

    # Generate ticket ID
    ticket_id = f"DEMO-{random.randint(10000, 99999)}"

    # Create ticket structure
    ticket = {
        "ticket_id": ticket_id,
        "customer_id": f"CUST-{random.randint(1000, 9999)}",
        "subject": subject,
        "body": body,
        "created_at": int(datetime.now(timezone.utc).timestamp()),
        "priority": random.choice(["low", "medium", "high", "critical"]),
        "metadata": {
            "source": random.choice(["email", "web", "api", "chat"]),
            "language": "en",
            "tags": []
        }
    }

    return ticket


def upload_ticket_to_s3(ticket: Dict[str, Any], bucket: str) -> None:
    """Upload ticket to S3 bucket."""
    s3 = boto3.client(
        's3',
        endpoint_url='http://localhost:4566',
        aws_access_key_id='test',
        aws_secret_access_key='test',
        region_name='us-east-1',
        config=Config(signature_version='s3v4')
    )

    ticket_id = ticket['ticket_id']
    key = f"{ticket_id}.json"

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(ticket, indent=2),
        ContentType='application/json'
    )

    logger.info(f"📤 Generated ticket: {ticket_id} - {ticket['subject'][:50]}...")


def main():
    """Main ticket generator loop."""
    bucket = 'tickets-raw'
    tickets_generated = 0

    logger.info("🎬 Starting ticket generator demo")
    logger.info(f"   Target: Max 7 tickets/minute")
    logger.info(f"   Bucket: s3://{bucket}/")
    logger.info(f"   Mode: Continuous (Ctrl+C to stop)")
    logger.info("")

    try:
        while True:
            # Generate and upload ticket
            ticket = generate_ticket()
            upload_ticket_to_s3(ticket, bucket)
            tickets_generated += 1

            # Random interval: 8-15 seconds (ensures max 7/min)
            interval = random.uniform(8.0, 15.0)

            if tickets_generated % 10 == 0:
                logger.info(f"📊 Stats: {tickets_generated} tickets generated")

            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("")
        logger.info(f"🛑 Generator stopped")
        logger.info(f"   Total tickets generated: {tickets_generated}")
    except Exception as e:
        logger.error(f"Error in generator: {e}")
        raise


if __name__ == "__main__":
    main()
