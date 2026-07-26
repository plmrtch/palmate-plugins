# Palmate coding-agent plugins

Standalone public marketplace source for Codex and Claude Code. This repository
contains no Palmate backend source, credentials, API schema, or CLI binary.

This directory is a publishable marketplace root for both supported hosts:

- Claude Code reads `.claude-plugin/marketplace.json` and installs
  `palmate-agent` from `claude-code/`.
- Codex reads `.agents/plugins/marketplace.json` and installs
  `palmate-agent-codex` from `codex/`.

The plugins are deliberately thin. They contain no MCP server, Palmate
request/response models, credentials, internal API schemas, or general backend
client. Every Palmate operation is delegated to the installed `palmate` CLI.

Installing a plugin does not authorize an account. Authentication remains
interactive and CLI-owned, and server authorization is checked on every
operation. On first use, the bundled bootstrap opens browser OAuth with PKCE,
downloads the protected CLI release, verifies its size and SHA-256 digest,
installs it atomically, lets the installed CLI store credentials, and resumes
the requested operation.

## Test locally

```bash
claude plugin marketplace add /home/developer/agent_build/palmate-plugins
claude plugin install palmate-agent@palmate

codex plugin marketplace add /home/developer/agent_build/palmate-plugins
codex plugin add palmate-agent-codex@palmate
```

Start a new host session after installing. Ask it to use `palmate-setup` and
perform the desired Palmate action.

## Install from a public Git domain

```bash
claude plugin marketplace add https://plugins.example/palmate-plugins.git
claude plugin install palmate-agent@palmate

codex plugin marketplace add https://plugins.example/palmate-plugins.git
codex plugin add palmate-agent-codex@palmate
```

Codex and Claude Code require an actual Git repository for remote marketplace
installation; a raw JSON or ZIP URL is insufficient.
