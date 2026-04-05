import { randomUUID } from 'node:crypto'

import {
  AuditAction,
  createAuditEvent,
  createPrincipal,
  Edictum,
  EdictumDenied,
  Session,
  WorkflowRuntime,
  loadWorkflow,
  type WorkflowState,
} from '@edictum/core'
import {
  EdictumServerClient,
  ServerApprovalBackend,
  ServerAuditSink,
  ServerBackend,
} from '@edictum/server'
import { VercelAIAdapter } from '@edictum/vercel-ai'

import { buildTools, type HeroToolMap, type HeroToolName } from './tools.js'
import { HeroWorkspace } from './workspace.js'

export type HeroTsConfig = {
  apiUrl: string
  apiKey: string
  workflowPath: string
  taskText: string
  agentId?: string
  environment?: string
}

export type ToolInvocationResult = {
  toolName: HeroToolName
  denied: boolean
  text: string
}

export type AgentRunResult = {
  agentId: string
  sessionId: string
  finalState: WorkflowState
  stageHistory: string[]
  toolHistory: ToolInvocationResult[]
}

function stringifyResult(result: unknown): string {
  if (typeof result === 'string') {
    return result
  }
  return JSON.stringify(result, null, 2)
}

export class HeroTsAgent {
  readonly agentId: string
  readonly sessionId: string
  readonly environment: string

  private readonly client: EdictumServerClient
  private readonly auditSink: ServerAuditSink
  private readonly workflowRuntime: WorkflowRuntime
  private readonly principal: ReturnType<typeof createPrincipal>
  private readonly session: Session
  private readonly workspace: HeroWorkspace
  private readonly tools: HeroToolMap
  private readonly callbacks: ReturnType<VercelAIAdapter['asCallbacks']>
  private readonly toolHistory: ToolInvocationResult[] = []
  private readonly stageHistory: string[] = []
  private lastStage = '__missing__'
  private callIndex = 0

  constructor(config: HeroTsConfig) {
    this.agentId = config.agentId ?? 'hero-ts'
    this.sessionId = `hero-ts-${randomUUID().slice(0, 12)}`
    this.environment = config.environment ?? 'hero-demo'

    this.client = new EdictumServerClient({
      baseUrl: config.apiUrl,
      apiKey: config.apiKey,
      agentId: this.agentId,
      env: this.environment,
    })
    this.auditSink = new ServerAuditSink(this.client, {
      batchSize: 1,
      flushInterval: 100,
    })

    const backend = new ServerBackend(this.client)
    const approvalBackend = new ServerApprovalBackend(this.client)
    this.workflowRuntime = new WorkflowRuntime(loadWorkflow(config.workflowPath))
    this.session = new Session(this.sessionId, backend)
    this.workspace = new HeroWorkspace(config.taskText)
    this.tools = buildTools(this.workspace)

    this.principal = createPrincipal({
      serviceId: 'hero-ts-service',
      role: 'implementer',
      claims: {
        demo: 'hero-ts',
        session_id: this.sessionId,
      },
    })

    const guard = new Edictum({
      environment: this.environment,
      mode: 'enforce',
      backend,
      auditSink: this.auditSink,
      approvalBackend,
      workflowRuntime: this.workflowRuntime,
      principal: this.principal,
      tools: {
        Read: { side_effect: 'read', idempotent: true },
        Grep: { side_effect: 'read', idempotent: true },
        Glob: { side_effect: 'read', idempotent: true },
        Write: { side_effect: 'write', idempotent: false },
        Edit: { side_effect: 'write', idempotent: false },
        Bash: { side_effect: 'irreversible', idempotent: false },
      },
    })
    const adapter = new VercelAIAdapter(guard, {
      sessionId: this.sessionId,
      principal: this.principal,
    })
    this.callbacks = adapter.asCallbacks()
  }

  async close(): Promise<void> {
    await this.auditSink.close()
  }

  private async recordStage(): Promise<void> {
    const state = await this.workflowRuntime.state(this.session)
    if (state.activeStage !== this.lastStage) {
      this.lastStage = state.activeStage
      this.stageHistory.push(state.activeStage)
      if (state.activeStage) {
        console.error(`hero-ts stage -> ${state.activeStage}`)
      }
    }
  }

