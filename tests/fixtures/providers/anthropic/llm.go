package llm

import (
	"context"

	"github.com/anthropics/anthropic-sdk-go"
)

func Ask(ctx context.Context, client anthropic.Client, q string) (*anthropic.Message, error) {
	return client.Messages.New(ctx, anthropic.MessageNewParams{
		Model:       "claude-opus-4-1-20250805",
		MaxTokens:   1024,
		Temperature: anthropic.Float(0.5),
		Messages: []anthropic.MessageParam{
			anthropic.NewUserMessage(anthropic.NewTextBlock(q)),
		},
	})
}
