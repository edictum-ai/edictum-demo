package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/edictum-ai/edictum-go/audit"
	edictum "github.com/edictum-ai/edictum-go"
	"github.com/edictum-ai/edictum-go/adapter/adkgo"
	"github.com/edictum-ai/edictum-go/guard"
	"github.com/edictum-ai/edictum-go/server"
	"github.com/edictum-ai/edictum-go/session"
	"github.com/edictum-ai/edictum-go/toolcall"
	"github.com/edictum-ai/edictum-go/workflow"
)

type summary struct {
	Succeeded       bool                   `json:"succeeded"`
	AgentID         string                 `json:"agent_id"`
	SessionID       string                 `json:"session_id"`
	StagesCompleted []string               `json:"stages_completed"`
	EventCount      int                    `json:"event_count"`
	BlockedCount    int                    `json:"blocked_count"`
	ApprovalCount   int                    `json:"approval_count"`
	WorkflowState   map[string]any         `json:"workflow_state"`
	StageHistory    []string               `json:"stage_history"`
	ToolHistory     []map[string]any       `json:"tool_history"`
}

type heroAgent struct {
	agentID      string
	sessionID    string
	environment  string
	client       *server.Client
	auditSink    *server.AuditSink
	runtime      *workflow.Runtime
	session      *session.Session
	principal    map[string]any
	workspace    *HeroWorkspace
	tools        map[string]ToolFunc
	wrappedTools map[string]ToolFunc
	stageHistory []string
	lastStage    string
	toolHistory  []map[string]any
	mu           sync.Mutex
}

func main() {
	ctx := context.Background()
	apiURL := mustEnv("EDICTUM_URL")
	apiKey := mustEnv("EDICTUM_API_KEY")

	controlClient, err := server.NewClient(server.ClientConfig{
		BaseURL: apiURL,
		APIKey:  apiKey,
		AgentID: "hero-go-runner",
		Env:     "hero-demo",
	})
	if err != nil {
		fail(err)
	}
	if err := waitForHealth(ctx, controlClient); err != nil {
		fail(err)
	}

	agent, err := newHeroAgent(ctx, apiURL, apiKey)
	if err != nil {
		fail(err)
	}
	defer agent.close(ctx)
	runStartedAt := time.Now()

	stop := make(chan struct{})
	approverDone := make(chan error, 1)
	go func() {
		approverDone <- autoApprove(ctx, controlClient, agent.agentID, agent.sessionID, runStartedAt, stop)
	}()

	if err := agent.run(ctx); err != nil {
		close(stop)
		<-approverDone
		fail(err)
	}

	close(stop)
	if err := <-approverDone; err != nil {
		fail(err)
	}
	if err := agent.close(ctx); err != nil {
		fail(err)
	}

	finalSummary, err := collectSummary(ctx, controlClient, agent, runStartedAt)
	if err != nil {
		fail(err)
	}
	encoded, err := json.MarshalIndent(finalSummary, "", "  ")
	if err != nil {
		fail(err)
	}
	fmt.Println(string(encoded))
}

