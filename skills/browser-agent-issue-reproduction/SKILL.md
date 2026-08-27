---
name: browser-agent-issue-reproduction
description: Reproduce OpenClaw browser-agent issues from provided issue text and classify them with evidence-backed reports. Use when deciding REPRODUCED, POTENTIAL, or NOT_REPRODUCIBLE.
version: 0.1.0
metadata: {"openclaw":{"os":["win32"]}}
---

# Browser Agent Issue Reproduction

Use this skill for reproduction engineering only. Do not rate severity, debate
whether Chromium should patch the issue, or invent missing exploit logic. The
job is to decide whether the provided issue can be reproduced by an OpenClaw
browser agent and to write evidence-backed artifacts.

## Reference Files

- Read `{baseDir}/criteria.md` when choosing a bucket or resolving edge cases.
- Read `{baseDir}/GUIDE.md` when checking OpenClaw skill loading, installing
  this skill for another user, or adapting the runtime/configuration.
- Keep reproduction outputs in the current workspace, not inside `{baseDir}`.

## Required Input

The minimum usable input is:

- issue id
- title or short claim
- full issue body / description / steps to reproduce

Useful enrichment includes comments, status fields, attachment names or URLs,
local HTML snapshots, prepared issue packages, and existing read/report paths.
If core steps or prerequisite state are missing, do not fabricate them;
classify as `POTENTIAL` and state the gap.

Only visit `https://issues.chromium.org/issues/<ID>` to retrieve attachments or
confirm attachment links. Do not fetch the issue text itself when the user has
provided local text or a package.

## Output Paths

Use workspace-relative paths unless the user requires a different layout:

- read note: `artifacts/reads/issue_<ID>.md`
- report: `artifacts/reports/issue_<ID>.md`
- reproduction workspace: `artifacts/repro/issue_<ID>/`
- optional POC scaffold: `artifacts/pocs/issue_<ID>/`
- batch summary: `artifacts/reports/_summary.md`

Create one report per issue. For batches, also update `_summary.md`.

## Bucket Flow

Every issue must land in exactly one bucket:

1. If the issue text says the behavior is removed, fixed, patched, or
   self-contradictory, choose `NOT_REPRODUCIBLE`.
2. If the attack logic is plausible but this environment cannot host the
   prerequisites, choose `POTENTIAL`.
3. Otherwise, run preflight and attempt real reproduction. If the observable
   effect is verified, choose `REPRODUCED`. After three consumed, verified
   attempts that fail, choose `NOT_REPRODUCIBLE`.

Consult `{baseDir}/criteria.md` for the detailed decision table.

## Windows/OpenClaw Preflight

Run preflight once per session, then cite the results in each report:

1. Identify the actual browser path and version.
   - Prefer Chrome/Chromium already configured for the workspace.
   - Record exact version text.
2. Ensure profile isolation.
   - Use a fresh `--user-data-dir` under `artifacts/repro/issue_<ID>/profile`
     or another run-specific temp path.
   - Kill or avoid stale browser processes that would ignore new flags.
3. Confirm automation capability.
   - Prefer OpenClaw browser tools when healthy.
   - Use CDP/Playwright/WebDriver/PowerShell as fallback when they provide
     stronger readback evidence.
4. Confirm filesystem and command helpers.
   - Use PowerShell for process, file, clipboard, and hash checks.
   - Use the native Python environment directly if a Python script is needed.

If browser automation is unavailable but the issue logic is still coherent,
choose `POTENTIAL` unless another verified fallback can reproduce the effect.

## Execution Rules

- Build only artifacts required by the issue: HTML, JavaScript, extension
  folders, crafted files, bookmarks, policy snippets, or local servers.
- Drive the browser through the most reliable available path.
- Verify every claimed action by reading state back.
- Treat screenshots as navigation aids only. They do not replace text evidence.
- Record exact commands, paths, URLs, DOM values, hashes, process ids, or
  browser state used as evidence.
- Retry up to three consumed end-to-end attempts. Fixing syntax errors,
  transient focus failures, or wait races does not consume an attempt.

## Verification Requirements

A step is successful only when the report includes a `verify:` line.

Common verification examples:

- downloaded file: `Get-Item`, size greater than zero, and preferably hash/type
- created file: path, size, and a short content sanity check
- navigated URL: read back active tab URL/title through browser/CDP
- clicked UI: read resulting DOM state, URL, file, dialog, or browser setting
- loaded extension: read `chrome://extensions` state or equivalent extension id
- changed clipboard: `Get-Clipboard` round trip
- killed process: `Get-Process` no longer shows the target process
- triggered bug: the exact observable named by the issue appears

Never soften errors. If a tool fails, record the exact failure and decide
whether to retry, switch approach, or classify the issue.

## Attachment Handling

Use this order:

1. Download direct URLs already present in the provided text.
2. If needed, open the issue page only to locate attachment links.
3. If automatic download fails, ask the user to provide the attachment.

Never claim an attachment was downloaded without verifying a non-empty local
file. Missing required attachment material means `POTENTIAL`, not
`NOT_REPRODUCIBLE`.

## Report Template

```markdown
# Issue <ID>

**Bucket:** REPRODUCED | POTENTIAL | NOT_REPRODUCIBLE

## Summary
<one or two sentences describing the issue claim>

## Environment
- OS/runtime: <Windows/OpenClaw details>
- Browser: <path and version>
- Automation path: <OpenClaw browser | CDP | Playwright | WebDriver | manual gap>
- Required environment: <from issue text>
- Attachments used: <list or none>

## Reproduction

### Steps executed
1. <action>
   - cmd: `<command/tool call>`
   - verify: <concrete observation>

## Artifacts
- `<workspace-relative path>` - <purpose>

## Notes
<gaps, failed attempts, or caveats>
```

For `POTENTIAL`, replace `Steps executed` with `Environment gap` and `Attack
chain`. For `NOT_REPRODUCIBLE`, replace it with `Reason` and the evidence from
the issue text or the three failed attempts.

## Hard Rules

- Do not report success without concrete readback evidence.
- Do not invent issue text, attachments, repro steps, or tool output.
- Do not fetch remote issue text when local/provided issue text exists.
- Do not use severity, exploitability, or product-impact labels as buckets.
- Keep paths workspace-relative in reports unless an absolute path is necessary
  for an executed command.
- In batch work, isolate each issue's artifacts and avoid session/profile reuse
  unless the user explicitly asks for it.
