from openai import OpenAI

client = OpenAI()


def make_assistant():
    return client.beta.assistants.create(model="gpt-6-luna", name="Helper")


def run(thread_id, assistant_id):
    return client.beta.threads.runs.create(thread_id=thread_id, assistant_id=assistant_id)


def with_saved_prompt(question):
    return client.responses.create(
        model="gpt-6-luna",
        prompt={"id": "pmpt_68ab12cd34", "variables": {"question": question}},
    )


def translate(f):
    return client.audio.translations.create(model="whisper-1", file=f)


REALTIME_HEADERS = {"OpenAI-Beta": "realtime=v1"}