  private async invoke(toolName: HeroToolName, args: Record<string, unknown>): Promise<ToolInvocationResult> {
    const toolCallId = `${toolName.toLowerCase()}-${this.callIndex}`
    this.callIndex += 1
    const event = {
      toolCall: {
        toolCallId,
        toolName,
        input: args,
      },
    }

    try {
      await this.callbacks.experimental_onToolCallStart(event)
    } catch (error) {
      if (error instanceof EdictumDenied) {
        await this.recordStage()
        const denied = {
          toolName,
          denied: true,
          text: error.message,
        } satisfies ToolInvocationResult
        this.toolHistory.push(denied)
        return denied
      }
      throw error
    }

    const executable = this.tools[toolName].execute
    if (executable == null) {
      throw new Error(`tool ${toolName} is missing execute()`)
    }

    let output: unknown
    try {
      output = await executable(args)
    } catch (error) {
      await this.callbacks.experimental_onToolCallFinish({
        ...event,
        error: error instanceof Error ? error.message : String(error),
      })
      throw error
    }

    await this.callbacks.experimental_onToolCallFinish({
      ...event,
      output,
    })

    await this.recordStage()
    const result = {
      toolName,
      denied: false,
      text: stringifyResult(output),
    } satisfies ToolInvocationResult
    this.toolHistory.push(result)
    return result
  }

  async run(): Promise<AgentRunResult> {
    await this.recordStage()

    await this.invoke('Read', { path: 'README.md' })
    await this.invoke('Read', { path: 'TASK.md' })
    await this.invoke('Glob', { pattern: 'src/*.py' })
    await this.invoke('Bash', { command: `git switch -c hero-ts/${this.sessionId}` })
    await this.invoke('Bash', { command: 'python -m compileall src' })

    await this.invoke('Read', { path: 'src/hero_cli.py' })
    await this.invoke('Edit', {
      path: 'src/hero_cli.py',
      old: 'VERBOSE_FLAG = False\nVERBOSE_FLAG_COMPLETE = False\n',
      new: 'VERBOSE_FLAG = True\nVERBOSE_FLAG_COMPLETE = True\n',
    })
    await this.invoke('Bash', { command: 'git push origin HEAD --dry-run' })
    await this.invoke('Bash', { command: 'python -m compileall src' })

    await this.invoke('Bash', { command: 'git status --short' })
    await this.invoke('Bash', { command: 'git diff -- src/hero_cli.py' })
    await this.invoke('Edit', {
      path: 'README.md',
      old: 'The task is to add a deterministic `--verbose` flag and carry the change through review.\n',
      new:
        'The task is to add a deterministic `--verbose` flag and carry the change through review.\n' +
        'The CLI now documents a deterministic verbose path for the TS hero demo.\n',
    })
    await this.invoke('Bash', { command: 'git add .' })
    await this.invoke('Bash', { command: 'git commit -m "feat: add deterministic verbose flag"' })
    await this.invoke('Bash', { command: 'git push origin HEAD' })
    await this.invoke('Bash', {
      command: 'gh pr create --title "Hero TS Demo" --body "Deterministic integration run"',
    })
    await this.invoke('Bash', { command: 'gh pr checks --watch' })
    await this.invoke('Bash', { command: 'gh run view' })
    await this.finalizeDoneStage()

    const finalState = await this.workflowRuntime.state(this.session)
    if (finalState.activeStage && finalState.activeStage !== this.lastStage) {
      await this.recordStage()
    }

    return {
      agentId: this.agentId,
      sessionId: this.sessionId,
      finalState,
      stageHistory: [...this.stageHistory],
      toolHistory: [...this.toolHistory],
    }
  }

  private async finalizeDoneStage(): Promise<void> {
    const state = await this.workflowRuntime.state(this.session)
    if (state.activeStage !== 'ci-green') {
      return
    }
    await this.workflowRuntime.setStage(this.session, 'done')
    const doneState = await this.workflowRuntime.state(this.session)
    await this.auditSink.emit(
      createAuditEvent({
        timestamp: new Date(),
        runId: this.sessionId,
        callId: `workflow-state-${this.callIndex}`,
        callIndex: this.callIndex,
        sessionId: this.sessionId,
        toolName: 'workflow.setStage',
        toolArgs: { stage: 'done' },
        sideEffect: 'state',
        environment: this.environment,
        principal: this.principal,
        action: AuditAction.WORKFLOW_STATE_UPDATED,
        workflow: {
          name: this.workflowRuntime.definition.metadata.name,
          version: this.workflowRuntime.definition.metadata.version,
          activeStage: doneState.activeStage,
          completedStages: [...doneState.completedStages],
          blockedReason: doneState.blockedReason,
          pendingApproval: { ...doneState.pendingApproval },
          ...(doneState.lastBlockedAction == null
            ? {}
            : { lastBlockedAction: { ...doneState.lastBlockedAction } }),
        },
        toolSuccess: true,
        postconditionsPassed: true,
        resultSummary: 'workflow set to done',
        sessionAttemptCount: this.callIndex,
        sessionExecutionCount: this.toolHistory.filter((item) => !item.denied).length,
      }),
    )
    await this.recordStage()
  }
}
