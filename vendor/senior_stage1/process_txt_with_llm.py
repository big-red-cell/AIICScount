import http.client
import json
import os
import shutil
import argparse
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


# Resolve the repository-local configuration from this vendored script location.
# This keeps Stage 1 independent of the caller's working directory and sibling projects.
PROJECT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(PROJECT_ENV_FILE, override=False)

# 自定义 system prompt，为空字符串时不添加 system 消息
SYSTEM_PROMPT_1 = """- Role: Chromium Security Vulnerability Outcome Harm Determination Expert
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

SYSTEM_PROMPT_2 = """reply in English. you are a helpful assistant for analyzing security issues. Analyze the issue I'm about to provide. What you need to do is to help me analyze the reproduction steps for this issue. Note that it's about reproduction, so ignore anything phishing-related or constructed, such as "write a Chrome extension to trick users into installing it". In the reproduction context, it becomes "install an extension". You just need to summarize the simplest reproduction steps. As for things like "observe..." or  environment setup, omit them. Desensitize the information within, for example: change "Fill in javascript://..." to "Fill in the corresponding URL". Focus on "doing..." rather than "achieving the effect of...". Each item must correspond to a specific action, such as "visit..." or "click...", rather than a vague "achieve the effect of...". Your reply should follow the format below: Each line should be in the form: `id: action`, where id starts from 1 and increments, and action describes what needs to be done in that step."""

SYSTEM_PROMPT_3 = "reply in English. you are a helpful assistant for analyzing security issues. Analyze the following steps for reproducing a browser vulnerability and determine whether these steps require user interaction. Our definition of user interaction is as follows: \n 1. Exclude actions that open a URL. For example, if a step is “open https://google.com”, it does not count as requiring user interaction. \n 2. Exclude actions that creates a file. For example, if a step is 'create a file in /home/user ...', it does not count as requiring user interaction. \n 3. Sending keyboard keys or key combinations, or mouse actions — such as Ctrl+C, Ctrl+V, mouse clicks, etc. — all count as requiring user interaction. \n 4. Installing an extension counts as user interaction. Your response format is as follows: If none of the steps require user interaction, reply 0. Otherwise, reply with the steps that do require user interaction, using the original format of each line as id: action. do not reply your analysis or summary."

SYSTEM_PROMPT_4 = """
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

def send_to_llm(content, system_prompt="", model=None):
    """Call an OpenAI-compatible endpoint configured through environment variables."""
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 LLM_API_KEY 环境变量，无法调用大模型。")
    endpoint = os.environ.get("LLM_API_URL") or "https://api.openai.com/v1/chat/completions"
    model = model or os.environ.get("LLM_MODEL") or "deepseek-ai/DeepSeek-V3"
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"LLM_API_URL 无效: {endpoint}")
    connection_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = connection_class(parsed.netloc, timeout=int(os.environ.get("LLM_TIMEOUT", "120")))
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


