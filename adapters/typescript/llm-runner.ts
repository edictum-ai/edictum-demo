/**
 * Shared LLM scenario runner for Edictum TypeScript adapter demos.
 *
 * Uses the Vercel AI SDK (`generateText`) with the OpenAI provider to send
 * directive prompts to a real LLM. The LLM decides which tool to call, and
 * governance intercepts via:
 *   - Vercel AI adapter: native callbacks (experimental_onToolCallStart/Finish)
 *   - Other adapters: LLM chooses tool -> guard.run() enforces
 *
 * Requires OPENAI_API_KEY in the environment or ../.env file.
 */

import { generateText, tool, stepCountIs } from "ai";
import { openai } from "@ai-sdk/openai";
import { z } from "zod";
import { config } from "dotenv";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import type {
  Edictum,
  CollectingAuditSink,
} from "@edictum/core";
import { EdictumDenied } from "@edictum/core";

import {
  type Scenario,
  type ScenarioResult,
  TOOL_MAP,
  classifyResult,
  printScenario,
  printResult,
} from "./shared.js";

// ---------------------------------------------------------------------------
// .env loading — load from repo root (two levels up from adapters/typescript)
// ---------------------------------------------------------------------------

const __dirname = dirname(fileURLToPath(import.meta.url));
config({ path: resolve(__dirname, "../../.env") });

// ---------------------------------------------------------------------------
// AI SDK tool definitions (wrapping the mock implementations from shared.ts)
// ---------------------------------------------------------------------------

export const aiTools = {
  get_weather: tool({
    description: "Get current weather for a city",
    inputSchema: z.object({ city: z.string() }),
    execute: async ({ city }: { city: string }) => TOOL_MAP.get_weather({ city }),
  }),
  search_web: tool({
    description: "Search the web",
    inputSchema: z.object({ query: z.string() }),
    execute: async ({ query }: { query: string }) => TOOL_MAP.search_web({ query }),
  }),
  read_file: tool({
    description: "Read a file from the filesystem",
    inputSchema: z.object({ path: z.string() }),
    execute: async ({ path }: { path: string }) => TOOL_MAP.read_file({ path }),
  }),
  send_email: tool({
    description: "Send an email",
    inputSchema: z.object({
      to: z.string(),
      subject: z.string(),
      body: z.string(),
    }),
    execute: async (args: { to: string; subject: string; body: string }) =>
      TOOL_MAP.send_email(args),
  }),
  update_record: tool({
    description: "Update a record in the database",
    inputSchema: z.object({
      record_id: z.string(),
      data: z.string(),
      confirmed: z.boolean().optional().default(false),
    }),
    execute: async (args: { record_id: string; data: string; confirmed: boolean }) =>
      TOOL_MAP.update_record(args),
  }),
  delete_record: tool({
    description: "Delete a record from the database",
    inputSchema: z.object({ record_id: z.string() }),
    execute: async ({ record_id }: { record_id: string }) =>
      TOOL_MAP.delete_record({ record_id }),
  }),
};

// ---------------------------------------------------------------------------
// LLM availability check
// ---------------------------------------------------------------------------

export function hasOpenAIKey(): boolean {
  return typeof process.env.OPENAI_API_KEY === "string" &&
    process.env.OPENAI_API_KEY.length > 0;
}

// ---------------------------------------------------------------------------
// Prompt builder
// ---------------------------------------------------------------------------

function buildDirectivePrompt(scenario: Scenario): string {
  const argsStr = Object.entries(scenario.args)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(", ");
  return `Call the ${scenario.tool} tool with these exact arguments: ${argsStr}. Do not call any other tools.`;
}

// ---------------------------------------------------------------------------
// ANSI
// ---------------------------------------------------------------------------

const RESET = "\x1b[0m";
const RED = "\x1b[31m";
const DIM = "\x1b[2m";

// ---------------------------------------------------------------------------
// LLM scenario runner via guard.run()
//
// Used by LangChain, OpenAI Agents, and Claude SDK demos where governance
// is enforced through guard.run() rather than native adapter callbacks.
//
// Flow: LLM decides tool call -> we extract it -> guard.run() enforces
// ---------------------------------------------------------------------------

