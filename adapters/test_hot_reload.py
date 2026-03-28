"""
Edictum Hot Reload Integration Test
====================================

Tests that contract changes deployed via the console propagate to connected
agents in real-time via SSE, without restarting the agent.

Flow:
  1. Login to console (get session cookie for dashboard API)
  2. Upload original contracts → deploy to production
  3. Connect guards via from_server() (SSE auto-watch)
  4. Verify baseline: email to evil.com → DENIED
  5. Upload modified contracts (email rule removed) → deploy
  6. Wait for guards to hot-reload (policy_version changes)
  7. Verify: email to evil.com → ALLOWED
  8. Re-deploy original contracts
  9. Wait for hot-reload again
  10. Verify: email to evil.com → DENIED again

Prerequisites:
  - Console running at EDICTUM_URL (default: localhost:8000)
  - EDICTUM_API_KEY in .env
  - Admin credentials: EDICTUM_ADMIN_EMAIL / EDICTUM_ADMIN_PASSWORD in .env
    (defaults: admin@demo.test / edictum2026)

Usage:
  python adapters/test_hot_reload.py
  python adapters/test_hot_reload.py --timeout 30
  python adapters/test_hot_reload.py --agents 3
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import argparse
import httpx
from edictum import Edictum, EdictumDenied, Principal

# ── Config ────────────────────────────────────────────────────────────────

CONSOLE_URL = os.environ.get("EDICTUM_URL", "http://localhost:8000")
API_KEY = os.environ.get("EDICTUM_API_KEY", "")
ADMIN_EMAIL = os.environ.get("EDICTUM_ADMIN_EMAIL", "admin@demo.test")
ADMIN_PASSWORD = os.environ.get("EDICTUM_ADMIN_PASSWORD", "edictum2026")
BUNDLE_NAME = "hot-reload-test"
ENV = "production"

# ── Colors ────────────────────────────────────────────────────────────────

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
CYAN = "\033[0;36m"
DIM = "\033[2m"
NC = "\033[0m"

# ── Contract YAML variants ───────────────────────────────────────────────

RULES_V1 = """\
apiVersion: edictum/v1
kind: ContractBundle

metadata:
  name: {bundle_name}
  description: Hot reload test — version A (email deny active)

defaults:
  mode: enforce

tools:
  send_email:
    side_effect: irreversible
  get_weather:
    side_effect: pure

contracts:
  - id: no-email-to-external
    type: pre
    tool: send_email
    when:
      args.to:
        contains_any: ["@evil.com", "@attacker.com"]
    then:
      effect: deny
      message: "Denied: emails to untrusted domain blocked"
      tags: [dlp, email]

  - id: no-sensitive-files
    type: pre
    tool: read_file
    when:
      args.path:
        contains_any: ["/etc/passwd", ".env"]
    then:
      effect: deny
      message: "Denied: sensitive file access"
      tags: [dlp]
""".format(bundle_name=BUNDLE_NAME)

RULES_V2 = """\
apiVersion: edictum/v1
kind: ContractBundle

metadata:
  name: {bundle_name}
  description: Hot reload test — version B (email deny REMOVED)

defaults:
  mode: enforce

tools:
  send_email:
    side_effect: irreversible
  get_weather:
    side_effect: pure

contracts:
  - id: no-sensitive-files
    type: pre
    tool: read_file
    when:
      args.path:
        contains_any: ["/etc/passwd", ".env"]
    then:
      effect: deny
      message: "Denied: sensitive file access"
      tags: [dlp]
