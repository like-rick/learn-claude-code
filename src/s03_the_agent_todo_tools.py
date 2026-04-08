#!/usr/bin/env python3
"""
s03_agent_todo_tools.py - The Agent Loop Todo Tools
SDK 自动处理函数调用循环的版本
"""
import os
import subprocess
import json

from dotenv import load_dotenv
from google import genai
from google.genai import types

# 全局任务列表存储
_todo_list = []
_todo_id_counter = 0

# 1. 加载配置
load_dotenv(override=True)

# 2. 初始化模型
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_ID = os.getenv("MODEL_ID", "gemini-2.5-flash")

SYSTEM = f"""You are a coding agent at {os.getcwd()}.
You have access to tools: bash, todo_write, todo_read.

WORKFLOW - FOLLOW THIS EXACT SEQUENCE:
1. Receive user request
2. Call todo_write to create task list and mark first task as IN_PROGRESS
3. Call bash to execute the IN_PROGRESS task
4. Call todo_write to mark task as COMPLETE and next as IN_PROGRESS
5. Repeat steps 3-4 until all tasks are COMPLETE
6. Only then provide final summary

EXAMPLE - User asks "create a hello.py file":
→ todo_write([{{"id": "1", "content": "Create hello.py", "status": "IN_PROGRESS"}}])
→ bash("echo 'print(\\\"Hello\\\")' > hello.py")
→ todo_write([{{"id": "1", "content": "Create hello.py", "status": "COMPLETE"}}])
→ Final response: "Created hello.py"

ABSOLUTE RULES:
1. NEVER output code or describe what you would do - ALWAYS call tools
2. Do not say "I will..." or "Let me..." - just call the tools
3. After todo_write, IMMEDIATELY call bash to execute (no waiting, no asking)
4. Continue calling tools until ALL tasks are COMPLETE
5. Only stop when there are no more IN_PROGRESS tasks

IMPORTANT: Only execute the minimum commands necessary. 
Do not perform extra verification steps unless requested."""


def run_bash(command: str) -> str:
    """实际执行系统命令的函数"""
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot"]
    if any(d in command for d in dangerous):
        return "Error: Command is too dangerous to execute."
    try:
        process = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=120
        )
        output = (process.stdout + process.stderr).strip()
        return output if output else "(command executed with no output)"
    except Exception as e:
        return f"Error executing command: {str(e)}"


def bash(command: str) -> str:
    """在当前工作目录执行 bash 命令。"""
    print(f"\033[33m[Executing] $ {command}\033[0m")
    result = run_bash(command)
    print(f"\033[90m[Output] {result[:200]}{'...' if len(result) > 200 else ''}\033[0m")
    return result