func newHeroAgent(ctx context.Context, apiURL, apiKey string) (*heroAgent, error) {
	client, err := server.NewClient(server.ClientConfig{
		BaseURL: apiURL,
		APIKey:  apiKey,
		AgentID: "hero-go",
		Env:     "hero-demo",
	})
	if err != nil {
		return nil, err
	}
	workflowPath := filepath.Clean(filepath.Join("..", "..", "workflows", "coding-guard.yaml"))
	definition, err := workflow.Load(workflowPath)
	if err != nil {
		return nil, err
	}
	runtime, err := workflow.NewRuntime(definition)
	if err != nil {
		return nil, err
	}
	backend := server.NewBackend(client)
	sessionID := fmt.Sprintf("hero-go-%d", time.Now().UnixNano())
	sess, err := session.New(sessionID, backend)
	if err != nil {
		return nil, err
	}
	taskBytes, err := os.ReadFile(filepath.Clean(filepath.Join("..", "hero", "TASK.md")))
	if err != nil {
		return nil, err
	}
	workspace := newHeroWorkspace(string(taskBytes))
	tools := buildTools(workspace)

	principal := toolcall.NewPrincipal(
		toolcall.WithServiceID("hero-go-service"),
		toolcall.WithRole("implementer"),
		toolcall.WithClaims(map[string]any{
			"demo":       "hero-go",
			"session_id": sessionID,
		}),
	)
	principalPayload := map[string]any{
		"serviceId": "hero-go-service",
		"role":      "implementer",
		"claims": map[string]any{
			"demo":       "hero-go",
			"session_id": sessionID,
		},
	}
	auditSink := server.NewAuditSink(
		client,
		server.WithBatchSize(1),
		server.WithFlushInterval(100*time.Millisecond),
	)
	approvalBackend := server.NewApprovalBackend(
		client,
		server.WithPollInterval(200*time.Millisecond),
	)
	g := guard.New(
		guard.WithEnvironment("hero-demo"),
		guard.WithBackend(backend),
		guard.WithAuditSink(auditSink),
		guard.WithApprovalBackend(approvalBackend),
		guard.WithWorkflowRuntime(runtime),
		guard.WithPrincipal(&principal),
		guard.WithTools(map[string]map[string]any{
			"Read":  {"side_effect": "read", "idempotent": true},
			"Grep":  {"side_effect": "read", "idempotent": true},
			"Glob":  {"side_effect": "read", "idempotent": true},
			"Write": {"side_effect": "write", "idempotent": false},
			"Edit":  {"side_effect": "write", "idempotent": false},
			"Bash":  {"side_effect": "irreversible", "idempotent": false},
		}),
	)
	adapter := adkgo.New(
		g,
		guard.WithSessionID(sessionID),
		guard.WithRunEnvironment("hero-demo"),
		guard.WithRunPrincipal(&principal),
	)

	wrapped := make(map[string]ToolFunc, len(tools))
	for name, fn := range tools {
		wrapped[name] = adapter.WrapTool(name, fn)
	}

	agent := &heroAgent{
		agentID:      "hero-go",
		sessionID:    sessionID,
		environment:  "hero-demo",
		client:       client,
		auditSink:    auditSink,
		runtime:      runtime,
		session:      sess,
		principal:    principalPayload,
		workspace:    workspace,
		tools:        tools,
		wrappedTools: wrapped,
		lastStage:    "__missing__",
	}
	if err := agent.recordStage(ctx); err != nil {
		return nil, err
	}
	return agent, nil
}

func (a *heroAgent) close(ctx context.Context) error {
	a.auditSink.Close(ctx)
	return nil
}