""".format(bundle_name=BUNDLE_NAME)


# ── Mock tool callable ───────────────────────────────────────────────────

def send_email(to: str, subject: str, body: str) -> str:
    return f"sent to {to}"


def get_weather(city: str) -> str:
    return f"{city}: sunny, 22C"


# ── Console API helpers (dashboard auth via session cookie) ──────────────

class ConsoleClient:
    """Thin wrapper for console dashboard API calls."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30,
            headers={"X-Requested-With": "test_hot_reload"},
        )
        self._session_cookie: str | None = None

    async def login(self, email: str, password: str) -> None:
        resp = await self._http.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        resp.raise_for_status()
        cookie = resp.cookies.get("session")
        if not cookie:
            # Some setups return the cookie with a different name
            for name, value in resp.cookies.items():
                if "session" in name.lower():
                    cookie = value
                    break
        if not cookie:
            raise RuntimeError(
                f"Login succeeded but no session cookie returned. "
                f"Response cookies: {dict(resp.cookies)}"
            )
        self._session_cookie = cookie
        self._http.cookies.set("session", cookie)

    async def upload_bundle(self, yaml_content: str) -> dict:
        resp = await self._http.post(
            "/api/v1/bundles",
            json={"yaml_content": yaml_content},
        )
        resp.raise_for_status()
        return resp.json()

    async def deploy_bundle(self, name: str, version: int, env: str) -> dict:
        resp = await self._http.post(
            f"/api/v1/bundles/{name}/{version}/deploy",
            json={"env": env},
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._http.aclose()


# ── Test helpers ─────────────────────────────────────────────────────────

async def test_email_denied(guard: Edictum, principal: Principal) -> bool:
    """Return True if sending email to evil.com is DENIED."""
    try:
        await guard.run(
            "send_email",
            {"to": "attacker@evil.com", "subject": "Leak", "body": "data"},
            send_email,
            principal=principal,
        )
        return False  # Was allowed
    except EdictumDenied:
        return True


async def test_weather_allowed(guard: Edictum, principal: Principal) -> bool:
    """Return True if weather lookup is ALLOWED (sanity check)."""
    try:
        result = await guard.run(
            "get_weather",
            {"city": "Tokyo"},
            get_weather,
            principal=principal,
        )
        return result is not None
    except EdictumDenied:
        return False


async def wait_for_reload(
    guards: list[Edictum],
    old_version: str | None,
    timeout: float,
) -> bool:
    """Wait until all guards have a different policy_version than old_version."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        all_reloaded = all(
            g.policy_version != old_version for g in guards
        )
        if all_reloaded:
            return True
        await asyncio.sleep(0.25)
    return False


# ── Main ─────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Edictum Hot Reload Test")
    parser.add_argument(
        "--timeout", type=float, default=15,
        help="Max seconds to wait for SSE hot-reload (default: 15)",
    )
    parser.add_argument(
        "--agents", type=int, default=2,
        help="Number of concurrent agent guards to connect (default: 2)",
    )
    args = parser.parse_args()

    if not API_KEY:
        print(f"{RED}ERROR: EDICTUM_API_KEY not set in .env{NC}")
        sys.exit(1)

    print()
    print("=" * 70)
    print("  EDICTUM HOT RELOAD TEST")
    print("=" * 70)
    print(f"  Console:  {CONSOLE_URL}")
    print(f"  Bundle:   {BUNDLE_NAME}")
    print(f"  Env:      {ENV}")
    print(f"  Agents:   {args.agents}")
    print(f"  Timeout:  {args.timeout}s")
    print()

    console = ConsoleClient(CONSOLE_URL)
    guards: list[Edictum] = []
    passed = 0
    failed = 0
    principal = Principal(user_id="hot-reload-tester", role="analyst")

    try:
        # ── Step 1: Login to console ──────────────────────────────────
        print(f"{CYAN}[1/9]{NC} Logging in to console...")
        await console.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        print(f"  {GREEN}OK{NC} — session established")

        # ── Step 2: Upload & deploy V1 (email deny active) ───────────
        print(f"{CYAN}[2/9]{NC} Uploading contracts V1 (email deny active)...")
        v1_resp = await console.upload_bundle(RULES_V1)
        v1_version = v1_resp["version"]
        print(f"  Uploaded: {BUNDLE_NAME} v{v1_version}")

        deploy_resp = await console.deploy_bundle(BUNDLE_NAME, v1_version, ENV)
        print(f"  {GREEN}Deployed{NC} to {ENV}")

        # ── Step 3: Connect guards via from_server() ──────────────────
        print(f"{CYAN}[3/9]{NC} Connecting {args.agents} agent guard(s) via SSE...")
        for i in range(args.agents):
            guard = await Edictum.from_server(
                url=CONSOLE_URL,
                api_key=API_KEY,
                agent_id=f"hot-reload-test-agent-{i}",
                bundle_name=BUNDLE_NAME,
                env=ENV,
            )
            guards.append(guard)
        versions = [g.policy_version for g in guards]
        print(f"  {GREEN}OK{NC} — {len(guards)} guard(s) connected")
        print(f"  {DIM}policy_version: {versions[0]}{NC}")

        # ── Step 4: Baseline — email to evil.com → DENIED ────────────
        print(f"{CYAN}[4/9]{NC} Baseline: email to evil.com...")
        baseline_results = []
        for i, g in enumerate(guards):
            denied = await test_email_denied(g, principal)
            baseline_results.append(denied)
            status = f"{GREEN}DENIED{NC}" if denied else f"{RED}ALLOWED (BUG!){NC}"
            print(f"  Agent {i}: {status}")

        if all(baseline_results):
            print(f"  {GREEN}PASS{NC} — all agents deny evil email")
            passed += 1
        else:
            print(f"  {RED}FAIL{NC} — some agents allowed evil email")
            failed += 1

        # Sanity check: weather should be allowed
        for g in guards:
            weather_ok = await test_weather_allowed(g, principal)
            if not weather_ok:
                print(f"  {RED}WARNING{NC}: weather lookup was denied (unexpected)")

        # Record current version for reload detection
        old_version = guards[0].policy_version

        # ── Step 5: Upload & deploy V2 (email deny REMOVED) ──────────
        print(f"{CYAN}[5/9]{NC} Uploading contracts V2 (email deny removed)...")
        v2_resp = await console.upload_bundle(RULES_V2)
        v2_version = v2_resp["version"]
        print(f"  Uploaded: {BUNDLE_NAME} v{v2_version}")

        deploy_resp = await console.deploy_bundle(BUNDLE_NAME, v2_version, ENV)
        print(f"  {GREEN}Deployed{NC} to {ENV}")

        # ── Step 6: Wait for hot reload ───────────────────────────────
        print(f"{CYAN}[6/9]{NC} Waiting for SSE hot-reload (up to {args.timeout}s)...")
        t0 = time.monotonic()
        reloaded = await wait_for_reload(guards, old_version, args.timeout)
        elapsed = time.monotonic() - t0

        if reloaded:
            new_versions = [g.policy_version for g in guards]
            print(f"  {GREEN}RELOADED{NC} in {elapsed:.1f}s")
            print(f"  {DIM}policy_version: {old_version} → {new_versions[0]}{NC}")
            passed += 1
        else:
            current = [g.policy_version for g in guards]
            print(f"  {RED}TIMEOUT{NC} — guards did not reload after {args.timeout}s")
            print(f"  {DIM}expected != {old_version}, got: {current}{NC}")
            failed += 1

        # ── Step 7: After reload — email to evil.com → ALLOWED ───────
        print(f"{CYAN}[7/9]{NC} After reload: email to evil.com...")
        reload_results = []
        for i, g in enumerate(guards):
            denied = await test_email_denied(g, principal)
            reload_results.append(not denied)  # We expect ALLOWED now
            status = f"{GREEN}ALLOWED{NC}" if not denied else f"{RED}DENIED (reload failed!){NC}"
            print(f"  Agent {i}: {status}")

        if all(reload_results):
            print(f"  {GREEN}PASS{NC} — all agents allow evil email after contract change")
            passed += 1
        else:
            print(f"  {RED}FAIL{NC} — some agents still deny (hot reload didn't take effect)")
            failed += 1

        # ── Step 8: Re-deploy V1 (restore email deny) ────────────────
        old_version_2 = guards[0].policy_version
        print(f"{CYAN}[8/9]{NC} Re-deploying V1 (restoring email deny)...")
        deploy_resp = await console.deploy_bundle(BUNDLE_NAME, v1_version, ENV)
        print(f"  {GREEN}Deployed{NC} v{v1_version} to {ENV}")

        print(f"  Waiting for SSE hot-reload...")
        t0 = time.monotonic()
        reloaded = await wait_for_reload(guards, old_version_2, args.timeout)
        elapsed = time.monotonic() - t0

        if reloaded:
            print(f"  {GREEN}RELOADED{NC} in {elapsed:.1f}s")
            passed += 1
        else:
            print(f"  {RED}TIMEOUT{NC} — guards did not reload after {args.timeout}s")
            failed += 1

        # ── Step 9: After restore — email to evil.com → DENIED ───────
        print(f"{CYAN}[9/9]{NC} After restore: email to evil.com...")
        restore_results = []
        for i, g in enumerate(guards):
            denied = await test_email_denied(g, principal)
            restore_results.append(denied)
            status = f"{GREEN}DENIED{NC}" if denied else f"{RED}ALLOWED (restore failed!){NC}"
            print(f"  Agent {i}: {status}")

        if all(restore_results):
            print(f"  {GREEN}PASS{NC} — all agents deny evil email again after restore")
            passed += 1
        else:
            print(f"  {RED}FAIL{NC} — some agents still allow (restore didn't take effect)")
            failed += 1

    except httpx.HTTPStatusError as exc:
        print(f"\n  {RED}HTTP ERROR{NC}: {exc.response.status_code} — {exc.response.text[:200]}")
        failed += 1
    except Exception as exc:
        print(f"\n  {RED}ERROR{NC}: {exc}")
        failed += 1
    finally:
        # Cleanup
        for g in guards:
            try:
                await g.close()
            except Exception:
                pass
        await console.close()

    # ── Summary ───────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("  HOT RELOAD TEST SUMMARY")
    print("=" * 70)
    total = passed + failed
    print(f"  {GREEN}{passed} passed{NC}, {RED}{failed} failed{NC} / {total} checks")
    print()
    checks = [
        ("Baseline governance (V1 denies evil email)", passed >= 1),
        ("SSE reload detected (policy_version changed)", passed >= 2),
        ("Behavior changed after reload (V2 allows evil email)", passed >= 3),
        ("Second reload detected (V1 re-deployed)", passed >= 4),
        ("Behavior restored after re-deploy (V1 denies again)", passed >= 5),
    ]
    for desc, ok in checks:
        icon = f"{GREEN}PASS{NC}" if ok else f"{RED}FAIL{NC}"
        print(f"  [{icon}]  {desc}")
    print("=" * 70)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
