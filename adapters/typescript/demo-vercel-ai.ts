/**
 * Edictum Vercel AI SDK Adapter Demo (TypeScript)
 *
 * Demonstrates how to integrate edictum with the Vercel AI SDK using
 * experimental_onToolCallStart / experimental_onToolCallFinish callbacks.
 *
 * Modes:
 *   Default:  governance testing via guard.run() (no API key needed)
 *   --llm:    real LLM integration via generateText + native adapter callbacks
 */

import { fileURLToPath } from "node:url";


import { VercelAIAdapter } from "@edictum/vercel-ai";

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
  printBanner("Vercel AI");

  // 1. Create guard from shared contracts
  const guard = createStandaloneGuard();
  guard.setPrincipal(makePrincipal("analyst"));

  // 2. Create adapter
  const adapter = new VercelAIAdapter(guard);

  // 3. Determine mode
  const useLLM = isLLMMode() && checkLLMAvailable();

  if (useLLM) {
    // ---------- LLM MODE ----------
    // NOTE: Native adapter.asCallbacks() integration with generateText has a
    // known bug: AI SDK v6 passes toolCall.input but the adapter expects
    // toolCall.args, so precondition checks see empty args and don't fire.
    // Until edictum-ts is updated, LLM mode uses guard.run() like other demos.
    console.log("  Mode: LLM (LLM decides tool call, guard.run() enforces)");
    console.log("  Model: gpt-4.1-mini (temperature=0)");
    console.log("  Adapter: VercelAIAdapter (asCallbacks for generateText)");
    console.log("  Note: native callback path blocked by input/args mismatch bug.");
    console.log("  Using guard.run() to demonstrate governance pipeline.");
    console.log();

    const { runLLMScenariosViaGuard } = await import("./llm-runner.js");
    const results = await runLLMScenariosViaGuard(guard, QUICK_SCENARIOS, "Vercel AI");

    printAuditSummary(guard.localSink);
    return printResultsSummary("Vercel AI", results);
  } else {
    // ---------- DIRECT MODE: guard.run() (no API key needed) ----------
    const callbacks = adapter.asCallbacks(); // shown for reference
    void callbacks;

    console.log("  Adapter: VercelAIAdapter");
    console.log("  Integration: experimental_onToolCallStart / experimental_onToolCallFinish");
    console.log("  Usage:");
    console.log("    const result = await generateText({");
    console.log("      model: openai('gpt-4.1-mini'),");
    console.log("      tools: { ... },");
    console.log("      ...adapter.asCallbacks(),");
    console.log("    });");
    console.log();

    // Demonstrate adapter deny path: call _pre() directly (simulates onToolCallStart)
    console.log("  Adapter demo: testing deny via _pre()...");
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
    const results = await runScenarios(guard, QUICK_SCENARIOS, "Vercel AI");

    printAuditSummary(guard.localSink);
    return printResultsSummary("Vercel AI", results);
  }
}

// Run if executed directly
const __filename = fileURLToPath(import.meta.url);
const isDirectRun = process.argv[1] === __filename ||
  process.argv[1]?.endsWith("/demo-vercel-ai.ts");
if (isDirectRun) {
  main()
    .then((ok) => process.exit(ok ? 0 : 1))
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