func (a *heroAgent) run(ctx context.Context) error {
	steps := []struct {
		tool string
		args map[string]any
	}{
		{"Read", map[string]any{"path": "README.md"}},
		{"Read", map[string]any{"path": "TASK.md"}},
		{"Glob", map[string]any{"pattern": "src/*.py"}},
		{"Bash", map[string]any{"command": fmt.Sprintf("git switch -c hero-go/%s", a.sessionID)}},
		{"Bash", map[string]any{"command": "python -m compileall src"}},
		{"Read", map[string]any{"path": "src/hero_cli.py"}},
		{"Edit", map[string]any{
			"path": "src/hero_cli.py",
			"old":  "VERBOSE_FLAG = False\nVERBOSE_FLAG_COMPLETE = False\n",
			"new":  "VERBOSE_FLAG = True\nVERBOSE_FLAG_COMPLETE = True\n",
		}},
		{"Bash", map[string]any{"command": "git push origin HEAD --dry-run"}},
		{"Bash", map[string]any{"command": "python -m compileall src"}},
		{"Bash", map[string]any{"command": "git status --short"}},
		{"Bash", map[string]any{"command": "git diff -- src/hero_cli.py"}},
		{"Edit", map[string]any{
			"path": "README.md",
			"old":  "The task is to add a deterministic `--verbose` flag and carry the change through review.\n",
			"new": "The task is to add a deterministic `--verbose` flag and carry the change through review.\n" +
				"The CLI now documents a deterministic verbose path for the Go hero demo.\n",
		}},
		{"Bash", map[string]any{"command": "git add ."}},
		{"Bash", map[string]any{"command": "git commit -m \"feat: add deterministic verbose flag\""}},
		{"Bash", map[string]any{"command": "git push origin HEAD"}},
		{"Bash", map[string]any{"command": "gh pr create --title \"Hero Go Demo\" --body \"Deterministic integration run\""}},
		{"Bash", map[string]any{"command": "gh pr checks --watch"}},
		{"Bash", map[string]any{"command": "gh run view"}},
	}

	for _, step := range steps {
		if _, _, err := a.invoke(ctx, step.tool, step.args); err != nil {
			return err
		}
	}
	state, err := a.runtime.State(ctx, a.session)
	if err != nil {
		return err
	}
	if state.ActiveStage == "ci-green" {
		if _, err := a.runtime.SetStage(ctx, a.session, "done"); err != nil {
			return err
		}
		if err := a.emitWorkflowStateUpdated(ctx, "ci-green", "done"); err != nil {
			return err
		}
		if err := a.recordStage(ctx); err != nil {
			return err
		}
	}
	return nil
}

func (a *heroAgent) emitWorkflowStateUpdated(ctx context.Context, stageID, toStageID string) error {
	state, err := a.runtime.State(ctx, a.session)
	if err != nil {
		return err
	}
	toolSuccess := true
	postconditionsPassed := true
	sessionAttempts := len(a.toolHistory)
	sessionExecutions := 0
	for _, item := range a.toolHistory {
		if denied, _ := item["denied"].(bool); !denied {
			sessionExecutions++
		}
	}
	event := audit.NewEvent()
	event.RunID = a.sessionID
	event.SessionID = a.sessionID
	event.CallID = fmt.Sprintf("workflow-state-%d", len(a.toolHistory))
	event.CallIndex = len(a.toolHistory)
	event.ToolName = "workflow.setStage"
	event.ToolArgs = map[string]any{"stage": toStageID}
	event.SideEffect = "state"
	event.Environment = a.environment
	event.Principal = a.principal
	event.Action = audit.ActionWorkflowStateUpdated
	event.Workflow = map[string]any{
		"name":             a.runtime.Definition().Metadata.Name,
		"version":          a.runtime.Definition().Metadata.Version,
		"stage_id":         stageID,
		"to_stage_id":      toStageID,
		"active_stage":     state.ActiveStage,
		"completed_stages": append([]string{}, state.CompletedStages...),
		"blocked_reason":   state.BlockedReason,
		"pending_approval": map[string]any{"required": state.PendingApproval.Required},
	}
	if state.PendingApproval.StageID != "" {
		event.Workflow["pending_approval"].(map[string]any)["stage_id"] = state.PendingApproval.StageID
	}
	if state.PendingApproval.Message != "" {
		event.Workflow["pending_approval"].(map[string]any)["message"] = state.PendingApproval.Message
	}
	if state.LastRecordedEvidence != nil {
		event.Workflow["last_recorded_evidence"] = map[string]any{
			"tool":      state.LastRecordedEvidence.Tool,
			"summary":   state.LastRecordedEvidence.Summary,
			"timestamp": state.LastRecordedEvidence.Timestamp,
		}
	}
	if state.LastBlockedAction != nil {
		event.Workflow["last_blocked_action"] = map[string]any{
			"tool":      state.LastBlockedAction.Tool,
			"summary":   state.LastBlockedAction.Summary,
			"message":   state.LastBlockedAction.Message,
			"timestamp": state.LastBlockedAction.Timestamp,
		}
	}
	event.ToolSuccess = &toolSuccess
	event.PostconditionsPassed = &postconditionsPassed
	event.ResultSummary = "workflow set to done"
	event.SessionAttemptCount = &sessionAttempts
	event.SessionExecutionCount = &sessionExecutions
	return a.auditSink.Emit(ctx, &event)
}

