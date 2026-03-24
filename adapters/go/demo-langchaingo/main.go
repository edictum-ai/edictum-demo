// demo-langchaingo demonstrates edictum-go governance with the LangChainGo adapter.
//
// Usage: go run ./demo-langchaingo/
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

	"github.com/edictum-ai/edictum-go/adapter/langchaingo"

	"github.com/edictum-ai/edictum-demo/adapters/go/shared"
)

func main() {
	contractsPath := shared.ContractsPath()

	g, err := shared.CreateGuard(contractsPath, "analyst")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	shared.PrintBanner("LangChainGo")

	// ── Show adapter integration ────────────────────────────────────
	// In a real LangChainGo application, you would wrap your tool
	// functions to run through the governance pipeline:
	//
	//   adapter := langchaingo.New(g)
	//   wrappedGetWeather := adapter.WrapTool("get_weather",
	//       func(ctx context.Context, input string) (string, error) {
	//           var args map[string]any
	//           json.Unmarshal([]byte(input), &args)
	//           result, _ := shared.GetWeather(args)
	//           return result.(string), nil
	//       },
	//   )
	//   // Pass wrappedGetWeather to your LangChainGo ToolNode/Agent

	adapter := langchaingo.New(g)

	// Demonstrate a single wrapped tool call
	fmt.Println("  Adapter demo: calling get_weather via LangChainGo wrapper...")
	wrappedWeather := adapter.WrapTool("get_weather",
		func(ctx context.Context, input string) (string, error) {
			var args map[string]any
			if err := json.Unmarshal([]byte(input), &args); err != nil {
				args = map[string]any{"city": input}
			}
			result, err := shared.GetWeather(args)
			if err != nil {
				return "", err
			}
			s, ok := result.(string)
			if !ok {
				return fmt.Sprintf("%v", result), nil
			}
			return s, nil
		},
	)

	result, err := wrappedWeather(context.Background(), `{"city": "Paris"}`)
	if err != nil {
		fmt.Printf("  Adapter call error: %v\n", err)
	} else {
		fmt.Printf("  Adapter result: %s\n", result)
	}

	// Demonstrate a denied call through the adapter
	fmt.Println("  Adapter demo: calling send_email to evil domain (should be DENIED)...")
	wrappedEmail := adapter.WrapTool("send_email",
		func(ctx context.Context, input string) (string, error) {
			var args map[string]any
			if err := json.Unmarshal([]byte(input), &args); err != nil {
				args = map[string]any{"to": input}
			}
			r, err := shared.SendEmail(args)
			if err != nil {
				return "", err
			}
			s, ok := r.(string)
			if !ok {
				return fmt.Sprintf("%v", r), nil
			}
			return s, nil
		},
	)
	_, err = wrappedEmail(context.Background(), `{"to":"attacker@evil.com","subject":"test","body":"hi"}`)
	if err != nil {
		fmt.Printf("  Adapter correctly denied: %v\n", err)
	} else {
		fmt.Println("  WARNING: expected denial but call was allowed")
	}

	// Clear sink before scenario run. Note: any marks taken before Clear()
	// become invalid (SinceMark would return MarkEvictedError).
	g.LocalSink().Clear()
	fmt.Println()
	fmt.Println("  Now running full scenario suite via guard.Run()...")

	// ── Run all scenarios ───────────────────────────────────────────
	shared.RunScenarios(g)
}
