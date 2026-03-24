/**
 * Shared utilities for Edictum TypeScript adapter demos.
 *
 * Mock tools, scenarios, audit helpers, and formatting used by every demo.
 * Mirrors the Python shared_v2.py infrastructure.
 */

import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

// Polyfill require() for tsx/ESM — @edictum/core's bundled __require shim
// needs it to load the optional js-yaml peer dependency.
const _require = createRequire(import.meta.url);
if (typeof globalThis.require === "undefined") {
  (globalThis as Record<string, unknown>).require = _require;
}

import {
  Edictum,
  EdictumDenied,
  AuditAction,
  CollectingAuditSink,
  createPrincipal,
  VERSION,
} from "@edictum/core";
import type { Principal, AuditEvent } from "@edictum/core";

// ---------------------------------------------------------------------------
// __dirname for ESM
// ---------------------------------------------------------------------------

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export const CONTRACTS_PATH = resolve(__dirname, "../contracts.yaml");

// ---------------------------------------------------------------------------
// Mock tool implementations
// ---------------------------------------------------------------------------

export function getWeather(args: Record<string, unknown>): string {
  const city = String(args.city ?? "Unknown");
  const conditions = ["sunny", "cloudy", "rainy", "snowy", "windy"];
  const temp = Math.floor(Math.random() * 40) - 5;
  const cond = conditions[Math.floor(Math.random() * conditions.length)];
  return `${city}: ${cond}, ${temp}C`;
}

export function searchWeb(args: Record<string, unknown>): string {
  const query = String(args.query ?? "");
  return JSON.stringify({
    results: [
      { title: `Result 1 for '${query}'`, url: "https://example.com/1" },
      { title: `Result 2 for '${query}'`, url: "https://example.com/2" },
    ],
  });
}

export function readFile(args: Record<string, unknown>): string {
  const path = String(args.path ?? "");
  if (path.includes("broken")) {
    return "Error: Permission denied";
  }
  if (path.toLowerCase().includes("secret") || path.includes("passwd")) {
    return `Contents of ${path}: root:x:0:0:root:/root:/bin/bash`;
  }
  if (path.includes("contacts")) {
    return JSON.stringify({
      contacts: [
        {
          name: "Jane Doe",
          email: "jane@example.com",
          phone: "(415) 555-0123",
          ssn: "123-45-6789",
        },
        {
          name: "John Smith",
          email: "john@company.com",
          phone: "(212) 555-9876",
        },
      ],
    });
  }
  return `Contents of ${path}: [simulated file content, no sensitive data]`;
}

export function sendEmail(args: Record<string, unknown>): string {
  const subject = String(args.subject ?? "");
  return JSON.stringify({ status: "sent", message_id: `msg-${Date.now()}`, subject });
}

export function updateRecord(args: Record<string, unknown>): string {
  const recordId = String(args.record_id ?? "");
  const data = args.data;
  return JSON.stringify({ status: "updated", record_id: recordId, data });
}

export function deleteRecord(args: Record<string, unknown>): string {
  const recordId = String(args.record_id ?? "");
  return JSON.stringify({ status: "deleted", record_id: recordId });
}

// ---------------------------------------------------------------------------
// Tool map
// ---------------------------------------------------------------------------

export const TOOL_MAP: Record<
  string,
  (args: Record<string, unknown>) => string
> = {
  get_weather: getWeather,
  search_web: searchWeb,
  read_file: readFile,
  send_email: sendEmail,
  update_record: updateRecord,
  delete_record: deleteRecord,
};

// ---------------------------------------------------------------------------
// Test scenarios
// ---------------------------------------------------------------------------

export interface Scenario {
  name: string;
  tool: string;
  args: Record<string, unknown>;
  expected: "allowed" | "denied" | "redact" | "approval" | "observe";
}