func (a *heroAgent) invoke(ctx context.Context, toolName string, args map[string]any) (string, bool, error) {
	fn, ok := a.wrappedTools[toolName]
	if !ok {
		return "", false, fmt.Errorf("unknown tool %s", toolName)
	}
	result, err := fn(ctx, args)
	if err != nil {
		var blocked *edictum.BlockedError
		if errors.As(err, &blocked) {
			if stageErr := a.recordStage(ctx); stageErr != nil {
				return "", true, stageErr
			}
			text := "DENIED: " + blocked.Reason
			a.appendToolHistory(toolName, true, text)
			return text, true, nil
		}
		return "", false, err
	}
	if err := a.recordStage(ctx); err != nil {
		return "", false, err
	}
	text := stringify(result)
	a.appendToolHistory(toolName, false, text)
	return text, false, nil
}

func (a *heroAgent) appendToolHistory(toolName string, denied bool, text string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.toolHistory = append(a.toolHistory, map[string]any{
		"tool_name": toolName,
		"denied":    denied,
		"text":      text,
	})
}

func (a *heroAgent) recordStage(ctx context.Context) error {
	state, err := a.runtime.State(ctx, a.session)
	if err != nil {
		return err
	}
	if state.ActiveStage != a.lastStage {
		a.lastStage = state.ActiveStage
		a.stageHistory = append(a.stageHistory, state.ActiveStage)
		if state.ActiveStage != "" {
			fmt.Fprintf(os.Stderr, "hero-go stage -> %s\n", state.ActiveStage)
		}
	}
	return nil
}

func waitForHealth(ctx context.Context, client *server.Client) error {
	deadline := time.Now().Add(15 * time.Second)
	var lastErr error
	for time.Now().Before(deadline) {
		if _, err := client.Get(ctx, "/v1/health"); err == nil {
			return nil
		} else {
			lastErr = err
		}
		time.Sleep(250 * time.Millisecond)
	}
	return fmt.Errorf("edictum-api did not become healthy: %w", lastErr)
}

func autoApprove(ctx context.Context, client *server.Client, agentID, sessionID string, runStartedAt time.Time, stop <-chan struct{}) error {
	handled := map[string]struct{}{}
	for {
		select {
		case <-stop:
			return nil
		default:
		}

		path := fmt.Sprintf("/v1/approvals?agent_id=%s&status=pending", url.QueryEscape(agentID))
		resp, err := client.Get(ctx, path)
		if err == nil && resp != nil {
			for _, approvalID := range approvalIDs(resp["approvals"], sessionID, runStartedAt) {
				if _, seen := handled[approvalID]; seen {
					continue
				}
				handled[approvalID] = struct{}{}
				_, postErr := client.Post(ctx, "/v1/approvals/"+approvalID+"/decide", map[string]any{
					"decision":    "approved",
					"decided_by":  "hero-go-reviewer",
					"decided_via": "hero-go-runner",
					"reason":      "Auto-approved deterministic Go hero demo",
				})
				if postErr != nil {
					return postErr
				}
			}
		}

		select {
		case <-stop:
			return nil
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(200 * time.Millisecond):
		}
	}
}