def legacy_main():
    current_dir = os.getcwd()
    txt_files = [f for f in os.listdir(current_dir) if f.endswith(".txt")]

    if not txt_files:
        print("当前文件夹下没有找到 .txt 文件。")
        return

    filtered_dir = os.path.join(current_dir, "filtered_txt")
    attack_chain_dir = os.path.join(current_dir, "attack_chain_output")  # 新增：step2 输出文件夹
    interaction_dir = os.path.join(current_dir, "interaction_required")  # 新增：step3 输出文件夹
    final_dir = os.path.join(current_dir, "final_selected")  # 第四步输出文件夹

    # step1: 初步筛选
    if 1 in steps_todo:
        os.makedirs(filtered_dir, exist_ok=True)
        for filename in txt_files:
            filepath = os.path.join(current_dir, filename)
            print(f"=== 正在处理文件: {filename} ===")
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()

                print(f"文件内容长度: {len(content)} 字符")
                print("--- 发送到大模型 ---")

                result = send_to_llm(content, SYSTEM_PROMPT_1)
                print("--- 大模型输出 ---")
                print(result)

                if result and result.strip() == "1":
                    shutil.copy2(filepath, filtered_dir)
                    print(f"--- 判定为有害，已复制到 {filtered_dir} ---")
                print("\n")
            except Exception as e:
                print(f"处理文件 {filename} 时出错: {e}")
                print("\n")

    # step2: 获取攻击链，并将结果保存到 attack_chain_output 文件夹
    if 2 in steps_todo:

        if os.path.exists(filtered_dir) and os.listdir(filtered_dir):
            target_dir = filtered_dir
            target_files = [f for f in os.listdir(filtered_dir) if f.endswith(".txt")]

        # 创建 step2 输出文件夹
        os.makedirs(attack_chain_dir, exist_ok=True)

        for filename in target_files:
            filepath = os.path.join(target_dir, filename)
            print(f"=== 正在处理文件: {filename} ===")
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()

                print(f"文件内容长度: {len(content)} 字符")
                print("--- 发送到大模型 ---")

                result = send_to_llm(content, SYSTEM_PROMPT_2)
                print("--- 大模型输出 ---")
                print(result)

                # 新增：保存结果到 attack_chain_output 文件夹，文件名不变
                output_path = os.path.join(attack_chain_dir, filename)
                with open(output_path, "w", encoding="utf-8") as out_f:
                    out_f.write(result)
                print(f"--- 攻击链已保存到: {output_path} ---")
                print("\n")
            except Exception as e:
                print(f"处理文件 {filename} 时出错: {e}")
                print("\n")

    # step3: 从 step2 的输出文件夹读取攻击链，判断是否需要用户交互
    if 3 in steps_todo:
        if not os.path.exists(attack_chain_dir):
            print(f"错误：Step3 需要的攻击链文件夹 '{attack_chain_dir}' 不存在。请先执行 step2。")
            return

        chain_files = [f for f in os.listdir(attack_chain_dir) if f.endswith(".txt")]
        if not chain_files:
            print("攻击链文件夹中没有 .txt 文件，无法执行 step3。")
            return

        os.makedirs(interaction_dir, exist_ok=True)

        for filename in chain_files:
            filepath = os.path.join(attack_chain_dir, filename)
            print(f"=== Step3 正在处理文件: {filename} ===")
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    chain_content = f.read()

                print(f"攻击链内容长度: {len(chain_content)} 字符")
                print("--- 发送到大模型（判断用户交互）---")

                result = send_to_llm(chain_content, SYSTEM_PROMPT_3)
                print("--- 大模型输出 ---")
                print(result)

                # 若非 "0"，则将模型输出写入 interaction_required 文件夹的同名文件
                if result and result.strip() != "0":
                    output_path = os.path.join(interaction_dir, filename)
                    with open(output_path, "w", encoding="utf-8") as out_f:
                        out_f.write(result)
                    print(f"--- 判定需要用户交互，已将模型输出写入 {output_path} ---")
                else:
                    print("--- 判定为不需要用户交互，跳过写入 ---")
                print("\n")
            except Exception as e:
                print(f"处理文件 {filename} 时出错: {e}")
                print("\n")
    # step4: 从 step3 筛选出的文件读取，再经大模型判断，若为 1 则复制第一步同名文件
    if 4 in steps_todo:
        if not os.path.exists(interaction_dir):
            print(f"错误：Step4 需要的交互文件夹 '{interaction_dir}' 不存在。请先执行 step3。")
            return

        interaction_files = [f for f in os.listdir(interaction_dir) if f.endswith(".txt")]
        if not interaction_files:
            print("交互文件夹中没有 .txt 文件，无法执行 step4。")
            return

        os.makedirs(final_dir, exist_ok=True)

        for filename in interaction_files:
            filepath = os.path.join(interaction_dir, filename)
            print(f"=== Step4 正在处理文件: {filename} ===")
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()

                print(f"Step3 输出内容长度: {len(content)} 字符")
                print("--- 发送到大模型（第四步判断）---")

                result = send_to_llm(content, SYSTEM_PROMPT_4)
                print("--- 大模型输出 ---")
                print(result)

                if result and result.strip() == "1":
                    # 确定第一步源文件的位置：优先使用 filtered_txt，若不存在则使用当前目录
                    if os.path.exists(filtered_dir) and os.path.isfile(os.path.join(filtered_dir, filename)):
                        src_path = os.path.join(filtered_dir, filename)
                    else:
                        src_path = os.path.join(current_dir, filename)

                    if os.path.exists(src_path):
                        dest_path = os.path.join(final_dir, filename)
                        shutil.copy2(src_path, dest_path)
                        print(f"--- 判定通过，已将原始文件复制到 {final_dir} ---")
                    else:
                        print(f"警告：未找到原始文件 {filename}，无法复制。")
                else:
                    print("--- 判定为 0，跳过复制 ---")
                print("\n")
            except Exception as e:
                print(f"处理文件 {filename} 时出错: {e}")
                print("\n")

if __name__ == "__main__":
    pass


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


