#!/bin/bash
aws ssm get-command-invocation \
  --command-id 36c38688-34fd-41b1-a498-d54233cb1680 \
  --instance-id i-0af917b28c402acca \
  --region us-east-1 \
  --query '{Status:Status,StatusDetails:StatusDetails,StandardErrorContent:StandardErrorContent,StandardOutputContent:StandardOutputContent}' \
  --output json | jq .
