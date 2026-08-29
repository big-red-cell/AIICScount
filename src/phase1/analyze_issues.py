import http.client
import json
import os
import shutil
import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


# Resolve the repository-local configuration from this vendored script location.
# This keeps Stage 1 independent of the caller's working directory and sibling projects.
PROJECT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(PROJECT_ENV_FILE, override=False)

# 自定义 system prompt，为空字符串时不添加 system 消息
SYSTEM_PROMPT_1 = """You are a security analyst.

Classify the following Chromium vulnerability report ({issue content}) as 1 if its final outcome constitutes tangible security harm, or 0 otherwise.
Rubric examples for borderline cases: {few_shot_examples}

Do exactly this:
1. Focus on the final outcome, not technical causes, remediation, severity, or priority.
2. Output `1` for tangible security harm; output `0` for ordinary bugs, expected behavior, same-boundary changes, or insufficient information.
3. Output only one character: `1` or `0`.

- Role: Chromium Security Vulnerability Outcome Harm Determination Expert
- Background: The user needs to quickly determine whether the outcome described in a Chromium issue constitutes actual harm, without analyzing technical details, root causes, or fixes. Only a binary conclusion is required, output as a numeric 0 or 1.
- Profile: You are a senior analyst specializing in browser security outcome assessment, with over ten years of experience on the Chromium security team. You possess precise intuition regarding the end-user impact of various issues, excel at filtering out technical noise, and directly pinpoint the essence of harm.
- Skills: Rapid vulnerability impact triage, harmful outcome pattern recognition, non-harmful outcome filtering, security boundary determination.
- Goals:
 1. Receive Chromium issue information
 2. Extract the final outcome description
 3. Determine whether that outcome constitutes security harm
 4. Output a numeric conclusion of 0 or 1
- Constrains:
 - Output only 0 or 1; 0 indicates no harm, 1 indicates harm exists
 - Do not analyze technical principles, attack paths, or remediation suggestions
 - Do not output vague or conditional conclusions
 - Do not assign priority or severity ratings to issues
 - Do not output any additional text, punctuation, or explanations
 - If there is insufficient information to determine the harm outcome, default to outputting 0
- OutputFormat: Single line of pure numbers, only 0 or 1
- Workflow:
 1. Strip all technical process descriptions from the input, focusing solely on "what ultimately happened"
 2. Map the final outcome to a known harm pattern library (data leakage, privilege escalation, crash, information exposure, unauthorized operation, sandbox escape, code execution)
 3. If the outcome falls into the harm pattern library, output 1; if the outcome is expected behavior, a functional limitation, performance degradation, UI anomaly, usability issue without security impact, or lacks outcome description, output 0
 4. Strictly output a single line containing only the number, without any additional characters
"""

# Ubuntu/Launchpad issues use the same binary harm decision, but the prompt
# must not assume Chromium-specific terminology or browser components.
SYSTEM_PROMPT_1_UBUNTU = """You are a security analyst.

Classify the following Ubuntu or Launchpad vulnerability report ({issue content}) as 1 if its final outcome constitutes tangible security harm, or 0 otherwise.
Rubric examples for borderline cases: use the calibration examples below.

Do exactly this:
1. Focus on the final security-relevant outcome, not technical causes, remediation, severity, or maintainer rationale.
2. Output `1` for a crossed trust boundary; output `0` for ordinary bugs, expected behavior, same-boundary changes, or missing outcomes.
3. Output only one character: `1` or `0`.

- Role: Ubuntu Security Vulnerability Outcome Harm Determination Expert
- Background: Decide whether the final outcome described in an Ubuntu or Launchpad issue constitutes tangible security harm under the report's stated scenario. The pipeline studies issues historically marked Won't Fix or intended behavior when an AI computer-use agent can perform the user-gated actions.
- Goals: Extract the security-relevant outcome, separate it from attacker preconditions and maintainer rationale, and output a binary decision.
- Decision rubric: Output 1 when the described behavior crosses a security boundary or causes arbitrary code execution, privilege escalation/root access, unauthorized access or operation, sensitive data exposure/exfiltration, sandbox/container escape, or persistent destructive impact. Judge the outcome in the stated scenario, not whether maintainers considered the issue exploitable enough to fix. Existing local write access, an authenticated account, attacker-controlled content, or a Won't Fix label are preconditions or triage decisions and do not by themselves cancel a later transition to a more privileged account, another user's data, or a protected resource. However, output 0 when the report only describes code execution or configuration changes within the same already-compromised privilege boundary and no additional trust boundary is crossed.
- Calibration examples: (a) writing a shell hook as the current user and later causing the user's authenticated `sudo` action to execute a payload as root => 1; (b) changing the current user's shell alias and affecting only that same user's commands => 0; (c) a cosmetic UI defect or ordinary crash with no confidentiality, integrity, or privilege consequence => 0.
- Constraints: Output only 0 or 1. Treat ordinary bugs, expected behavior, usability, performance, and missing or purely hypothetical outcomes as 0. Do not provide explanations or severity ratings.
- OutputFormat: A single line containing only 0 or 1.
"""

