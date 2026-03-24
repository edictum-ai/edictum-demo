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

	// Clear sink and reset session for the scenario run
	g.LocalSink().Clear()
	fmt.Println()
	fmt.Println("  Now running full scenario suite via guard.Run()...")
	_ = adapter // adapter shown above; scenarios use guard.Run() directly

	// ── Run all scenarios ───────────────────────────────────────────
	shared.RunScenarios(g)
}
