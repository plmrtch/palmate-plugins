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
