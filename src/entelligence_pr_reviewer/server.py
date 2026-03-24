"""MCP Server for Entelligence AI PR Reviewer."""

import json
import os
import time
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_URL = os.environ.get("ENTELLIGENCE_API_URL", "https://entelligence.ddbrief.com")
DASHBOARD_URL = os.environ.get("ENTELLIGENCE_DASHBOARD_URL", "https://app.entelligence.ai")
CREDENTIALS_DIR = Path.home() / ".entelligence"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"

SETUP_NEEDED_FLAG = "__ENTELLIGENCE_SETUP_NEEDED__"
SETUP_MESSAGE = f"""{SETUP_NEEDED_FLAG}

Welcome to Entelligence PR Reviewer! To get started, you need an API key.

Get your API key at: {DASHBOARD_URL}/settings?tab=api

Once you have it, paste it here and I'll save it for you."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_api_key() -> str:
    """Read API key from env var or credentials file."""
    key = os.environ.get("ENTELLIGENCE_API_KEY", "")
    if key:
        return key

    try:
        if CREDENTIALS_FILE.exists():
            creds = json.loads(CREDENTIALS_FILE.read_text())
            if creds.get("api_key"):
                return creds["api_key"]
    except Exception:
        pass

    return ""


def _save_api_key(key: str) -> None:
    """Save API key to ~/.entelligence/credentials.json."""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(json.dumps({"api_key": key}, indent=2))
    CREDENTIALS_FILE.chmod(0o600)


def _check_api_key() -> str | None:
    """Return setup message if API key is missing, None otherwise."""
    if not _get_api_key():
        return SETUP_MESSAGE
    return None


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
    }


def _parse_response(data: any) -> any:
    """Handle double-encoded JSON from backend."""
    if isinstance(data, str):
        try:
            return json.loads(data)
        except Exception:
            return data
    return data


def _get_user_info() -> dict:
    """Fetch user info from the API."""
    resp = httpx.get(f"{API_URL}/getUserInfo/", headers=_headers(), timeout=30)
    resp.raise_for_status()
    return _parse_response(resp.json())


def _format_review(result: dict) -> str:
    """Format review result into readable markdown."""
    parts: list[str] = []

    walkthrough = result.get("walkthrough_and_changes")
    if walkthrough:
        parts.append(f"## Walkthrough\n\n{walkthrough}")

    comments = result.get("gitdiff_chunks_review") or []
    if comments:
        parts.append("## Code Review Comments\n")
        for c in comments:
            severity = (c.get("severity") or "info").upper()
            file_name = c.get("fileName") or "unknown"
            summary = c.get("summary") or ""
            suggestion = c.get("suggestion") or ""
            suggested_code = c.get("suggested_code") or ""
            agent_prompt = c.get("prompt_for_ai_agents_for_addressing_review") or ""

            parts.append(f"### [{severity}] {file_name}\n")
            parts.append(f"**Issue:** {summary}\n")
            if suggestion:
                parts.append(f"**Suggestion:** {suggestion}\n")
            if suggested_code:
                parts.append(f"```diff\n{suggested_code}\n```\n")
            if agent_prompt:
                parts.append(f"**Agent fix prompt:** {agent_prompt}\n")

    release_note = result.get("releaseNote")
    if release_note:
        parts.append(f"## Release Note\n\n{release_note}")

    files_changed = result.get("files_changed")
    if files_changed is not None:
        parts.append(f"\n---\n*{files_changed} file(s) changed*")

    if not parts:
        return json.dumps(result, indent=2)

    return "\n\n".join(parts)


def _poll_review_status(job_id: str, max_wait: int = 600) -> dict:
    """Poll until async review job completes."""
    start = time.time()
    while time.time() - start < max_wait:
        resp = httpx.get(
            f"{API_URL}/getReviewStatus/{job_id}/",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") == "done":
            return data
        if data.get("status") == "failed":
            raise Exception(f"Review failed: {data.get('error', 'Unknown error')}")

        time.sleep(10)

    raise Exception(
        f"Review timed out after {max_wait}s. Job ID: {job_id} — check later with get_review_status."
    )


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "entelligence-pr-reviewer",
    version="1.0.0",
    description="AI-powered PR review by Entelligence.AI",
)


@mcp.tool()
def save_api_key(api_key: str) -> str:
    """Save your Entelligence API key. Called during first-time setup after the user provides their key."""
    try:
        resp = httpx.get(
            f"{API_URL}/getUserInfo/",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=30,
        )
        if not resp.is_success:
            return f"Invalid API key — the server returned {resp.status_code}. Please double-check and try again.\n\nGet your key at: {DASHBOARD_URL}/settings?tab=api"

        info = _parse_response(resp.json())
        if info.get("Error"):
            return f"API key validation failed: {info['Error']}"

        _save_api_key(api_key)
        return f"API key saved successfully! Logged in as **{info.get('Name')}** ({info.get('Email')}) in organization **{info.get('OrgName')}**.\n\nYou're all set — you can now use `/entelligence-review` to review PRs."
    except Exception as e:
        return f"Error validating API key: {e}"


@mcp.tool()
def review_pr(
    repo: str,
    pr_number: int,
    pr_diff: str = "",
    priority_level: str = "low",
    mode: str = "concise",
) -> str:
    """Review a pull request using Entelligence AI. Analyzes code quality, security, performance, and best practices.

    Args:
        repo: Repository in "owner/repo" format
        pr_number: Pull request number
        pr_diff: Unified diff string. If omitted the backend fetches it from GitHub.
        priority_level: Review depth — "low" (fast), "medium", or "high" (thorough)
        mode: Output verbosity — "concise" or "verbose"
    """
    setup_err = _check_api_key()
    if setup_err:
        return setup_err

    try:
        user_info = _get_user_info()
        if user_info.get("Error"):
            return f"Error: {user_info['Error']}"

        body: dict = {
            "orgUUID": user_info["OrgUUID"],
            "repoName": repo,
            "prNumber": str(pr_number),
            "priorityLevel": priority_level,
            "mode": mode,
            "walkthroughEnable": True,
            "releaseNoteEnable": True,
            "codeReviewEnable": True,
        }
        if user_info.get("GitHubToken"):
            body["githubToken"] = user_info["GitHubToken"]
        if pr_diff:
            body["prDiff"] = pr_diff

        resp = httpx.post(
            f"{API_URL}/generateReviewForCLIAsync/",
            headers=_headers(),
            json=body,
            timeout=60,
        )
        if not resp.is_success:
            return f"Error submitting review ({resp.status_code}): {resp.text}"

        job_id = resp.json().get("job_id")
        result = _poll_review_status(job_id)
        return _format_review(result.get("result") or {})
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def review_diff(
    diff: str,
    repo_name: str = "local/repo",
    priority_level: str = "low",
    mode: str = "concise",
) -> str:
    """Review a raw diff string synchronously. Best for small diffs or local uncommitted changes.

    Args:
        diff: Unified diff string (e.g. output of `git diff`)
        repo_name: Repository name in "owner/repo" format
        priority_level: Review depth — "low", "medium", or "high"
        mode: Output verbosity — "concise" or "verbose"
    """
    setup_err = _check_api_key()
    if setup_err:
        return setup_err

    try:
        user_info = _get_user_info()
        if user_info.get("Error"):
            return f"Error: {user_info['Error']}"

        body: dict = {
            "orgUUID": user_info["OrgUUID"],
            "repoName": repo_name,
            "prDiff": diff,
            "priorityLevel": priority_level,
            "mode": mode,
            "walkthroughEnable": True,
            "releaseNoteEnable": True,
            "codeReviewEnable": True,
        }
        if user_info.get("GitHubToken"):
            body["githubToken"] = user_info["GitHubToken"]

        resp = httpx.post(
            f"{API_URL}/generateReviewForCLI/",
            headers=_headers(),
            json=body,
            timeout=300,
        )
        if not resp.is_success:
            return f"Error ({resp.status_code}): {resp.text}"

        return _format_review(resp.json())
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def get_review_status(job_id: str) -> str:
    """Check the status of a previously submitted async PR review job.

    Args:
        job_id: Job ID returned from a prior review_pr call
    """
    try:
        resp = httpx.get(
            f"{API_URL}/getReviewStatus/{job_id}/",
            headers=_headers(),
            timeout=30,
        )
        if not resp.is_success:
            return f"Error ({resp.status_code}): {resp.text}"

        data = resp.json()
        if data.get("status") == "done" and data.get("result"):
            return _format_review(data["result"])

        error_msg = f" | error: {data['error']}" if data.get("error") else ""
        return f"Job {job_id}: status = {data.get('status')}{error_msg}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def get_user_info() -> str:
    """Get the current user's Entelligence account info. Also used to check if the API key is configured."""
    setup_err = _check_api_key()
    if setup_err:
        return setup_err

    try:
        info = _get_user_info()
        if info.get("Error"):
            return f"Error: {info['Error']}"

        return "\n".join([
            f"**Name:** {info.get('Name')}",
            f"**Email:** {info.get('Email')}",
            f"**Organization:** {info.get('OrgName')}",
            f"**Org UUID:** {info.get('OrgUUID')}",
            f"**User UUID:** {info.get('UserUUID')}",
        ])
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Skill installer
# ---------------------------------------------------------------------------

SKILL_CONTENT = '''---
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
'''


@mcp.tool()
def install_skill() -> str:
    """Install the /entelligence-review slash command globally so it's available in all projects. Run this once after installing the package."""
    try:
        skill_dir = Path.home() / ".claude" / "skills" / "entelligence-review"
        skill_file = skill_dir / "SKILL.md"

        if skill_file.exists():
            return f"Skill already installed at `{skill_file}`.\n\nRestart Claude Code and use `/entelligence-review` to review PRs."

        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(SKILL_CONTENT.strip() + "\n")

        return f"Skill installed globally at `{skill_file}`.\n\n`/entelligence-review` will be available in all projects. Restart Claude Code to activate."
    except Exception as e:
        return f"Error installing skill: {e}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