def todo_write(todos_json: str) -> str:
    """
    创建或更新任务列表。强制单任务执行：任何时候最多只能有一个 IN_PROGRESS 任务。
    
    关键规则：
    - 如果当前已有 IN_PROGRESS 任务，必须先完成它（设为 COMPLETE）才能开始新任务
    - 这防止模型在多步任务中丢失进度、重复工作或跳步
    
    Args:
        todos_json: JSON 字符串，格式示例：
        [
            {"id": "1", "content": "分析需求", "status": "COMPLETE"},
            {"id": "2", "content": "修改代码", "status": "IN_PROGRESS"},
            {"id": "3", "content": "测试验证", "status": "PENDING"}
        ]
        status 可选值: PENDING, IN_PROGRESS, COMPLETE, CANCELLED
    
    Returns:
        当前任务列表状态，或错误信息（如果违反单任务规则）
    """
    global _todo_list, _todo_id_counter
    
    print(f"\033[33m[TodoWrite] 更新任务列表\033[0m")
    
    try:
        new_todos = json.loads(todos_json)
        
        # 验证格式
        if not isinstance(new_todos, list):
            return "Error: todos_json must be a JSON array"
        print(f"\033[90m[new_todos] {new_todos}\033[0m")
        # 检查是否有超过一个 IN_PROGRESS
        in_progress_count = sum(1 for t in new_todos if t.get("status") == "IN_PROGRESS")
        if in_progress_count > 1:
            # 找到当前正在进行的任务
            current_in_progress = [t for t in _todo_list if t.get("status") == "IN_PROGRESS"]
            current_task = current_in_progress[0] if current_in_progress else None
            current_task_info = f"当前进行中的任务: '{current_task['content']}' (id: {current_task['id']})" if current_task else ""
            
            return f"Error: 只能有一个 IN_PROGRESS 任务！{current_task_info}\n请先完成或取消当前任务，再开始新任务。"
        
        # 更新任务列表
        _todo_list = new_todos
        
        # 生成状态摘要
        status_summary = []
        for t in _todo_list:
            icon = {"PENDING": "○", "IN_PROGRESS": "●", "COMPLETE": "✓", "CANCELLED": "✗"}.get(t.get("status"), "?")
            status_summary.append(f"  {icon} [{t.get('status')}] {t.get('content')}")
        
        result = "任务列表已更新:\n" + "\n".join(status_summary) if status_summary else "任务列表已清空"
        print(f"\033[90m{result}\033[0m")
        return result
        
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON format - {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


def todo_read() -> str:
    """
    读取当前任务列表状态。
    
    Returns:
        当前所有任务及其状态的格式化列表
    """
    print(f"\033[33m[TodoRead] 读取任务列表\033[0m")
    
    if not _todo_list:
        return "当前没有任务"
    
    status_summary = []
    for t in _todo_list:
        icon = {"PENDING": "○", "IN_PROGRESS": "●", "COMPLETE": "✓", "CANCELLED": "✗"}.get(t.get("status"), "?")
        status_summary.append(f"  {icon} [{t.get('status')}] {t.get('content')}")
    
    result = "当前任务列表:\n" + "\n".join(status_summary)
    print(f"\033[90m{result}\033[0m")
    return result


def agent_todo_tools():
    history = []
    print("\033[32mAgent Ready (Type 'exit' to quit)\033[0m")
    
    while True:
        user_input = input("\033[36muser >> \033[0m").strip()
        if user_input.lower() in ["exit", "quit", "q"]:
            print("\033[31mExiting. Goodbye!\033[0m")
            break
        
        # 添加用户消息到历史
        history.append(types.Content(
            role="user",
            parts=[types.Part(text=user_input)]
        ))
        
        # 手动循环处理工具调用，直到模型生成最终回复
        max_iterations = 10
        for iteration in range(max_iterations):
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=history,
                config={
                    "tools": [bash, todo_write, todo_read],
                    "system_instruction": SYSTEM,
                },
            )
            
            # 检查是否有工具调用
            if response.candidates and response.candidates[0].content:
                content = response.candidates[0].content
                has_function_call = False
                
                # 检查是否有 function_call
                if content.parts:
                    for part in content.parts:
                        if hasattr(part, 'function_call') and part.function_call:
                            has_function_call = True
                            fc = part.function_call
                            tool_name = fc.name
                            tool_args = dict(fc.args) if fc.args else {}
                            
                            print(f"\033[35m[Tool Call] {tool_name}({tool_args})\033[0m")
                            
                            # 执行对应的工具函数
                            result = ""
                            if tool_name == "bash":
                                result = bash(**tool_args)
                            elif tool_name == "todo_write":
                                result = todo_write(**tool_args)
                            elif tool_name == "todo_read":
                                result = todo_read(**tool_args)
                            else:
                                result = f"Error: Unknown tool {tool_name}"
                            
                            # 将工具结果添加到历史
                            history.append(content)  # 添加模型的 function_call
                            
                            # 构建 FunctionResponse，包含 id 字段用于匹配
                            func_response = types.FunctionResponse(
                                name=tool_name,
                                response={"result": result}
                            )
                            # 如果 function_call 有 id，需要设置到 FunctionResponse
                            if hasattr(fc, 'id') and fc.id:
                                func_response.id = fc.id
                            
                            history.append(types.Content(
                                role="user",
                                parts=[types.Part(function_response=func_response)]
                            ))
                            break
                
                if not has_function_call:
                    # 没有工具调用，生成最终回复
                    if response.text:
                        print(f"\033[32mModel: {response.text}\033[0m")
                    history.append(content)
                    break
            else:
                # 没有有效内容
                if response.text:
                    print(f"\033[32mModel: {response.text}\033[0m")
                break
        else:
            print("\033[31mWarning: Max iterations reached\033[0m")


if __name__ == "__main__":
    agent_todo_tools()
