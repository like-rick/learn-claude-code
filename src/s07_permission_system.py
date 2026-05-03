#!/usr/bin/env python3
# Harness: safety -- the pipeline between intent and execution.
"""
s07_permission_system.py - Permission System
Every tool call passes through a permission pipeline before execution.
Teaching pipeline:
  1. deny rules
  2. mode check
  3. allow rules
  4. ask user
This version intentionally teaches three modes first:
  - default
  - plan
  - auto
That is enough to build a real, understandable permission system without
burying readers under every advanced policy branch on day one.
Key insight: "Safety is a pipeline, not a boolean."
"""

from dotenv import load_dotenv
from openai import OpenAI
import os
from pathlib import Path
import re
from fnmatch import fnmatch
import json
import subprocess

#加载当前项目环境的环境变量，覆盖系统环境变量
load_dotenv(override=True)

#当前工作目录
WORKDIR = Path.cwd()
# 当前使用的模型ID，默认为"deepseek-chat"，可以通过环境变量"MODEL_ID"进行覆盖
MODEL = os.getenv("MODEL_ID", "deepseek-chat")
# 创建deepseek的OpenAI客户端实例
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)
#权限系统的三种模式：默认、计划和自动
MODES = ("default", "plan", "auto")

# 读写工具权限
# plan模式只允许读
READ_ONLY_TOOLS = {"read_file", "bash_readonly"}
WRITE_TOOLS = {"write_file", "edit_file", "bash"}


#检查bash命令是否包含潜在的危险模式
class BashSecurityValidator:
    VALIDATORS = [
        ("shell_metachar", r"[;&|`$]"),
        ("sudo", r"\bsudo\b"),
        ("rm_rf", r"\brm\s+(-[a-zA-Z]*)?r"),
        ("cmd_substitution", r"\$\("),
        ("ifs_injection", r"\bIFS\s*="),
    ]

    # 看看当前的bash命令是否在VALIDATORS中匹配，如果匹配则返回失败的规则名称和模式
    def validate(self, command):
        failures = []
        for name, pattern in self.VALIDATORS:
            if re.search(pattern,command):
                failures.append((name, pattern))
        return failures
    
    def describe_failures(self, command: str):
        failures = self.validate(command)
        if not failures:
            return "No issues detected"
        return "Security flags: " + ", ".join(
            f"{n} (pattern: {p})" for n, p in failures
        )
    
# 初始化一个bash安全验证器实例，用于后续的权限检查
bash_validator = BashSecurityValidator()

# 默认的检查规则，比如：
# 如果调用bash工具，执行的bash内容是 "rm -rf /", 那么就拒接执行；
# 如果调用bash工具，执行的bash内容包含 "sudo *", 那么也拒绝执行；
# 如果调用read_file工具，访问任何路径都允许执行。
DEFAULT_RULES = [
    {"tool": "bash", "content": "rm -rf /", "behavior": "deny"},
    {"tool": "bash", "content": "sudo *", "behavior": "deny"},
    {"tool": "read_file", "path": "*", "behavior": "allow"},
]