def run_stage1(root, final_dir):
    """Run the original four filters and leave selected issues in final_dir."""
    source_files = txt_files(root)
    if not source_files:
        raise RuntimeError(f"{root} 下没有找到 .txt 文件。")

    filtered_dir = root / ".pipeline_filtered"
    chain_dir = root / ".pipeline_chain"
    interaction_dir = root / ".pipeline_interaction"
    for directory in (filtered_dir, chain_dir, interaction_dir, final_dir):
        directory.mkdir(parents=True, exist_ok=True)
        clear_txt_files(directory)

    for path in source_files:
        print(f"[Stage 1/4] {path.name}")
        result = send_to_llm(read_text(path), SYSTEM_PROMPT_1).strip()
        if result == "1":
            shutil.copy2(path, filtered_dir / path.name)

    filtered_files = txt_files(filtered_dir)
    if not filtered_files:
        print("第一阶段没有筛选出 issue。")
        return

    for path in filtered_files:
        print(f"[Stage 2/4] {path.name}")
        write_text(chain_dir / path.name,
                   send_to_llm(read_text(path), SYSTEM_PROMPT_2))

    for path in txt_files(chain_dir):
        print(f"[Stage 3/4] {path.name}")
        result = send_to_llm(read_text(path), SYSTEM_PROMPT_3).strip()
        if result and result != "0":
            write_text(interaction_dir / path.name, result)

    for path in txt_files(interaction_dir):
        print(f"[Stage 4/4] {path.name}")
        result = send_to_llm(read_text(path), SYSTEM_PROMPT_4).strip()
        if result == "1":
            shutil.copy2(filtered_dir / path.name, final_dir / path.name)

    print(f"第一阶段完成：{len(txt_files(final_dir))} 个 issue -> {final_dir}")


def run_stage2(final_dir, chain_dir):
    """Generate reproduction/attack chains from stage-1 selected issues."""
    files = txt_files(final_dir)
    if not files:
        raise RuntimeError(f"第二阶段输入目录没有 .txt 文件: {final_dir}")
    chain_dir.mkdir(parents=True, exist_ok=True)
    clear_txt_files(chain_dir)
    for path in files:
        print(f"[Stage 2] {path.name}")
        write_text(chain_dir / path.name,
                   send_to_llm(read_text(path), SYSTEM_PROMPT_2))
    print(f"第二阶段完成：{len(files)} 个攻击链 -> {chain_dir}")


def run_stage3(chain_dir, prompt_dir):
    """Turn attack chains into Browser Agent-ready attack prompts."""
    files = txt_files(chain_dir)
    if not files:
        raise RuntimeError(f"第三阶段输入目录没有 .txt 文件: {chain_dir}")
    prompt_dir.mkdir(parents=True, exist_ok=True)
    clear_txt_files(prompt_dir)
    generated = 0
    for path in files:
        print(f"[Stage 3] {path.name}")
        interaction = send_to_llm(read_text(path), SYSTEM_PROMPT_3).strip()
        if not interaction or interaction == "0":
            continue
        capability = send_to_llm(interaction, SYSTEM_PROMPT_4).strip()
        if capability == "1":
            write_text(prompt_dir / path.name, interaction)
            generated += 1
    print(f"第三阶段完成：{generated} 个攻击提示 -> {prompt_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Run the issue-selection and attack-prompt pipeline.")
    parser.add_argument("--input-dir", type=Path, default=Path.cwd(),
                        help="Stage-1 issue directory (default: current directory)")
    parser.add_argument("--stage", choices=("1", "2", "3", "all"), default="all",
                        help="Stage to run (default: all)")
    parser.add_argument("--final-dir", default="final_selected",
                        help="Stage-1 output / Stage-2 input directory")
    parser.add_argument("--chain-dir", default="attack_chain_output",
                        help="Stage-2 output / Stage-3 input directory")
    parser.add_argument("--prompt-dir", default="attack_prompt_output",
                        help="Stage-3 generated attack prompts")
    args = parser.parse_args()

    root = args.input_dir.expanduser().resolve()
    final_dir = (root / args.final_dir).resolve()
    chain_dir = (root / args.chain_dir).resolve()
    prompt_dir = (root / args.prompt_dir).resolve()
    output_dirs = (final_dir, chain_dir, prompt_dir)
    if root in output_dirs or len(set(output_dirs)) != len(output_dirs):
        raise ValueError("三个输出目录必须互不相同，且不能是输入目录本身。")
    if args.stage in {"1", "all"}:
        run_stage1(root, final_dir)
    if args.stage in {"2", "all"}:
        run_stage2(final_dir, chain_dir)
    if args.stage in {"3", "all"}:
        run_stage3(chain_dir, prompt_dir)


if __name__ == "__main__":
    main()
