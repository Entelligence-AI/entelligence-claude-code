#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

// ---------------------------------------------------------------------------
// Config — API key is read lazily from file or env on every request
// ---------------------------------------------------------------------------

const API_URL =
  process.env.ENTELLIGENCE_API_URL || "https://entelligence.ddbrief.com";
const DASHBOARD_URL =
  process.env.ENTELLIGENCE_DASHBOARD_URL || "https://app.entelligence.ai";
const CREDENTIALS_DIR = join(homedir(), ".entelligence");
const CREDENTIALS_FILE = join(CREDENTIALS_DIR, "credentials.json");

function getApiKey(): string {
  // 1. Env var takes priority (for CI, advanced users)
  if (process.env.ENTELLIGENCE_API_KEY) {
    return process.env.ENTELLIGENCE_API_KEY;
  }

  // 2. Read from credentials file (written by save_api_key tool)
  try {
    if (existsSync(CREDENTIALS_FILE)) {
      const raw = readFileSync(CREDENTIALS_FILE, "utf-8");
      const creds = JSON.parse(raw) as { api_key?: string };
      if (creds.api_key) return creds.api_key;
    }
  } catch {
    // File corrupt or unreadable — treat as missing
  }

  return "";
}

function saveApiKey(key: string): void {
  if (!existsSync(CREDENTIALS_DIR)) {
    mkdirSync(CREDENTIALS_DIR, { recursive: true });
  }
  writeFileSync(
    CREDENTIALS_FILE,
    JSON.stringify({ api_key: key }, null, 2),
    { mode: 0o600 } // Owner-only read/write
  );
}

const SETUP_NEEDED_FLAG = "__ENTELLIGENCE_SETUP_NEEDED__";

const SETUP_MESSAGE = `${SETUP_NEEDED_FLAG}

Welcome to Entelligence PR Reviewer! To get started, you need an API key.

Get your API key at: ${DASHBOARD_URL}/settings?tab=api

Once you have it, paste it here and I'll save it for you.`;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function apiRequest(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const apiKey = getApiKey();
  const url = `${API_URL}${path}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${apiKey}`,
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  return fetch(url, { ...options, headers });
}

function checkApiKey(): string | null {
  const key = getApiKey();
  if (!key) return SETUP_MESSAGE;
  return null;
}

interface UserInfo {
  UserUUID: string;
  OrgUUID: string;
  OrgName: string;
  Email: string;
  Name: string;
  GitHubToken: string | null;
  Error: string | null;
}

