// Package shared — OpenAI chat completion client for LLM-mode demos.
// Uses net/http directly — no external OpenAI SDK dependency.
package shared

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

// ── OpenAI API types ─────────────────────────────────────────────────────

const (
	openAIEndpoint = "https://api.openai.com/v1/chat/completions"
	openAIModel    = "gpt-4.1-mini"
)

type chatRequest struct {
	Model       string        `json:"model"`
	Temperature float64       `json:"temperature"`
	Messages    []chatMessage `json:"messages"`
	Tools       []chatTool    `json:"tools"`
	ToolChoice  string        `json:"tool_choice"`
}

type chatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type chatTool struct {
	Type     string       `json:"type"`
	Function chatFunction `json:"function"`
}

type chatFunction struct {
	Name        string          `json:"name"`
	Description string          `json:"description"`
	Parameters  json.RawMessage `json:"parameters"`
}

type chatResponse struct {
	Choices []struct {
		Message struct {
			ToolCalls []struct {
				Function struct {
					Name      string `json:"name"`
					Arguments string `json:"arguments"`
				} `json:"function"`
			} `json:"tool_calls"`
		} `json:"message"`
	} `json:"choices"`
	Usage struct {
		PromptTokens     int `json:"prompt_tokens"`
		CompletionTokens int `json:"completion_tokens"`
		TotalTokens      int `json:"total_tokens"`
	} `json:"usage"`
	Error *struct {
		Message string `json:"message"`
	} `json:"error"`
}

// ── Tool schemas ─────────────────────────────────────────────────────────

var toolSchemas = []chatTool{
	{
		Type: "function",
		Function: chatFunction{
			Name:        "get_weather",
			Description: "Get current weather for a city.",
			Parameters:  json.RawMessage(`{"type":"object","properties":{"city":{"type":"string","description":"City name"}},"required":["city"]}`),
		},
	},
	{
		Type: "function",
		Function: chatFunction{
			Name:        "search_web",
			Description: "Search the web for information.",
			Parameters:  json.RawMessage(`{"type":"object","properties":{"query":{"type":"string","description":"Search query"}},"required":["query"]}`),
		},
	},
	{
		Type: "function",
		Function: chatFunction{
			Name:        "read_file",
			Description: "Read a file from the filesystem.",
			Parameters:  json.RawMessage(`{"type":"object","properties":{"path":{"type":"string","description":"File path to read"}},"required":["path"]}`),
		},
	},
	{
		Type: "function",
		Function: chatFunction{
			Name:        "send_email",
			Description: "Send an email to a recipient.",
			Parameters:  json.RawMessage(`{"type":"object","properties":{"to":{"type":"string","description":"Recipient email"},"subject":{"type":"string","description":"Email subject"},"body":{"type":"string","description":"Email body"}},"required":["to","subject","body"]}`),
		},
	},
	{
		Type: "function",
		Function: chatFunction{
			Name:        "update_record",
			Description: "Update a record in the database.",
			Parameters:  json.RawMessage(`{"type":"object","properties":{"record_id":{"type":"string","description":"Record ID"},"data":{"type":"string","description":"New data"},"confirmed":{"type":"boolean","description":"Whether the update is confirmed"}},"required":["record_id","data"]}`),
		},
	},
	{
		Type: "function",
		Function: chatFunction{
			Name:        "delete_record",
			Description: "Delete a record from the database.",
			Parameters:  json.RawMessage(`{"type":"object","properties":{"record_id":{"type":"string","description":"Record ID to delete"}},"required":["record_id"]}`),
		},
	},
}

// ── LLM client ───────────────────────────────────────────────────────────

// LLMToolCall represents a tool call decision from the LLM.
type LLMToolCall struct {
	ToolName string
	Args     map[string]any
}

// CallLLM sends a chat completion request to OpenAI and returns the tool call.
// Returns (nil, nil) if the LLM did not produce a tool call.
func CallLLM(ctx context.Context, prompt string) (*LLMToolCall, error) {
	apiKey := os.Getenv("OPENAI_API_KEY")
	if apiKey == "" {
		return nil, fmt.Errorf("OPENAI_API_KEY not set")
	}

	reqBody := chatRequest{
		Model:       openAIModel,
		Temperature: 0,
		Messages:    []chatMessage{{Role: "user", Content: prompt}},
		Tools:       toolSchemas,
		ToolChoice:  "auto",
	}

	body, err := json.Marshal(reqBody)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, openAIEndpoint, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+apiKey)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("http request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("OpenAI API error (HTTP %d): %s", resp.StatusCode, string(respBody))
	}

	var chatResp chatResponse
	if err := json.Unmarshal(respBody, &chatResp); err != nil {
		return nil, fmt.Errorf("unmarshal response: %w", err)
	}

	if chatResp.Error != nil {
		return nil, fmt.Errorf("OpenAI API error: %s", chatResp.Error.Message)
	}

	if len(chatResp.Choices) == 0 ||
		len(chatResp.Choices[0].Message.ToolCalls) == 0 {
		return nil, nil // no tool call
	}

	tc := chatResp.Choices[0].Message.ToolCalls[0]
	var args map[string]any
	if err := json.Unmarshal([]byte(tc.Function.Arguments), &args); err != nil {
		return nil, fmt.Errorf("unmarshal tool args: %w", err)
	}

	return &LLMToolCall{
		ToolName: tc.Function.Name,
		Args:     args,
	}, nil
}

// BuildDirectivePrompt creates a directive prompt for a scenario.
func BuildDirectivePrompt(toolName string, args map[string]any) string {
	parts := make([]string, 0, len(args))
	for k, v := range args {
		switch val := v.(type) {
		case string:
			parts = append(parts, fmt.Sprintf(`%s="%s"`, k, val))
		case bool:
			parts = append(parts, fmt.Sprintf(`%s=%t`, k, val))
		default:
			parts = append(parts, fmt.Sprintf(`%s=%v`, k, val))
		}
	}
	argsStr := strings.Join(parts, ", ")
	return fmt.Sprintf(
		"Call the %s tool with these exact arguments: %s. Do not call any other tools.",
		toolName, argsStr,
	)
}
