import anthropic

client = anthropic.Anthropic()

MODEL = "claude-sonnet-4-5"


def summarize(text):
    return client.messages.create(
        model=MODEL,
        max_tokens=1024,
        temperature=0.2,
        messages=[{"role": "user", "content": text}],
    )


def classify(text):
    return client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=16,
        top_k=None,
        messages=[{"role": "user", "content": text}],
    )


def draft(text):
    return client.messages.create(model="claude-sonnet-5-5", max_tokens=512, messages=[])
