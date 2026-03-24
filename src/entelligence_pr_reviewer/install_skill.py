"""Install the /entelligence-review skill globally for Claude Code."""

from pathlib import Path

SKILL_CONTENT = '''---
name: entelligence-review
description: Review a pull request or local diff using Entelligence AI
allowed-tools: Bash, Read
---

# Entelligence PR Review

Review code changes using Entelligence AI. Analyzes code quality, security vulnerabilities, performance issues, and best practices.

## Step 1: Check CLI is installed

Run `which entelligence` to check if the CLI is installed.

If NOT installed, run `pip install entelligence-cli` to install it automatically. Then continue to Step 2.

## Step 2: Check auth

Run `entelligence auth status` to check if authenticated.

If NOT authenticated (output contains "Not authenticated"):

1. Open the API key page: run `open "https://app.entelligence.ai/settings?tab=api"` (macOS) or `xdg-open "https://app.entelligence.ai/settings?tab=api"` (Linux)
2. Ask the user: **"Paste your API key here:"**
3. When the user pastes their key, run `entelligence auth login --token <THE_KEY>`
4. Verify with `entelligence auth status`
5. If successful, proceed to Step 3. If failed, ask them to try again.

If already authenticated, proceed to Step 3.

## Step 3: Run the review

Analyze `$ARGUMENTS` to determine what to review:

### PR number (e.g. `42` or `#42`):
1. Run `entelligence review --committed-only --prompt-only --base-branch main` (the current branch should have the PR changes)
2. If the user is not on the PR branch, tell them to check it out first

### GitHub/GitLab PR URL:
1. Parse the PR number from the URL
2. Same as above — tell user to check out the branch, then run review

### "local", "staged", "diff", or no arguments:
1. Run `entelligence review --prompt-only` to review uncommitted local changes

### With options like "high priority" or "verbose":
- Add `--priority high` or `--priority medium` if mentioned
- Add `--mode verbose` if user wants detailed output (default is verbose)
- Add `--mode concise` for shorter output

**Default command:** `entelligence review --prompt-only`

## Step 4: Present results

Parse the output and present clearly:

1. **Summary** — High-level walkthrough of changes
2. **Review Comments** — Grouped by file, ordered by severity (critical > warning > info)
   - For each: file, issue, suggestion, and suggested fix
3. **Release Note** — If available
4. **Stats** — Files changed, comments generated

If actionable issues found, ask: "Want me to apply the suggested fixes?"
'''


def main():
    skill_dir = Path.home() / ".claude" / "skills" / "entelligence-review"
    skill_file = skill_dir / "SKILL.md"

    if skill_file.exists():
        print(f"Skill already installed at {skill_file}")
        print("Restart Claude Code and use /entelligence-review to review PRs.")
        return

    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(SKILL_CONTENT.strip() + "\n")

    print(f"Skill installed at {skill_file}")
    print()
    print("Restart Claude Code, then use /entelligence-review to review PRs.")


if __name__ == "__main__":
    main()
