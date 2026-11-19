// Calls the API over plain HTTP, without the SDK.
export async function listAssistants(key) {
  const res = await fetch("https://api.openai.com/v1/assistants", {
    headers: { Authorization: `Bearer ${key}`, "OpenAI-Beta": "assistants=v2" },
  });
  return res.json();
}
