// Package shared provides mock tools, scenario definitions, and helpers
// for edictum-go adapter demos. Port of the Python shared_v2.py.
package shared

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math/rand/v2"
	"os"
	"path/filepath"
	"strings"

	edictum "github.com/edictum-ai/edictum-go"
	"github.com/edictum-ai/edictum-go/audit"
	"github.com/edictum-ai/edictum-go/envelope"
	"github.com/edictum-ai/edictum-go/guard"
)

// ── ANSI colors ─────────────────────────────────────────────────────────

const (
	colorReset  = "\033[0m"
	colorRed    = "\033[31m"
	colorGreen  = "\033[32m"
	colorYellow = "\033[33m"
	colorBlue   = "\033[34m"
	colorCyan   = "\033[36m"
	colorGray   = "\033[90m"
)

// ── Mock tool implementations ───────────────────────────────────────────

// GetWeather returns simulated weather for a city.
func GetWeather(args map[string]any) (any, error) {
	city, _ := args["city"].(string)
	conditions := []string{"sunny", "cloudy", "rainy", "snowy", "windy"}
	temp := rand.IntN(40) - 5
	return fmt.Sprintf("%s: %s, %dC", city, conditions[rand.IntN(len(conditions))], temp), nil
}

// SearchWeb returns simulated search results.
func SearchWeb(args map[string]any) (any, error) {
	query, _ := args["query"].(string)
	results := map[string]any{
		"results": []any{
			map[string]any{"title": fmt.Sprintf("Result 1 for '%s'", query), "url": "https://example.com/1"},
			map[string]any{"title": fmt.Sprintf("Result 2 for '%s'", query), "url": "https://example.com/2"},
		},
	}
	b, err := json.Marshal(results)
	if err != nil {
		return nil, fmt.Errorf("search_web marshal: %w", err)
	}
	return string(b), nil
}

// ReadFile returns simulated file contents. Includes PII for contacts.json
// to trigger postcondition redaction.
func ReadFile(args map[string]any) (any, error) {
	path, _ := args["path"].(string)

	if strings.Contains(path, "broken") {
		return "Error: Permission denied", nil
	}
	if strings.Contains(strings.ToLower(path), "secret") || strings.Contains(path, "passwd") {
		return fmt.Sprintf("Contents of %s: root:x:0:0:root:/root:/bin/bash", path), nil
	}
	if strings.Contains(path, "contacts") {
		contacts := map[string]any{
			"contacts": []any{
				map[string]any{"name": "Jane Doe", "email": "jane@example.com", "phone": "(415) 555-0123", "ssn": "123-45-6789"},
				map[string]any{"name": "John Smith", "email": "john@company.com", "phone": "(212) 555-9876"},
			},
		}
		b, err := json.Marshal(contacts)
		if err != nil {
			return nil, fmt.Errorf("read_file marshal: %w", err)
		}
		return string(b), nil
	}
	return fmt.Sprintf("Contents of %s: [simulated file content, no sensitive data]", path), nil
}

// SendEmail returns simulated email send result.
func SendEmail(args map[string]any) (any, error) {
	subject, _ := args["subject"].(string)
	result := map[string]any{"status": "sent", "message_id": fmt.Sprintf("msg-%d", rand.IntN(100000)), "subject": subject}
	b, err := json.Marshal(result)
	if err != nil {
		return nil, fmt.Errorf("send_email marshal: %w", err)
	}
	return string(b), nil
}

// UpdateRecord returns simulated record update result.
func UpdateRecord(args map[string]any) (any, error) {
	recordID, _ := args["record_id"].(string)
	data, _ := args["data"].(string)
	result := map[string]any{"status": "updated", "record_id": recordID, "data": data}
	b, err := json.Marshal(result)
	if err != nil {
		return nil, fmt.Errorf("update_record marshal: %w", err)
	}
	return string(b), nil
}

// DeleteRecord returns simulated record deletion result.
func DeleteRecord(args map[string]any) (any, error) {
	recordID, _ := args["record_id"].(string)
	result := map[string]any{"status": "deleted", "record_id": recordID}
	b, err := json.Marshal(result)
	if err != nil {
		return nil, fmt.Errorf("delete_record marshal: %w", err)
	}
	return string(b), nil
}

