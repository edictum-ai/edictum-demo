// demo-anthropic demonstrates edictum-go governance with the Anthropic SDK adapter.
//
// Usage: go run ./demo-anthropic/
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

	"github.com/edictum-ai/edictum-go/adapter/anthropic"

	"github.com/edictum-ai/edictum-demo/adapters/go/shared"
)

func main() {
	shared.LoadEnv()
	contractsPath := shared.ContractsPath()

	g, err := shared.CreateGuard(contractsPath, "analyst")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	shared.PrintBanner("Anthropic SDK")

	// ── Show adapter integration ────────────────────────────────────
	// In a real Anthropic Go SDK application, you would wrap your tool
	// functions with governance:
	//
	//   adapter := anthropic.New(g)
	//   wrappedGetWeather := adapter.WrapTool("get_weather",
	//       func(ctx context.Context, input json.RawMessage) (any, error) {
	//           var args map[string]any
	//           json.Unmarshal(input, &args)
	//           return shared.GetWeather(args)
	//       },
	//   )
	//   // Use wrappedGetWeather in your Anthropic tool_use handler

	adapter := anthropic.New(g)

	// Demonstrate a single wrapped tool call
	fmt.Println("  Adapter demo: calling get_weather via Anthropic wrapper...")
	wrappedWeather := adapter.WrapTool("get_weather",
		func(ctx context.Context, input json.RawMessage) (any, error) {
			var args map[string]any
			if err := json.Unmarshal(input, &args); err != nil {
				return nil, err
			}
			return shared.GetWeather(args)
		},
	)

	inputJSON := json.RawMessage(`{"city": "Paris"}`)
	result, err := wrappedWeather(context.Background(), inputJSON)
	if err != nil {
		fmt.Printf("  Adapter call error: %v\n", err)
	} else {
		fmt.Printf("  Adapter result: %v\n", result)
	}

	// Demonstrate a denied call through the adapter
	fmt.Println("  Adapter demo: calling send_email to evil domain (should be DENIED)...")
	wrappedEmail := adapter.WrapTool("send_email",
		func(ctx context.Context, input json.RawMessage) (any, error) {
			var args map[string]any
			if err := json.Unmarshal(input, &args); err != nil {
				return nil, err
			}
			return shared.SendEmail(args)
		},
	)
	evilInput := json.RawMessage(`{"to":"attacker@evil.com","subject":"test","body":"hi"}`)
	_, err = wrappedEmail(context.Background(), evilInput)
	if err != nil {
		fmt.Printf("  Adapter correctly denied: %v\n", err)
	} else {
		fmt.Println("  WARNING: expected denial but call was allowed")
	}

	// Create a fresh guard for scenario run (adapter demo consumed session state)
	g2, err := shared.CreateGuard(contractsPath, "analyst")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error creating scenario guard: %v\n", err)
		os.Exit(1)
	}
	fmt.Println()
	fmt.Println("  Now running full scenario suite via guard.Run()...")

	// ── Run all scenarios ───────────────────────────────────────────
	if shared.IsLLMMode() {
		fmt.Println("  Running scenarios with LLM-driven tool calls...")
		shared.RunLLMScenarios(g2)
	} else {
		shared.RunScenarios(g2)
	}
}