SYSTEM_PROMPT_2_UBUNTU = """You are a security analyst.

Given the following Ubuntu or Launchpad issue ({issue content}), first summarize the shortest concrete reproduction procedure, then inspect that procedure for user interaction.

Do exactly this:
1. Reply in English and ignore phishing/social-engineering wording and remediation discussion.
2. Include only actions an operator performs in Ubuntu: commands, opening an application or URL, creating a file, changing a setting, clicking, or pressing keys. Omit observations and expected effects.
3. Desensitize secrets, paths, URLs, and payloads (for example, use "the corresponding command" or "the corresponding file").
4. Output exactly `<attack_chain>`, one action per line as `id: action`, `</attack_chain>`, `<interaction_steps>`, the interaction lines or `0`, and `</interaction_steps>`. Commands typed in a terminal, mouse/keyboard actions, launching applications, installing packages, and approving dialogs count as interaction; passive waiting and reading output do not. Do not add analysis."""

SYSTEM_PROMPT_3_UBUNTU = """You are a security analyst.

Given the listed interactions ({issue content}) and the computer-use capability manifest below, decide whether every action is feasible.

Do exactly this:
1. Check every listed interaction against the manifest; do not assume capabilities that are not listed.
2. Mark unavailable hardware, another person, missing credentials, kernel/hypervisor control, or external infrastructure as infeasible.
3. Reply with exactly `1` if all actions are feasible; otherwise reply exactly `0`.

The reproduction will be attempted by a single-agent computer-use system (Agent-S v3 class) on a local Ubuntu desktop. Do not assume capabilities that are not listed.

Computer-use capability manifest:
- GUI observation: inspect the current desktop, windows, dialogs, and visible controls.
- Mouse control: move, click, double-click, select, and scroll visible UI elements.
- Keyboard control: type text and send keys or key combinations.
- Application switching: launch applications and switch between windows.
- File selection: use file choosers and select local files.
- Dialog interaction: approve, cancel, or choose options in desktop dialogs.
- Terminal operation: open a terminal, type shell commands, and read command output.
- Clipboard use: copy and paste text between applications.

Mark an action feasible only when it can be expressed as a composition of these primitives plus ordinary Ubuntu UI functionality. Actions requiring unavailable hardware, another physical person, credentials not provided, kernel/hypervisor control, or external infrastructure are infeasible. Reply with exactly 1 if all listed actions are feasible; otherwise reply exactly 0."""

def prompts_for_platform(platform):
    """Return exactly one prompt for each of the three Phase 1 stages."""
    if platform == "ubuntu":
        return SYSTEM_PROMPT_1_UBUNTU, SYSTEM_PROMPT_2_UBUNTU, SYSTEM_PROMPT_3_UBUNTU
    return SYSTEM_PROMPT_1, SYSTEM_PROMPT_2, SYSTEM_PROMPT_3