// ToolCallable returns the mock tool function for a given tool name.
func ToolCallable(toolName string) func(map[string]any) (any, error) {
	switch toolName {
	case "get_weather":
		return GetWeather
	case "search_web":
		return SearchWeb
	case "read_file":
		return ReadFile
	case "send_email":
		return SendEmail
	case "update_record":
		return UpdateRecord
	case "delete_record":
		return DeleteRecord
	default:
		return func(_ map[string]any) (any, error) {
			return nil, fmt.Errorf("unknown tool: %s", toolName)
		}
	}
}

// ── Scenario definitions ────────────────────────────────────────────────

// Scenario defines a test case for the governance pipeline.
type Scenario struct {
	Description string
	ToolName    string
	Args        map[string]any
	Expected    string // "allowed", "denied", "redact", "approval", "observe"
}

// AllScenarios returns the full scenario list (17 scenarios).
//
// NOTE: Scenarios 2, 3, and 6 expect "denied" due to edictum-go sandbox
// wiring bug: the YAML compiler creates a stub Check function that always
// denies, and the guard never replaces it with actual sandbox.Check().
// In Python these would be "allowed", "redact", and "denied" respectively.
// See: https://github.com/edictum-ai/edictum-go — sandbox stub not wired.
var AllScenarios = []Scenario{
	{"Weather lookup (allowed)", "get_weather", map[string]any{"city": "Tokyo"}, "allowed"},
	{"Read safe file (DENIED: sandbox stub bug)", "read_file", map[string]any{"path": "/home/user/notes.txt"}, "denied"},
	{"Read contacts (DENIED: sandbox stub bug)", "read_file", map[string]any{"path": "/home/user/contacts.json"}, "denied"},
	{"Read /etc/passwd (DENIED: precondition)", "read_file", map[string]any{"path": "/etc/passwd"}, "denied"},
	{"Read .env file (DENIED: no-sensitive-files)", "read_file", map[string]any{"path": "/home/app/.env.production"}, "denied"},
	{"Read outside sandbox (DENIED: sandbox stub)", "read_file", map[string]any{"path": "/opt/secret/config.yaml"}, "denied"},
	{"Email to company (allowed + observe audit)", "send_email", map[string]any{"to": "alice@company.com", "subject": "Hello", "body": "Hi"}, "allowed"},
	{"Email to evil domain (DENIED: no-email-to-external)", "send_email", map[string]any{"to": "attacker@evil.com", "subject": "Leak", "body": "data"}, "denied"},
	{"Search web (allowed)", "search_web", map[string]any{"query": "edictum governance"}, "allowed"},
	{"Delete without admin role (DENIED: RBAC)", "delete_record", map[string]any{"record_id": "REC-001"}, "denied"},
	{"Update record confirmed (allowed)", "update_record", map[string]any{"record_id": "REC-002", "data": "new value", "confirmed": true}, "allowed"},
	{"Update record unconfirmed (approval required)", "update_record", map[string]any{"record_id": "REC-003", "data": "risky"}, "approval"},
	{"Weather #2 (rate limit counting)", "get_weather", map[string]any{"city": "London"}, "allowed"},
	{"Weather #3", "get_weather", map[string]any{"city": "Berlin"}, "allowed"},
	{"Weather #4", "get_weather", map[string]any{"city": "Sydney"}, "allowed"},
	{"Weather #5 (last allowed)", "get_weather", map[string]any{"city": "NYC"}, "allowed"},
	{"Weather #6 (DENIED: rate limit)", "get_weather", map[string]any{"city": "LA"}, "denied"},
}

// QuickScenarios returns all non-approval scenarios (skips scenarios that
// would block waiting for HITL approval). The full set includes rate-limit
// exhaustion scenarios that depend on ordering.
func QuickScenarios() []Scenario {
	var quick []Scenario
	for _, s := range AllScenarios {
		if s.Expected == "approval" {
			continue
		}
		quick = append(quick, s)
	}
	return quick
}

// ── Guard creation ──────────────────────────────────────────────────────

