---
name: palmate-setup
description: Install and authenticate the Palmate CLI on first use. Trigger before any Palmate CLI workflow when `palmate` is unavailable or unauthenticated.
---

# Palmate first-use setup

Before every Palmate CLI action, resolve `../../scripts/bootstrap_palmate.py`
relative to this `SKILL.md` and run:

```text
python3 <plugin-root>/scripts/bootstrap_palmate.py --host <https-origin> --check
```

If that check exits nonzero, this plugin has not completed first-use setup:

1. Tell the user that a Palmate browser login is opening.
2. Run the bootstrap with the user's Palmate HTTPS origin:

   ```text
   python3 <plugin-root>/scripts/bootstrap_palmate.py --host <https-origin>
   ```

3. Wait while the user completes browser login. Never ask the user to paste a
   token, password, authorization code, or browser cookie.
4. After setup succeeds, run `palmate auth status --json`.
5. Resume the user's original Palmate operation automatically.

Do not treat an unrelated preinstalled `palmate` executable as completed plugin
setup. Only the bootstrap's non-secret completion marker may skip first-use
login and download.

The bootstrap owns PKCE, the loopback callback, authenticated download,
checksum verification, atomic installation, and credential initialization.
Never reproduce those steps with `curl`, direct HTTP calls, or shell parsing.
Never read or display the Palmate credential file.
