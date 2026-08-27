# Findings & Decisions

## Requirements
- Chrome and OpenClaw are user-configured via `.env`; that is allowed
- Source code, skills, and docs must not contain extra-repo absolute paths
- After the three stages are wired, run them with the real API key
- Search all folders under the Agents parent directory for real issues matching the Stage 1 definition
- Verify analyze / reproduce / attack can complete

## Research Findings
- `.env` already has `CHROME_PATH` and `OPENCLAW_PATH` (user-local; gitignored)
- `scripts/run_openclaw_reproduction.ps1` still falls back to `ProgramFiles\Google\Chrome\...`
- `skills/browser-agent-issue-reproduction/GUIDE.md` uses `D:\openclaw-skill-pack\skills\` as an example
- `vendor/senior_stage1/process_txt_with_llm.py` defaults `LLM_API_URL` to a specific provider host
- `vendor/attack_generator/openai_responses_client.py` has a machine-like default User-Agent
- Stage 1 definition: harm outcome + reproduction steps + user interaction (click/keys/extension install) + Browser Agent capable
- Existing candidates in-repo: `issues/e2e_candidate/330693450.txt` (already REPRODUCED), `368562236.txt`, `issues/source/real_chromium/466978527.txt`

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Remove ProgramFiles Chrome fallbacks | Extra-repo paths in source; discovery is `.env` then PATH |
| Replace GUIDE.md Windows example with placeholders | Avoid extra-repo path in packaged skill docs |
| Copy sibling-folder issues into `issues/source/` | Keep the reproduction repo self-contained |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Glob over `D:\Codes\agents` timed out | Use a top-level directory listing instead |

## Resources
- `pipeline.py`, `scripts/run_openclaw_reproduction.ps1`, `DEPLOYMENT.md`
- Stage 1 prompts in `vendor/senior_stage1/process_txt_with_llm.py`
