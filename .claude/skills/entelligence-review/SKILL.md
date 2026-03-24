---
name: entelligence-review
description: Review a pull request or local diff using Entelligence AI
allowed-tools: mcp__entelligence-pr-reviewer__review_pr, mcp__entelligence-pr-reviewer__review_diff, mcp__entelligence-pr-reviewer__get_review_status, mcp__entelligence-pr-reviewer__get_user_info, mcp__entelligence-pr-reviewer__save_api_key, Bash, Read
---

# Entelligence PR Review

Review code changes using Entelligence AI. Analyzes code quality, security vulnerabilities, performance issues, and best practices.

## Step 1: Auth Check (ALWAYS do this first)

Call the `get_user_info` tool to check if the user is authenticated.

### If the response contains `__ENTELLIGENCE_SETUP_NEEDED__`:

This is the user's **first time**. Run the onboarding flow:

1. Tell the user:
   > **Welcome to Entelligence PR Reviewer!**
   >
   > To get started, I need your API key. You can get it from your Entelligence dashboard.
   >
   > Let me open it for you.

2. Run `open https://app.entelligence.ai/settings?tab=api` (macOS) or `xdg-open https://app.entelligence.ai/settings?tab=api` (Linux) to open the API key page in their browser.

3. Ask the user: **"Paste your API key here and I'll save it for you:"**

4. When the user pastes their key, call the `save_api_key` tool with it. This validates the key and stores it in `~/.entelligence/credentials.json`.

5. If `save_api_key` succeeds, tell the user they're set up and proceed to Step 2.
   If it fails (invalid key), ask them to double-check and try again.

### If `get_user_info` returns valid user info:

The user is already authenticated. Proceed to Step 2.

## Step 2: Run the Review

Analyze `$ARGUMENTS` to determine what to review:

### PR number (e.g. `42` or `#42`):
1. Get repo from `git remote get-url origin`, parse to `owner/repo`
2. Call `review_pr` with the repo and PR number
3. Present results grouped by file, ordered by severity

### GitHub/GitLab PR URL (e.g. `https://github.com/owner/repo/pull/42`):
1. Parse owner, repo, PR number from URL
2. Call `review_pr` with parsed values
3. Present results grouped by file, ordered by severity

### "local", "staged", "diff", or no arguments:
1. Run `git diff` (or `git diff --staged` for "staged") to get changes
2. Get repo name from `git remote get-url origin`
3. Call `review_diff` with the diff
4. Present results grouped by file, ordered by severity

### Job ID (UUID):
1. Call `get_review_status` with the job ID
2. Present status or results

## Step 3: Present Results

1. **Summary** — High-level walkthrough of changes
2. **Review Comments** — Grouped by file, ordered by severity (critical > warning > info)
   - For each: file, issue, suggestion, and suggested fix
   - If `prompt_for_ai_agents_for_addressing_review` is present, offer to auto-fix
3. **Release Note** — If available
4. **Stats** — Files changed, comments generated

If actionable issues found, ask: "Want me to apply the suggested fixes?"
