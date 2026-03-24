/**
 * Edictum LangChain.js Adapter Demo (TypeScript)
 *
 * Demonstrates how to integrate edictum with LangChain.js using the
 * wrapToolCall middleware pattern for ToolNode.
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
import { LangChainAdapter } from "@edictum/langchain";

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
  printBanner("LangChain");

  // 1. Create guard from shared contracts
  const guard = createStandaloneGuard();
  guard.setPrincipal(makePrincipal("analyst"));

  // 2. Show adapter integration (how you would wire it into a ToolNode)
  const adapter = new LangChainAdapter(guard);
  const middleware = adapter.asMiddleware();

  console.log("  Adapter: LangChainAdapter");
  console.log("  Integration: wrapToolCall middleware for ToolNode");
  console.log("  Usage:");
  console.log("    const adapter = new LangChainAdapter(guard);");
  console.log("    const toolNode = new ToolNode(tools, {");
  console.log("      handleToolErrors: true,");
  console.log("      toolCallMiddleware: adapter.asMiddleware(),");
  console.log("    });");
  console.log();

  // 3. Run governance scenarios using guard.run()
  const results = await runScenarios(guard, QUICK_SCENARIOS, "LangChain");

  // 4. Print summary
  printAuditSummary(guard.localSink);
  return printResultsSummary("LangChain", results);
}

// Run if executed directly
const __filename = fileURLToPath(import.meta.url);
if (process.argv[1] === __filename || process.argv[1]?.endsWith("/tsx") || process.argv[1]?.includes("demo-langchain")) {
  main()
    .then((ok) => process.exit(ok ? 0 : 1))
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