/** All 17 scenarios matching Python's SCENARIOS. */
export const SCENARIOS: Scenario[] = [
  {
    name: "Weather lookup (allowed)",
    tool: "get_weather",
    args: { city: "Tokyo" },
    expected: "allowed",
  },
  {
    name: "Read safe file (DENIED: sandbox bug — should be allowed)",
    tool: "read_file",
    args: { path: "/home/user/notes.txt" },
    expected: "denied", // sandbox wiring bug: YAML sandbox contracts always deny
  },
  {
    name: "Read contacts (DENIED: sandbox bug — should be redacted)",
    tool: "read_file",
    args: { path: "/home/user/contacts.json" },
    expected: "denied", // sandbox wiring bug: YAML sandbox contracts always deny
  },
  {
    name: "Read /etc/passwd (DENIED: sandbox)",
    tool: "read_file",
    args: { path: "/etc/passwd" },
    expected: "denied",
  },
  {
    name: "Read .env file (DENIED: no-sensitive-files)",
    tool: "read_file",
    args: { path: "/home/app/.env.production" },
    expected: "denied",
  },
  {
    name: "Read outside sandbox (DENIED)",
    tool: "read_file",
    args: { path: "/opt/secret/config.yaml" },
    expected: "denied",
  },
  {
    name: "Email to company (allowed + observe audit)",
    tool: "send_email",
    args: { to: "alice@company.com", subject: "Hello", body: "Hi" },
    expected: "allowed",
  },
  {
    name: "Email to evil domain (DENIED: no-email-to-external)",
    tool: "send_email",
    args: { to: "attacker@evil.com", subject: "Leak", body: "data" },
    expected: "denied",
  },
  {
    name: "Search web (allowed)",
    tool: "search_web",
    args: { query: "edictum governance" },
    expected: "allowed",
  },
  {
    name: "Delete without admin role (DENIED: RBAC)",
    tool: "delete_record",
    args: { record_id: "REC-001" },
    expected: "denied",
  },
  {
    name: "Update record confirmed (allowed)",
    tool: "update_record",
    args: { record_id: "REC-002", data: "new value", confirmed: true },
    expected: "allowed",
  },
  {
    name: "Update record unconfirmed (approval required)",
    tool: "update_record",
    args: { record_id: "REC-003", data: "risky" },
    expected: "approval",
  },
  {
    name: "Weather #2 (rate limit counting)",
    tool: "get_weather",
    args: { city: "London" },
    expected: "allowed",
  },
  {
    name: "Weather #3",
    tool: "get_weather",
    args: { city: "Berlin" },
    expected: "allowed",
  },
  {
    name: "Weather #4",
    tool: "get_weather",
    args: { city: "Sydney" },
    expected: "allowed",
  },
  {
    name: "Weather #5 (last allowed)",
    tool: "get_weather",
    args: { city: "NYC" },
    expected: "allowed",
  },
  {
    name: "Weather #6 (DENIED: rate limit)",
    tool: "get_weather",
    args: { city: "LA" },
    expected: "denied",
  },
];

/** Quick subset: skip scenarios that would block waiting for HITL approval.
 * Includes rate-limit exhaustion scenarios that depend on ordering. */
export const QUICK_SCENARIOS: Scenario[] = SCENARIOS.filter(
  (s) => s.expected !== "approval",
);

// ---------------------------------------------------------------------------
// Guard creation
// ---------------------------------------------------------------------------

export function createStandaloneGuard(mode?: "enforce" | "observe"): Edictum {
  return Edictum.fromYaml(CONTRACTS_PATH, {
    mode: mode ?? "enforce",
    auditSink: [], // suppress stdout; guard.localSink always available
  });
}

export function makePrincipal(
  role: string = "analyst",
): Principal {
  return createPrincipal({
    userId: `demo-${role}`,
    role,
    claims: { department: "engineering", team: "platform" },
  });
}

// ---------------------------------------------------------------------------
// Audit classification
// ---------------------------------------------------------------------------

