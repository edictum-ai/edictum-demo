package main

import (
	"context"
	"encoding/json"
	"fmt"
)

type ToolFunc func(context.Context, map[string]any) (any, error)

func buildTools(workspace *HeroWorkspace) map[string]ToolFunc {
	return map[string]ToolFunc{
		"Read": func(_ context.Context, args map[string]any) (any, error) {
			path, ok := args["path"].(string)
			if !ok || path == "" {
				return nil, fmt.Errorf("Read.path is required")
			}
			return workspace.ReadFile(path)
		},
		"Write": func(_ context.Context, args map[string]any) (any, error) {
			path, ok := args["path"].(string)
			if !ok || path == "" {
				return nil, fmt.Errorf("Write.path is required")
			}
			content, ok := args["content"].(string)
			if !ok {
				return nil, fmt.Errorf("Write.content is required")
			}
			return workspace.WriteFile(path, content)
		},
		"Edit": func(_ context.Context, args map[string]any) (any, error) {
			path, ok := args["path"].(string)
			if !ok || path == "" {
				return nil, fmt.Errorf("Edit.path is required")
			}
			oldText, ok := args["old"].(string)
			if !ok {
				return nil, fmt.Errorf("Edit.old is required")
			}
			newText, ok := args["new"].(string)
			if !ok {
				return nil, fmt.Errorf("Edit.new is required")
			}
			return workspace.EditFile(path, oldText, newText)
		},
		"Grep": func(_ context.Context, args map[string]any) (any, error) {
			pattern, ok := args["pattern"].(string)
			if !ok || pattern == "" {
				return nil, fmt.Errorf("Grep.pattern is required")
			}
			results, err := workspace.Grep(pattern)
			if err != nil {
				return nil, err
			}
			if len(results) == 0 {
				return "No matches", nil
			}
			return joinLines(results), nil
		},
		"Glob": func(_ context.Context, args map[string]any) (any, error) {
			pattern, ok := args["pattern"].(string)
			if !ok || pattern == "" {
				return nil, fmt.Errorf("Glob.pattern is required")
			}
			raw, err := json.Marshal(workspace.Glob(pattern))
			if err != nil {
				return nil, err
			}
			return string(raw), nil
		},
		"Bash": func(_ context.Context, args map[string]any) (any, error) {
			command, ok := args["command"].(string)
			if !ok || command == "" {
				return nil, fmt.Errorf("Bash.command is required")
			}
			return workspace.Bash(command), nil
		},
	}
}

func joinLines(items []string) string {
	if len(items) == 0 {
		return ""
	}
	output := items[0]
	for _, item := range items[1:] {
		output += "\n" + item
	}
	return output
}
