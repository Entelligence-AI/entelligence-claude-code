# Entelligence PR Reviewer for Claude Code

AI-powered PR review inside [Claude Code](https://claude.ai/code). Analyzes code quality, security, performance, and best practices using [Entelligence.AI](https://entelligence.ai).

## Quick Start

Install and add to your Claude Code MCP config (`~/.claude/.mcp.json`):

```bash
pip install entelligence-pr-reviewer
```

```json
{
  "mcpServers": {
    "entelligence-pr-reviewer": {
      "command": "entelligence-pr-reviewer"
    }
  }
}
```

Restart Claude Code. On first use, you'll be prompted to enter your API key — no manual config needed.

## What You Get

- **`/entelligence-review 42`** — Review PR #42 in your current repo
- **`/entelligence-review`** — Review your local uncommitted changes
- **Natural language** — Just say "review PR #42" and Claude calls the tool automatically

## Setup

### 1. Install & Add the MCP Server

```bash
pip install entelligence-pr-reviewer
```

Add to `~/.claude/.mcp.json` (global) or `.mcp.json` (per-project):

```json
{
  "mcpServers": {
    "entelligence-pr-reviewer": {
      "command": "entelligence-pr-reviewer"
    }
  }
}
```

### 2. Get Your API Key

On first use, the plugin will:
1. Open your [Entelligence dashboard](https://app.entelligence.ai/settings?tab=api) in the browser
2. Ask you to paste your API key
3. Save it securely to `~/.entelligence/credentials.json`

That's it. No config file editing required.

**Already have a key?** You can also set it via environment variable:

```json
{
  "mcpServers": {
    "entelligence-pr-reviewer": {
      "command": "entelligence-pr-reviewer",
      "env": {
        "ENTELLIGENCE_API_KEY": "ent-your-key-here"
      }
    }
  }
}
```

### 3. Copy the Skill (optional — for `/entelligence-review` slash command)

To get the `/entelligence-review` slash command, copy the skill to your project:

```bash
mkdir -p .claude/skills/entelligence-review
curl -o .claude/skills/entelligence-review/SKILL.md \
  https://raw.githubusercontent.com/Entelligence-AI/entelligence-claude-code/main/.claude/skills/entelligence-review/SKILL.md
```

Without the skill, the MCP tools still work — just say "review PR #42" in natural language.

## Usage

### Slash Command

```
/entelligence-review 42                                      # Review PR #42
/entelligence-review https://github.com/owner/repo/pull/42   # Review by URL
/entelligence-review                                         # Review local changes
/entelligence-review staged                                  # Review staged changes
```

### Natural Language

Just tell Claude what you want:

- "Review PR #42"
- "Review this PR: https://github.com/owner/repo/pull/42"
- "Review my local changes"
- "Do a high-priority review of PR #100"

### MCP Tools

| Tool | Description |
|------|-------------|
| `review_pr` | Review a PR by number (async, handles large PRs) |
| `review_diff` | Review a raw diff string (sync, for small/local diffs) |
| `get_review_status` | Check status of a previously submitted review |
| `get_user_info` | Show your Entelligence account info |
| `save_api_key` | Save your API key (called automatically during setup) |

### Options

| Parameter | Values | Default | Description |
|-----------|--------|---------|-------------|
| `priority_level` | `low`, `medium`, `high` | `low` | Review depth |
| `mode` | `concise`, `verbose` | `concise` | Output verbosity |

Example: "Do a high-priority verbose review of PR #42"

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `ENTELLIGENCE_API_KEY` | — | API key (or use interactive setup) |
| `ENTELLIGENCE_API_URL` | `https://entelligence.ddbrief.com` | API base URL |
| `ENTELLIGENCE_DASHBOARD_URL` | `https://app.entelligence.ai` | Dashboard URL |

## How It Works

```
You: "/entelligence-review 42"
  → Claude calls get_user_info (auth check)
  → Claude calls review_pr with repo + PR #42
  → MCP server submits async review job to Entelligence API
  → Polls until review is complete (~1-5 min)
  → Claude presents results with actionable fix suggestions
  → You can ask Claude to apply the fixes automatically
```

## Development

```bash
git clone https://github.com/Entelligence-AI/entelligence-claude-code.git
cd entelligence-claude-code
npm install
npm run build

# Point your .mcp.json to the local build for testing
# "args": ["/path/to/entelligence-claude-code/dist/index.js"]
```

## License

MIT