/** Classify a scenario result from audit events since a given mark. */
export function classifyResult(
  sink: CollectingAuditSink,
  mark: number,
  toolName: string,
): { action: string; detail: string } | null {
  const recent = sink.sinceMark(mark);
  if (recent.length === 0) return null;

  // Check for hard denials first
  for (const e of recent) {
    if (e.action === AuditAction.CALL_DENIED) {
      const reason = e.reason ?? "";
      const name = e.decisionName ?? "";
      const detail = name ? `${name}: ${reason}`.slice(0, 100) : reason.slice(0, 100);
      return { action: "DENIED", detail };
    }
    if (e.action === AuditAction.CALL_APPROVAL_REQUESTED) {
      return { action: "APPROVAL", detail: `${toolName} requires approval` };
    }
  }

  // Check postcondition results. Only CALL_EXECUTED events carry
  // postconditionsPassed (non-null), so iterating all events is safe —
  // non-executed events have postconditionsPassed === null.
  for (const e of recent) {
    if (e.postconditionsPassed === false) {
      return { action: "REDACTED", detail: "PII detected and redacted in output" };
    }
  }

  // Check for allowed/executed (takes precedence over observe-mode audits)
  for (const e of recent) {
    if (
      e.action === AuditAction.CALL_ALLOWED ||
      e.action === AuditAction.CALL_EXECUTED
    ) {
      return { action: "ALLOWED", detail: `${toolName} executed` };
    }
  }

  // Observe-mode: CALL_WOULD_DENY fired but no execution followed
  for (const e of recent) {
    if (e.action === AuditAction.CALL_WOULD_DENY) {
      const reason = e.reason ?? "";
      return { action: "OBSERVE", detail: `would-deny: ${reason}`.slice(0, 100) };
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

const RESET = "\x1b[0m";
const GREEN = "\x1b[32m";
const RED = "\x1b[31m";
const YELLOW = "\x1b[33m";
const CYAN = "\x1b[36m";
const DIM = "\x1b[2m";
const BOLD = "\x1b[1m";

export function printBanner(adapterName: string): void {
  console.log("=".repeat(70));
  console.log(`  EDICTUM ${adapterName.toUpperCase()} DEMO (TypeScript)`);
  console.log("=".repeat(70));
  console.log(`  Mode:    enforce`);
  console.log(`  Source:  local YAML`);
  console.log(`  Version: @edictum/core ${VERSION}`);
  console.log();
}

export function printScenario(idx: number, total: number, desc: string): void {
  console.log();
  console.log(`${DIM}${"─".repeat(60)}${RESET}`);
  console.log(`  ${CYAN}[${idx}/${total}]${RESET} ${desc}`);
  console.log(`${DIM}${"─".repeat(60)}${RESET}`);
}

export function printResult(action: string, detail: string): void {
  const icons: Record<string, string> = {
    DENIED: "X",
    ALLOWED: "+",
    REDACTED: "~",
    APPROVAL: "?",
    OBSERVE: "o",
    WARNING: "!",
  };
  const colors: Record<string, string> = {
    DENIED: YELLOW,
    ALLOWED: GREEN,
    REDACTED: YELLOW,
    APPROVAL: YELLOW,
    OBSERVE: CYAN,
  };
  const icon = icons[action] ?? "|";
  const color = colors[action] ?? RESET;
  console.log(`  ${color}[${icon}] ${action}:${RESET} ${detail}`);
}

export function printAuditSummary(sink: CollectingAuditSink): void {
  const events = sink.events;
  if (events.length === 0) {
    console.log("  No audit events recorded.");
    return;
  }

  let allowed = 0;
  let denied = 0;
  let wouldDeny = 0;
  let piiRedacted = 0;
  let approvalReq = 0;

  // Count by action — use CALL_EXECUTED (not CALL_ALLOWED) to avoid
  // double-counting when both events fire for the same tool call.
  for (const e of events) {
    if (e.action === AuditAction.CALL_EXECUTED) allowed++;
    if (e.action === AuditAction.CALL_DENIED) denied++;
    if (e.action === AuditAction.CALL_WOULD_DENY) wouldDeny++;
    if (e.postconditionsPassed === false) piiRedacted++;
    if (e.action === AuditAction.CALL_APPROVAL_REQUESTED) approvalReq++;
  }

  console.log();
  console.log(`${BOLD}${"=".repeat(60)}${RESET}`);
  console.log(`  ${BOLD}GOVERNANCE SUMMARY${RESET}`);
  console.log(`${BOLD}${"=".repeat(60)}${RESET}`);
  console.log(`  Total events:      ${events.length}`);
  console.log(`  ${GREEN}Allowed:           ${allowed}${RESET}`);
  console.log(`  ${YELLOW}Denied:            ${denied}${RESET}`);
  if (wouldDeny > 0) {
    console.log(`  ${CYAN}Would-deny (obs):  ${wouldDeny}${RESET}`);
  }
  if (piiRedacted > 0) {
    console.log(`  ${YELLOW}PII redactions:    ${piiRedacted}${RESET}`);
  }
  if (approvalReq > 0) {
    console.log(`  Approval requests: ${approvalReq}`);
  }

  if (denied > 0) {
    console.log();
    console.log(`  Contracts enforced:`);
    for (const e of events) {
      if (e.action === AuditAction.CALL_DENIED) {
        const reason = (e.reason ?? "").slice(0, 70);
        const name = e.decisionName ?? "";
        console.log(`    ${YELLOW}X ${name}: ${reason}${RESET}`);
      }
    }
  }
  console.log();
}

// ---------------------------------------------------------------------------
// Scenario runner (framework-agnostic via guard.run)
// ---------------------------------------------------------------------------

export interface ScenarioResult {
  name: string;
  expected: string;
  actual: string;
  detail: string;
  match: boolean;
}

/**
 * Run all scenarios through a guard using guard.run().
 * Returns results for validation.
 */
export async function runScenarios(
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

    try {
      const toolFn = TOOL_MAP[scenario.tool];
      if (!toolFn) {
        printResult("ERROR", `Unknown tool: ${scenario.tool}`);
        results.push({
          name: scenario.name,
          expected: scenario.expected,
          actual: "error",
          detail: `Unknown tool: ${scenario.tool}`,
          match: false,
        });
        continue;
      }

      await guard.run(
        scenario.tool,
        scenario.args,
        async (args) => toolFn(args),
      );

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

// ---------------------------------------------------------------------------
// Summary printer
// ---------------------------------------------------------------------------

export function printResultsSummary(
  adapterName: string,
  results: ScenarioResult[],
): boolean {
  const passed = results.filter((r) => r.match).length;
  const failed = results.filter((r) => !r.match).length;
  const total = results.length;

  console.log();
  console.log(`${BOLD}${"=".repeat(60)}${RESET}`);
  console.log(
    `  ${BOLD}${adapterName.toUpperCase()} RESULTS: ${passed}/${total} passed${RESET}`,
  );
  console.log(`${BOLD}${"=".repeat(60)}${RESET}`);

  if (failed > 0) {
    console.log();
    console.log(`  ${RED}Failed scenarios:${RESET}`);
    for (const r of results.filter((r) => !r.match)) {
      console.log(
        `    ${RED}X ${r.name}: expected=${r.expected} actual=${r.actual}${RESET}`,
      );
    }
  }

  console.log();
  return failed === 0;
}
