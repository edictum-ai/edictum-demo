"""
Edictum Fintech Agent Demo
============================

A real AI agent (GPT-4.1 via LangChain) assists with trading compliance tasks.
Edictum governs every tool call -- the agent doesn't know it's being governed.

Run it multiple times. The agent is non-deterministic. The checks are not.

Usage:
    python fintech_agent.py
    python fintech_agent.py --role analyst             # gets denied on full account data
    python fintech_agent.py --role compliance_officer   # full access
    python fintech_agent.py --mode observe              # observe mode, nothing denied
    python fintech_agent.py --ticket AUD-2025-118       # enables compliance reports
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ── Verify setup ─────────────────────────────────────────────────────────────

if not os.getenv("OPENAI_API_KEY"):
    print("ERROR: Set OPENAI_API_KEY in .env file")
    sys.exit(1)

try:
    from edictum import Edictum, Principal, FileAuditSink
    from edictum.adapters.langchain import LangChainAdapter
except ImportError:
    print("ERROR: pip install edictum[yaml]")
    sys.exit(1)

try:
    from langchain_openai import ChatOpenAI
    from langchain_core.tools import tool
    from langgraph.prebuilt import create_react_agent, ToolNode
except ImportError:
    print("ERROR: pip install langchain langchain-openai langgraph")
    sys.exit(1)


# ── Mock trading databases ───────────────────────────────────────────────────
# These simulate real data sources. Some contain PII intentionally
# to demonstrate postcondition detection.

ACCOUNTS = {
    "ACC-847291": {
        "account_id": "ACC-847291",
        "holder": "Meridian Capital Partners LLC",
        "type": "Institutional",
        "status": "Active",
        "aum": "$47.2M",
        "risk_rating": "Moderate",
        "contact": "James Mitchell, j.mitchell@meridian-cap.com, (212) 555-0147",
        "ssn_ein": "83-4729105",
    },
    "ACC-312058": {
        "account_id": "ACC-312058",
        "holder": "Sarah Chen",
        "type": "Individual",
        "status": "Active",
        "balance": "$2.1M",
        "risk_rating": "Conservative",
        "contact": "Sarah Chen, s.chen@gmail.com, (415) 555-0293",
        "ssn_ein": "294-71-8305",
    },
    "ACC-RESTRICTED-001": {
        "account_id": "ACC-RESTRICTED-001",
        "holder": "[UNDER INVESTIGATION]",
        "type": "Institutional",
        "status": "Frozen",
        "note": "SEC investigation pending -- no access permitted",
    },
}

TRANSACTIONS = [
    {"id": "TXN-001", "account": "ACC-847291", "symbol": "AAPL", "side": "BUY", "quantity": 500, "price": 198.50, "timestamp": "2025-12-20T10:15:00Z"},
    {"id": "TXN-002", "account": "ACC-847291", "symbol": "MSFT", "side": "SELL", "quantity": 200, "price": 445.20, "timestamp": "2025-12-20T11:30:00Z"},
    {"id": "TXN-003", "account": "ACC-312058", "symbol": "NVDA", "side": "BUY", "quantity": 100, "price": 875.00, "timestamp": "2025-12-20T14:00:00Z"},
]

RISK_PROFILES = {
    "ACC-847291": {"var_95": "$1.2M", "beta": 1.15, "sector_concentration": {"Tech": "42%", "Healthcare": "28%", "Finance": "30%"}},
    "ACC-312058": {"var_95": "$180K", "beta": 0.85, "sector_concentration": {"Tech": "35%", "Bonds": "45%", "Real Estate": "20%"}},
}

COMPLIANCE_DATA = {
    "quarterly_summary": {
        "period": "Q4 2025",
        "total_trades": 1847,
        "flagged_trades": 12,
        "breaches": 0,
        "regulatory_filings": ["SOX 302", "MiFID II RTS 25"],
    },
    "suspicious_activity": [
        {
            "id": "SAR-001",
            "account": "ACC-847291",
            "type": "Unusual volume",
            "status": "Under review",
            "analyst": "J. Rodriguez",
            "holder": "Meridian Capital Partners LLC",
            "contact": "j.mitchell@meridian-cap.com, (212) 555-0147",
            "ein": "83-4729105",
        },
    ],
}


# ── Tool functions (LangChain @tool decorator) ──────────────────────────────

@tool
def query_account_data(account_id: str, dataset: str = "summary") -> str:
    """Query account data. Available datasets: summary, full_profile, transaction_history, risk_assessment."""
    if account_id not in ACCOUNTS:
        return json.dumps({"error": f"Account {account_id} not found."})

    acct = ACCOUNTS[account_id]

    if dataset == "summary":
        # Safe summary -- no PII
        return json.dumps({
            "account_id": acct["account_id"],
            "holder": acct["holder"],
            "type": acct["type"],
            "status": acct["status"],
            "risk_rating": acct.get("risk_rating", "N/A"),
        }, indent=2)
    elif dataset == "full_profile":
        # Full profile -- contains PII (SSN/EIN, email, phone)
        return json.dumps(acct, indent=2)
    elif dataset == "transaction_history":
        txns = [t for t in TRANSACTIONS if t["account"] == account_id]
        return json.dumps({"account_id": account_id, "transactions": txns}, indent=2)
    elif dataset == "risk_assessment":
        profile = RISK_PROFILES.get(account_id, {"error": "No risk profile available."})
        return json.dumps({"account_id": account_id, "risk_profile": profile}, indent=2)
    else:
        return json.dumps({"error": f"Unknown dataset: {dataset}"})


@tool
def execute_trade(symbol: str, quantity: int, side: str, account_id: str) -> str:
    """Execute a trade order. Requires symbol, quantity, side (BUY/SELL), and account_id."""
    if account_id not in ACCOUNTS:
        return json.dumps({"error": f"Account {account_id} not found."})
    if ACCOUNTS[account_id].get("status") == "Frozen":
        return json.dumps({"error": f"Account {account_id} is frozen. Cannot execute trades."})

    return json.dumps({
        "status": "executed",
        "trade_id": f"TRD-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "symbol": symbol,
        "quantity": quantity,
        "side": side,
        "account_id": account_id,
        "timestamp": datetime.now().isoformat(),
        "estimated_value": f"${quantity * 198.50:,.2f}" if symbol == "AAPL" else f"${quantity * 450.00:,.2f}",
    })


@tool
def generate_compliance_report(report_type: str, period: str) -> str:
    """Generate a compliance report. Types: quarterly_summary, suspicious_activity, regulatory_filing."""
    if report_type == "quarterly_summary":
        data = COMPLIANCE_DATA["quarterly_summary"]
        return json.dumps({
            "report_type": "quarterly_summary",
            "period": period,
            "data": data,
            "generated_at": datetime.now().isoformat(),
        }, indent=2)
    elif report_type == "suspicious_activity":
        # This intentionally includes PII -- postcondition should catch it
        return json.dumps({
            "report_type": "suspicious_activity",
            "period": period,
            "items": COMPLIANCE_DATA["suspicious_activity"],
            "generated_at": datetime.now().isoformat(),
        }, indent=2)
    elif report_type == "regulatory_filing":
        return json.dumps({
            "report_type": "regulatory_filing",
            "period": period,
            "filings": ["SOX 302 certification", "MiFID II RTS 25 transaction report"],
            "status": "Draft -- pending review",
            "generated_at": datetime.now().isoformat(),
        }, indent=2)
    else:
        return json.dumps({"error": f"Unknown report type: {report_type}"})


@tool
def search_market_data(query: str) -> str:
    """Search market data for stock quotes, sector analysis, and market news."""
    return json.dumps({
        "results": [
            {"symbol": "AAPL", "price": 198.50, "change": "+1.2%", "volume": "52.3M"},
            {"symbol": "MSFT", "price": 445.20, "change": "-0.3%", "volume": "28.1M"},
            {"symbol": "NVDA", "price": 875.00, "change": "+2.8%", "volume": "41.7M"},
        ],
        "market_summary": "S&P 500 up 0.4%, Nasdaq up 0.7%. Tech sector leading gains.",
        "query": query,
    })


# ── PII redaction (postcondition-aware) ──────────────────────────────────────


def redact_pii(text: str) -> str:
    """Replace PII patterns with redaction markers.

    These match the same patterns as the postcondition rules in
    fintech_rules.yaml, so redaction fires exactly when postconditions warn.
    """
    text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[SSN/EIN REDACTED]', text)
    text = re.sub(r'\bACC-\d{6,10}\b', '[ACCOUNT-ID REDACTED]', text)
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL REDACTED]', text)
    text = re.sub(r'\b(\+1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b', '[PHONE REDACTED]', text)
    return text


# ── Formatting helpers ───────────────────────────────────────────────────────

def print_header(text: str):
    print(f"\n{'─' * 70}")
    print(f"  {text}")
    print(f"{'─' * 70}")


def print_event(label: str, detail: str, icon: str = "│"):
    print(f"  {icon} {label}: {detail}")


def print_check(action: str, detail: str):
    icons = {
        "DENIED": "⛔",
        "ALLOWED": "✓",
        "WARNING": "⚠",
        "OBSERVE": "👁",
    }
    icon = icons.get(action, "│")
    print(f"  {icon} [{action}] {detail}")


# ── Audit trail display ─────────────────────────────────────────────────────

def display_audit_trail(audit_path: str):
    """Read and display the audit trail in a human-readable format."""
    if not Path(audit_path).exists():
        print("  No audit events recorded.")
        return

    with open(audit_path) as f:
        events = [json.loads(line) for line in f if line.strip()]

    if not events:
        print("  No audit events recorded.")
        return

    print(f"  {len(events)} events recorded\n")

    for i, event in enumerate(events, 1):
        action = event.get("action", "unknown")
        tool_name = event.get("tool_name", "?")
        decision = event.get("decision_name", "")
        reason = event.get("reason", "")
        pv = event.get("policy_version", "")[:12]
        postcond = event.get("postconditions_passed")

        icons = {
            "call_allowed": "✓",
            "call_denied": "⛔",
            "call_would_deny": "👁",
            "call_executed": "✓",
        }
        icon = icons.get(action, "│")

        print(f"  {icon} Event {i}: {action}")
        print(f"    Tool: {tool_name}")
        if decision:
            print(f"    Rule: {decision}")
        if reason:
            print(f"    Reason: {reason[:100]}")
        if postcond is False:
            print(f"    ⚠ Postcondition warning: PII detected in output")
        if pv:
            print(f"    Policy: {pv}...")
        print()


# ── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a trading compliance AI assistant. You help with account queries, \
trade execution, compliance reporting, and market research. Follow all compliance protocols. \
If a tool call is denied, read the denial reason carefully and adjust your approach. \
Never fabricate financial data."""


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Edictum Fintech Agent Demo")
    parser.add_argument("--role", default="compliance_officer",
                        choices=["compliance_officer", "senior_trader", "analyst", "risk_manager"],
                        help="Principal role (default: compliance_officer)")
    parser.add_argument("--ticket", default=None,
                        help="Audit ticket reference (e.g., AUD-2025-118)")
    parser.add_argument("--mode", default="enforce",
                        choices=["enforce", "observe"],
                        help="Governance mode (default: enforce)")
    parser.add_argument("--task", default=None,
                        help="Custom task for the agent")
    args = parser.parse_args()

    # Setup principal
    claims = {"department": "trading", "desk": "equities"}
    if args.role in ("compliance_officer", "senior_trader", "risk_manager"):
        claims["trade_approval"] = True

    principal = Principal(
        user_id=f"demo-{args.role}",
        role=args.role,
        ticket_ref=args.ticket,
        claims=claims,
    )

    # Setup audit
    audit_path = "audit_trail.jsonl"
    if Path(audit_path).exists():
        Path(audit_path).unlink()

    rules_path = Path(__file__).parent / "fintech_rules.yaml"
    mode = "observe" if args.mode == "observe" else None
    audit_sink = FileAuditSink(audit_path)
    guard = Edictum.from_yaml(
        str(rules_path),
        mode=mode,
        audit_sink=audit_sink,
    )

    # Setup LangChain adapter + redacting wrapper
    adapter = LangChainAdapter(guard, principal=principal)

    def redact_callback(result, findings):
        if hasattr(result, 'content') and isinstance(result.content, str):
            result.content = redact_pii(result.content)
        return result

    tools = [query_account_data, execute_trade, generate_compliance_report, search_market_data]
    tool_node = ToolNode(tools=tools, wrap_tool_call=adapter.as_tool_wrapper(on_postcondition_warn=redact_callback))

    llm = ChatOpenAI(model="gpt-4.1", temperature=0.3)
    agent = create_react_agent(llm, tools=tool_node, prompt=SYSTEM_PROMPT)

    # Default task
    task = args.task or (
        "Review account ACC-847291's trading activity and risk profile. "
        "Check recent transactions. "
        "Generate a quarterly compliance summary. "
        "Then execute a small test trade of 100 shares of AAPL for this account."
    )

    # Banner
    print("=" * 70)
    print("  EDICTUM FINTECH AGENT DEMO")
    print("  Runtime rules for AI agents in trading compliance")
    print("=" * 70)

    print_header(f"TASK: {task}")
    print_event("Principal", f"{principal.user_id} (role: {principal.role}, ticket: {principal.ticket_ref or 'none'})")
    print_event("Mode", "observe" if args.mode == "observe" else "enforce")
    print_event("Adapter", "LangChainAdapter → ToolNode(wrap_tool_call=...)")
    print()

    # Run agent
    result = agent.invoke({"messages": [("user", task)]})

    # Token tracking
    total_prompt_tokens = 0
    total_completion_tokens = 0
    llm_calls = 0

    # Display results from messages
    for msg in result["messages"]:
        # Track tokens from ALL AI messages (including those with tool_calls)
        if getattr(msg, 'type', None) == 'ai':
            usage = getattr(msg, 'usage_metadata', None)
            if usage:
                llm_calls += 1
                total_prompt_tokens += usage.get('input_tokens', 0)
                total_completion_tokens += usage.get('output_tokens', 0)

        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                print(f"\n  🔧 Agent calls: {tc['name']}({json.dumps(tc['args'], separators=(',', ':'))})")
        elif hasattr(msg, 'content') and hasattr(msg, 'tool_call_id'):
            # ToolMessage
            if msg.content.startswith("DENIED:"):
                print_check("DENIED", msg.content[8:])
            elif '[REDACTED]' in msg.content:
                print_check("WARNING", "PII detected -- output redacted before reaching LLM")
                if len(msg.content) > 200:
                    print_event("Result", f"{msg.content[:200]}...", "  ")
                else:
                    print_event("Result", msg.content, "  ")
            else:
                print_check("ALLOWED", "executed successfully")
                if len(msg.content) > 200:
                    print_event("Result", f"{msg.content[:200]}...", "  ")
                else:
                    print_event("Result", msg.content, "  ")
        elif getattr(msg, 'type', None) == 'ai' and not getattr(msg, 'tool_calls', None) and msg.content:
            print_header("AGENT RESPONSE")
            print(f"  {msg.content[:500]}")
            if len(msg.content) > 500:
                print(f"  ... ({len(msg.content)} chars total)")

    # Display audit trail
    print_header("AUDIT TRAIL")
    display_audit_trail(audit_path)

    # Summary
    print_header("GOVERNANCE SUMMARY")
    if Path(audit_path).exists():
        with open(audit_path) as f:
            events = [json.loads(line) for line in f if line.strip()]
        allowed = sum(1 for e in events if e.get("action") in ("call_allowed", "call_executed"))
        denied = sum(1 for e in events if e.get("action") == "call_denied")
        would_deny = sum(1 for e in events if e.get("action") == "call_would_deny")
        pii_warnings = sum(1 for e in events if e.get("postconditions_passed") is False)
        pv = events[0].get("policy_version", "")[:16] if events else "?"

        print(f"  Policy version:    {pv}...")
        print(f"  Tool calls made:   {allowed + denied}")
        print(f"  Allowed:           {allowed}")
        print(f"  Denied:            {denied}")
        if would_deny:
            print(f"  Would-deny (obs):  {would_deny}")
        if pii_warnings:
            print(f"  PII warnings:      {pii_warnings}")
        print(f"  Audit events:      {len(events)}")
        print()

        if denied > 0:
            print("  Rules enforced:")
            for e in events:
                if e.get("action") == "call_denied":
                    print(f"    ⛔ {e.get('decision_name', '?')}: {e.get('reason', '')[:80]}")
            print()

        if pii_warnings > 0:
            print("  PII detections:")
            for e in events:
                if e.get("postconditions_passed") is False:
                    print(f"    ⚠ {e.get('tool_name', '?')}: output contained potential financial PII")
            print()

    # Token usage
    if total_prompt_tokens > 0:
        cost_in = total_prompt_tokens * 2.00 / 1_000_000
        cost_out = total_completion_tokens * 8.00 / 1_000_000
        total_cost = cost_in + cost_out
        print(f"  ── Token Usage (gpt-4.1) ──")
        print(f"  LLM round-trips:   {llm_calls}")
        print(f"  Prompt tokens:     {total_prompt_tokens:,}")
        print(f"  Completion tokens: {total_completion_tokens:,}")
        print(f"  Total tokens:      {total_prompt_tokens + total_completion_tokens:,}")
        print(f"  Est. cost:         ${total_cost:.4f}")
        print()

    print("  The agent was non-deterministic. The checks were not.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