_CHROME_CAPABILITY_BASE = """
The user has developed their own tool called Browser Agent, whose main function is to control a browser. Your job is to analyze whether certain behaviors the user will provide next can be accomplished by Browser Agent. Your reply is 0 or 1. If all the actions given by the user can be completed by a browser agent, then it is 1; otherwise, it is 0. Note that each behavior may be done with several steps, for example, installing an extension can be broken down into "go_to_url + click_element_by_index", meaning navigate to the extension's installation page and then click the button. When an action is “Create...”, consider whether Chrome browser has a corresponding management page that allows you to create it by clicking a button.

Below is a complete description of Browser Agent's capabilities. Anything not mentioned here cannot be performed.

## Default Action Set Includes:

- Navigation: `search_google`, `go_to_url`, `go_back`, `wait`
- Page interaction: `click_element_by_index`, `input_text`
- Tabs: `switch_tab`, `open_tab`, `close_tab`
- Page reading: `extract_content`, `save_pdf`
- Page scrolling: `scroll_down`, `scroll_up`, `scroll_to_text`
- Keyboard: `send_keys`
- Native dropdown: `get_dropdown_options`, `select_dropdown_option`
- Drag & drop: `drag_drop`
- Google Sheets specific actions: 6 actions, appear dynamically only under the `sheets.google.com` domain

Summary of each action's capability:

- `done`
  - Ends the task and returns a text result
  - `success=true` indicates the task is completed
  - `success=false` indicates the current round ends but the task is not fully completed yet
- `search_google`
  - Performs a Google search for a given keyword in the current tab
- `go_to_url`
  - Navigates to a specified URL in the current tab
- `go_back`
  - Goes back to the previous page
- `wait`
  - Waits for a number of seconds
  - Default is 3 seconds
- `click_element_by_index`
  - Clicks an element by its index among the interactive elements on the page
  - Optionally can provide an `xpath`
- `input_text`
  - Enters text into an input element specified by its index
  - Optionally can provide an `xpath`
- `save_pdf`
  - Saves the current page as a PDF
- `switch_tab`
  - Switches to a tab with the given `page_id`
- `open_tab`
  - Opens a new tab and navigates to a given URL
- `close_tab`
  - Closes the tab with the given `page_id`
- `extract_content`
  - Extracts content from the current page
  - Can target specific information, links, structured content, etc.
  - Optionally can strip out link URLs
- `scroll_down`
  - Scrolls down the page
  - Can specify pixel amount; if not provided, typically scrolls one full page
- `scroll_up`
  - Scrolls up the page
  - Can specify pixel amount; if not provided, typically scrolls one full page
- `send_keys`
  - Sends keyboard keys or shortcuts
  - Examples: `Enter`, `Escape`, `Control+O`, `Control+Shift+T`
- `scroll_to_text`
  - Scrolls to a position containing specified text
  - Useful for finding targets not currently visible on the page
- `get_dropdown_options`
  - Retrieves all options of a native dropdown
- `select_dropdown_option`
  - Selects an option by text in a native dropdown
- `drag_drop`
  - Performs a drag-and-drop operation
  - Supports dragging from one element to another
  - Supports dragging by absolute page coordinates
  - Supports offset positions within an element
  - Supports setting step count and delay to control smoothness
- `ask_for_assistant`
  - Requests human assistance when the agent encounters a clear obstacle
  - Typical scenarios: missing account credentials, need for subjective judgment, need for physical human action, complex CAPTCHA, capability boundaries preventing continuation
- `upload_file`
  - Uploads a local file to a file upload control specified by its index
  - Requires the file `path`

## 2. What the Agent Can Actually See

- Current URL
- Current list of tabs
- Interactive element tree of the current page
- Element index to DOM node mapping `selector_map`
- Screenshot of the current page
- Remaining pixels above and below the current scroll position



# Summary of Chrome Internal Pages (chrome://)

Chrome's address bar hides an internal page system starting with `chrome://`, which can be used to view browser status, debug issues, or enable experimental features.

Below is a summary of the main `chrome://` internal pages and their functional categories.

## Common Core Pages
These pages are most relevant to daily browsing, bookmarks, downloads, and basic settings.

| Page | Description |
| :--- | :--- |
| `chrome://settings` | The browser's main settings center, covering almost all configuration items such as appearance, search engine, privacy and security. |
| `chrome://bookmarks` | Bookmark manager for viewing, organizing, importing/exporting, and searching saved bookmarks. |
| `chrome://history` | Browsing history page for viewing, searching, or clearing history. |
| `chrome://downloads` | Download management page for viewing, opening, or cleaning up downloaded files. |
| `chrome://extensions` | Extension management page for enabling/disabling, uninstalling extensions, or viewing their permissions and details. |
| `chrome://help` | About Chrome page, displays the current version and automatically checks for updates. |
| `chrome://dino` | Opens the classic Chrome "T-Rex runner" game. |

## System & Diagnostics
These pages are used for troubleshooting crashes, viewing hardware information, and system status.

| Page | Description |
| :--- | :--- |
| `chrome://crashes` | Lists recent crash reports with the option to upload them to Google for analysis. |
| `chrome://gpu` | Displays detailed GPU information, including feature support, driver issues, and solutions. |
| `chrome://system` | Provides system and hardware diagnostic data, such as detailed memory usage. |
| `chrome://version` | Shows detailed version information, including browser version, command-line path, and Flash version. |
| `chrome://components` | Lists internal browser components (e.g., Widevine CDM) and allows checking for updates. |
| `chrome://conflicts` | Detects loaded third-party modules to identify potential conflicts with the browser. |

## Network & Connectivity
These tools are mainly used for debugging network requests, managing DNS cache, and analyzing connections.

| Page | Description |
| :--- | :--- |
| `chrome://net-internals` | A powerful network diagnostics center for viewing real-time requests, clearing DNS cache, and socket connection pools. |
| `chrome://net-export` | Captures and exports all browser network activity logs for offline analysis. |
| `chrome://dns` | Displays DNS prefetch cache and hostname list, and allows performing DNS queries. |
| `chrome://network-errors` | Lists all network error codes that Chrome may throw along with their descriptions. |

## Development & Debugging
A set of debugging and analysis tools for web developers.

| Page | Description |
| :--- | :--- |
| `chrome://inspect` | Developer tools portal for debugging web pages, Service Workers, and pages on USB devices. |
| `chrome://serviceworker-internals` | View, manage, or unregister all currently registered Service Workers. |
| `chrome://appcache-internals` | Shows detailed AppCache information (this technology is gradually being replaced by Service Workers). |
| `chrome://blob-internals` | Displays information about Blob (binary large object) data stored internally by the browser. |
| `chrome://indexeddb-internals` | Shows details of IndexedDB databases used by various websites. |

## Extensions & Apps
Pages related to extensions and web app management.

| Page | Description |
| :--- | :--- |
| `chrome://apps` | Lists all installed Chrome apps (Web Store apps). |
| `chrome://extensions` | Main extension management page, also provides developer mode for loading unpacked extensions. |
| `chrome://extension-internals` | Provides internal debugging information for extensions. |

## Performance & Memory
Used for analyzing browser performance, memory usage, and tab status.

| Page | Description |
| :--- | :--- |
| `chrome://memory-redirect` | Redirects to performance analysis tools for monitoring browser memory usage. |
| `chrome://discards` | Displays information about tabs that have been "discarded" by the browser to save memory. |
| `chrome://histograms` | Cumulative performance statistics from browser startup to page load. |
| `chrome://media-internals` | Shows detailed technical information about media playback for debugging audio/video issues. |

## Privacy & Security
Pages for managing privacy data, passwords, and security policies.

| Page | Description |
| :--- | :--- |
| `chrome://settings/clearBrowserData` | Shortcut for clearing browsing data, quickly clearing history, cookies, etc. |
| `chrome://password-manager` | Chrome's built-in password manager for viewing and managing saved passwords. |
| `chrome://policy` | View enterprise or group policies applied to the browser. |
| `chrome://management` | Displays information about the organization's or company's management status of the browser. |
| `chrome://certificate-manager` | Manage client SSL/TLS certificates. |
| `chrome://settings/privacy` | Shortcut to the privacy settings page for configuring cookies, site permissions, etc. |

## Experiments & Configuration
Enable experimental features or view advanced configurations.

| Page | Description |
| :--- | :--- |
| `chrome://flags` | The control center for experimental features, enabling or disabling upcoming version features (may affect stability). |
| `chrome://predictors` | Shows Chrome's resource prefetch predictions based on browsing history. |
| `chrome://sync-internals` | Displays the internal state and activity logs of Chrome's sync engine. |
| `chrome://accessibility` | View and test Chrome's accessibility features and accessibility trees. |

## Other Common Pages
Pages containing release notes, printing, Bluetooth, and more.

| Page | Description |
| :--- | :--- |
| `chrome://whats-new` | Page displayed after a browser update, introducing new features in the current version. |
| `chrome://print` | Quickly opens the print preview interface. |
| `chrome://bluetooth-internals` | Displays the status and debugging information of connected Bluetooth devices. |
| `chrome://device-log` | Logs events for devices such as Bluetooth, USB, etc. |
| `chrome://credits` | Shows license information for open-source software or components used by Chrome. |

## Overview & Navigation
These two pages serve as portals for exploring all internal pages.

| Page | Description |
| :--- | :--- |
| `chrome://about` | Lists all internal pages as a navigation hub; click to jump to any. |
| `chrome://chrome-urls` | Same functionality as `chrome://about` – a complete list of all internal pages. |

## Important Notes
- **Risk Warning**: Modifying experimental features in `chrome://flags` or accessing certain internal pages may affect browser stability, security, or performance. If problems occur, reset the relevant settings promptly.
- **How to Access**: Copy the above URLs into Chrome's address bar and press Enter.

> `chrome://about` or `chrome://chrome-urls` is the best entry point for exploring all internal pages.
"""

