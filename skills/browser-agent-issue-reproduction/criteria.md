# Reproduction Bucket Criteria

Use this file to decide between `REPRODUCED`, `POTENTIAL`, and
`NOT_REPRODUCIBLE`. Apply the flow in `SKILL.md` first; use this table when the
answer is not obvious.

## 1. NOT_REPRODUCIBLE

Choose this bucket immediately when the issue text itself shows the behavior
cannot exist in the target being tested.

| Signal | Examples |
|---|---|
| Removed feature/API | "removed in M120", "deprecated and deleted" |
| Fixed by a landed change | "fixed by crrev.com/c/...", "landed in stable" |
| Contradictory prerequisites | one step requires a state another step forbids |
| Dependency already patched | depends on a fixed CVE or removed bundled library |
| Valid environment, three failed attempts | each attempt reached the expected trigger point and readback disproved the effect |

Do not write a POC for this bucket. Keep the report short and evidence based.

## 2. POTENTIAL

Choose this bucket when the attack chain is plausible but this environment
cannot supply required prerequisites or material.

| Category | Examples |
|---|---|
| OS/platform mismatch | Android, ChromeOS, Linux-only, macOS-only, iOS/WebKit, Windows-only when not available |
| Browser version/channel mismatch | requires an old build, Canary-only feature, or removed flag |
| Hardware requirement | security key touch, NFC, Bluetooth device, TPM, camera/microphone model, special GPU |
| Enterprise or managed context | policy, MDM, forced sign-in, managed account, kiosk mode |
| External native dependency | native messaging host, installed app, OS service, custom protocol handler |
| Network-position requirement | MITM, corporate proxy, captive portal, ISP DNS behavior |
| Region/account/OOB requirement | country lock, SMS/email code outside agent control, CAPTCHA that cannot be solved |
| Missing repro material | required attachment or payload cannot be obtained or read |
| Insufficient issue steps | core steps or prerequisite state are absent from all provided material |

For `POTENTIAL`, write a concrete attack chain for the correct environment. A
local scaffold under `artifacts/pocs/issue_<ID>/` is optional if it helps make
the chain precise.

## 3. REPRODUCED

Choose this bucket only when the issue's observable effect was actually
triggered and verified.

Acceptable evidence includes:

| Claimed action | Required readback |
|---|---|
| File downloaded | path, non-zero size, and preferably hash/type |
| File created or modified | path, size/hash, and content sanity check |
| URL navigation | active tab URL/title from browser/CDP/WebDriver |
| Button/menu clicked | resulting DOM state, browser setting, file, URL, or dialog |
| Extension loaded | extension id/card/enabled state read back from browser |
| Clipboard changed | `Get-Clipboard` round trip |
| Process killed/launched | process list or port/listener readback |
| Vulnerability triggered | the exact observable described by the issue |

A screenshot alone is not sufficient. Use it only as supplementary navigation
context.

## Retry Accounting

An attempt is consumed when:

- the full sequence reaches the expected trigger point but the observable effect
  does not occur, or
- the approach reaches a real dead end and needs a different strategy

An attempt is not consumed when:

- fixing a syntax error in the same artifact
- retrying a transient focus/timing/browser wait issue
- iterating before the first complete trigger path
- repeating a readback after an obvious wait race

After three consumed attempts in a valid environment, choose
`NOT_REPRODUCIBLE` and list each attempt with the readback evidence that
disproved it.

## Edge Cases

- If only exfiltration is blocked but the vulnerable browser behavior itself is
  verified, choose `REPRODUCED` and note the exfiltration limitation.
- If an attachment is required and cannot be retrieved or supplied, choose
  `POTENTIAL`.
- If the issue needs a different but realistic Chrome version, choose
  `POTENTIAL` unless that version is already available and can be safely used.
- If browser automation is partially broken, use a verified fallback only when
  it gives stronger readback evidence than the broken path.
- If the issue describes user actions such as clicking, importing a file, or
  pressing a shortcut, those are not barriers; automate them when possible.
