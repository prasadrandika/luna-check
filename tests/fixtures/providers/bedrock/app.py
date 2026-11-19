import json

import boto3

runtime = boto3.client("bedrock-runtime", region_name="us-east-1")

SONNET = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
LLAMA = "meta.llama3-1-70b-instruct-v1:0"


def ask(prompt):
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": prompt}],
    })
    return runtime.invoke_model(modelId=SONNET, body=body)
