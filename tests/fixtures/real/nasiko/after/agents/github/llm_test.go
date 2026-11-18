package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

// gpt-4o-mini leaves the OpenAI API on Jan 14, 2027; the agent must default to its
// replacement when neither OPENAI_MODEL nor MODEL is set.
func TestNewLLMClientDefaultsToGPT6Luna(t *testing.T) {
	t.Setenv("OPENAI_MODEL", "")
	t.Setenv("MODEL", "")

	if got := newLLMClient().model; got != "gpt-6-luna" {
		t.Fatalf("default model = %q, want %q", got, "gpt-6-luna")
	}
}

// gpt-6-luna rejects function tools on /chat/completions unless reasoning_effort is
// "none"; other models must not receive the field at all.
func TestChatSendsReasoningEffortOnlyForGPT6Luna(t *testing.T) {
	tests := []struct {
		model      string
		wantEffort any
	}{
		{model: "gpt-6-luna", wantEffort: "none"},
		{model: "deepseek-v4-flash", wantEffort: nil},
	}
	for _, tt := range tests {
		t.Run(tt.model, func(t *testing.T) {
			var sent map[string]any
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				body, _ := io.ReadAll(r.Body)
				if err := json.Unmarshal(body, &sent); err != nil {
					t.Errorf("request body is not JSON: %v", err)
				}
				_, _ = w.Write([]byte(`{"choices":[{"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}`))
			}))
			defer srv.Close()

			c := &llmClient{baseURL: srv.URL, model: tt.model, http: srv.Client()}
			tools := []toolDef{{Type: "function"}}
			if _, err := c.chat(context.Background(), []chatMessage{{Role: "user", Content: "hi"}}, tools, ""); err != nil {
				t.Fatalf("chat: %v", err)
			}

			if got := sent["reasoning_effort"]; got != tt.wantEffort {
				t.Fatalf("reasoning_effort = %v, want %v", got, tt.wantEffort)
			}
		})
	}
}
