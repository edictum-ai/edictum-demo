import { tool } from 'ai'
import { z } from 'zod'

import { HeroWorkspace } from './workspace.js'

type ExecutableTool = {
  execute?: (args: Record<string, unknown>) => Promise<unknown> | unknown
}

export type HeroToolName = 'Read' | 'Write' | 'Edit' | 'Grep' | 'Glob' | 'Bash'
export type HeroToolMap = Record<HeroToolName, ExecutableTool>

export function buildTools(workspace: HeroWorkspace): HeroToolMap {
  return {
    Read: tool({
      description: 'Read a file from the deterministic hero workspace.',
      inputSchema: z.object({
        path: z.string(),
      }),
      execute: async ({ path }: { path: string }) => workspace.readFile(path),
    }) as ExecutableTool,
    Write: tool({
      description: 'Write a file in the deterministic hero workspace.',
      inputSchema: z.object({
        path: z.string(),
        content: z.string(),
      }),
      execute: async ({ path, content }: { path: string; content: string }) =>
        workspace.writeFile(path, content),
    }) as ExecutableTool,
    Edit: tool({
      description: 'Replace one deterministic snippet in a workspace file.',
      inputSchema: z.object({
        path: z.string(),
        old: z.string(),
        new: z.string(),
      }),
      execute: async ({
        path,
        old,
        new: replacement,
      }: {
        path: string
        old: string
        new: string
      }) => workspace.editFile(path, old, replacement),
    }) as ExecutableTool,
    Grep: tool({
      description: 'Search workspace files with a regex pattern.',
      inputSchema: z.object({
        pattern: z.string(),
      }),
      execute: async ({ pattern }: { pattern: string }) =>
        workspace.grep(pattern).join('\n') || 'No matches',
    }) as ExecutableTool,
    Glob: tool({
      description: 'Return workspace files matching a glob.',
      inputSchema: z.object({
        pattern: z.string(),
      }),
      execute: async ({ pattern }: { pattern: string }) => JSON.stringify(workspace.glob(pattern)),
    }) as ExecutableTool,
    Bash: tool({
      description: 'Run a deterministic bash simulation against the hero workspace.',
      inputSchema: z.object({
        command: z.string(),
      }),
      execute: async ({ command }: { command: string }) => workspace.bash(command),
    }) as ExecutableTool,
  }
}
