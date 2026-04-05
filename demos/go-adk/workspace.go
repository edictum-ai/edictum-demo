package main

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
)

type workspaceState struct {
	BranchName string
	Staged     []string
	LastCommit string
	Pushed     bool
	PRURL      string
	CIGreen    bool
}

type HeroWorkspace struct {
	baseline map[string]string
	files    map[string]string
	state    workspaceState
}

func newHeroWorkspace(taskText string) *HeroWorkspace {
	files := map[string]string{
		"README.md": "# Hero Workspace\n\n" +
			"This workspace simulates a small CLI project used by the Edictum hero demo.\n" +
			"The task is to add a deterministic `--verbose` flag and carry the change through review.\n",
		"TASK.md": strings.TrimSpace(taskText) + "\n",
		"src/hero_cli.py": "from __future__ import annotations\n\n" +
			"VERBOSE_FLAG = False\n" +
			"VERBOSE_FLAG_COMPLETE = False\n\n" +
			"def run(verbose: bool = False) -> str:\n" +
			"    if verbose:\n" +
			"        return \"debug: verbose mode active\"\n" +
			"    return \"ok\"\n",
		"tests/test_hero_cli.py": "from src.hero_cli import VERBOSE_FLAG_COMPLETE, run\n\n" +
			"def test_verbose_flag_path() -> None:\n" +
			"    assert run(verbose=True).startswith(\"debug:\")\n" +
			"    assert VERBOSE_FLAG_COMPLETE is True\n",
	}

	baseline := make(map[string]string, len(files))
	current := make(map[string]string, len(files))
	for path, content := range files {
		baseline[path] = content
		current[path] = content
	}

	return &HeroWorkspace{
		baseline: baseline,
		files:    current,
		state: workspaceState{
			BranchName: "master",
		},
	}
}

func (w *HeroWorkspace) ReadFile(path string) (string, error) {
	content, ok := w.files[path]
	if !ok {
		return "", fmt.Errorf("missing workspace file: %s", path)
	}
	return content, nil
}

func (w *HeroWorkspace) WriteFile(path, content string) (string, error) {
	w.files[path] = content
	return fmt.Sprintf("Wrote %s", path), nil
}

func (w *HeroWorkspace) EditFile(path, oldText, newText string) (string, error) {
	current, err := w.ReadFile(path)
	if err != nil {
		return "", err
	}
	if !strings.Contains(current, oldText) {
		return "", fmt.Errorf("edit target not found in %s", path)
	}
	w.files[path] = strings.Replace(current, oldText, newText, 1)
	return fmt.Sprintf("Edited %s", path), nil
}

func (w *HeroWorkspace) Glob(pattern string) []string {
	matcher := globToRegexp(pattern)
	matches := make([]string, 0)
	for path := range w.files {
		if matcher.MatchString(path) {
			matches = append(matches, path)
		}
	}
	sort.Strings(matches)
	return matches
}

func (w *HeroWorkspace) Grep(pattern string) ([]string, error) {
	re, err := regexp.Compile(pattern)
	if err != nil {
		return nil, err
	}
	results := make([]string, 0)
	for _, path := range w.Glob("**/*") {
		lines := strings.Split(w.files[path], "\n")
		for idx, line := range lines {
			if re.MatchString(line) {
				results = append(results, fmt.Sprintf("%s:%d:%s", path, idx+1, line))
			}
		}
	}
	return results, nil
}

func (w *HeroWorkspace) ChangedFiles() []string {
	changed := make([]string, 0)
	for path, content := range w.files {
		if w.baseline[path] != content {
			changed = append(changed, path)
		}
	}
	sort.Strings(changed)
	return changed
}

func (w *HeroWorkspace) Diff(paths []string) string {
	selected := paths
	if len(selected) == 0 {
		selected = w.ChangedFiles()
	}
	chunks := make([]string, 0, len(selected))
	for _, path := range selected {
		before := w.baseline[path]
		after, ok := w.files[path]
		if !ok || before == after {
			continue
		}
		chunks = append(chunks, buildNaiveDiff(path, before, after))
	}
	if len(chunks) == 0 {
		return "No changes"
	}
	return strings.Join(chunks, "\n")
}

func (w *HeroWorkspace) GitStatusShort() string {
	staged := make(map[string]struct{}, len(w.state.Staged))
	for _, path := range w.state.Staged {
		staged[path] = struct{}{}
	}
	rows := make([]string, 0)
	for _, path := range w.ChangedFiles() {
		prefix := "M"
		if _, ok := w.baseline[path]; !ok {
			prefix = "A"
		}
		stagePrefix := " "
		if _, ok := staged[path]; ok {
			stagePrefix = prefix
		}
		rows = append(rows, fmt.Sprintf("%s%s %s", stagePrefix, prefix, path))
	}
	if len(rows) == 0 {
		return "clean"
	}
	return strings.Join(rows, "\n")
}

