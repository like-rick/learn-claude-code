#!/usr/bin/env python3
"""
s04_subagent.py - 父子 Agent 架构演示
手动工具调用版本，展示父 Agent 如何调用子 Agent

核心概念:
- 子 Agent: 只有基础文件操作工具 (read_file, write_file, edit_file)
- 父 Agent: 在子 Agent 基础上增加 task 工具，可以创建子 Agent 执行复杂任务
"""
import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types

# 1. 加载配置
load_dotenv(override=True)

# 2. 初始化模型
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_ID = os.getenv("MODEL_ID", "gemini-2.5-flash")

# ============ 基础工具函数 ============

def read_file(file_path: str) -> str:
    """读取文件内容"""
    print(f"  \033[33m[read_file] {file_path}\033[0m")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except Exception as e:
        return f"Error: {str(e)}"


def write_file(file_path: str, content: str) -> str:
    """写入文件内容"""
    print(f"  \033[33m[write_file] {file_path}\033[0m")
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote {len(content)} chars to {file_path}"
    except Exception as e:
        return f"Error: {str(e)}"


def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """编辑文件内容（替换字符串）"""
    print(f"  \033[33m[edit_file] {file_path}\033[0m")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        if old_string not in content:
            return f"Error: old_string not found in file"
        content = content.replace(old_string, new_string)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully edited {file_path}"
    except Exception as e:
        return f"Error: {str(e)}"


# ============ 子 Agent 核心 ============

# 子 Agent 的系统提示词 - 专注于文件操作
SUBAGENT_SYSTEM = """You are a sub-agent specialized in file operations.
Your ONLY capabilities are:
1. read_file - Read file contents
2. write_file - Create or overwrite files
3. edit_file - Modify existing files

WORKFLOW:
1. Analyze the task you received
2. Use the appropriate file tools to complete it
3. Report back the result

IMPORTANT:
- You do NOT have bash or other tools
- Focus ONLY on file operations
- Be concise in your response"""

# 子 Agent 可用的工具列表
SUBAGENT_TOOLS = [read_file, write_file, edit_file]


def run_subagent(task_description: str) -> str:
    """
    运行子 Agent 执行特定任务
    
    这是手动工具调用的核心实现:
    1. 构建子 Agent 的上下文（系统提示 + 任务）
    2. 循环调用模型，检查是否需要工具调用
    3. 如果有工具调用，执行工具并将结果返回给模型
    4. 直到模型生成最终回复
    """
    print(f"\n\033[94m[SubAgent] Starting task: {task_description[:60]}...\033[0m")
    
    # 初始化对话历史
    history = [
        types.Content(
            role="user",
            parts=[types.Part(text=f"Task: {task_description}")]
        )
    ]
    
    # 手动工具调用循环
    max_iterations = 10
    for iteration in range(max_iterations):
        # 调用模型生成内容
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=history,
            config={
                "tools": SUBAGENT_TOOLS,
                "system_instruction": SUBAGENT_SYSTEM,
                # 关键：禁用自动工具调用，让我们手动控制
                "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True)
            }
        )
        
        # 检查是否有工具调用
        if response.candidates and response.candidates[0].content:
            content = response.candidates[0].content
            
            # 检查是否有 function_call（Gemini 使用 function_call 而不是 tool_call）
            has_function_call = False
            if content.parts:
                for part in content.parts:
                    if hasattr(part, 'function_call') and part.function_call:
                        has_function_call = True
                        fc = part.function_call
                        tool_name = fc.name
                        tool_args = dict(fc.args) if fc.args else {}
                        
                        print(f"  \033[35m[Tool Call] {tool_name}({json.dumps(tool_args)})\033[0m")
                        
                        # 执行对应的工具函数
                        result = ""
                        if tool_name == "read_file":
                            result = read_file(**tool_args)
                        elif tool_name == "write_file":
                            result = write_file(**tool_args)
                        elif tool_name == "edit_file":
                            result = edit_file(**tool_args)
                        else:
                            result = f"Error: Unknown tool {tool_name}"
                        
                        # 将模型的 function_call 添加到历史
                        history.append(content)
                        
                        # 构建 FunctionResponse 返回给模型
                        # 注意：必须使用 role="user"，Gemini 要求 function_response 作为 user 消息
                        func_response = types.FunctionResponse(
                            name=tool_name,
                            response={"result": result}
                        )
                        # 如果 function_call 有 id，需要传递回去用于匹配
                        if hasattr(fc, 'id') and fc.id:
                            func_response.id = fc.id
                        
                        history.append(types.Content(
                            role="user",
                            parts=[types.Part(function_response=func_response)]
                        ))
                        break
            
            if not has_function_call:
                # 没有工具调用，子 Agent 完成任务
                result_text = response.text or "Task completed"
                print(f"  \033[92m[SubAgent Done] {result_text[:80]}...\033[0m\n")
                return result_text
        else:
            # 没有有效内容
            return "Error: No valid response from subagent"
    
    return "Error: Max iterations reached"