export async function runLLMScenariosViaGuard(
  guard: Edictum,
  scenarios: Scenario[],
  adapterLabel: string,
): Promise<ScenarioResult[]> {
  const results: ScenarioResult[] = [];
  const sink = guard.localSink;

  for (let i = 0; i < scenarios.length; i++) {
    const scenario = scenarios[i];
    const mark = sink.mark();
    printScenario(i + 1, scenarios.length, scenario.name);

    console.log(`  ${DIM}LLM prompt: "${buildDirectivePrompt(scenario).slice(0, 80)}..."${RESET}`);

    try {
      // Step 1: Ask the LLM what tool to call
      const llmResult = await generateText({
        model: openai("gpt-4.1-mini", { temperature: 0 }),
        tools: aiTools,
        stopWhen: stepCountIs(3),
        prompt: buildDirectivePrompt(scenario),
      });

      // Step 2: Extract the tool call from the LLM response
      const toolCall = llmResult.steps?.[0]?.toolCalls?.[0];
      if (!toolCall) {
        printResult("WARNING", "LLM did not produce a tool call");
        results.push({
          name: scenario.name,
          expected: scenario.expected,
          actual: "error",
          detail: "LLM did not produce a tool call",
          match: false,
        });
        continue;
      }

      console.log(`  ${DIM}LLM chose: ${toolCall.toolName}(${JSON.stringify(toolCall.args).slice(0, 60)})${RESET}`);

      // Step 3: Run through governance via guard.run()
      const toolFn = TOOL_MAP[toolCall.toolName];
      if (!toolFn) {
        printResult("ERROR", `Unknown tool from LLM: ${toolCall.toolName}`);
        results.push({
          name: scenario.name,
          expected: scenario.expected,
          actual: "error",
          detail: `Unknown tool: ${toolCall.toolName}`,
          match: false,
        });
        continue;
      }

      await guard.run(
        toolCall.toolName,
        toolCall.args as Record<string, unknown>,
        async (args) => toolFn(args),
      );

      // Classify from audit events
      const classification = classifyResult(sink, mark, toolCall.toolName);
      if (classification) {
        printResult(classification.action, classification.detail);
        const actualNorm = normalizeAction(classification.action);
        const match = actualNorm === scenario.expected;
        if (!match) {
          console.log(
            `    ${RED}MISMATCH: expected=${scenario.expected} actual=${actualNorm}${RESET}`,
          );
        }
        results.push({
          name: scenario.name,
          expected: scenario.expected,
          actual: actualNorm,
          detail: classification.detail,
          match,
        });
      } else {
        printResult("ALLOWED", `${toolCall.toolName} executed`);
        const match = scenario.expected === "allowed";
        if (!match) {
          console.log(
            `    ${RED}MISMATCH: expected=${scenario.expected} actual=allowed${RESET}`,
          );
        }
        results.push({
          name: scenario.name,
          expected: scenario.expected,
          actual: "allowed",
          detail: `${toolCall.toolName} executed`,
          match,
        });
      }
    } catch (err) {
      if (err instanceof EdictumDenied) {
        printResult("DENIED", err.message.slice(0, 100));
        const match =
          scenario.expected === "denied" || scenario.expected === "approval";
        if (!match) {
          console.log(
            `    ${RED}MISMATCH: expected=${scenario.expected} actual=denied${RESET}`,
          );
        }
        results.push({
          name: scenario.name,
          expected: scenario.expected,
          actual: scenario.expected === "approval" ? "approval" : "denied",
          detail: err.message.slice(0, 100),
          match,
        });
      } else {
        const msg = err instanceof Error ? err.message : String(err);
        printResult("ERROR", msg.slice(0, 100));
        results.push({
          name: scenario.name,
          expected: scenario.expected,
          actual: "error",
          detail: msg.slice(0, 100),
          match: false,
        });
      }
    }
  }

  return results;
}

// ---------------------------------------------------------------------------
// LLM scenario runner via native Vercel AI adapter callbacks
//
// The adapter's asCallbacks() hooks intercept tool calls inside generateText:
//   experimental_onToolCallStart -> precondition check
//   experimental_onToolCallFinish -> postcondition check
//
// NOTE: The @edictum/vercel-ai adapter expects `args` in the toolCall event,
// but the real Vercel AI SDK passes `input`. We map `input` -> `args` below.
// This is tracked as a bug in the adapter's type definitions.
// ---------------------------------------------------------------------------