async function getUserInfo(): Promise<UserInfo> {
  const res = await apiRequest("/getUserInfo/");
  if (!res.ok) {
    throw new Error(
      `Failed to fetch user info: ${res.status} ${res.statusText}`
    );
  }
  // Backend returns double-encoded JSON (string inside JSON), so parse twice
  const raw = await res.json();
  return (typeof raw === "string" ? JSON.parse(raw) : raw) as UserInfo;
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Poll for async review result
// ---------------------------------------------------------------------------

interface ReviewResult {
  job_id: string;
  status: string;
  result?: Record<string, unknown>;
  error?: string;
}

async function pollReviewStatus(
  jobId: string,
  maxWaitMs: number = 600_000
): Promise<ReviewResult> {
  const start = Date.now();
  const pollIntervalMs = 10_000;

  while (Date.now() - start < maxWaitMs) {
    const res = await apiRequest(`/getReviewStatus/${jobId}/`);
    if (!res.ok) {
      throw new Error(
        `Failed to poll review status: ${res.status} ${res.statusText}`
      );
    }

    const data = (await res.json()) as ReviewResult;

    if (data.status === "done") return data;
    if (data.status === "failed") {
      throw new Error(`Review failed: ${data.error || "Unknown error"}`);
    }

    await sleep(pollIntervalMs);
  }

  throw new Error(
    `Review timed out after ${maxWaitMs / 1000}s. Job ID: ${jobId} — you can check later with get_review_status.`
  );
}

// ---------------------------------------------------------------------------
// Format review output
// ---------------------------------------------------------------------------

function formatReviewOutput(result: Record<string, unknown>): string {
  const parts: string[] = [];

  const walkthrough = result.walkthrough_and_changes as string | undefined;
  if (walkthrough) {
    parts.push("## Walkthrough\n\n" + walkthrough);
  }

  const comments = result.gitdiff_chunks_review as
    | Array<Record<string, unknown>>
    | undefined;
  if (comments && comments.length > 0) {
    parts.push("## Code Review Comments\n");
    for (const c of comments) {
      const severity = (c.severity as string) || "info";
      const fileName = (c.fileName as string) || "unknown";
      const summary = (c.summary as string) || "";
      const suggestion = (c.suggestion as string) || "";
      const suggestedCode = (c.suggested_code as string) || "";
      const agentPrompt =
        (c.prompt_for_ai_agents_for_addressing_review as string) || "";

      parts.push(`### [${severity.toUpperCase()}] ${fileName}\n`);
      parts.push(`**Issue:** ${summary}\n`);
      if (suggestion) parts.push(`**Suggestion:** ${suggestion}\n`);
      if (suggestedCode)
        parts.push("```diff\n" + suggestedCode + "\n```\n");
      if (agentPrompt)
        parts.push(`**Agent fix prompt:** ${agentPrompt}\n`);
    }
  }

  const releaseNote = result.releaseNote as string | undefined;
  if (releaseNote) {
    parts.push("## Release Note\n\n" + releaseNote);
  }

  const filesChanged = result.files_changed as number | undefined;
  if (filesChanged !== undefined) {
    parts.push(`\n---\n*${filesChanged} file(s) changed*`);
  }

  if (parts.length === 0) {
    return JSON.stringify(result, null, 2);
  }

  return parts.join("\n\n");
}

// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------

const server = new McpServer({
  name: "entelligence-pr-reviewer",
  version: "1.0.0",
});

// ---- Tool: save_api_key ----

server.tool(
  "save_api_key",
  "Save your Entelligence API key. Called during first-time setup after the user provides their key.",
  {
    api_key: z
      .string()
      .min(1)
      .describe("The Entelligence API key to save"),
  },
  async ({ api_key }) => {
    try {
      // Validate the key by calling getUserInfo
      const res = await fetch(`${API_URL}/getUserInfo/`, {
        headers: {
          Authorization: `Bearer ${api_key}`,
          "Content-Type": "application/json",
        },
      });

      if (!res.ok) {
        return {
          content: [
            {
              type: "text" as const,
              text: `Invalid API key — the server returned ${res.status}. Please double-check the key and try again.\n\nGet your key at: ${DASHBOARD_URL}/settings?tab=api`,
            },
          ],
          isError: true,
        };
      }

      // Backend returns double-encoded JSON
      const rawInfo = await res.json();
      const info = (typeof rawInfo === "string" ? JSON.parse(rawInfo) : rawInfo) as UserInfo;
      if (info.Error) {
        return {
          content: [
            {
              type: "text" as const,
              text: `API key validation failed: ${info.Error}`,
            },
          ],
          isError: true,
        };
      }

      // Key is valid — save it
      saveApiKey(api_key);

      return {
        content: [
          {
            type: "text" as const,
            text: `API key saved successfully! Logged in as **${info.Name}** (${info.Email}) in organization **${info.OrgName}**.\n\nYou're all set — you can now use \`/entelligence-review\` to review PRs.`,
          },
        ],
      };
    } catch (err) {
      return {
        content: [
          {
            type: "text" as const,
            text: `Error validating API key: ${err instanceof Error ? err.message : String(err)}`,
          },
        ],
        isError: true,
      };
    }
  }
);

// ---- Tool: review_pr ----

server.tool(
  "review_pr",
  "Review a pull request using Entelligence AI. Analyzes code quality, security, performance, and best practices.",
  {
    repo: z.string().describe('Repository in "owner/repo" format'),
    pr_number: z.number().int().positive().describe("Pull request number"),
    pr_diff: z
      .string()
      .optional()
      .describe("Unified diff string. If omitted the backend fetches it."),
    priority_level: z
      .enum(["low", "medium", "high"])
      .default("low")
      .describe("Review depth: low (fast), medium, high (thorough)"),
    mode: z
      .enum(["concise", "verbose"])
      .default("concise")
      .describe("Output verbosity"),
  },
  async ({ repo, pr_number, pr_diff, priority_level, mode }) => {
    try {
      const setupErr = checkApiKey();
      if (setupErr) {
        return { content: [{ type: "text" as const, text: setupErr }] };
      }

      const userInfo = await getUserInfo();
      if (userInfo.Error) {
        return {
          content: [{ type: "text" as const, text: `Error: ${userInfo.Error}` }],
          isError: true,
        };
      }

      const body: Record<string, unknown> = {
        orgUUID: userInfo.OrgUUID,
        repoName: repo,
        prNumber: String(pr_number),
        priorityLevel: priority_level,
        mode,
        walkthroughEnable: true,
        releaseNoteEnable: true,
        codeReviewEnable: true,
      };
      if (userInfo.GitHubToken) body.githubToken = userInfo.GitHubToken;
      if (pr_diff) body.prDiff = pr_diff;

      const submitRes = await apiRequest("/generateReviewForCLIAsync/", {
        method: "POST",
        body: JSON.stringify(body),
      });

      if (!submitRes.ok) {
        const errBody = await submitRes.text();
        return {
          content: [
            { type: "text" as const, text: `Error submitting review (${submitRes.status}): ${errBody}` },
          ],
          isError: true,
        };
      }

      const { job_id } = (await submitRes.json()) as { job_id: string };
      const result = await pollReviewStatus(job_id);
      const formatted = formatReviewOutput(result.result || {});
      return { content: [{ type: "text" as const, text: formatted }] };
    } catch (err) {
      return {
        content: [
          { type: "text" as const, text: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ],
        isError: true,
      };
    }
  }
);

// ---- Tool: review_diff ----

server.tool(
  "review_diff",
  "Review a raw diff string synchronously. Best for small diffs or local uncommitted changes.",
  {
    diff: z.string().describe("Unified diff string (e.g. output of `git diff`)"),
    repo_name: z
      .string()
      .default("local/repo")
      .describe('Repository name in "owner/repo" format'),
    priority_level: z
      .enum(["low", "medium", "high"])
      .default("low")
      .describe("Review depth"),
    mode: z
      .enum(["concise", "verbose"])
      .default("concise")
      .describe("Output verbosity"),
  },
  async ({ diff, repo_name, priority_level, mode }) => {
    try {
      const setupErr = checkApiKey();
      if (setupErr) {
        return { content: [{ type: "text" as const, text: setupErr }] };
      }

      const userInfo = await getUserInfo();
      if (userInfo.Error) {
        return {
          content: [{ type: "text" as const, text: `Error: ${userInfo.Error}` }],
          isError: true,
        };
      }

      const reviewBody: Record<string, unknown> = {
        orgUUID: userInfo.OrgUUID,
        repoName: repo_name,
        prDiff: diff,
        priorityLevel: priority_level,
        mode,
        walkthroughEnable: true,
        releaseNoteEnable: true,
        codeReviewEnable: true,
      };
      if (userInfo.GitHubToken) reviewBody.githubToken = userInfo.GitHubToken;

      const res = await apiRequest("/generateReviewForCLI/", {
        method: "POST",
        body: JSON.stringify(reviewBody),
      });

      if (!res.ok) {
        const errBody = await res.text();
        return {
          content: [{ type: "text" as const, text: `Error (${res.status}): ${errBody}` }],
          isError: true,
        };
      }

      const result = (await res.json()) as Record<string, unknown>;
      return { content: [{ type: "text" as const, text: formatReviewOutput(result) }] };
    } catch (err) {
      return {
        content: [
          { type: "text" as const, text: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ],
        isError: true,
      };
    }
  }
);

// ---- Tool: get_review_status ----

server.tool(
  "get_review_status",
  "Check the status of a previously submitted async PR review job.",
  {
    job_id: z.string().uuid().describe("Job ID from a prior review_pr call"),
  },
  async ({ job_id }) => {
    try {
      const res = await apiRequest(`/getReviewStatus/${job_id}/`);
      if (!res.ok) {
        const errBody = await res.text();
        return {
          content: [{ type: "text" as const, text: `Error (${res.status}): ${errBody}` }],
          isError: true,
        };
      }

      const data = (await res.json()) as ReviewResult;

      if (data.status === "done" && data.result) {
        return {
          content: [{ type: "text" as const, text: formatReviewOutput(data.result) }],
        };
      }

      return {
        content: [
          {
            type: "text" as const,
            text: `Job ${job_id}: status = ${data.status}${data.error ? ` | error: ${data.error}` : ""}`,
          },
        ],
      };
    } catch (err) {
      return {
        content: [
          { type: "text" as const, text: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ],
        isError: true,
      };
    }
  }
);

// ---- Tool: get_user_info ----

server.tool(
  "get_user_info",
  "Get the current user's Entelligence account info. Also used to check if the API key is configured.",
  {},
  async () => {
    try {
      const setupErr = checkApiKey();
      if (setupErr) {
        return { content: [{ type: "text" as const, text: setupErr }] };
      }

      const info = await getUserInfo();
      if (info.Error) {
        return {
          content: [{ type: "text" as const, text: `Error: ${info.Error}` }],
          isError: true,
        };
      }

      const text = [
        `**Name:** ${info.Name}`,
        `**Email:** ${info.Email}`,
        `**Organization:** ${info.OrgName}`,
        `**Org UUID:** ${info.OrgUUID}`,
        `**User UUID:** ${info.UserUUID}`,
      ].join("\n");

      return { content: [{ type: "text" as const, text }] };
    } catch (err) {
      return {
        content: [
          { type: "text" as const, text: `Error: ${err instanceof Error ? err.message : String(err)}` },
        ],
        isError: true,
      };
    }
  }
);

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
