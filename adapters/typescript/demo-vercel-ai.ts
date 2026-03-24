/**
 * Edictum Vercel AI SDK Adapter Demo (TypeScript)
 *
 * Demonstrates how to integrate edictum with the Vercel AI SDK using
 * experimental_onToolCallStart / experimental_onToolCallFinish callbacks.
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
import { VercelAIAdapter } from "@edictum/vercel-ai";

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
  printBanner("Vercel AI");

  // 1. Create guard from shared contracts
  const guard = createStandaloneGuard();
  guard.setPrincipal(makePrincipal("analyst"));

  // 2. Show adapter integration (how you would wire it into generateText)
  const adapter = new VercelAIAdapter(guard);
  const callbacks = adapter.asCallbacks();

  console.log("  Adapter: VercelAIAdapter");
  console.log("  Integration: experimental_onToolCallStart / experimental_onToolCallFinish");
  console.log("  Usage:");
  console.log("    const result = await generateText({");
  console.log("      model: openai('gpt-4o'),");
  console.log("      tools: { ... },");
  console.log("      ...adapter.asCallbacks(),");
  console.log("    });");
  console.log();

  // 3. Run governance scenarios using guard.run()
  const results = await runScenarios(guard, QUICK_SCENARIOS, "Vercel AI");

  // 4. Print summary
  printAuditSummary(guard.localSink);
  return printResultsSummary("Vercel AI", results);
}

// Run if executed directly
const __filename = fileURLToPath(import.meta.url);
if (process.argv[1] === __filename || process.argv[1]?.endsWith("/tsx") || process.argv[1]?.includes("demo-vercel-ai")) {
  main()
    .then((ok) => process.exit(ok ? 0 : 1))
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
