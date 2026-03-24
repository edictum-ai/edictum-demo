/**
 * Edictum OpenAI Agents SDK Adapter Demo (TypeScript)
 *
 * Demonstrates how to integrate edictum with the OpenAI Agents SDK using
 * input/output guardrails.
 *
 * The adapter setup is shown for reference, but since we don't invoke a real
 * LLM here, governance testing uses guard.run() directly.
 */

import { fileURLToPath } from "node:url";


import { OpenAIAgentsAdapter } from "@edictum/openai-agents";

import {
  QUICK_SCENARIOS,
  createStandaloneGuard,
  makePrincipal,
  printBanner,
  printAuditSummary,
  printResultsSummary,
  runScenarios,
} from "./shared.js";

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export async function main(): Promise<boolean> {
  printBanner("OpenAI Agents");

  // 1. Create guard from shared contracts
  const guard = createStandaloneGuard();
  guard.setPrincipal(makePrincipal("analyst"));

  // 2. Show adapter integration (how you would wire it into an Agent)
  const adapter = new OpenAIAgentsAdapter(guard);
  const guardrails = adapter.asGuardrails();

  console.log("  Adapter: OpenAIAgentsAdapter");
  console.log("  Integration: inputGuardrail / outputGuardrail for Agent");
  console.log("  Usage:");
  console.log("    const adapter = new OpenAIAgentsAdapter(guard);");
  console.log("    const { inputGuardrail, outputGuardrail } = adapter.asGuardrails();");
  console.log("    const agent = new Agent({");
  console.log("      inputGuardrails: [inputGuardrail],");
  console.log("      outputGuardrails: [outputGuardrail],");
  console.log("    });");
  console.log();

  // Demonstrate adapter deny path via _pre()
  console.log("  Adapter demo: testing deny via guardrail _pre()...");
  const denyResult = await adapter._pre(
    "send_email",
    { to: "attacker@evil.com", subject: "test", body: "hi" },
    "demo-deny-call",
  );
  if (denyResult) {
    console.log(`  Adapter correctly denied: ${denyResult.slice(0, 80)}`);
  } else {
    console.log("  WARNING: expected denial but call was allowed");
  }
  console.log();

  // 3. Run governance scenarios using guard.run()
  const results = await runScenarios(guard, QUICK_SCENARIOS, "OpenAI Agents");

  // 4. Print summary
  printAuditSummary(guard.localSink);
  return printResultsSummary("OpenAI Agents", results);
}

// Run if executed directly
const __filename = fileURLToPath(import.meta.url);
const isDirectRun = process.argv[1] === __filename ||
  process.argv[1]?.endsWith("/demo-openai-agents.ts");
if (isDirectRun) {
  main()
    .then((ok) => process.exit(ok ? 0 : 1))
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
