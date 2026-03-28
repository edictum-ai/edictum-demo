"""
Edictum Customer Support Agent Demo
=====================================

A real AI agent (GPT-4.1 via LangChain) assists with customer support tasks.
Edictum governs every tool call -- the agent doesn't know it's being governed.

Run it multiple times. The agent is non-deterministic. The checks are not.

Usage:
    python support_agent.py
    python support_agent.py --role support_agent        # gets denied on billing data
    python support_agent.py --role billing_specialist    # full billing access
    python support_agent.py --role supervisor            # full access + high refunds
    python support_agent.py --mode observe               # observe mode, nothing denied
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

# --- Verify setup ---------------------------------------------------------

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


# --- Mock customer support databases ---------------------------------------
# These simulate real data sources. Some contain PII intentionally
# to demonstrate postcondition detection.

CUSTOMERS = {
    "CUST-10042": {
        "customer_id": "CUST-10042",
        "name": "Emily Rodriguez",
        "email": "e.rodriguez@outlook.com",
        "phone": "(503) 555-0184",
        "address": "2847 NW Westover Rd, Portland, OR 97210",
        "plan": "Business Pro",
        "status": "Active",
        "since": "2023-06-15",
        "billing": {
            "card_on_file": "Visa ****4829",
            "monthly_amount": "$299.00",
            "next_billing": "2026-01-15",
            "past_due": False,
        },
    },
    "CUST-20087": {
        "customer_id": "CUST-20087",
        "name": "David Kim",
        "email": "d.kim@protonmail.com",
        "phone": "(206) 555-0312",
        "address": "1523 Capitol Hill Ave, Seattle, WA 98102",
        "plan": "Personal",
        "status": "Active",
        "since": "2024-01-22",
        "billing": {
            "card_on_file": "Mastercard ****7156",
            "monthly_amount": "$49.00",
            "next_billing": "2026-01-22",
            "past_due": True,
            "past_due_amount": "$98.00",
        },
    },
}

TICKETS = [
    {
        "ticket_id": "TKT-78432",
        "customer_id": "CUST-10042",
        "subject": "Cannot access dashboard after password reset",
        "status": "open",
        "priority": "high",
        "created": "2025-12-28T09:15:00Z",
        "assigned_to": "Agent Mike",
        "history": [
            {"timestamp": "2025-12-28T09:15:00Z", "action": "created", "note": "Customer reports dashboard login failure after password reset"},
            {"timestamp": "2025-12-28T10:30:00Z", "action": "response", "note": "Sent password reset link, waiting for customer confirmation"},
        ],
    },
    {
        "ticket_id": "TKT-78501",
        "customer_id": "CUST-20087",
        "subject": "Billing discrepancy -- charged twice in December",
        "status": "open",
        "priority": "medium",
        "created": "2025-12-30T14:20:00Z",
        "assigned_to": None,
        "history": [
            {"timestamp": "2025-12-30T14:20:00Z", "action": "created", "note": "Customer reports duplicate charge of $49.00 on Dec statement"},
        ],
    },
    {
        "ticket_id": "TKT-78555",
        "customer_id": "CUST-10042",
        "subject": "Feature request: API rate limit increase",
        "status": "pending",
        "priority": "low",
        "created": "2026-01-02T11:00:00Z",
        "assigned_to": "Agent Sarah",
        "history": [],
    },
]

ORDERS = {
    "ORD-44821": {
        "order_id": "ORD-44821",
        "customer_id": "CUST-20087",
        "amount": 49.00,
        "date": "2025-12-01",
        "status": "completed",
        "description": "Personal plan -- December 2025",
    },
    "ORD-44822": {
        "order_id": "ORD-44822",
        "customer_id": "CUST-20087",
        "amount": 49.00,
        "date": "2025-12-15",
        "status": "completed",
        "description": "Personal plan -- duplicate charge",
    },
}


# --- Tool functions (LangChain @tool decorator) ----------------------------

@tool
def lookup_customer(customer_id: str, include_billing: bool = False) -> str:
    """Look up a customer profile by ID. Set include_billing=True to retrieve billing details (requires elevated role)."""
    if customer_id not in CUSTOMERS:
        return json.dumps({"error": f"Customer {customer_id} not found."})
    customer = CUSTOMERS[customer_id].copy()
    if not include_billing:
        customer.pop("billing", None)
    return json.dumps(customer, indent=2)


@tool
def search_tickets(query: str = "", status: str = "") -> str:
    """Search support tickets by keyword or status filter. Returns matching tickets."""
    results = []
    for ticket in TICKETS:
        if status and ticket["status"] != status:
            continue
        if query and query.lower() not in ticket["subject"].lower():
            continue
        if not query and not status:
            results.append(ticket)
        elif query or status:
            results.append(ticket)
    return json.dumps(results, indent=2)


@tool
def update_ticket(ticket_id: str, status: str, note: str) -> str:
    """Update a support ticket status and add a note."""
    ticket = next((t for t in TICKETS if t["ticket_id"] == ticket_id), None)
    if not ticket:
        return json.dumps({"error": f"Ticket {ticket_id} not found."})
    return json.dumps({
        "status": "updated",
        "ticket_id": ticket_id,
        "new_status": status,
        "note": note,
        "timestamp": datetime.now().isoformat(),
    })


@tool
def process_refund(order_id: str, amount: float, reason: str) -> str:
    """Process a refund for a given order. Returns confirmation with refund details."""
    if order_id not in ORDERS:
        return json.dumps({"error": f"Order {order_id} not found."})
    order = ORDERS[order_id]
    if amount > order["amount"]:
        return json.dumps({"error": f"Refund amount ${amount:.2f} exceeds order amount ${order['amount']:.2f}."})
    return json.dumps({
        "status": "refund_processed",
        "order_id": order_id,
        "customer_id": order["customer_id"],
        "refund_amount": f"${amount:.2f}",
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "note": f"Refund of ${amount:.2f} will appear in 3-5 business days.",
    })


@tool
def escalate_ticket(ticket_id: str, reason: str = "") -> str:
    """Escalate a support ticket to a supervisor for review."""
    ticket = next((t for t in TICKETS if t["ticket_id"] == ticket_id), None)
    if not ticket:
        return json.dumps({"error": f"Ticket {ticket_id} not found."})
    return json.dumps({
        "status": "escalated",
        "ticket_id": ticket_id,
        "escalated_to": "Supervisor Queue",
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
    })


# --- PII redaction (postcondition-aware) -----------------------------------


def redact_pii(text: str) -> str:
    """Replace PII patterns with redaction markers.

    These match the same patterns as the postcondition rules in
    support_rules.yaml, so redaction fires exactly when postconditions warn.
    """
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL REDACTED]', text)
    text = re.sub(r'\b(\+1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b', '[PHONE REDACTED]', text)
    text = re.sub(r'\b\d{1,5}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pl)\b', '[ADDRESS REDACTED]', text)
    text = re.sub(r'\*{4}\d{4}', '[CARD REDACTED]', text)
    text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[SSN REDACTED]', text)
    return text


# --- Formatting helpers ----------------------------------------------------

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


# --- Audit trail display ---------------------------------------------------

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


# --- System prompt ---------------------------------------------------------

SYSTEM_PROMPT = """You are a customer support AI assistant. You help resolve customer issues, \
manage support tickets, process refunds, and escalate when needed. Always verify customer \
identity before sharing account details. If a tool call is denied, read the denial reason \
and adjust your approach. Never share more customer data than necessary."""


# --- Main ------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Edictum Customer Support Agent Demo")
    parser.add_argument("--role", default="support_agent",
                        choices=["support_agent", "senior_agent", "billing_specialist", "supervisor"],
                        help="Principal role (default: support_agent)")
    parser.add_argument("--ticket", default=None,
                        help="Ticket reference (e.g., TKT-78501)")
    parser.add_argument("--mode", default="enforce",
                        choices=["enforce", "observe"],
                        help="Governance mode (default: enforce)")
    parser.add_argument("--task", default=None,
                        help="Custom task for the agent")
    args = parser.parse_args()

    # Setup principal
    principal = Principal(
        user_id=f"demo-{args.role}",
        role=args.role,
        ticket_ref=args.ticket,
        claims={"department": "customer_support", "region": "us-west"},
    )

    # Setup audit
    audit_path = "audit_trail.jsonl"
    if Path(audit_path).exists():
        Path(audit_path).unlink()

    rules_path = Path(__file__).parent / "support_rules.yaml"
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

    tools = [lookup_customer, search_tickets, update_ticket, process_refund, escalate_ticket]
    tool_node = ToolNode(tools=tools, wrap_tool_call=adapter.as_tool_wrapper(on_postcondition_warn=redact_callback))

    llm = ChatOpenAI(model="gpt-4.1", temperature=0.3)
    agent = create_react_agent(llm, tools=tool_node, prompt=SYSTEM_PROMPT)

    # Default task
    task = args.task or (
        "Customer CUST-20087 is calling about a billing discrepancy. "
        "Look up their account, find the relevant tickets, and help resolve "
        "the duplicate charge issue. Process a refund if appropriate."
    )

    # Banner
    print("=" * 70)
    print("  EDICTUM CUSTOMER SUPPORT AGENT DEMO")
    print("  Runtime rules for AI agents in customer support")
    print("=" * 70)

    print_header(f"TASK: {task}")
    print_event("Principal", f"{principal.user_id} (role: {principal.role}, ticket: {principal.ticket_ref or 'none'})")
    print_event("Mode", "observe" if args.mode == "observe" else "enforce")
    print_event("Adapter", "LangChainAdapter -> ToolNode(wrap_tool_call=...)")
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
                    print(f"    ⚠ {e.get('tool_name', '?')}: output contained potential customer PII")
            print()

    # Token usage
    if total_prompt_tokens > 0:
        cost_in = total_prompt_tokens * 2.00 / 1_000_000
        cost_out = total_completion_tokens * 8.00 / 1_000_000
        total_cost = cost_in + cost_out
        print(f"  -- Token Usage (gpt-4.1) --")
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
