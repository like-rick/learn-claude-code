#!/usr/bin/env python3
"""
s02_agent_tools.py - The Agent Loop Tools
SDK 自动处理函数调用循环的版本, 多tools
"""
import os
import subprocess
from dotenv import load_dotenv
from google import genai
from google.genai import types

# 1. 加载配置
load_dotenv(override=True)

# 2. 初始化模型
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_ID = os.getenv("MODEL_ID", "gemini-2.5-flash-lite")

SYSTEM = f"""You are a coding agent at {os.getcwd()}.
Your primary capability is executing bash commands to solve tasks.
When the user asks you to do something, you MUST use the bash tool to execute commands.
Do not just describe what to do - actually execute the commands using the bash tool.
Act, don't explain.

IMPORTANT: Only execute the minimum commands necessary to complete the task. 
Do not perform extra verification steps, cleanup, or demonstrations unless explicitly requested."""


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


def read_file(file_path: str) -> str:
    """
    读取并返回文件的内容。
    
    当你需要查看文件内容、检查代码或分析配置文件时使用此工具。
    
    Args:
        file_path: 文件的绝对路径或相对路径。
    
    Returns:
        文件内容字符串，如果出错则返回错误信息。
    """
    print(f"\033[33m[Reading] {file_path}\033[0m")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        print(f"\033[90m[Read {len(content)} chars]\033[0m")
        return content
    except Exception as e:
        return f"Error reading file: {str(e)}"


def write_file(file_path: str, content: str) -> str:
    """
    将内容写入文件。如果文件不存在则创建，存在则覆盖。
    
    当你需要创建新文件或修改现有文件内容时使用此工具。
    
    Args:
        file_path: 文件的绝对路径或相对路径。
        content: 要写入文件的字符串内容。
    
    Returns:
        成功或失败的状态信息。
    """
    print(f"\033[33m[Writing] {file_path}\033[0m")
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote {len(content)} chars to {file_path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"


def agent_tools():
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
        
        # SDK 自动处理函数调用循环
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=history,
            config={
                "tools": [bash, read_file, write_file],
                "system_instruction": SYSTEM,
            },
        )
        
        # 输出最终回复
        if response.text:
            print(f"\033[32mModel: {response.text}\033[0m")
        
        # 将模型回复加入历史
        if response.candidates and response.candidates[0].content:
            history.append(response.candidates[0].content)


if __name__ == "__main__":
    agent_tools()
