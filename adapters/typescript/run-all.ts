/**
 * Run all Edictum TypeScript adapter demos sequentially and validate results.
 */

import { fileURLToPath } from "node:url";

import { main as vercelAI } from "./demo-vercel-ai.js";
import { main as langchain } from "./demo-langchain.js";
import { main as openaiAgents } from "./demo-openai-agents.js";
import { main as claudeSdk } from "./demo-claude-sdk.js";

// ---------------------------------------------------------------------------
// ANSI
// ---------------------------------------------------------------------------

const RESET = "\x1b[0m";
const GREEN = "\x1b[32m";
const RED = "\x1b[31m";
const BOLD = "\x1b[1m";

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------

interface DemoEntry {
  name: string;
  fn: () => Promise<boolean>;
}

const DEMOS: DemoEntry[] = [
  { name: "Vercel AI", fn: vercelAI },
  { name: "LangChain", fn: langchain },
  { name: "OpenAI Agents", fn: openaiAgents },
  { name: "Claude Agent SDK", fn: claudeSdk },
];

async function runAll(): Promise<void> {
  console.log();
  console.log(`${BOLD}${"#".repeat(70)}${RESET}`);
  console.log(`${BOLD}  EDICTUM TypeScript ADAPTER DEMOS${RESET}`);
  console.log(`${BOLD}  Running ${DEMOS.length} adapters...${RESET}`);
  console.log(`${BOLD}${"#".repeat(70)}${RESET}`);
  console.log();

  const results: { name: string; ok: boolean; error?: string }[] = [];

  for (const demo of DEMOS) {
    console.log();
    console.log(`${"#".repeat(70)}`);
    console.log(`  Starting: ${demo.name}`);
    console.log(`${"#".repeat(70)}`);

    try {
      const ok = await demo.fn();
      results.push({ name: demo.name, ok });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`  ${RED}FATAL: ${msg}${RESET}`);
      results.push({ name: demo.name, ok: false, error: msg });
    }
  }

  // Final summary
  console.log();
  console.log(`${BOLD}${"#".repeat(70)}${RESET}`);
  console.log(`${BOLD}  FINAL SUMMARY${RESET}`);
  console.log(`${BOLD}${"#".repeat(70)}${RESET}`);
  console.log();

  let allPassed = true;
  for (const r of results) {
    const icon = r.ok ? `${GREEN}PASS${RESET}` : `${RED}FAIL${RESET}`;
    const extra = r.error ? ` (${r.error})` : "";
    console.log(`  [${icon}] ${r.name}${extra}`);
    if (!r.ok) allPassed = false;
  }

  const passCount = results.filter((r) => r.ok).length;
  const totalCount = results.length;

  console.log();
  if (allPassed) {
    console.log(
      `  ${GREEN}${BOLD}All ${totalCount} adapters passed.${RESET}`,
    );
  } else {
    console.log(
      `  ${RED}${BOLD}${passCount}/${totalCount} adapters passed.${RESET}`,
    );
  }
  console.log();

  process.exit(allPassed ? 0 : 1);
}

runAll().catch((err) => {
  console.error(err);
  process.exit(1);
});