func collectSummary(ctx context.Context, client *server.Client, agent *heroAgent, runStartedAt time.Time) (summary, error) {
	workflowPath := fmt.Sprintf(
		"/v1/agents/%s/workflow-state?session_id=%s",
		url.PathEscape(agent.agentID),
		url.QueryEscape(agent.sessionID),
	)
	workflowState, err := client.Get(ctx, workflowPath)
	if err != nil {
		return summary{}, err
	}
	eventsResp, err := client.Get(
		ctx,
		fmt.Sprintf(
			"/v1/events?agent_id=%s&session_id=%s&limit=500",
			url.QueryEscape(agent.agentID),
			url.QueryEscape(agent.sessionID),
		),
	)
	if err != nil {
		return summary{}, err
	}
	approvalsResp, err := client.Get(
		ctx,
		fmt.Sprintf(
			"/v1/approvals?agent_id=%s",
			url.QueryEscape(agent.agentID),
		),
	)
	if err != nil {
		return summary{}, err
	}

	state, err := agent.runtime.State(ctx, agent.session)
	if err != nil {
		return summary{}, err
	}
	stagesCompleted := append([]string{}, state.CompletedStages...)
	if activeStage, _ := workflowState["active_stage"].(string); activeStage == "done" && !contains(stagesCompleted, "done") {
		stagesCompleted = append(stagesCompleted, "done")
	}

	eventCount := len(asSlice(eventsResp["events"]))
	if total, ok := number(eventsResp["total"]); ok {
		eventCount = total
	}
	blockedCount := 0
	for _, item := range asSlice(eventsResp["events"]) {
		if event, ok := item.(map[string]any); ok {
			if action, _ := event["action"].(string); action == "call_blocked" {
				blockedCount++
			}
		}
	}

	return summary{
		Succeeded:       workflowState["active_stage"] == "done",
		AgentID:         agent.agentID,
		SessionID:       agent.sessionID,
		StagesCompleted: stagesCompleted,
		EventCount:      eventCount,
		BlockedCount:    blockedCount,
		ApprovalCount:   len(approvalsByScope(approvalsResp["approvals"], agent.sessionID, runStartedAt)),
		WorkflowState:   workflowState,
		StageHistory:    append([]string{}, agent.stageHistory...),
		ToolHistory:     append([]map[string]any{}, agent.toolHistory...),
	}, nil
}

func approvalIDs(value any, sessionID string, runStartedAt time.Time) []string {
	approvals := approvalsByScope(value, sessionID, runStartedAt)
	ids := make([]string, 0, len(approvals))
	for _, approval := range approvals {
		if id, ok := approval["id"].(string); ok && id != "" {
			ids = append(ids, id)
		}
	}
	return ids
}

func approvalsByScope(value any, sessionID string, runStartedAt time.Time) []map[string]any {
	items := asSlice(value)
	approvals := make([]map[string]any, 0, len(items))
	for _, item := range items {
		approval, ok := item.(map[string]any)
		if !ok {
			continue
		}
		approvalSessionID, _ := approval["session_id"].(string)
		if approvalSessionID == sessionID {
			approvals = append(approvals, approval)
			continue
		}
		if approvalSessionID != "" {
			continue
		}
		createdAt, _ := approval["created_at"].(string)
		if createdAt == "" {
			continue
		}
		parsed, err := time.Parse(time.RFC3339Nano, createdAt)
		if err != nil {
			continue
		}
		if !parsed.Before(runStartedAt) {
			approvals = append(approvals, approval)
		}
	}
	return approvals
}

func asSlice(value any) []any {
	items, ok := value.([]any)
	if !ok {
		return []any{}
	}
	return items
}

func number(value any) (int, bool) {
	switch typed := value.(type) {
	case float64:
		return int(typed), true
	case int:
		return typed, true
	default:
		return 0, false
	}
}

func stringify(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	default:
		raw, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			return fmt.Sprintf("%v", value)
		}
		return string(raw)
	}
}

func contains(items []string, needle string) bool {
	for _, item := range items {
		if item == needle {
			return true
		}
	}
	return false
}

func mustEnv(name string) string {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		fail(fmt.Errorf("%s is required", name))
	}
	return value
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