# 权限管理工具
class PermissionManager:
    # 初始化权限管理器，接受模式和规则列表作为参数，如果没有提供规则，则使用默认规则
    def __init__(self, mode="default", rules=None):
        self.mode = mode
        self.rules = rules or list(DEFAULT_RULES)
        self.max_consecutive_denials = 3  # 熔断阈值
        self.consecutive_denials = 0  # 连续拒绝计数器
    
    # 检查工具调用是否被允许执行，返回一个包含是否允许和理由的字典
    # 检查优先级：bash > deny > mode check > allow > ask
    def check(self, tool_name, tool_input):
        # 如果是bash命令，那么需要检查tool_input的command是否合法
        if tool_name == "bash":
            cmd = tool_input.get("command", "")
            failures = bash_validator.validate(cmd)
            if failures:
                # 如果是sudo，rm rf 这些危险操作，直接拒绝
                severe = {"sudo", "rm_rf"}
                if any(f[0] in severe for f in failures):
                    desc = bash_validator.describe_failures(cmd)
                    return {"behavior": "deny",
                            "reason": f"Bash validator: {desc}"}
                desc = bash_validator.describe_failures(cmd)
                return {"behavior": "ask",
                        "reason": f"Bash validator flagged: {desc}"}
        
        # deny规则校验
        for rule in self.rules:
            if rule["behavior"] != 'deny':
                continue
            # 如果是deny规则，并且匹配了当前的工具调用，那么直接拒绝执行，并给出匹配的规则作为理由
            if self._matches(rule, tool_name, tool_input):
                return {"behavior": "deny", "reason": f"Matched deny rule: {rule}"}
        
        # mode check
        # plan模式检查，只允许读工具，拒绝写工具
        if self.mode == "plan": 
            if tool_name in WRITE_TOOLS:
                return {"behavior": "deny", "reason": f"Mode 'plan' does not allow write tools like {tool_name}"}
            return {"behavior": "allow", "reason": f"Mode 'plan' allows read-only tool {tool_name}"}
        
        # auto模式检查，自动允许read-only工具，其他工具交给后续规则检查
        if self.mode == "auto":
            if tool_name in READ_ONLY_TOOLS or tool_name == "read_file":
                return {"behavior": "allow",
                        "reason": "Auto mode: read-only tool auto-approved"}
            pass  # 其他工具继续走后续规则检查

        # allow规则校验
        for rule in self.rules:
            if rule["behavior"] != "allow":
                continue
            if self._matches(rule, tool_name, tool_input):
                # 如果是allow规则，并且匹配了当前的工具调用，那么允许执行，并给出匹配的规则作为理由，同时重置连续拒绝计数器
                self.consecutive_denials = 0
                return {"behavior": "allow",
                        "reason": f"Matched allow rule: {rule}"}
            
        # 其他情况，询问用户是否允许执行，并给出没有匹配规则的理由
        return {"behavior": "ask",
                "reason": f"No rule matched for {tool_name}, asking user"}
    
    # 询问用户是否同意工具执行
    def ask_user(self, tool_name, tool_input):
        preview = json.dumps(tool_input, ensure_ascii=False)[:200]
        print(f"\n  [Permission] {tool_name}: {preview}")
        try:
            answer = input("  Allow? (y/n/always): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        
        # 如果输入always，那么就添加一条新的allow规则到规则列表中，允许这个工具调用的所有情况，并重置连续拒绝计数器
        if answer == "always":
            self.rules.append({"tool": tool_name, "path": "*", "behavior": "allow"})
            self.consecutive_denials = 0
            return True

        # 如果输入y或者yes，那么就允许执行，并重置连续拒绝计数器
        if answer in ("y", "yes"):
            self.consecutive_denials = 0
            return True

                # ✅ 熔断计数（必须存在）
        self.consecutive_denials += 1

        # ✅ 熔断提示（必须存在）
        if self.consecutive_denials >= self.max_consecutive_denials:
            print(f"  [{self.consecutive_denials} consecutive denials -- "
                  "consider switching to plan mode]")

        return False

    # 根据规则列表，检查当前工具调用+工具调用内容，是否匹配
    def _matches(self, rule, tool_name, tool_input):
        if rule.get("tool") and rule["tool"] != "*":
            if rule["tool"] != tool_name:
                return False
        # 举例来说，如果规则是 {"tool": "read_file", "path": "*", "behavior": "allow"}，而当前工具调用是 read_file + {"path": "/etc/passwd"},
        # 那么就匹配了这个规则，返回True，外部在调用的时候发现allow匹配上了，就应该允许执行
        if "path" in rule and rule["path"] != "*":
            path = tool_input.get("path", "")
            if not fnmatch(path, rule["path"]):
                return False
        # 举例来说，如果规则是 {"tool": "bash", "content": "rm -rf /", "behavior": "deny"}，而当前工具调用是 bash + {"command": "rm -rf /"},
        # 那么就匹配了这个规则，返回True，外部在调用的时候发现deny匹配上了，就应该拒绝执行
        if "content" in rule:
            command = tool_input.get("command", "")
            if not fnmatch(command, rule["content"]):
                return False

        return True

            
#TOOLS定义
# 1. bash工具：运行shell命令，参数是一个字符串类型的command
def run_bash(command):
    r = subprocess.run(command, shell=True, cwd=WORKDIR,
                       capture_output=True, text=True, timeout=120)
    return (r.stdout + r.stderr).strip()[:50000]

# 2. read_file工具：读取文件内容，参数是一个字符串类型的path
def run_read(path, limit):
    lines = (WORKDIR / path).read_text().splitlines()
    if limit and limit < len(lines):
        lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
    return "\n".join(lines)[:50000]

# 3. write_file工具：写入内容到文件，参数是一个字符串类型的path和content
def run_write(path, content):
    fp = (WORKDIR / path)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content)
    return f"Wrote {len(content)} bytes"

