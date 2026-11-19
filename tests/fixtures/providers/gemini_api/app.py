import os

from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def answer(question):
    return client.models.generate_content(model="gemini-2.5-pro", contents=question)


def quick(question):
    return client.models.generate_content(model="models/gemini-2.0-flash", contents=question)


def current(question):
    return client.models.generate_content(model="gemini-3.8-flash", contents=question)
