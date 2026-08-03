# Install the Palmate coding-agent plugin

This is the official public marketplace repository for the Palmate plugins for
Codex and Claude Code. The plugins install and use Palmate's signed CLI; this
repository contains no Palmate backend source, credentials, API schema, or CLI
binary.

Choose your coding agent below and complete every step in order.

If you do not mention a host in your request, both plugins select:

```text
https://api.palmate.ai
```

The LLM passes that selected host explicitly to the setup script. The script
itself intentionally requires `--host`, allowing developers to switch safely
between development, test, and production. Provide a host in your prompt when
you want anything other than `https://api.palmate.ai`. A custom Palmate
address is not this GitHub repository URL.

On the first Palmate operation in each coding-agent session, the setup skill
checks the authenticated release metadata. It downloads and atomically installs
the CLI only when the signed remote semantic version is newer. The existing
binary remains in place when the version is equal, older, invalid, or the check
cannot be completed.

## Install and log in with Codex

### 1. Install the Codex plugin

Run:

```text
codex plugin marketplace add https://github.com/plmrtch/palmate-plugins.git
codex plugin add palmate-agent-codex@palmate
```

Restart Codex after installation so it loads the Palmate skills.

### 2. Tell Codex to start Palmate login

Open Codex and send this prompt:

```text
Set up and log in to Palmate. Show me the one-time login code, wait for me to
approve it in my browser, verify that Palmate is installed and authenticated,
and then list my Palmate projects.
```

Because that prompt does not name a host, Codex uses
`https://api.palmate.ai`. To use another Palmate installation, say
`Set up and log in to Palmate at https://YOUR-PALMATE-HOST` instead.

Codex will check whether Palmate setup is already complete. On first use it
will run the plugin's bootstrap and tell you that browser approval is needed.
Leave Codex running while you complete the browser steps.

### 3. Complete login in your browser

The setup process prints a short one-time code and attempts to open the Palmate
login page in your default browser.

If no browser opens, copy the complete URL printed by Codex and open it
yourself. Then:

1. Confirm that the browser address starts with the same
   `https://YOUR-PALMATE-HOST` address you gave Codex.
2. Sign in with your normal Palmate account.
3. Complete MFA if your account requires it.
4. Confirm that the one-time code in the browser matches the code Codex
   displayed.
5. Approve that code.
6. Wait until the browser confirms approval, then return to Codex.

Do not paste your password, MFA code, access token, refresh token, or browser
cookie into Codex. Enter login information only on the Palmate website.

After approval, Codex will automatically:

1. Download the authenticated Palmate CLI release.
2. Verify its file size, SHA-256 checksum, and pinned RSA signature.
3. Install the CLI atomically.
4. Store the CLI credentials outside your project checkout.
5. Run `palmate auth status --json`.
6. Continue the original request and list your projects.

If Codex reports that `~/.local/bin` is not on `PATH`, add it and restart
Codex:

```text
export PATH="$HOME/.local/bin:$PATH"
```

To check the installation later, tell Codex:

```text
Check my Palmate authentication status for https://YOUR-PALMATE-HOST and show
the installed Palmate CLI version.
```

## Install and log in with Claude Code

### 1. Install the Claude Code plugin

Run:

```text
claude plugin marketplace add https://github.com/plmrtch/palmate-plugins.git
claude plugin install palmate-agent@palmate
```

Restart Claude Code after installation so it loads the Palmate skills.

### 2. Tell Claude Code to start Palmate login

Open Claude Code and send this prompt:

```text
Use the Palmate plugin. Set up and log in to Palmate. Show me the one-time
login code, wait for me to approve it in my browser, verify that Palmate is
installed and authenticated, and then list my Palmate projects.
```

Because that prompt does not name a host, Claude Code uses
`https://api.palmate.ai`. To use another Palmate installation, say
`Set up and log in to Palmate at https://YOUR-PALMATE-HOST` instead.

Claude Code will check whether Palmate setup is already complete. On first use
it will run the plugin's bootstrap and tell you that browser approval is
needed. Leave Claude Code running while you complete the browser steps.

### 3. Complete login in your browser

The setup process prints a short one-time code and attempts to open the Palmate
login page in your default browser.

