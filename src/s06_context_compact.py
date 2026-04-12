#!/usr/bin/env python3
"""
s06_context_compact.py - Context Compression Demo
演示三种上下文压缩策略：
1. 大结果输出持久化（完整内容落盘，历史保留预览）
2. 旧工具结果微压缩（只保留最近3个工具结果）
3. 上下文整体压缩（保留关键信息）

使用 OpenAI SDK + DeepSeek 模型，手动处理工具调用
"""

import os
import json
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from openai import OpenAI

# ============ 配置 ============
load_dotenv(override=True)

# 使用 DeepSeek API
# 注意：如果没有设置 DEEPSEEK_API_KEY，交互模式将无法工作，但测试可以正常运行
client = None
MODEL_ID = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

def get_client():
    """延迟初始化客户端，避免在导入时失败"""
    global client
    if client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable is not set")
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1"
        )
    return client

# 压缩阈值（为了测试，设置较低的值）
LARGE_OUTPUT_THRESHOLD = 200  # 大输出阈值（字符数）
CONTEXT_LENGTH_THRESHOLD = 1000  # 上下文长度阈值（字符数）
TOOL_RESULTS_TO_KEEP = 3  # 保留最近N个工具结果
MAX_ITERATIONS = 20  # 每轮对话最大工具调用次数

# 输出目录
OUTPUT_DIR = "/Users/like/Desktop/learn-claude-code/output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============ 日志工具 ============
def log_event(event: str, details: str = ""):
    """记录关键节点日志"""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"\033[90m[{timestamp}] [LOG] {event}\033[0m")
    if details:
        print(f"\033[90m       → {details}\033[0m")


# ============ 工具函数 ============
def run_bash(command: str) -> str:
    """实际执行系统命令的函数"""
    log_event("Tool Execution", f"Command: {command}")
    
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "rm -rf /*"]
    if any(d in command for d in dangerous):
        return "Error: Command is too dangerous to execute."
    
    try:
        import subprocess
        process = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        output = (process.stdout + process.stderr).strip()
        result = output if output else "(command executed with no output)"
        log_event("Tool Result", f"Length: {len(result)} chars")
        return result
    except Exception as e:
        return f"Error executing command: {str(e)}"


def read_file(file_path: str) -> str:
    """读取文件内容"""
    log_event("Tool Execution", f"Reading file: {file_path}")
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        log_event("Tool Result", f"Length: {len(content)} chars")
        return content
    except Exception as e:
        return f"Error reading file: {str(e)}"


def write_file(file_path: str, content: str) -> str:
    """写入文件内容"""
    log_event("Tool Execution", f"Writing file: {file_path}")
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, 'w') as f:
            f.write(content)
        result = f"Successfully wrote {len(content)} chars to {file_path}"
        log_event("Tool Result", result)
        return result
    except Exception as e:
        return f"Error writing file: {str(e)}"


# 工具定义（OpenAI 格式）
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "执行 bash 命令",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "文件内容"}
                },
                "required": ["file_path", "content"]
            }
        }
    }
]

SYSTEM_PROMPT = f"""You are a coding agent.
You have access to bash commands and file operations.
When you need to execute commands, use the available tools.
Current working directory: {os.getcwd()}

EFFICIENCY GUIDELINES:
1. When analyzing multiple files, use BATCH operations instead of individual calls:
   - Use `wc -l file1 file2 file3` instead of separate calls for each file
   - Use `find . -name "*.py" -exec wc -l {{}} +` for bulk operations
   - Use `cat file1 file2 | grep pattern` to search multiple files at once

2. Combine related operations in a single command:
   - `ls -la | grep pattern` instead of listing then filtering separately
   - `head -20 file && tail -20 file` in one bash call

3. Avoid repetitive tool calls:
   - If you need to check multiple files, get the list first, then process in batch
   - Maximum {MAX_ITERATIONS} tool calls per conversation, use them wisely
"""


# ============ 策略1: 大结果输出持久化 ============
def persist_large_output(content: str, prefix: str = "output") -> str:
    """
    将大输出内容持久化到文件，返回预览格式
    
    Args:
        content: 原始输出内容
        prefix: 文件名前缀
    
    Returns:
        压缩后的预览字符串
    """
    if len(content) <= LARGE_OUTPUT_THRESHOLD:
        return content
    
    # 生成文件名
    content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}_{content_hash}.txt"
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    # 写入文件
    with open(filepath, 'w') as f:
        f.write(content)
    
    # 生成预览（保留前100字符）
    preview_lines = content.split('\n')[:5]  # 前5行
    preview = '\n'.join(preview_lines)
    if len(preview) > 150:
        preview = preview[:150] + "..."
    
    # 相对路径
    rel_path = os.path.relpath(filepath, os.getcwd())
    
    log_event("Large Output Persisted", f"Saved to {rel_path}, original length: {len(content)}")
    
    return f"""<persisted-output>
Full output saved to: {rel_path}
Preview:
{preview}
</persisted-output>"""