func (w *HeroWorkspace) findings() []string {
	source := w.files["src/hero_cli.py"]
	findings := make([]string, 0)
	if !strings.Contains(source, "VERBOSE_FLAG = True") || !strings.Contains(source, "VERBOSE_FLAG_COMPLETE = True") {
		findings = append(findings, "src/hero_cli.py does not finish the verbose flag implementation")
	}
	return findings
}

func (w *HeroWorkspace) Bash(command string) string {
	normalized := strings.TrimSpace(command)

	switch {
	case strings.HasPrefix(normalized, "git switch -c "):
		parts := strings.Fields(normalized)
		if len(parts) > 0 {
			w.state.BranchName = parts[len(parts)-1]
		}
		return fmt.Sprintf("Switched to a new branch '%s'", w.state.BranchName)
	case strings.HasPrefix(normalized, "python -m compileall"), strings.HasPrefix(normalized, "python3 -m compileall"):
		return "Listing 'src'...\nCompiling deterministic hero workspace"
	case strings.HasPrefix(normalized, "python -m pytest"), strings.HasPrefix(normalized, "python3 -m pytest"), strings.HasPrefix(normalized, "pytest"):
		if findings := w.findings(); len(findings) > 0 {
			return "FAILED: " + strings.Join(findings, "; ")
		}
		return "1 passed in 0.01s"
	case strings.HasPrefix(normalized, "git status"):
		return w.GitStatusShort()
	case strings.HasPrefix(normalized, "git diff"):
		if strings.Contains(normalized, " -- ") {
			selected := strings.Fields(strings.SplitN(normalized, " -- ", 2)[1])
			return w.Diff(selected)
		}
		return w.Diff(nil)
	case strings.HasPrefix(normalized, "git add"):
		w.state.Staged = w.ChangedFiles()
		return "staged " + strings.Join(w.state.Staged, ", ")
	case strings.HasPrefix(normalized, "git commit"):
		if len(w.state.Staged) == 0 {
			return "Error: nothing staged to commit"
		}
		w.state.LastCommit = normalized
		return fmt.Sprintf("[%s] %s", w.state.BranchName, normalized)
	case strings.HasPrefix(normalized, "git push"):
		if w.state.LastCommit == "" {
			return "Error: nothing committed to push"
		}
		w.state.Pushed = true
		return fmt.Sprintf("pushed %s to origin", w.state.BranchName)
	case strings.HasPrefix(normalized, "gh pr create"):
		w.state.PRURL = fmt.Sprintf("https://example.test/hero/%s", w.state.BranchName)
		return w.state.PRURL
	case strings.HasPrefix(normalized, "gh pr checks"), strings.HasPrefix(normalized, "gh run view"):
		if !w.state.Pushed || w.state.PRURL == "" {
			return "Error: PR is not ready for checks"
		}
		w.state.CIGreen = true
		return "All required checks passed"
	default:
		return "Simulated bash command: " + normalized
	}
}

func globToRegexp(pattern string) *regexp.Regexp {
	var builder strings.Builder
	builder.WriteString("^")
	for index := 0; index < len(pattern); index++ {
		current := pattern[index]
		if current == '*' {
			if index+1 < len(pattern) && pattern[index+1] == '*' {
				index++
				if index+1 < len(pattern) && pattern[index+1] == '/' {
					index++
					builder.WriteString("(?:.*\\/)?")
				} else {
					builder.WriteString(".*")
				}
			} else {
				builder.WriteString("[^/]*")
			}
			continue
		}
		builder.WriteString(regexp.QuoteMeta(string(current)))
	}
	builder.WriteString("$")
	return regexp.MustCompile(builder.String())
}

func buildNaiveDiff(path, before, after string) string {
	beforeLines := strings.Split(before, "\n")
	afterLines := strings.Split(after, "\n")
	rows := []string{
		fmt.Sprintf("--- a/%s", path),
		fmt.Sprintf("+++ b/%s", path),
		"@@",
	}
	maxLines := len(beforeLines)
	if len(afterLines) > maxLines {
		maxLines = len(afterLines)
	}
	for index := 0; index < maxLines; index++ {
		var left string
		var right string
		leftOK := index < len(beforeLines)
		rightOK := index < len(afterLines)
		if leftOK {
			left = beforeLines[index]
		}
		if rightOK {
			right = afterLines[index]
		}
		if leftOK && rightOK && left == right {
			rows = append(rows, " "+left)
			continue
		}
		if leftOK {
			rows = append(rows, "-"+left)
		}
		if rightOK {
			rows = append(rows, "+"+right)
		}
	}
	return strings.Join(rows, "\n")
}
