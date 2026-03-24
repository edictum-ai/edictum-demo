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
import { dirname, resolve } from "node:path";

import {
  Edictum,
  EdictumDenied,
  createPrincipal,
} from "@edictum/core";
import { OpenAIAgentsAdapter } from "@edictum/openai-agents";

import {
  CONTRACTS_PATH,
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

  // 3. Run governance scenarios using guard.run()
  const results = await runScenarios(guard, QUICK_SCENARIOS, "OpenAI Agents");

  // 4. Print summary
  printAuditSummary(guard.localSink);
  return printResultsSummary("OpenAI Agents", results);
}

// Run if executed directly
const __filename = fileURLToPath(import.meta.url);
if (process.argv[1] === __filename || process.argv[1]?.endsWith("/tsx") || process.argv[1]?.includes("demo-openai-agents")) {
  main()
    .then((ok) => process.exit(ok ? 0 : 1))
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