# ============ 策略2: 旧工具结果微压缩 ============
def compact_old_tool_results(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    压缩旧的工具结果，只保留最近 N 个工具的完整结果
    
    Args:
        messages: 消息历史列表
    
    Returns:
        压缩后的消息列表
    """
    # 找到所有工具相关的消息索引
    tool_indices = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "tool":
            tool_indices.append(i)
    
    if len(tool_indices) <= TOOL_RESULTS_TO_KEEP:
        return messages
    
    # 需要压缩的旧工具结果
    indices_to_compact = tool_indices[:-TOOL_RESULTS_TO_KEEP]
    
    log_event("Compacting Old Tool Results", 
              f"Total tools: {len(tool_indices)}, keeping last {TOOL_RESULTS_TO_KEEP}, compacting {len(indices_to_compact)}")
    
    # 创建新消息列表
    compacted_messages = []
    for i, msg in enumerate(messages):
        if i in indices_to_compact and msg.get("role") == "tool":
            # 压缩这条工具结果
            compacted_msg = msg.copy()
            compacted_msg["content"] = "[Earlier tool result compacted. Re-run the tool if you need full detail.]"
            compacted_messages.append(compacted_msg)
        else:
            compacted_messages.append(msg)
    
    return compacted_messages


# ============ 策略3: 上下文整体压缩（LLM-based） ============
def calculate_context_length(messages: List[Dict[str, Any]]) -> int:
    """计算上下文的总体字符长度"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    total += len(item["text"])
    return total


def format_messages_for_compression(messages: List[Dict[str, Any]]) -> str:
    """将消息历史格式化为文本，用于LLM压缩"""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        
        if role == "system":
            lines.append(f"[System]: {content[:100]}...")
        elif role == "user":
            lines.append(f"[User]: {content}")
        elif role == "assistant":
            if msg.get("tool_calls"):
                # 记录工具调用
                tool_info = []
                for call in msg["tool_calls"]:
                    fn = call.get("function", {})
                    tool_info.append(f"{fn.get('name', 'unknown')}({fn.get('arguments', '{}')})")
                lines.append(f"[Assistant]: Tool calls: {', '.join(tool_info)}")
            if content:
                lines.append(f"[Assistant]: {content}")
        elif role == "tool":
            # 工具结果只保留前100字符
            preview = content[:100] + "..." if len(content) > 100 else content
            lines.append(f"[Tool Result]: {preview}")
    
    return "\n".join(lines)


def llm_based_compress(messages: List[Dict[str, Any]]) -> str:
    """
    使用LLM生成语义摘要
    
    调用模型理解对话历史，生成结构化的关键信息摘要
    """
    # 格式化历史记录
    history_text = format_messages_for_compression(messages)
    
    # 构建压缩提示词
    compression_prompt = f"""You are a context compression assistant. Your task is to analyze the following conversation history and extract the key information that must be preserved for the AI to continue working effectively.

Conversation History:
{history_text}

Please provide a structured summary with the following sections:

1. **Current Goal**: What is the user trying to achieve? (Be specific)

2. **Completed Actions**: What has been done so far? (List key actions)

3. **Key Findings**: What important information was discovered? (Critical insights)

4. **Files/Resources**: What files were accessed or modified? (Full paths if available)

5. **Next Steps**: What needs to be done next? (Pending tasks)

6. **Important Context**: Any constraints, preferences, or critical context to remember?

Be concise but comprehensive. The summary should allow someone to continue the task without re-reading the full history.
"""
    
    log_event("LLM Compression", "Calling model to generate semantic summary...")
    
    try:
        # 调用模型生成摘要
        response = get_client().chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that summarizes conversation history for context compression."},
                {"role": "user", "content": compression_prompt}
            ],
            temperature=0.3,  # 低温度保证稳定性
            max_tokens=1000
        )
        
        summary = response.choices[0].message.content
        log_event("LLM Compression", f"Generated summary: {len(summary)} chars")
        return summary
        
    except Exception as e:
        log_event("LLM Compression Failed", str(e))
        # 降级到简单的文本截断
        return f"[Context Compressed - Fallback]\n\nHistory too long. Last user query: {messages[-1].get('content', '')[:200]}"


def count_conversation_rounds(messages: List[Dict[str, Any]]) -> int:
    """
    计算已经完成的对话轮数
    一轮对话 = 用户输入 + 助手回复（或工具调用）
    """
    rounds = 0
    has_user = False
    
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            has_user = True
        elif role == "assistant" and has_user:
            # 助手回复了，完成一轮
            rounds += 1
            has_user = False
    
    return rounds


