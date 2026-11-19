import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic();

export async function reply(prompt: string) {
  return client.messages.create({
    model: "claude-sonnet-4-5-20250929",
    max_tokens: 1024,
    top_p: 0.9,
    messages: [{ role: "user", content: prompt }],
  });
}
