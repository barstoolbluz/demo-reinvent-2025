"""AWS client factory with LocalStack support.

This module provides boto3 client wrappers that automatically detect
and configure for LocalStack vs real AWS based on environment variables.
"""
import os
from typing import Literal, Optional

import boto3
from botocore.client import BaseClient
from botocore.config import Config


ServiceName = Literal["s3", "sqs", "dynamodb", "lambda", "secretsmanager"]


def is_localstack() -> bool:
    """Check if we should use LocalStack based on environment."""
    return os.getenv("USE_LOCALSTACK", "false").lower() == "true"


def get_endpoint_url() -> Optional[str]:
    """Get LocalStack endpoint URL if enabled."""
    if is_localstack():
        return os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
    return None


def get_aws_config() -> Config:
    """Get boto3 Config with sensible defaults."""
    return Config(
        retries={'max_attempts': 3, 'mode': 'standard'},
        connect_timeout=5,
        read_timeout=30,
    )


def get_aws_client(service: ServiceName, localstack: Optional[bool] = None) -> BaseClient:
    """
    Create AWS client with automatic LocalStack detection.

    Args:
        service: AWS service name (s3, sqs, dynamodb, lambda, secretsmanager)
        localstack: Force LocalStack mode (auto-detects if None)

    Returns:
        Boto3 client configured for LocalStack or real AWS

    Example:
        >>> s3 = get_aws_client("s3")
        >>> s3.list_buckets()
    """
    use_localstack = localstack if localstack is not None else is_localstack()

    kwargs = {
        "service_name": service,
        "config": get_aws_config(),
    }

    if use_localstack:
        kwargs.update({
            "endpoint_url": get_endpoint_url(),
            "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", "test"),
            "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
            "region_name": os.getenv("AWS_REGION", "us-east-1"),
        })
    else:
        # Real AWS - let boto3 handle credentials from environment/IAM
        kwargs["region_name"] = os.getenv("AWS_REGION", "us-east-1")

    return boto3.client(**kwargs)


def get_aws_resource(service: ServiceName, localstack: Optional[bool] = None):
    """
    Create AWS resource with automatic LocalStack detection.

    Args:
        service: AWS service name (currently only dynamodb supported)
        localstack: Force LocalStack mode (auto-detects if None)

    Returns:
        Boto3 resource configured for LocalStack or real AWS

    Example:
        >>> dynamodb = get_aws_resource("dynamodb")
        >>> table = dynamodb.Table("tickets")
    """
    use_localstack = localstack if localstack is not None else is_localstack()

    kwargs = {
        "service_name": service,
        "config": get_aws_config(),
    }

    if use_localstack:
        kwargs.update({
            "endpoint_url": get_endpoint_url(),
            "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", "test"),
            "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
            "region_name": os.getenv("AWS_REGION", "us-east-1"),
        })
    else:
        kwargs["region_name"] = os.getenv("AWS_REGION", "us-east-1")

    return boto3.resource(**kwargs)


# Convenience functions for specific services


def get_s3_client(localstack: Optional[bool] = None) -> BaseClient:
    """Get S3 client."""
    return get_aws_client("s3", localstack)


def get_sqs_client(localstack: Optional[bool] = None) -> BaseClient:
    """Get SQS client."""
    return get_aws_client("sqs", localstack)


def get_dynamodb_client(localstack: Optional[bool] = None) -> BaseClient:
    """Get DynamoDB client."""
    return get_aws_client("dynamodb", localstack)


def get_dynamodb_resource(localstack: Optional[bool] = None):
    """Get DynamoDB resource (table interface)."""
    return get_aws_resource("dynamodb", localstack)


def get_lambda_client(localstack: Optional[bool] = None) -> BaseClient:
    """Get Lambda client."""
    return get_aws_client("lambda", localstack)


def get_secretsmanager_client(localstack: Optional[bool] = None) -> BaseClient:
    """Get Secrets Manager client."""
    return get_aws_client("secretsmanager", localstack)


# Helper for awslocal-style resource names
def get_arn(service: str, resource: str, localstack: Optional[bool] = None) -> str:
    """
    Generate AWS ARN with LocalStack compatibility.

    Args:
        service: AWS service (e.g., 's3', 'sqs')
        resource: Resource identifier
        localstack: Force LocalStack mode

    Returns:
        ARN string

    Example:
        >>> get_arn("sqs", "ticket-processing-queue")
        "arn:aws:sqs:us-east-1:000000000000:ticket-processing-queue"
    """
    use_localstack = localstack if localstack is not None else is_localstack()
    region = os.getenv("AWS_REGION", "us-east-1")

    if use_localstack:
        account_id = "000000000000"  # LocalStack default
    else:
        # In production, get from STS or environment
        account_id = os.getenv("AWS_ACCOUNT_ID", "123456789012")

    return f"arn:aws:{service}:{region}:{account_id}:{resource}"
