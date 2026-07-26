---
name: palmate-setup
description: Install, authenticate, or update the Palmate CLI. Trigger before a Palmate CLI workflow when `palmate` is unavailable or unauthenticated, and whenever the user asks to update, upgrade, refresh, or reinstall Palmate CLI.
---

# Palmate first-use setup

## User-requested update

When the user asks to update, upgrade, refresh, or reinstall Palmate CLI, do
not use `--check` to skip the operation. Tell the user that browser approval
may be required, then run:

```text
python3 <plugin-root>/scripts/bootstrap_palmate.py --host <https-origin> --update
```

Let the authenticated download finish without interruption. Then run
`palmate --version` and report the installed version. The update is complete
only after checksum and pinned-signature verification succeeds.

## First-use check

Before every Palmate CLI action, resolve `../../scripts/bootstrap_palmate.py`
relative to this `SKILL.md` and run:

```text
python3 <plugin-root>/scripts/bootstrap_palmate.py --host <https-origin> --check
```

If that check exits nonzero, this plugin has not completed first-use setup:

1. Tell the user that a Palmate browser login is opening.
2. Run the bootstrap with network access enabled and the user's Palmate HTTPS
   origin:

   ```text
   python3 <plugin-root>/scripts/bootstrap_palmate.py --host <https-origin>
   ```

3. Show the short one-time code printed by the bootstrap and wait while the
   user logs in and approves that same code in the browser. Never ask the user
   to paste a password, access token, refresh token, or browser cookie.
4. After setup succeeds, run `palmate auth status --json`.
5. Resume the user's original Palmate operation automatically.

The `--check` operation is local and does not need network access. The
bootstrap without `--check`, and every later `palmate` operation that contacts
the host, must run in a network-enabled shell context. Sandboxed agents must
request network permission explicitly because ordinary CLI commands obtain the
host from the credential store rather than showing it in their arguments.

Do not treat an unrelated preinstalled `palmate` executable as completed plugin
setup. Only the bootstrap's non-secret completion marker may skip first-use
login and download.

The bootstrap owns the port-free OAuth device flow, polling, authenticated
download, checksum and pinned-signature verification, atomic installation, and credential
initialization. It never opens a localhost callback port. Never reproduce
those steps with `curl`, direct HTTP calls, or shell parsing. Never read or
display the Palmate credential file.
