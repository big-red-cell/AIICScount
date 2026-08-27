# AIIC Three-Stage Pipeline

This workspace contains local copies of the three required implementations:

1. `vendor/senior_stage1/process_txt_with_llm.py` is the senior's four-filter
   analyzer. Its output is written directly to `issues/final_selected`.
2. OpenClaw plus the local reproduction skill checks the selected issues in an
   isolated browser profile and writes evidence-backed reports.
3. `vendor/attack_generator` generates attack-prompt letters from Stage 2
   issues labelled `REPRODUCED` or `POTENTIAL`.

## Layout

```text
issues/
  source/              Default Stage 1 input. Scratch copies belong in archive/.
  staged_raw/          Recursively collected, collision-safe analyzer input.
  final_selected/      Phase 1 selected issues.
  reproduced/          Phase 2 REPRODUCED and POTENTIAL copies for Stage 3.
artifacts/
  analyzer/            Report Analyzer working data and command records.
  reproduction/        OpenClaw manifest, reports, evidence, isolated profiles.
  attack_prompts/      Phase 3 letters and status files.
skills/
  browser-agent-issue-reproduction/  OpenClaw entrypoint plus original protocol
vendor/
  senior_stage1/       Local copy of the senior's Phase 1 source.
  attack_generator/   Local copy of the Phase 3 source and tests.
```

## Commands

Run the following from this directory. `--dry-run` performs no LLM calls.

```powershell
python pipeline.py --stage analyze --source issues/source --model <analyzer-model>
python pipeline.py --stage reproduce
python pipeline.py --stage attack --model <attack-model>
python pipeline.py --stage all --source issues/source --model <model>
```

`--stage all` executes live Phase 2 and routes Phase 3 from
`issues/reproduced`. The Stage 2 runner is
`scripts/run_openclaw_reproduction.ps1`; it invokes `openclaw agent --local`
with the workspace-local skill and an isolated artifact directory for each
issue. Configure credentials only through this project's root `.env`, using
`.env.example` as a template. No source, skill, configuration, or issue path
outside this folder is required; real LLM calls still require network access,
OpenClaw, Chrome, and valid API credentials.

For a no-API wiring check, use the included fixture and dry run:

```powershell
python pipeline.py --stage reproduce --dry-run
python pipeline.py --stage attack --dry-run --attack-input final
pytest -q
```

`--attack-input final` is retained only for generator-development checks. The
study pipeline should use the default Stage 2 handoff:

```powershell
python pipeline.py --stage attack --attack-input reproduced --model <attack-model>
```

## OpenClaw Phase 2

The original supplied protocol is preserved verbatim in
`skills/browser-agent-issue-reproduction/REFERENCE_PROTOCOL.md`. The adjacent
`SKILL.md` is the OpenClaw-compatible entrypoint. The generated
`artifacts/reproduction/manifest.json` lists the exact selected issues. A
`REPRODUCED` report still requires concrete `verify:` evidence. Both
`REPRODUCED` and `POTENTIAL` issues are copied into `issues/reproduced/` for
Stage 3. `NOT_REPRODUCIBLE` issues stay out.

See `DEPLOYMENT.md` for the full clean-machine setup and runbook.
