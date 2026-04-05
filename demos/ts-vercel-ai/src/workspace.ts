type WorkspaceState = {
  branchName: string
  stagedPaths: string[]
  lastCommit: string
  pushed: boolean
  prUrl: string
  ciGreen: boolean
}

const DEFAULT_TASK_TEXT = `# Hero Demo Task

Add a deterministic --verbose flag to the sample CLI used by the hero demo.

Acceptance criteria:

- Read the task brief and the workspace README before editing.
- Create a feature branch before implementation.
- Run a baseline verification command before making changes.
- Implement the verbose flag in src/hero_cli.py.
- Trigger at least one blocked action during implementation so the workflow emits a visible block event.
- Run local verification after the change.
- Send the change through external review.
- Update the README after approval.
- Stage, commit, push, open a PR, and check CI.
`

function escapeRegExp(value: string): string {
  return value.replace(/[|\\{}()[\]^$+?.]/g, '\\$&')
}

function globToRegExp(pattern: string): RegExp {
  let output = '^'
  for (let index = 0; index < pattern.length; index += 1) {
    const current = pattern[index]
    const next = pattern[index + 1]
    if (current === '*') {
      if (next === '*') {
        index += 1
        if (pattern[index + 1] === '/') {
          index += 1
          output += '(?:.*\\/)?'
        } else {
          output += '.*'
        }
      } else {
        output += '[^/]*'
      }
      continue
    }
    output += escapeRegExp(current ?? '')
  }
  output += '$'
  return new RegExp(output)
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

function buildNaiveDiff(path: string, before: string, after: string): string {
  const beforeLines = before.split('\n')
  const afterLines = after.split('\n')
  const rows = [`--- a/${path}`, `+++ b/${path}`, '@@']
  const max = Math.max(beforeLines.length, afterLines.length)
  for (let index = 0; index < max; index += 1) {
    const left = beforeLines[index]
    const right = afterLines[index]
    if (left === right) {
      if (left !== undefined) {
        rows.push(` ${left}`)
      }
      continue
    }
    if (left !== undefined) {
      rows.push(`-${left}`)
    }
    if (right !== undefined) {
      rows.push(`+${right}`)
    }
  }
  return rows.join('\n')
}

export class HeroWorkspace {
  private readonly baseline = new Map<string, string>()
  private readonly files = new Map<string, string>()
  private readonly state: WorkspaceState = {
    branchName: 'master',
    stagedPaths: [],
    lastCommit: '',
    pushed: false,
    prUrl: '',
    ciGreen: false,
  }

  constructor(taskText: string = DEFAULT_TASK_TEXT) {
    const seedFiles: Record<string, string> = {
      'README.md':
        '# Hero Workspace\n\n' +
        'This workspace simulates a small CLI project used by the Edictum hero demo.\n' +
        'The task is to add a deterministic `--verbose` flag and carry the change through review.\n',
      'TASK.md': `${taskText.trim()}\n`,
      'src/hero_cli.py':
        'from __future__ import annotations\n\n' +
        'VERBOSE_FLAG = False\n' +
        'VERBOSE_FLAG_COMPLETE = False\n\n' +
        'def run(verbose: bool = False) -> str:\n' +
        '    if verbose:\n' +
        '        return "debug: verbose mode active"\n' +
        '    return "ok"\n',
      'tests/test_hero_cli.py':
        'from src.hero_cli import VERBOSE_FLAG_COMPLETE, run\n\n' +
        'def test_verbose_flag_path() -> None:\n' +
        '    assert run(verbose=True).startswith("debug:")\n' +
        '    assert VERBOSE_FLAG_COMPLETE is True\n',
    }

    for (const [path, content] of Object.entries(seedFiles)) {
      this.baseline.set(path, content)
      this.files.set(path, content)
    }
  }

  readFile(path: string): string {
    const content = this.files.get(path)
    if (content == null) {
      throw new Error(`missing workspace file: ${path}`)
    }
    return content
  }

  writeFile(path: string, content: string): string {
    this.files.set(path, content)
    return `Wrote ${path}`
  }

  editFile(path: string, oldText: string, newText: string): string {
    const current = this.readFile(path)
    if (!current.includes(oldText)) {
      throw new Error(`edit target not found in ${path}`)
    }
    this.files.set(path, current.replace(oldText, newText))
    return `Edited ${path}`
  }

  glob(pattern: string): string[] {
    const matcher = globToRegExp(pattern)
    return [...this.files.keys()].filter((path) => matcher.test(path)).sort()
  }

  grep(pattern: string): string[] {
    const matcher = new RegExp(pattern)
    const results: string[] = []
    for (const path of this.glob('**/*')) {
      const lines = this.readFile(path).split('\n')
      lines.forEach((line, index) => {
        if (matcher.test(line)) {
          results.push(`${path}:${index + 1}:${line}`)
        }
      })
    }
    return results
  }

  changedFiles(): string[] {
    const changed: string[] = []
    for (const [path, content] of this.files.entries()) {
      if (this.baseline.get(path) !== content) {
        changed.push(path)
      }
    }
    return changed.sort()
  }

  diff(paths?: string[]): string {
    const selected = (paths ?? this.changedFiles()).filter((path) => this.files.has(path)).sort()
    const chunks = selected
      .map((path) => {
        const before = this.baseline.get(path) ?? ''
        const after = this.readFile(path)
        if (before === after) {
          return ''
        }
        return buildNaiveDiff(path, before, after)
      })
      .filter(Boolean)
    return chunks.join('\n') || 'No changes'
  }

  gitStatusShort(): string {
    const staged = new Set(this.state.stagedPaths)
    const rows = this.changedFiles().map((path) => {
      const prefix = this.baseline.has(path) ? 'M' : 'A'
      const stagePrefix = staged.has(path) ? prefix : ' '
      return `${stagePrefix}${prefix} ${path}`
    })
    return rows.length > 0 ? rows.join('\n') : 'clean'
  }

  private findings(): string[] {
    const source = this.readFile('src/hero_cli.py')
    const findings: string[] = []
    if (!source.includes('VERBOSE_FLAG = True') || !source.includes('VERBOSE_FLAG_COMPLETE = True')) {
      findings.push('src/hero_cli.py does not finish the verbose flag implementation')
    }
    return findings
  }

  bash(command: string): string {
    const normalized = command.trim()

    if (normalized.startsWith('git switch -c ')) {
      const branchName = normalized.split(/\s+/).at(-1) ?? 'hero-ts'
      this.state.branchName = branchName
      return `Switched to a new branch '${branchName}'`
    }

    if (
      normalized.startsWith('python -m compileall') ||
      normalized.startsWith('python3 -m compileall')
    ) {
      return "Listing 'src'...\nCompiling deterministic hero workspace"
    }

    if (
      normalized.startsWith('python -m pytest') ||
      normalized.startsWith('python3 -m pytest') ||
      normalized.startsWith('pytest')
    ) {
      const findings = this.findings()
      if (findings.length > 0) {
        return `FAILED: ${findings.join('; ')}`
      }
      return '1 passed in 0.01s'
    }

    if (normalized.startsWith('git status')) {
      return this.gitStatusShort()
    }

    if (normalized.startsWith('git diff')) {
      const separator = normalized.split(' -- ', 2)
      if (separator.length === 2) {
        const selected = separator[1]!.split(/\s+/).filter(Boolean)
        return this.diff(selected)
      }
      return this.diff()
    }

    if (normalized.startsWith('git add')) {
      this.state.stagedPaths = this.changedFiles()
      return `staged ${this.state.stagedPaths.join(', ')}`
    }

    if (normalized.startsWith('git commit')) {
      if (this.state.stagedPaths.length === 0) {
        return 'Error: nothing staged to commit'
      }
      this.state.lastCommit = normalized
      return `[${this.state.branchName}] ${normalized}`
    }

    if (normalized.startsWith('git push')) {
      if (!this.state.lastCommit) {
        return 'Error: nothing committed to push'
      }
      this.state.pushed = true
      return `pushed ${this.state.branchName} to origin`
    }

    if (normalized.startsWith('gh pr create')) {
      this.state.prUrl = `https://example.test/hero/${this.state.branchName}`
      return this.state.prUrl
    }

    if (normalized.startsWith('gh pr checks') || normalized.startsWith('gh run view')) {
      if (!this.state.pushed || !this.state.prUrl) {
        return 'Error: PR is not ready for checks'
      }
      this.state.ciGreen = true
      return 'All required checks passed'
    }

    return `Simulated bash command: ${normalized}`
  }

  summary(): Record<string, unknown> {
    return {
      branch_name: this.state.branchName,
      changed_files: this.changedFiles(),
      pushed: this.state.pushed,
      pr_url: this.state.prUrl,
      ci_green: this.state.ciGreen,
      staged_paths: [...this.state.stagedPaths],
      last_commit: this.state.lastCommit,
      files: formatJson(Object.fromEntries(this.files.entries())),
    }
  }
}
