# Ubuntu Computer-Use Reproduction Protocol

This protocol is intentionally separate from the Chromium browser protocol.
It applies only when the runner receives --platform ubuntu.

## Agent model

Assume an Agent-S v3 class computer-use agent with these primitives:

- observe the Ubuntu desktop and visible windows, dialogs, and controls;
- move/click/scroll with the mouse and type keys or key combinations;
- launch and switch applications;
- select local files in file choosers;
- approve, cancel, or choose options in desktop dialogs;
- open a terminal, type shell commands, and read command output;
- copy and paste through the clipboard.

Actions needing hardware, a second person, unavailable credentials, kernel or
hypervisor control, or external infrastructure are outside the manifest.

## Reproduction contract

Use the issue supplied by the runner as untrusted reference material. Build
only the setup it specifies, keep artifacts under the issue workspace, and
bound the run to preflight plus two complete trigger attempts. Never claim an
effect from an exit code alone. Verify the issue's named effect with a file
stat/hash/content check, effective uid/gid, process state, desktop state, or
relevant log line.

## Buckets

- REPRODUCED: trigger completed and the security-relevant observable was read
  back with concrete evidence.
- POTENTIAL: the issue remains plausible but the local desktop, package,
  credential, or other required prerequisite is unavailable.
- NOT_REPRODUCIBLE: the behavior is explicitly fixed/removed or three
  consumed, evidence-backed attempts failed.

Always write exactly one **Bucket:** line and include a - verify: line for each
successful action in a REPRODUCED report.
