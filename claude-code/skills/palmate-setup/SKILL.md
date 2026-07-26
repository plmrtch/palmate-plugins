---
name: palmate-setup
description: Install and authenticate the Palmate CLI on first use. Trigger before any Palmate CLI workflow when `palmate` is unavailable or unauthenticated.
---

# Palmate first-use setup

Before a Palmate CLI action, run `palmate auth status --json`.

If `palmate` is missing or reports that it is unauthenticated:

1. Tell the user that a Palmate browser login is opening.
2. Resolve `../../scripts/bootstrap_palmate.py` relative to this `SKILL.md`.
3. Run it with the user's Palmate HTTPS origin:

   ```text
   python3 <plugin-root>/scripts/bootstrap_palmate.py --host <https-origin>
   ```

4. Wait while the user completes browser login. Never ask the user to paste a
   token, password, authorization code, or browser cookie.
5. After setup succeeds, run `palmate auth status --json`.
6. Resume the user's original Palmate operation automatically.

The bootstrap owns PKCE, the loopback callback, authenticated download,
checksum verification, atomic installation, and credential initialization.
Never reproduce those steps with `curl`, direct HTTP calls, or shell parsing.
Never read or display the Palmate credential file.