# ============ 父 Agent 核心 ============

# 父 Agent 的系统提示词 - 包含 task 工具的使用说明
PARENT_SYSTEM = """You are a parent agent that can delegate tasks to sub-agents.

AVAILABLE TOOLS:
1. read_file - Read file contents
2. write_file - Create or overwrite files  
3. edit_file - Modify existing files
4. task - Delegate complex tasks to a sub-agent

WHEN TO USE task TOOL:
- Use it for complex file operations that require multiple steps
- Use it when you need to create/modify multiple related files
- Use it to parallelize independent tasks

WORKFLOW:
1. Analyze user request
2. For simple file operations: use read_file/write_file/edit_file directly
3. For complex tasks: use task tool to delegate to sub-agent
4. Report the final result to user

IMPORTANT:
- The task tool creates a NEW sub-agent with its own context
- Sub-agents can only do file operations
- Be specific in task descriptions"""


def task(description: str) -> str:
    """
    创建子 Agent 执行复杂任务
    
    Args:
        description: 任务描述，要具体明确
    
    Returns:
        子 Agent 的执行结果
    """
    print(f"\033[96m[Parent] Delegating to sub-agent: {description[:50]}...\033[0m")
    # 调用子 Agent 执行
    return run_subagent(description)


# 父 Agent 可用的工具列表（包含 task）
PARENT_TOOLS = [read_file, write_file, edit_file, task]


def run_parent_agent():
    """
    运行父 Agent 主循环
    
    这也是手动工具调用的实现，与 run_subagent 类似
    但多了一个 task 工具可以创建子 Agent
    """
    history = []
    print("\033[32mParent Agent Ready (Type 'exit' to quit)\033[0m")
    print("\033[90mParent has tools: read_file, write_file, edit_file, task\033[0m")
    print("\033[90mSub-agent has tools: read_file, write_file, edit_file\033[0m\n")
    
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
        
        # 手动工具调用循环
        max_iterations = 15
        for iteration in range(max_iterations):
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=history,
                config={
                    "tools": PARENT_TOOLS,
                    "system_instruction": PARENT_SYSTEM,
                    "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True)
                }
            )
            
            # 检查是否有工具调用
            if response.candidates and response.candidates[0].content:
                content = response.candidates[0].content
                has_function_call = False
                
                if content.parts:
                    for part in content.parts:
                        if hasattr(part, 'function_call') and part.function_call:
                            has_function_call = True
                            fc = part.function_call
                            tool_name = fc.name
                            tool_args = dict(fc.args) if fc.args else {}
                            
                            print(f"\033[35m[Tool Call] {tool_name}({json.dumps(tool_args)})\033[0m")
                            
                            # 执行对应的工具函数
                            result = ""
                            if tool_name == "read_file":
                                result = read_file(**tool_args)
                            elif tool_name == "write_file":
                                result = write_file(**tool_args)
                            elif tool_name == "edit_file":
                                result = edit_file(**tool_args)
                            elif tool_name == "task":
                                # task 工具会调用 run_subagent
                                result = task(**tool_args)
                            else:
                                result = f"Error: Unknown tool {tool_name}"
                            
                            # 将模型的 function_call 添加到历史
                            history.append(content)
                            
                            # 构建 FunctionResponse
                            func_response = types.FunctionResponse(
                                name=tool_name,
                                response={"result": result}
                            )
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
                        print(f"\033[32mParent: {response.text}\033[0m")
                    history.append(content)
                    break
            else:
                if response.text:
                    print(f"\033[32mParent: {response.text}\033[0m")
                break
        else:
            print("\033[31mWarning: Max iterations reached\033[0m")


if __name__ == "__main__":
    run_parent_agent()
