import os

from openai import AzureOpenAI

client = AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_version="2024-10-21",
)


def chat(messages):
    return client.chat.completions.create(model="gpt-4o", messages=messages)


def legacy(messages):
    # Not on Azure's retirement schedule page, so not reported for an Azure file.
    return client.chat.completions.create(model="gpt-35-turbo", messages=messages)


def mini(messages):
    return client.chat.completions.create(model="gpt-4o-mini", messages=messages)
