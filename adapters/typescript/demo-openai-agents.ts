/**
 * Edictum OpenAI Agents SDK Adapter Demo (TypeScript)
 *
 * Demonstrates how to integrate edictum with the OpenAI Agents SDK using
 * input/output guardrails.
 *
 * Modes:
 *   Default:  governance testing via guard.run() (no API key needed)
 *   --llm:    LLM decides tool call -> guard.run() enforces governance
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
  isLLMMode,
  checkLLMAvailable,
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
  const guardrails = adapter.asGuardrails(); // shown for reference
  void guardrails;

  // 3. Determine mode
  const useLLM = isLLMMode() && checkLLMAvailable();

  if (useLLM) {
    // ---------- LLM MODE: LLM chooses tool -> guard.run() enforces ----------
    console.log("  Mode: LLM (LLM decides tool call, guard.run() enforces)");
    console.log("  Model: gpt-4.1-mini (temperature=0)");
    console.log("  Adapter: OpenAIAgentsAdapter (input/output guardrails)");
    console.log("  In a real app, guardrails wrap the Agent automatically.");
    console.log("  Here we use guard.run() to demonstrate the governance pipeline.");
    console.log();

    const { runLLMScenariosViaGuard } = await import("./llm-runner.js");
    const results = await runLLMScenariosViaGuard(guard, QUICK_SCENARIOS, "OpenAI Agents");

    printAuditSummary(guard.localSink);
    return printResultsSummary("OpenAI Agents", results);
  } else {
    // ---------- DIRECT MODE: guard.run() (no API key needed) ----------
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

    // Run governance scenarios using guard.run()
    const results = await runScenarios(guard, QUICK_SCENARIOS, "OpenAI Agents");

    printAuditSummary(guard.localSink);
    return printResultsSummary("OpenAI Agents", results);
  }
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