# 4. edit_file工具：编辑文件内容，参数是一个字符串类型的path、old_text和new_text，功能是将文件中第一次出现的old_text替换为new_text
def run_edit(path: str, old_text: str, new_text: str) -> str:
    fp = WORKDIR / path
    content = fp.read_text()
    if old_text not in content:
        return f"Error: Text not found in {path}"
    fp.write_text(content.replace(old_text, new_text, 1))
    return f"Edited {path}"

# 工具名称到处理函数的映射字典，方便后续根据工具名称调用对应的处理函数
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}

# 工具定义
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run shell command",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit file by replacing text",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"}
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
]


SYSTEM = f"""You are a coding agent at {WORKDIR}. Use tools to solve tasks.
The user controls permissions. Some tool calls may be denied."""

def agent_loop(messages, perms):
    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM}] + messages,
            tools=TOOLS,  # type: ignore
        )

        msg = response.choices[0].message

        # 无 tool 调用
        if not msg.tool_calls:
            if msg.content:
                print(msg.content)
            return
        
        # 有 tool 调用，先拼接工具调用信息（必须带上 tool_calls，否则 API 报错：
        # "Messages with role 'tool' must be a response to a preceding message with 'tool_calls'"）
        tool_calls_data = []
        for tc in msg.tool_calls:
            tool_calls_data.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                }
            })
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": tool_calls_data
        })

        results = []

        for tc in msg.tool_calls:
            if tc.type != "function" or not hasattr(tc, "function") or not tc.function:
                print(f"  [ERROR] Unsupported tool call type: {tc.type}")
                continue
            tool_name = tc.function.name 
            tool_input = json.loads(tc.function.arguments or "{}") 
            decision = perms.check(tool_name, tool_input)

            if decision["behavior"] == "deny":
                output = f"Permission denied: {decision['reason']}"
                print(f"  [DENIED] {tool_name}: {decision['reason']}")

            elif decision["behavior"] == "ask":
                if perms.ask_user(tool_name, tool_input):
                    handler = TOOL_HANDLERS.get(tool_name)
                    if handler:
                        output = handler(**tool_input)
                        print(f"> {tool_name}: {str(output)[:200]}")
                    else:
                        output = f"Unknown tool: {tool_name}"
                        print(f"  [ERROR] {tool_name}: {output}")
                else:
                    output = f"Permission denied by user for {tool_name}"
                    print(f"  [USER DENIED] {tool_name}")

            else:
                handler = TOOL_HANDLERS.get(tool_name)
                if handler:
                    output = handler(**tool_input)
                    print(f"> {tool_name}: {str(output)[:200]}")
                else:
                    output = f"Unknown tool: {tool_name}"
                    print(f"  [ERROR] {tool_name}: {output}")

            results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(output),
            })

        messages.extend(results)

if __name__ == "__main__":
    # Choose permission mode at startup
    print("Permission modes: default, plan, auto")
    mode_input = input("Mode (default): ").strip().lower() or "default"
    if mode_input not in MODES:
        mode_input = "default"
    perms = PermissionManager(mode=mode_input)
    print(f"[Permission mode: {mode_input}]")

    history = []

    while True:
        try:
            query = input("\033[36ms07 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        if query.strip().lower() in ("q", "exit", ""):
            break

        history.append({"role": "user", "content": query})
        agent_loop(history, perms)
        print()