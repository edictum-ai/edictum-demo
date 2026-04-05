import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { config as loadDotEnv } from 'dotenv'
import { EdictumServerClient } from '@edictum/server'

import { HeroTsAgent } from './agent.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

type JsonRecord = Record<string, unknown>

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function parseTimestamp(value: unknown): number {
  if (typeof value !== 'string') {
    return 0
  }
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? 0 : parsed
}

function requireEnv(name: string): string {
  const value = process.env[name]?.trim()
  if (!value) {
    throw new Error(`${name} is required`)
  }
  return value
}

function stagesCompleted(workflow: JsonRecord | null, fallback: string[]): string[] {
  if (workflow == null) {
    return [...fallback]
  }
  const completed = Array.isArray(workflow['completed_stages'])
    ? workflow['completed_stages'].map((item) => String(item))
    : [...fallback]
  const activeStage = typeof workflow['active_stage'] === 'string' ? workflow['active_stage'] : ''
  if (activeStage === 'done' && !completed.includes('done')) {
    completed.push('done')
  }
  return completed
}

async function waitForHealth(client: EdictumServerClient): Promise<void> {
  const deadline = Date.now() + 15_000
  let lastError: unknown = null
  while (Date.now() < deadline) {
    try {
      await client.get('/v1/health')
      return
    } catch (error) {
      lastError = error
      await sleep(250)
    }
  }
  throw new Error(`edictum-api did not become healthy: ${String(lastError)}`)
}

async function autoApprove(
  client: EdictumServerClient,
  agentId: string,
  sessionId: string,
  runStartedAtMs: number,
  stop: { done: boolean },
): Promise<void> {
  const handled = new Set<string>()
  while (!stop.done) {
    try {
      const response = await client.get('/v1/approvals', {
        agent_id: agentId,
        status: 'pending',
      })
      const approvals = Array.isArray(response['approvals'])
        ? (response['approvals'] as JsonRecord[])
        : []
      for (const approval of approvals) {
        const approvalId = typeof approval['id'] === 'string' ? approval['id'] : ''
        const approvalSessionId =
          typeof approval['session_id'] === 'string' ? approval['session_id'] : ''
        const createdAtMs = parseTimestamp(approval['created_at'])
        const matchesRun =
          approvalSessionId === sessionId ||
          (approvalSessionId === '' && createdAtMs >= runStartedAtMs)
        if (!approvalId || handled.has(approvalId) || !matchesRun) {
          continue
        }
        handled.add(approvalId)
        await client.post(`/v1/approvals/${approvalId}/decide`, {
          decision: 'approved',
          decided_by: 'hero-ts-reviewer',
          decided_via: 'hero-ts-runner',
          reason: 'Auto-approved deterministic TS hero demo',
        })
      }
    } catch (error) {
      if (!stop.done) {
        console.error(`hero-ts auto-approve retry: ${String(error)}`)
      }
    }
    await sleep(200)
  }
}

async function queryFinalSummary(
  client: EdictumServerClient,
  agentId: string,
  sessionId: string,
  runStartedAtMs: number,
  fallbackStages: string[],
): Promise<JsonRecord> {
  const workflow = await client.get(`/v1/agents/${agentId}/workflow-state`, {
    session_id: sessionId,
  })
  const eventsResponse = await client.get('/v1/events', {
    agent_id: agentId,
    session_id: sessionId,
    limit: '500',
  })
  const approvalsResponse = await client.get('/v1/approvals', {
    agent_id: agentId,
  })

  const events = Array.isArray(eventsResponse['events']) ? (eventsResponse['events'] as JsonRecord[]) : []
  const approvals = (
    Array.isArray(approvalsResponse['approvals']) ? (approvalsResponse['approvals'] as JsonRecord[]) : []
  ).filter((approval) => {
    const approvalSessionId =
      typeof approval['session_id'] === 'string' ? approval['session_id'] : ''
    const createdAtMs = parseTimestamp(approval['created_at'])
    return approvalSessionId === sessionId || (approvalSessionId === '' && createdAtMs >= runStartedAtMs)
  })
  const eventCount =
    typeof eventsResponse['total'] === 'number' ? Number(eventsResponse['total']) : events.length
  const blockedCount = events.filter((event) => event['action'] === 'call_blocked').length

  return {
    succeeded: workflow['active_stage'] === 'done',
    agent_id: agentId,
    session_id: sessionId,
    stages_completed: stagesCompleted(workflow, fallbackStages),
    event_count: eventCount,
    blocked_count: blockedCount,
    approval_count: approvals.length,
    workflow_state: workflow,
  }
}

async function main(): Promise<void> {
  loadDotEnv({ path: path.resolve(__dirname, '../.env') })

  const apiUrl = requireEnv('EDICTUM_URL')
  const apiKey = requireEnv('EDICTUM_API_KEY')
  const taskText = await readFile(path.resolve(__dirname, '../../hero/TASK.md'), 'utf-8')
  const workflowPath = path.resolve(__dirname, '../../../workflows/coding-guard.yaml')

  const controlClient = new EdictumServerClient({
    baseUrl: apiUrl,
    apiKey,
    agentId: 'hero-ts-runner',
    env: 'hero-demo',
  })
  await waitForHealth(controlClient)

  const agent = new HeroTsAgent({
    apiUrl,
    apiKey,
    workflowPath,
    taskText,
  })
  const runStartedAtMs = Date.now()

  const stop = { done: false }
  const approver = autoApprove(controlClient, agent.agentId, agent.sessionId, runStartedAtMs, stop)

  try {
    const result = await agent.run()
    stop.done = true
    await approver
    await agent.close()
    const summary = await queryFinalSummary(
      controlClient,
      result.agentId,
      result.sessionId,
      runStartedAtMs,
      [...result.finalState.completedStages],
    )
    console.log(JSON.stringify(summary, null, 2))
  } finally {
    stop.done = true
    await agent.close()
  }
}

main().catch((error: unknown) => {
  console.error(error)
  process.exitCode = 1
})