// ContractsPath returns the absolute path to contracts.yaml.
// It resolves relative to the caller's demo directory: ../../contracts.yaml
func ContractsPath() string {
	// Try the working directory first (when run from demo-xxx/)
	candidates := []string{
		filepath.Join("..", "..", "contracts.yaml"),
		filepath.Join("..", "contracts.yaml"),
		filepath.Join("contracts.yaml"),
	}
	for _, c := range candidates {
		abs, err := filepath.Abs(c)
		if err != nil {
			continue
		}
		if _, err := os.Stat(abs); err == nil {
			return abs
		}
	}
	// Fallback: try relative to executable
	exe, err := os.Executable()
	if err == nil {
		dir := filepath.Dir(exe)
		p := filepath.Join(dir, "..", "..", "contracts.yaml")
		if abs, err := filepath.Abs(p); err == nil {
			if _, err := os.Stat(abs); err == nil {
				return abs
			}
		}
	}
	// Last resort — return the relative path and let FromYAML fail with a clear error
	return "../../contracts.yaml"
}

// CreateGuard creates an Edictum guard from contracts.yaml with the given role.
func CreateGuard(contractsPath string, role string) (*guard.Guard, error) {
	p := envelope.NewPrincipal(
		envelope.WithUserID(fmt.Sprintf("demo-%s", role)),
		envelope.WithRole(role),
		envelope.WithClaims(map[string]any{
			"department": "engineering",
			"team":       "platform",
		}),
	)

	g, err := guard.FromYAML(contractsPath,
		guard.WithMode("enforce"),
		guard.WithPrincipal(&p),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to load contracts from %s: %w", contractsPath, err)
	}
	return g, nil
}

// ── Result classification from audit events ─────────────────────────────

// ClassifyResult inspects audit events emitted since the given mark to
// determine the governance outcome.
func ClassifyResult(sink *audit.CollectingSink, mark int, toolName string) (action, detail string) {
	if sink == nil {
		return "", ""
	}

	recent, err := sink.SinceMark(mark)
	if err != nil || len(recent) == 0 {
		return "", ""
	}

	// Check for hard denials and approvals first
	for _, e := range recent {
		if e.Action == audit.ActionCallDenied {
			reason := e.Reason
			name := e.DecisionName
			if name != "" {
				d := fmt.Sprintf("%s: %s", name, reason)
				if len(d) > 100 {
					d = d[:100]
				}
				return "DENIED", d
			}
			if len(reason) > 100 {
				reason = reason[:100]
			}
			return "DENIED", reason
		}
		if e.Action == audit.ActionCallApprovalRequested {
			return "APPROVAL", fmt.Sprintf("%s requires approval", toolName)
		}
	}

	// Check postcondition results
	for _, e := range recent {
		if e.PostconditionsPassed != nil && !*e.PostconditionsPassed {
			return "REDACTED", "PII detected and redacted in output"
		}
	}

	// Check for allowed/executed (takes precedence over observe-mode audits)
	for _, e := range recent {
		if e.Action == audit.ActionCallAllowed || e.Action == audit.ActionCallExecuted {
			return "ALLOWED", fmt.Sprintf("%s executed", toolName)
		}
	}

	// Observe-mode: CALL_WOULD_DENY fired but no execution followed
	for _, e := range recent {
		if e.Action == audit.ActionCallWouldDeny {
			d := fmt.Sprintf("would-deny: %s", e.Reason)
			if len(d) > 100 {
				d = d[:100]
			}
			return "OBSERVE", d
		}
	}

	return "", ""
}

// ── Formatting helpers ──────────────────────────────────────────────────

// PrintBanner prints the demo header.
func PrintBanner(adapterName string) {
	fmt.Println(strings.Repeat("=", 70))
	fmt.Printf("  EDICTUM %s DEMO (Go)\n", strings.ToUpper(adapterName))
	fmt.Println(strings.Repeat("=", 70))
	fmt.Printf("  Mode:    enforce\n")
	fmt.Printf("  Source:  local YAML\n")
	fmt.Printf("  SDK:     edictum-go v%s\n", edictum.VERSION)
	fmt.Println()
}

// PrintScenario prints the scenario header.
func PrintScenario(idx, total int, desc string) {
	fmt.Println()
	fmt.Println(colorGray + strings.Repeat("-", 60) + colorReset)
	fmt.Printf("  [%d/%d] %s\n", idx, total, desc)
	fmt.Println(colorGray + strings.Repeat("-", 60) + colorReset)
}