If no browser opens, copy the complete URL printed by Claude Code and open it
yourself. Then:

1. Confirm that the browser address starts with the same
   `https://YOUR-PALMATE-HOST` address you gave Claude Code.
2. Sign in with your normal Palmate account.
3. Complete MFA if your account requires it.
4. Confirm that the one-time code in the browser matches the code Claude Code
   displayed.
5. Approve that code.
6. Wait until the browser confirms approval, then return to Claude Code.

Do not paste your password, MFA code, access token, refresh token, or browser
cookie into Claude Code. Enter login information only on the Palmate website.

After approval, Claude Code will automatically download and verify the signed
Palmate CLI, install it, initialize its credential store, run
`palmate auth status --json`, and continue the project-list request.

If Claude Code does not continue automatically, send:

```text
I completed the Palmate browser approval. Verify authentication for
https://YOUR-PALMATE-HOST and continue by listing my Palmate projects.
```

If Claude Code reports that `~/.local/bin` is not on `PATH`, add it and restart
Claude Code:

```text
export PATH="$HOME/.local/bin:$PATH"
```

To check the installation later, tell Claude Code:

```text
Check my Palmate authentication status for https://YOUR-PALMATE-HOST and show
the installed Palmate CLI version.
```

## Use the setup skill in Claude Chat and Cowork

The Claude setup skill is self-contained at
`claude-code/skills/palmate-setup/`: its `scripts/bootstrap_palmate.py` travels
with `SKILL.md` when the skill is imported independently.

For Claude Chat, upload the complete skill as a ZIP; do not upload `SKILL.md`
by itself. The archive must have this structure:

```text
palmate-setup.zip
└── palmate-setup/
    ├── SKILL.md
    └── scripts/
        └── bootstrap_palmate.py
```

Open **Customize > Skills**, remove the incomplete Palmate skill, choose
**+ Create skill > Upload a skill**, upload the ZIP, and enable it. The same
uploaded skill is then available in both Chat and Cowork for that account.
Upload `palmate-workflow` as a second skill ZIP when Chat should also perform
project discovery, checkout, diff, commit, test, and merge-request workflows.

For an organization marketplace managed by manual upload, use
`dist/palmate-agent-claude-0.5.2.zip`. Uploading the same `palmate-agent` plugin
name replaces the previous version; deleting it first is unnecessary. For a
GitHub-synced marketplace, an Owner must trigger **Update** after a direct push.

Cowork code execution must be allowed to reach the selected Palmate hostname.
For Team and Enterprise organizations, an Owner should:

1. Open **Organization settings > Capabilities**.
2. Under **Code execution**, enable network egress to package managers and
   specific domains.
3. Add the exact Palmate hostname, such as `harezmi.palmate.net`.
4. Start a new Cowork conversation after saving the change. Existing sessions
   retain the network policy they started with.

If the bootstrap reports `Tunnel connection failed: 403 Forbidden`, this
allowlist has not taken effect in that session. Retrying with elevated shell
permission or switching between `*.palmate.net` hosts cannot bypass Cowork's
egress proxy. A skill cannot add its own allowed domain.

See Anthropic's [Cowork network access
guidance](https://support.claude.com/en/articles/13455879-use-claude-cowork-on-team-and-enterprise-plans)
for the current organization settings.

## Start working after login

After authentication succeeds, ask either coding agent to perform a Palmate
workflow. For example:

```text
Use Palmate to list my projects. Check out the project and branch I select,
show its status, and do not commit or create a merge request until I ask.
```

The plugins delegate project discovery, checkout, diff, commit, revision
testing, training, reports, and merge-request creation to the installed
`palmate` CLI. Server authorization is checked on every operation.
Merge-request approval and completion remain in the authorized Palmate admin
interface.

## Local marketplace testing

Plugin developers can install directly from a local clone:

```text
claude plugin marketplace add /home/developer/agent_build/palmate-plugins
claude plugin install palmate-agent@palmate

codex plugin marketplace add /home/developer/agent_build/palmate-plugins
codex plugin add palmate-agent-codex@palmate
```

Restart the selected host after installation. Remote marketplace installation
requires an actual Git repository; a raw JSON or ZIP URL is insufficient.
