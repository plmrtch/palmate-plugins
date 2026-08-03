---
name: palmate-setup
description: Install, authenticate, or update the Palmate CLI. Trigger before a Palmate CLI workflow when `palmate` is unavailable or unauthenticated, and whenever the user asks to update, upgrade, refresh, or reinstall Palmate CLI.
---

# Palmate first-use setup

## Host selection

Resolve the host before every setup command:

- If the user explicitly mentions a host, use that exact HTTPS Palmate origin.
- If the user does not mention a host, use `https://api.palmate.ai`.

Do not stop to ask for a host when none was mentioned. Always pass the resolved
host to the bootstrap with `--host`; the bootstrap intentionally has no default
because developers commonly switch between development, test, and production.

## User-requested update

When the user asks to update, upgrade, refresh, or reinstall Palmate CLI, do
not use `--check` to skip the operation. Tell the user that browser approval
may be required, then run:

```text
python3 <skill-dir>/scripts/bootstrap_palmate.py --host <resolved-https-origin> --update
```

Let the authenticated download finish without interruption. Then run
`palmate --version` and report the installed version. The update is complete
only after checksum and pinned-signature verification succeeds.

## First operation in an agent session

Before the first Palmate CLI action in the current coding-agent session, resolve
`scripts/bootstrap_palmate.py` relative to this `SKILL.md` and run:

```text
python3 <skill-dir>/scripts/bootstrap_palmate.py --host <resolved-https-origin> --check
```

For an installed and authenticated CLI, this performs at most one remote version
check per coding-agent session. If the signed remote semantic version is newer,
the bootstrap downloads it with the existing credentials, verifies its size,
SHA-256 digest, and pinned RSA signature, and atomically replaces the binary.
Equal, older, invalid, or unverifiable releases never replace the known-good
binary. A failed version check warns and allows the installed CLI to continue.

If the check exits nonzero, this plugin has not completed first-use setup:

1. Tell the user that a Palmate browser login is opening.
2. Run the bootstrap with network access enabled and the user's Palmate HTTPS
   origin:

   ```text
   python3 <skill-dir>/scripts/bootstrap_palmate.py --host <resolved-https-origin>
   ```

3. Show the short one-time code printed by the bootstrap and wait while the
   user logs in and approves that same code in the browser. Never ask the user
   to paste a password, access token, refresh token, or browser cookie.
4. After setup succeeds, run `palmate auth status --json`.
5. Resume the user's original Palmate operation automatically.

The first `--check` in a session, the bootstrap without `--check`, and every
later `palmate` operation that contacts the host must run in a network-enabled
shell context. Sandboxed agents must request network permission explicitly
because ordinary CLI commands obtain the host from the credential store rather
than showing it in their arguments.

If Claude Cowork reports a proxy tunnel `403 Forbidden`, do not retry or change
Palmate hosts. Tell a Team/Enterprise owner to allow the selected hostname under
Organization settings > Capabilities > Code execution, then tell the user to
start a new Cowork conversation because egress changes do not affect an
existing session. A skill cannot grant its own network access.

Do not treat an unrelated preinstalled `palmate` executable as completed plugin
setup. Only the bootstrap's non-secret completion marker may skip first-use
login and download.

The bootstrap owns the port-free OAuth device flow, polling, authenticated
download, checksum and pinned-signature verification, atomic installation, and credential
initialization. It never opens a localhost callback port. Never reproduce
those steps with `curl`, direct HTTP calls, or shell parsing. Never read or
display the Palmate credential file.