def compact_context_if_needed(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    如果上下文过长，使用LLM进行语义压缩
    
    注意：只在至少完成一轮对话后才压缩，避免第一轮就触发
    
    Args:
        messages: 消息历史列表
    
    Returns:
        压缩后的消息列表
    """
    context_length = calculate_context_length(messages)
    conversation_rounds = count_conversation_rounds(messages)
    
    log_event("Context Length Check", 
              f"Current length: {context_length} chars (threshold: {CONTEXT_LENGTH_THRESHOLD}), "
              f"Completed rounds: {conversation_rounds}")
    
    # 条件1: 长度超过阈值
    if context_length < CONTEXT_LENGTH_THRESHOLD:
        return messages
    
    # 条件2: 至少完成一轮对话（避免第一轮就压缩）
    if conversation_rounds < 1:
        log_event("Context Compression Skipped", 
                  f"Length {context_length} exceeds threshold but no completed conversation round yet")
        return messages
    
    log_event("Context Compression Triggered", 
              f"Length {context_length} exceeds threshold {CONTEXT_LENGTH_THRESHOLD}, "
              f"completed {conversation_rounds} rounds")
    
    # 使用LLM生成语义摘要
    summary = llm_based_compress(messages)
    
    # 重建消息历史
    compressed_messages = []
    
    # 保留系统消息
    system_msg = None
    for msg in messages:
        if msg.get("role") == "system":
            system_msg = msg
            break
    
    if system_msg:
        compressed_messages.append(system_msg)
    
    # 添加LLM生成的摘要作为用户消息
    compressed_messages.append({
        "role": "user",
        "content": f"[Context Compressed by LLM]\n\n{summary}\n\n[Note: Full conversation history has been compressed. Refer to persisted outputs if specific details are needed.]"
    })
    
    # 添加最后一条用户消息保持上下文连贯
    user_messages = [m for m in messages if m.get("role") == "user"]
    if user_messages:
        last_user_msg = user_messages[-1]
        # 避免重复添加相同内容
        if last_user_msg.get("content") not in summary:
            compressed_messages.append(last_user_msg)
    
    log_event("Context Compressed", f"Reduced from {len(messages)} messages to {len(compressed_messages)} messages using LLM")
    
    return compressed_messages


# ============ 核心 Agent 循环 ============
class CompactAgent:
    """带上下文压缩功能的 Agent"""
    
    def __init__(self):
        self.messages: List[Dict[str, Any]] = []
        self.tool_call_count = 0
        
    def add_system_message(self):
        """添加系统消息"""
        self.messages.append({
            "role": "system",
            "content": SYSTEM_PROMPT
        })
    
    def process_tool_result(self, result: str) -> str:
        """处理工具结果，应用大输出压缩策略"""
        return persist_large_output(result, prefix=f"tool_result_{self.tool_call_count}")
    
    def apply_compaction_strategies(self):
        """应用所有压缩策略"""
        log_event("Applying Compaction Strategies")
        
        # 策略2: 旧工具结果微压缩
        self.messages = compact_old_tool_results(self.messages)
        
        # 策略3: 上下文整体压缩
        self.messages = compact_context_if_needed(self.messages)
    
    def call_model(self) -> Dict[str, Any]:
        """调用模型"""
        log_event("Calling Model", f"Messages: {len(self.messages)}")
        
        response = get_client().chat.completions.create(
            model=MODEL_ID,
            messages=self.messages,
            tools=TOOLS,
            tool_choice="auto"
        )
        
        return response
    
    def handle_tool_calls(self, response) -> bool:
        """
        处理工具调用
        
        Returns:
            bool: 是否执行了工具调用
        """
        message = response.choices[0].message
        
        # 如果没有工具调用，直接返回
        if not message.tool_calls:
            return False
        
        # 添加助手消息（包含工具调用）到历史
        assistant_msg = {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                } for tc in message.tool_calls
            ]
        }
        self.messages.append(assistant_msg)
        
        # 执行每个工具调用
        for tool_call in message.tool_calls:
            self.tool_call_count += 1
            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            
            print(f"\033[33m[Tool Call] {function_name}({arguments})\033[0m")
            
            # 执行工具
            if function_name == "run_bash":
                result = run_bash(arguments["command"])
                # 策略1: 只对 run_bash 的大输出进行压缩
                processed_result = self.process_tool_result(result)
            elif function_name == "read_file":
                result = read_file(arguments["file_path"])
                # read_file 的结果不压缩，让模型能看到完整内容
                processed_result = result
            elif function_name == "write_file":
                result = write_file(arguments["file_path"], arguments["content"])
                processed_result = result
            else:
                result = f"Unknown function: {function_name}"
                processed_result = result
            
            # 添加工具结果到历史
            tool_msg = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": processed_result
            }
            self.messages.append(tool_msg)
        
        return True
    
    def run_turn(self, user_input: str) -> str:
        """运行一个完整的对话回合
        
        流程:
        1. 先压缩历史（不包含当前用户输入）
        2. 添加当前用户输入
        3. 调用模型处理
        4. 添加助手回复
        """
        # 步骤1: 先压缩历史（不包含当前用户输入）
        self.apply_compaction_strategies()
        
        # 步骤2: 添加当前用户输入
        self.messages.append({
            "role": "user",
            "content": user_input
        })
        
        max_iterations = MAX_ITERATIONS
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            log_event(f"Iteration {iteration}/{max_iterations}")
            
            # 调用模型
            response = self.call_model()
            
            # 处理工具调用
            if self.handle_tool_calls(response):
                # 有工具调用，继续循环
                continue
            
            # 没有工具调用，返回最终回复
            final_message = response.choices[0].message
            content = final_message.content or "(no response)"
            
            # 添加助手回复到历史
            self.messages.append({
                "role": "assistant",
                "content": content
            })
            
            return content
        
        return "Reached maximum iterations without completion."
    
    def print_history(self):
        """打印当前消息历史并保存到文件"""
        # 生成完整历史文本
        lines = []
        lines.append("="*80)
        lines.append("CURRENT MESSAGE HISTORY")
        lines.append("="*80)
        lines.append(f"Total messages: {len(self.messages)}")
        lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("="*80)
        
        for i, msg in enumerate(self.messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", None)
            tool_call_id = msg.get("tool_call_id", None)
            
            lines.append(f"\n[{i}] ROLE: {role.upper()}")
            
            if tool_call_id:
                lines.append(f"    TOOL_CALL_ID: {tool_call_id}")
            
            if tool_calls:
                lines.append(f"    TOOL_CALLS:")
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    lines.append(f"      - {fn.get('name', 'unknown')}({fn.get('arguments', '{}')})")
            
            lines.append(f"    CONTENT:")
            if isinstance(content, str):
                # 保留完整内容，不截断
                for line in content.split('\n'):
                    lines.append(f"      {line}")
            else:
                lines.append(f"      {content}")
            lines.append("-"*80)
        
        full_history = '\n'.join(lines)
        
        # 保存到文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"history_{timestamp}.txt"
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(full_history)
        
        # 同时在终端打印摘要
        print("\n" + "="*60)
        print("CURRENT MESSAGE HISTORY (Summary)")
        print("="*60)
        for i, msg in enumerate(self.messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 100:
                content = content[:100] + "..."
            print(f"[{i}] {role.upper()}: {content}")
        print("="*60)
        print(f"\nFull history saved to: {filepath}")
        print(f"Total messages: {len(self.messages)}\n")


# ============ 主程序 ============
def interactive_mode():
    """交互模式"""
    agent = CompactAgent()
    agent.add_system_message()
    
    print("\n" + "="*60)
    print("Interactive Mode (type 'exit' to quit, 'history' to view history)")
    print("="*60 + "\n")
    
    while True:
        try:
            user_input = input("\033[36muser >> \033[0m").strip()
            
            if user_input.lower() in ["exit", "quit", "q"]:
                print("\033[31mExiting. Goodbye!\033[0m")
                break
            
            if user_input.lower() == "history":
                agent.print_history()
                continue
            
            if not user_input:
                continue
            
            print("\033[90mProcessing...\033[0m")
            response = agent.run_turn(user_input)
            print(f"\n\033[32mAssistant: {response}\033[0m\n")
            
        except KeyboardInterrupt:
            print("\n\033[31mInterrupted. Goodbye!\033[0m")
            break
        except Exception as e:
            print(f"\n\033[31mError: {e}\033[0m")


# ============ 使用示例 ============
"""
使用示例:

1. 启动交互模式:
   poetry run python src/s06_context_compact.py

2. 测试大输出持久化:
   输入: 列出当前目录的所有文件详情
   （会产生大输出，观察是否被保存到 output/ 目录）

3. 测试多轮工具调用:
   输入: 读取 README.md 文件，然后读取 pyproject.toml 文件
   （观察旧工具结果是否被压缩）

4. 测试上下文整体压缩:
   连续进行多轮对话，超过 1000 字符阈值后会触发 LLM 压缩
   （观察日志中的 "Context Compression Triggered"）

5. 查看历史:
   输入: history
   （打印当前消息历史）

6. 退出:
   输入: exit
"""

if __name__ == "__main__":
    interactive_mode()
