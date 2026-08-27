# Deployment Guide

This project is self-contained: Stage 1 source, the Stage 2 OpenClaw skill, the
Stage 3 generator, and all runtime output directories are under this repository.
It does not read code, skills, issue files, or configuration from a sibling
project. Network access, an LLM provider, OpenClaw, and Chrome remain normal
runtime dependencies.

## 1. Install

Install Python 3.12 or newer, OpenClaw, and Google Chrome or Chromium. Then,
from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Check that the browser and OpenClaw command are available through the
paths you configured in `.env`, or that they are on `PATH`:

```powershell
openclaw --version
& $env:CHROME_PATH --version
```

## 2. Configure Credentials

Copy `.env.example` to `.env` and configure values supplied by your provider.
Do not commit `.env`.

- Stage 1 uses `LLM_API_KEY`, `LLM_API_URL`, and `LLM_MODEL` with a chat-completions API.
- Stage 3 uses `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` with an
  OpenAI-compatible Responses API.
- Stage 2 runs `openclaw agent --local`. Configure OpenClaw with a browser-capable
  model provider, or provide the provider variables supported by your OpenClaw installation.
- `CHROME_PATH` and `OPENCLAW_PATH` are optional runtime executable paths. Keep
  them in the local, ignored `.env`, never in source code. If blank, the
  controller looks up `chrome` and `openclaw` on `PATH`.

The repository intentionally contains no credentials and no absolute user paths.

For a machine where either executable is not on `PATH`, set the corresponding
values in `.env`. These are deployment-machine settings, not repository
dependencies.

## 3. Add Issues

Place supplied issue text in `issues/source/`. Subdirectories are accepted, except
`archive/`, `fixtures/`, and `example_inputs/`, which are ignored. Each issue
must be a UTF-8 `.txt` file containing the complete description and any
available reproduction steps or attachment URLs. Scratch copies from earlier
trials live in `issues/archive/` and are not part of the default run.

## 4. Run The Pipeline

Run all three stages:

```powershell
.\.venv\Scripts\python.exe pipeline.py --stage all --source issues/source --model <model-name>
```

The data flow is strict:

```text
issues/source -> issues/staged_raw -> issues/final_selected
-> artifacts/reproduction/reports + issues/reproduced -> artifacts/attack_prompts
```

Stage 2 creates one isolated browser workspace per selected issue and calls the
workspace-local skill through `scripts/run_openclaw_reproduction.ps1`. Issues
labelled `REPRODUCED` (with concrete `verify:` evidence) or `POTENTIAL` are
copied to `issues/reproduced`. `NOT_REPRODUCIBLE` issues are not forwarded.
Stage 3 reads that directory by default. To inspect a stage independently:

```powershell
.\.venv\Scripts\python.exe pipeline.py --stage analyze --source issues/source --model <stage1-model>
.\.venv\Scripts\python.exe pipeline.py --stage reproduce --reproduction-timeout 900
.\.venv\Scripts\python.exe pipeline.py --stage attack --model <stage3-model>
```

For wiring checks that do not call an LLM or launch a browser:

```powershell
.\.venv\Scripts\python.exe pipeline.py --stage analyze --source issues/source --dry-run
.\.venv\Scripts\python.exe pipeline.py --stage reproduce --dry-run
.\.venv\Scripts\python.exe pipeline.py --stage attack --dry-run --attack-input final
.\.venv\Scripts\python.exe -m pytest -q
```

`--attack-input final` exists only for generator development. Do not use it for
the end-to-end study pipeline because it bypasses reproduction evidence.

## 5. Outputs

- `issues/final_selected/`: Stage 1 selections.
- `artifacts/reproduction/reports/`: per-issue evidence reports and summary.
- `artifacts/reproduction/openclaw/`: OpenClaw JSON responses and logs.
- `issues/reproduced/`: Stage 2 `REPRODUCED` and `POTENTIAL` outputs for Stage 3.
- `artifacts/attack_prompts/`: Stage 3 letters and processing status.

Before publishing results, remove all files below `issues/` and `artifacts/`
unless they are intended as anonymized research fixtures. `.env`, virtual
environments, and transient runtime state are already ignored by Git.