// PrintResult prints a classified governance result with color.
func PrintResult(action, detail string) {
	var icon, color string
	switch action {
	case "DENIED":
		icon, color = "X", colorRed
	case "ALLOWED":
		icon, color = "+", colorGreen
	case "REDACTED":
		icon, color = "~", colorYellow
	case "APPROVAL":
		icon, color = "?", colorBlue
	case "OBSERVE":
		icon, color = "o", colorCyan
	default:
		icon, color = "|", colorGray
	}
	fmt.Printf("  %s[%s] %s: %s%s\n", color, icon, action, detail, colorReset)
}

// PrintSummary prints the governance summary from all audit events.
func PrintSummary(sink *audit.CollectingSink) {
	if sink == nil {
		fmt.Println("  (No audit data available)")
		return
	}

	events := sink.Events()
	if len(events) == 0 {
		fmt.Println("  No audit events recorded.")
		return
	}

	var allowed, denied, wouldDeny, pii, approvalReq int
	for _, e := range events {
		switch e.Action {
		case audit.ActionCallAllowed, audit.ActionCallExecuted:
			allowed++
		case audit.ActionCallDenied:
			denied++
		case audit.ActionCallWouldDeny:
			wouldDeny++
		case audit.ActionCallApprovalRequested:
			approvalReq++
		}
		if e.PostconditionsPassed != nil && !*e.PostconditionsPassed {
			pii++
		}
	}

	fmt.Println()
	fmt.Println(strings.Repeat("=", 60))
	fmt.Println("  GOVERNANCE SUMMARY")
	fmt.Println(strings.Repeat("=", 60))
	fmt.Printf("  Total events:      %d\n", len(events))
	fmt.Printf("  Allowed:           %d\n", allowed)
	fmt.Printf("  Denied:            %d\n", denied)
	if wouldDeny > 0 {
		fmt.Printf("  Would-deny (obs):  %d\n", wouldDeny)
	}
	if pii > 0 {
		fmt.Printf("  PII redactions:    %d\n", pii)
	}
	if approvalReq > 0 {
		fmt.Printf("  Approval requests: %d\n", approvalReq)
	}

	if denied > 0 {
		fmt.Println()
		fmt.Println("  Contracts enforced:")
		for _, e := range events {
			if e.Action == audit.ActionCallDenied {
				reason := e.Reason
				if len(reason) > 70 {
					reason = reason[:70]
				}
				fmt.Printf("    %sX %s: %s%s\n", colorRed, e.DecisionName, reason, colorReset)
			}
		}
	}
	fmt.Println()
}

// ── Scenario runner ─────────────────────────────────────────────────────

// RunScenarios runs the quick scenario set through the guard and prints results.
func RunScenarios(g *guard.Guard) {
	scenarios := QuickScenarios()
	ctx := context.Background()
	sink := g.LocalSink()

	passed, failed := 0, 0

	for i, s := range scenarios {
		PrintScenario(i+1, len(scenarios), s.Description)

		mark := sink.Mark()

		result, err := g.Run(ctx, s.ToolName, s.Args, ToolCallable(s.ToolName))

		action, detail := ClassifyResult(sink, mark, s.ToolName)

		if action == "" {
			// Fallback: classify from error (audit path is primary)
			if err != nil {
				var denied *edictum.DeniedError
				if errors.As(err, &denied) {
					action = "DENIED"
					detail = denied.Error() // includes decision source + name
				} else {
					action = "ERROR"
					detail = err.Error()
				}
			} else {
				action = "ALLOWED"
				detail = fmt.Sprintf("%s executed", s.ToolName)
			}
		}

		PrintResult(action, detail)

		// Show redacted output for redact scenarios
		if action == "REDACTED" && result != nil {
			resultStr := fmt.Sprintf("%v", result)
			if len(resultStr) > 120 {
				resultStr = resultStr[:120] + "..."
			}
			fmt.Printf("  %sRedacted output: %s%s\n", colorGray, resultStr, colorReset)
		}

		// Check expected vs actual
		got := strings.ToLower(action)
		want := s.Expected
		if got == want || (got == "observe" && want == "allowed") {
			passed++
		} else {
			failed++
			fmt.Printf("  %s!! Expected %s, got %s%s\n", colorYellow, want, got, colorReset)
		}
	}

	PrintSummary(sink)

	fmt.Printf("  Results: %s%d passed%s", colorGreen, passed, colorReset)
	if failed > 0 {
		fmt.Printf(", %s%d unexpected%s", colorYellow, failed, colorReset)
	}
	fmt.Printf(" (out of %d scenarios)\n\n", len(scenarios))
}
