/**
 * Edictum Claude Agent SDK Adapter Demo (TypeScript)
 *
 * Demonstrates how to integrate edictum with the Claude Agent SDK using
 * PreToolUse / PostToolUse hooks.
 *
 * The adapter setup is shown for reference, but since we don't invoke a real
 * LLM here, governance testing uses guard.run() directly.
 */

import { fileURLToPath } from "node:url";


import { ClaudeAgentSDKAdapter } from "@edictum/claude-sdk";

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
  printBanner("Claude Agent SDK");

  // 1. Create guard from shared contracts
  const guard = createStandaloneGuard();
  guard.setPrincipal(makePrincipal("analyst"));

  // 2. Show adapter integration (how you would wire it into Claude Agent SDK)
  const adapter = new ClaudeAgentSDKAdapter(guard);
  const hooks = adapter.toSdkHooks(); // shown for reference
  void hooks;

  console.log("  Adapter: ClaudeAgentSDKAdapter");
  console.log("  Integration: PreToolUse / PostToolUse hooks");
  console.log("  Usage:");
  console.log("    const adapter = new ClaudeAgentSDKAdapter(guard);");
  console.log("    const hooks = adapter.toSdkHooks();");
  console.log("    const client = new Claude({");
  console.log("      hooks: {");
  console.log("        PreToolUse: hooks.PreToolUse,");
  console.log("        PostToolUse: hooks.PostToolUse,");
  console.log("      },");
  console.log("    });");
  console.log();

  // Demonstrate adapter deny path via _pre()
  console.log("  Adapter demo: testing deny via hook _pre()...");
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
  const results = await runScenarios(guard, QUICK_SCENARIOS, "Claude Agent SDK");

  // 4. Print summary
  printAuditSummary(guard.localSink);
  return printResultsSummary("Claude Agent SDK", results);
}

// Run if executed directly
const __filename = fileURLToPath(import.meta.url);
const isDirectRun = process.argv[1] === __filename ||
  process.argv[1]?.endsWith("/demo-claude-sdk.ts");
if (isDirectRun) {
  main()
    .then((ok) => process.exit(ok ? 0 : 1))
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