SYSTEM_PROMPT_2 = """You are a security analyst.

Given the vulnerability report ({issue content}), identify its shortest concrete attack/reproduction chain and then inspect that chain for user interaction.

Do exactly this:
1. Reply in English; ignore phishing or social-engineering wording, remediation discussion, observations, and expected effects.
2. List only operator actions, desensitizing secrets, paths, URLs, and payloads. A URL navigation or file creation alone is not interaction; mouse clicks, keyboard input/shortcuts, and extension installation are interaction.
3. Output exactly `<attack_chain>`, one `id: action` per line, `</attack_chain>`, `<interaction_steps>`, the matching interaction lines or `0`, and `</interaction_steps>`. Do not add analysis."""

SYSTEM_PROMPT_3 = """You are a security analyst.

Given the user-interaction steps ({issue content}) and the Browser Agent capability manifest below, determine whether every step is feasible.

Do exactly this:
1. Treat an action as feasible only when it can be expressed using the listed Browser Agent primitives and ordinary Chrome UI functionality.
2. Treat unavailable hardware, another physical person, missing credentials, kernel/hypervisor control, or external infrastructure as infeasible.
3. Reply with exactly `1` if all listed actions are feasible; otherwise reply with exactly `0`.

Browser Agent capability manifest:
""" + _CHROME_CAPABILITY_BASE

