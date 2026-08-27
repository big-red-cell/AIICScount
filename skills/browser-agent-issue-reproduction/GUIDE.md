# Install and Porting Guide

This file is for maintainers or users packaging this skill for another
OpenClaw workspace. Do not load it during normal issue reproduction unless you
need to check installation, discovery, or runtime setup.

## Recommended Layout

Package the skill as its own folder:

```text
browser-agent-issue-reproduction/
  SKILL.md
  GUIDE.md
  criteria.md
```

If this repository contains multiple skills, keep that folder under a shared
`skills/` parent:

```text
skills/
  browser-agent-issue-reproduction/
    SKILL.md
    GUIDE.md
    criteria.md
```

The folder name should stay lowercase and match the skill name:

```text
browser-agent-issue-reproduction
```

## OpenClaw Readability Conditions

OpenClaw can read a local skill when these conditions hold:

1. The skill root contains `SKILL.md`.
2. `SKILL.md` starts with YAML front matter delimited by `---`.
3. Front matter includes both `name` and `description`.
4. `name` is stable and uses lowercase letters, digits, and hyphens.
5. `description` clearly states what the skill does and when to invoke it.
6. The skill folder is inside a scanned skill source:
   - `<workspace>/skills`
   - `<workspace>/.agents/skills`
   - `~/.agents/skills`
   - `~/.openclaw/skills`
   - or a parent directory listed in `skills.load.extraDirs`

## Installation Options

Choose one of these layouts:

### 1. Workspace-local

Copy the entire `browser-agent-issue-reproduction/` folder to:

```text
<workspace>/skills/browser-agent-issue-reproduction/
```

This is the highest-precedence, project-specific option.

### 2. Shared managed install

Copy the folder to:

```text
~/.openclaw/skills/browser-agent-issue-reproduction/
```

This makes the skill available to multiple workspaces on the same machine.

### 3. Shared extra directory

Keep the packaged skill folder anywhere you want, then add the parent directory
that contains `browser-agent-issue-reproduction/` to `skills.load.extraDirs`.

Example:

```text
<skill-pack>/skills/
  browser-agent-issue-reproduction/
    SKILL.md
```

## Minimal Config Snippet

If the skill is not installed directly under the active workspace's `skills/`
directory, add a config entry similar to this:

```json
{
  "agents": {
    "defaults": {
      "skills": ["browser-agent-issue-reproduction"]
    }
  },
  "skills": {
    "load": {
      "extraDirs": ["<skill-pack>/skills"]
    }
  }
}
```

## Validation Commands

Run these from any shell that has OpenClaw on `PATH`:

```powershell
openclaw --version
openclaw skills list
```

The list should include:

```text
browser-agent-issue-reproduction
```

If it does not appear, verify:

- the active OpenClaw config file is the one you edited
- `skills.load.extraDirs` points to the parent directory that contains the
  skill folder
- `agents.defaults.skills` includes `browser-agent-issue-reproduction`, if you
  use an allowlist
- `SKILL.md` front matter includes `name` and `description`
- the packaged folder name matches the skill name

## Porting Notes

Keep the decision logic platform-neutral where possible, but keep the default
execution path honest about current support:

| Capability | Current guidance |
|---|---|
| Browser UI automation | OpenClaw browser tools, Playwright, WebDriver, CDP |
| DOM read/write | CDP, Playwright, WebDriver execute script |
| Process control | `Get-Process`, `Stop-Process`, `taskkill /F` |
| Filesystem checks | `Get-Item`, `Get-FileHash`, `Get-Content` |
| Clipboard checks | `Set-Clipboard`, `Get-Clipboard` |
| Local helper scripts | `python ...` |

If you later port this skill to macOS or Linux, update both the body of
`SKILL.md` and the front matter `metadata.openclaw.os` gate together.

## Packaging Rules

- Keep `SKILL.md` as the only required entrypoint.
- Keep bucket details in `criteria.md`.
- Keep installation and maintenance details in this file.
- Use `{baseDir}` inside `SKILL.md` when referencing bundled support files.
- Store reproduction artifacts in the user's workspace, not in the skill
  folder.
- Keep the package text-only if you intend to publish it through ClawHub.
