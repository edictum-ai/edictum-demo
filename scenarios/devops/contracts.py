"""Shared rules for the file organizer demo.

Used by demo_with.py (and examples/demo_sdk.py) to govern tool calls.
demo_without.py intentionally skips these to show what happens without
governance.

These demonstrate Edictum's governance primitives:
- Built-in preconditions (deny_sensitive_reads)
- Custom preconditions (no_destructive_commands, require_target_dir)
- Session rules (limit_total_operations)
- Postconditions (check_bash_errors)
"""

from edictum import Verdict, deny_sensitive_reads, precondition, session_rule
from edictum.rules import postcondition


# --- Built-in precondition ---
sensitive_reads = deny_sensitive_reads()


# --- Custom preconditions ---

@precondition("Bash")
def no_destructive_commands(envelope):
    """Block rm, rmdir, and other destructive commands.

    Checks every line of multi-line commands so the agent can't hide
    destructive calls behind comments or other commands.
    """
    cmd = (envelope.bash_command or "").strip()
    destructive = ["rm ", "rm\t", "rmdir ", "shred "]
    for line in cmd.splitlines():
        line = line.strip()
        if any(line.startswith(d) for d in destructive) or line == "rm":
            return Verdict.fail(
                f"Destructive command blocked: '{line.split()[0]}'. "
                "Use 'mv' to reorganize files instead of deleting them. "
                "If cleanup is needed, move files to /tmp/trash/ first."
            )
    return Verdict.pass_()


def make_require_target_dir(base="/tmp/", organized="organized"):
    """Factory: build a precondition that confines `mv` targets to *base*.

    The default (base="/tmp/") is used by the OpenAI SDK demos.
    The Claude Agent SDK sandboxes commands to the working directory,
    so the SDK demo passes base="./" instead.
    """

    @precondition("Bash")
    def require_target_dir(envelope):
        cmd = (envelope.bash_command or "").strip()
        if cmd.startswith("mv "):
            parts = cmd.split()
            if len(parts) >= 3:
                target = parts[-1]
                if not target.startswith(base):
                    return Verdict.fail(
                        f"Move target '{target}' is outside '{base}'. "
                        f"All organized files must go under {base}{organized}/. "
                        f"Create subdirectories like {base}{organized}/code/, "
                        f"{base}{organized}/docs/, {base}{organized}/data/."
                    )
        return Verdict.pass_()

    return require_target_dir


require_target_dir = make_require_target_dir()


# --- Session rule ---

@session_rule
async def limit_total_operations(session):
    """Cap total tool executions to prevent runaway agents."""
    count = await session.execution_count()
    if count >= 25:
        return Verdict.fail(
            "Operation limit reached (25 tool calls). "
            "Summarize what you've organized so far and stop."
        )
    return Verdict.pass_()


# --- Postcondition (observe-only in v0.0.1) ---

@postcondition("Bash")
def check_bash_errors(envelope, result):
    """Warn if a bash command returned an error."""
    if isinstance(result, str):
        if "No such file" in result or "Permission denied" in result:
            return Verdict.fail(
                f"Command may have failed: {result[:200]}"
            )
    return Verdict.pass_()