def send_to_llm(content, system_prompt="", model=None):
    """Call an OpenAI-compatible endpoint configured through environment variables."""
    api_key = os.environ.get("PHASE1_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 PHASE1_API_KEY 环境变量，无法调用大模型。")
    endpoint = os.environ.get("PHASE1_BASE_URL") or os.environ.get("LLM_API_URL") or "https://api.openai.com/v1/chat/completions"
    model = model or os.environ.get("PHASE1_MODEL") or os.environ.get("LLM_MODEL") or "deepseek-ai/DeepSeek-V3"
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"PHASE1_BASE_URL 无效: {endpoint}")
    connection_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = connection_class(parsed.netloc, timeout=int(os.environ.get("PHASE1_TIMEOUT") or os.environ.get("LLM_TIMEOUT", "120")))
    payload = json.dumps({
        "model": model,
        "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
        ]
    })
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    xsrf_token = os.environ.get("XSRF_TOKEN") or os.environ.get("XSRF-TOKEN")
    if xsrf_token:
        headers["X-XSRF-TOKEN"] = xsrf_token
    conn.request("POST", parsed.path or "/v1/chat/completions", payload, headers)
    res = conn.getresponse()
    data = res.read()
    response_str = data.decode("utf-8")

    # 解析 OpenAI 格式的响应
    try:
        response_json = json.loads(response_str)
        if "choices" in response_json and len(response_json["choices"]) > 0:
            choice = response_json["choices"][0]
            if "message" in choice and "content" in choice["message"]:
                return choice["message"]["content"]
        # 如果无法按预期解析，返回原始响应以便排查
        return response_str
    except json.JSONDecodeError:
        return response_str


def txt_files(directory):
    return sorted(path for path in directory.iterdir()
                  if path.is_file() and path.suffix.lower() == ".txt")


def read_text(path):
    return path.read_text(encoding="utf-8")


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def clear_txt_files(directory):
    """Remove only generated text outputs so reruns are deterministic."""
    if directory.exists():
        for path in directory.iterdir():
            if path.is_file() and path.suffix.lower() == ".txt":
                path.unlink()


