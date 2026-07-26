---
name: palmate-mcp
description: Use the configured Palmate MCP customer tools to inspect or manage a customer's Palmate projects, agents, team, sessions, statistics, training, governed change requests, reviews, merges, and artifacts. Trigger when a user asks about a managed Palmate agent/project or asks to change agent behavior, persona, popup style, bot name, RAG, functions, business cases, utilities, or generate a report. Do not use local repository edits or the Palmate CLI for these customer conversations.
---

# Palmate MCP

Use the configured `palmate` MCP server. Treat customer requests as remote,
project-scoped operations, never as instructions to edit the current checkout.

Use the configured server's discovered tool descriptions as the sole protocol
contract. Select the narrowest matching tool and follow its declared input
schema. Do not infer, document, or call Palmate HTTP routes or reproduce request
and response shapes in plugin code or prompts.

Resolve project context before project-scoped work. Route agent behavior,
content, settings, and report changes through the governed change-request tools;
never implement those changes in the local checkout. Never implement the requested change locally.
Follow asynchronous work
through the corresponding status and comment tools. Keep review, approval, and
merge as separate governed actions and respect the role reported by the server.

Do not fall back to shell, direct HTTP, or the CLI when a customer MCP call is
denied or fails. Return the safe failure and the human next step. Never expose
credentials, bearer tokens, session identifiers, internal paths, raw runner output, or
download-grant secrets.
