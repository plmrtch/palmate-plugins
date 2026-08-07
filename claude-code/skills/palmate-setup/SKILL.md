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
not use `--check` to skip the operation. Follow the resumable start/status flow
below, adding `--update` to the start command. The bootstrap first reuses the
stored renewable machine credential, so a CLI release update normally returns
`approved` immediately without browser interaction. Browser approval is needed
only when the 14-day machine credential is absent, expired, or revoked. After
the update, run `palmate --version` and report the installed version. The update
is complete only after checksum and pinned-signature verification succeeds.

## Resumable browser approval

Never run the legacy blocking bootstrap from an agent turn. Start approval with:

```text
python3 <skill-dir>/scripts/bootstrap_palmate.py login start --host <resolved-https-origin> --json
```

For an update, append `--update`. This command persists the device grant to
`~/.palmate/login-state.json`, prints the code, URL, and expiry, and exits
immediately. Show those values to the user and end the turn so the browser can
be approved. Do not keep a foreground process alive and do not start another
code. An unexpired retry redisplays the same code; use `--new` only when the
user explicitly asks to replace it.

When the user returns after approval, run one stateless check:

```text
python3 <skill-dir>/scripts/bootstrap_palmate.py login status --host <resolved-https-origin> --json
```

If the result is `pending`, show the remaining expiry and wait for the user;
call status again later. If it is `approved`, run `palmate auth status --json`
and resume the original operation. Surface `denied`, `expired`, and `error`
verbatim. A temporary network or download failure remains durable and can be
retried with the same status command. Never ask for a password, access token,
refresh token, or browser cookie.

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

1. Tell the user that Palmate browser approval is starting.
2. Follow the resumable `login start`/`login status` flow above.
3. After setup succeeds, run `palmate auth status --json`.
4. Resume the user's original Palmate operation automatically.

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

The bootstrap owns the port-free OAuth device flow, one-shot status checks,
authenticated download, checksum and pinned-signature verification, atomic
installation, and credential initialization. It never opens a localhost
callback port. Never reproduce those steps with `curl`, direct HTTP calls, or
shell parsing. Never read or display the Palmate credential file.
