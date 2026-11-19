from google import genai

client = genai.Client(vertexai=True, project="my-project", location="us-central1")


def answer(question):
    return client.models.generate_content(model="gemini-2.5-flash", contents=question)


def embed(text):
    return client.models.embed_content(model="text-embedding-004", contents=text)