export async function runLLMScenariosNative(
  callbacks: {
    experimental_onToolCallStart: (event: Record<string, unknown>) => Promise<void>;
    experimental_onToolCallFinish: (event: Record<string, unknown>) => Promise<void>;
  },
  sink: CollectingAuditSink,
  scenarios: Scenario[],
  _adapterLabel: string,
): Promise<ScenarioResult[]> {
  const results: ScenarioResult[] = [];

  for (let i = 0; i < scenarios.length; i++) {
    const scenario = scenarios[i];
    const mark = sink.mark();
    printScenario(i + 1, scenarios.length, scenario.name);

    const prompt = buildDirectivePrompt(scenario);
    console.log(`  ${DIM}LLM prompt: "${prompt.slice(0, 80)}..."${RESET}`);

    try {
      // Use generateText with the adapter's callbacks spread in.
      // The adapter's onToolCallStart fires _pre(), onToolCallFinish fires _post().
      //
      // IMPORTANT: The Vercel AI SDK passes `input` (not `args`) in the toolCall
      // event. The @edictum/vercel-ai adapter destructures `args`. We wrap the
      // callbacks to map `input` -> `args` for compatibility.
      await generateText({
        model: openai("gpt-4.1-mini", { temperature: 0 }),
        tools: aiTools,
        stopWhen: stepCountIs(3),
        prompt,
        experimental_onToolCallStart: async (event: {
          toolCall: { toolCallId: string; toolName: string; input: unknown };
        }) => {
          // Map SDK's `input` field to the adapter's expected `args` field
          const mapped = {
            toolCall: {
              toolCallId: event.toolCall.toolCallId,
              toolName: event.toolCall.toolName,
              args: event.toolCall.input as Record<string, unknown>,
            },
          };
          await callbacks.experimental_onToolCallStart(
            mapped as unknown as Record<string, unknown>,
          );
        },
        experimental_onToolCallFinish: async (event: {
          toolCall: { toolCallId: string; toolName: string; input: unknown };
          output?: unknown;
          error?: unknown;
        }) => {
          const mapped = {
            toolCall: {
              toolCallId: event.toolCall.toolCallId,
              toolName: event.toolCall.toolName,
              args: event.toolCall.input as Record<string, unknown>,
            },
            output: event.output,
            error: event.error,
          };
          await callbacks.experimental_onToolCallFinish(
            mapped as unknown as Record<string, unknown>,
          );
        },
      });

      // Classify from audit events
      const classification = classifyResult(sink, mark, scenario.tool);
      if (classification) {
        printResult(classification.action, classification.detail);
        const actualNorm = normalizeAction(classification.action);
        const match = actualNorm === scenario.expected;
        if (!match) {
          console.log(
            `    ${RED}MISMATCH: expected=${scenario.expected} actual=${actualNorm}${RESET}`,
          );
        }
        results.push({
          name: scenario.name,
          expected: scenario.expected,
          actual: actualNorm,
          detail: classification.detail,
          match,
        });
      } else {
        printResult("ALLOWED", `${scenario.tool} executed`);
        const match = scenario.expected === "allowed";
        if (!match) {
          console.log(
            `    ${RED}MISMATCH: expected=${scenario.expected} actual=allowed${RESET}`,
          );
        }
        results.push({
          name: scenario.name,
          expected: scenario.expected,
          actual: "allowed",
          detail: `${scenario.tool} executed`,
          match,
        });
      }
    } catch (err) {
      if (err instanceof EdictumDenied) {
        printResult("DENIED", err.message.slice(0, 100));
        const match =
          scenario.expected === "denied" || scenario.expected === "approval";
        if (!match) {
          console.log(
            `    ${RED}MISMATCH: expected=${scenario.expected} actual=denied${RESET}`,
          );
        }
        results.push({
          name: scenario.name,
          expected: scenario.expected,
          actual: scenario.expected === "approval" ? "approval" : "denied",
          detail: err.message.slice(0, 100),
          match,
        });
      } else {
        const msg = err instanceof Error ? err.message : String(err);
        printResult("ERROR", msg.slice(0, 100));
        results.push({
          name: scenario.name,
          expected: scenario.expected,
          actual: "error",
          detail: msg.slice(0, 100),
          match: false,
        });
      }
    }
  }

  return results;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function normalizeAction(action: string): string {
  switch (action.toUpperCase()) {
    case "DENIED":
      return "denied";
    case "ALLOWED":
      return "allowed";
    case "REDACTED":
      return "redact";
    case "APPROVAL":
      return "approval";
    case "OBSERVE":
      return "observe";
    default:
      return action.toLowerCase();
  }
}