def _resolve_output_arg(root, value, *, default_base=None):
    """Resolve CLI output paths without nesting cwd-relative paths under input.

    A bare name (the documented default, e.g. stage1) remains relative to
    the input tree. Paths containing a directory component are interpreted
    relative to the caller's working directory, while absolute paths are
    preserved.
    """
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    if len(candidate.parts) == 1:
        return (default_base or root).joinpath(candidate).resolve()
    return (Path.cwd() / candidate).resolve()


def run_stage1(root, platform="chrome", stage1_dir=None, stage2_dir=None, stage3_dir=None):
    """Run the three logical Phase 1 stages and leave selected issues in stage3_dir.

    Stage 2 uses one call that derives the attack/reproduction chain and then
    identifies user-interaction steps from that chain. Stage 3 checks only
    issues whose merged result contains at least one interaction step.
    """
    source_files = txt_files(root)
    if not source_files:
        raise RuntimeError(f"{root} 下没有找到 .txt 文件。")

    # Keep each Phase 1 result in its documented stage directory.
    filtered_dir = Path(stage1_dir) if stage1_dir else root / "stage1"
    chain_dir = Path(stage2_dir) if stage2_dir else root / "stage2"
    interaction_dir = Path(stage3_dir) if stage3_dir else root / "stage3"
    for directory in (filtered_dir, chain_dir, interaction_dir):
        directory.mkdir(parents=True, exist_ok=True)
        clear_txt_files(directory)

    harm_prompt, stage2_prompt, capability_prompt = prompts_for_platform(platform)
    for path in source_files:
        print(f"[Stage 1/3] {path.name}")
        result = send_to_llm(read_text(path), harm_prompt).strip()
        if result == "1":
            shutil.copy2(path, filtered_dir / path.name)

    filtered_files = txt_files(filtered_dir)
    if not filtered_files:
        print("第一阶段没有筛选出 issue。")
        return

    for path in filtered_files:
        print(f"[Stage 2/3] {path.name}: attack chain then user-interaction extraction")
        result = send_to_llm(read_text(path), stage2_prompt).strip()
        if result and result != "0":
            # Stage 2 is the merged attack-chain/interaction stage.
            write_text(chain_dir / path.name, result)

    for path in txt_files(chain_dir):
        print(f"[Stage 3/3] {path.name}")
        # Stage 3 receives interaction steps, not the full attack chain.
        interaction_match = re.search(r"<interaction_steps>\s*(.*?)\s*</interaction_steps>", read_text(path), re.S | re.I)
        interaction = interaction_match.group(1).strip() if interaction_match else read_text(path).strip()
        if not interaction or interaction == "0":
            continue
        result = send_to_llm(interaction, capability_prompt).strip()
        if result == "1":
            shutil.copy2(filtered_dir / path.name, interaction_dir / path.name)

    print(f"第一阶段完成：{len(txt_files(interaction_dir))} 个 issue -> {interaction_dir}")


def main():
    parser = argparse.ArgumentParser(description="Run the three-stage Phase 1 issue-selection pipeline.")
    parser.add_argument("--input-dir", type=Path, default=Path.cwd(),
                        help="Stage-1 issue directory (default: current directory)")
    parser.add_argument("--stage1-dir", default=None, help="Stage 1 harm-filter output directory")
    parser.add_argument("--stage2-dir", default=None, help="Stage 2 attack-chain/interaction output directory")
    parser.add_argument("--stage3-dir", default=None, help="Stage 3 capability-passed output directory")
    parser.add_argument("--platform", choices=("chrome", "ubuntu"), default="chrome",
                        help="Issue family; selects prompts for every stage")
    args = parser.parse_args()

    root = args.input_dir.expanduser().resolve()
    stage_root = root.parent if root.name in {"input", "prepared_input"} else root
    stage1_dir = _resolve_output_arg(stage_root, args.stage1_dir or "stage1")
    stage2_dir = _resolve_output_arg(stage_root, args.stage2_dir or "stage2")
    stage3_dir = _resolve_output_arg(stage_root, args.stage3_dir or "stage3")
    output_dirs = tuple(item for item in (stage1_dir, stage2_dir, stage3_dir) if item is not None)
    if root in output_dirs or len(set(output_dirs)) != len(output_dirs):
        raise ValueError("各输出目录必须互不相同，且不能是输入目录本身。")
    run_stage1(root, platform=args.platform, stage1_dir=stage1_dir, stage2_dir=stage2_dir, stage3_dir=stage3_dir)


if __name__ == "__main__":
    main()
