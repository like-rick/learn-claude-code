#!/usr/bin/env python3
"""
s05_agent_skills.py - Skills 系统演示
手动工具调用版本，展示如何渐进式加载自定义 skills

核心概念:
1. 注册 skills: 扫描 .qoder/skills 目录，发现可用的 skill
2. 加载 skills: 用户选择要加载的 skill
3. 读取 YAML 元数据: 解析 skill 的元信息（名称、描述等）
4. 读取完整内容: 将 skill 内容注入到系统提示词中

Skills 目录结构:
.qoder/skills/
  └── skill-name/
      └── SKILL.md  (包含 YAML frontmatter + markdown 内容)
"""
import os
import json
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types

# 1. 加载配置
load_dotenv(override=True)

# 2. 初始化模型
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_ID = os.getenv("MODEL_ID", "gemini-2.5-flash")

# ============ 全局状态 ============
# 存储已加载的 skills
_loaded_skills = {}

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


# ============ Skills 系统核心 ============

def parse_yaml_frontmatter(content: str) -> tuple[dict, str]:
    """
    解析 YAML frontmatter
    
    Args:
        content: skill 文件的完整内容
        
    Returns:
        (metadata_dict, markdown_content)
        
    Example:
        ---
        name: python-style
        description: Python coding style guide
        ---
        # Python Style Guide
        ...
    """
    # 匹配 --- 开头和结尾的 YAML frontmatter
    pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
    match = re.match(pattern, content, re.DOTALL)
    
    if not match:
        # 没有 frontmatter，返回空元数据和原始内容
        return {}, content
    
    yaml_text = match.group(1)
    markdown_content = match.group(2)
    
    # 简单解析 YAML（只处理 key: value 格式）
    metadata = {}
    for line in yaml_text.strip().split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            metadata[key.strip()] = value.strip()
    
    return metadata, markdown_content


def list_skills() -> str:
    """
    列出所有可用的 skills
    
    扫描 .qoder/skills 目录，返回所有 skill 的名称和描述
    """
    print(f"  \033[33m[list_skills] scanning .qoder/skills\033[0m")
    
    skills_dir = ".qoder/skills"
    if not os.path.exists(skills_dir):
        return "No skills directory found. Create .qoder/skills/ to add skills."
    
    skills = []
    for item in os.listdir(skills_dir):
        skill_path = os.path.join(skills_dir, item)
        if os.path.isdir(skill_path):
            # 检查是否有 SKILL.md 文件
            skill_file = os.path.join(skill_path, "SKILL.md")
            if os.path.exists(skill_file):
                content = read_file(skill_file)
                metadata, _ = parse_yaml_frontmatter(content)
                name = metadata.get('name', item)
                description = metadata.get('description', 'No description')
                skills.append(f"- {name}: {description}")
    
    if not skills:
        return "No skills found in .qoder/skills/"
    
    return "Available skills:\n" + "\n".join(skills)


def load_skill(skill_name: str) -> str:
    """
    加载指定的 skill
    
    Args:
        skill_name: skill 的名称（对应目录名或 YAML 中的 name 字段）
        
    加载过程:
    1. 读取 SKILL.md 文件
    2. 解析 YAML frontmatter 获取元数据
    3. 保存到 _loaded_skills
    4. 返回加载结果
    """
    print(f"  \033[33m[load_skill] {skill_name}\033[0m")
    
    skills_dir = ".qoder/skills"
    skill_path = os.path.join(skills_dir, skill_name, "SKILL.md")
    
    if not os.path.exists(skill_path):
        return f"Error: Skill '{skill_name}' not found at {skill_path}"
    
    # 读取 skill 文件
    content = read_file(skill_path)
    if content.startswith("Error:"):
        return content
    
    # 解析元数据和内容
    metadata, markdown_content = parse_yaml_frontmatter(content)
    
    # 保存到全局状态
    _loaded_skills[skill_name] = {
        "metadata": metadata,
        "content": markdown_content
    }
    
    name = metadata.get('name', skill_name)
    description = metadata.get('description', 'No description')
    
    return f"Successfully loaded skill: {name}\nDescription: {description}"


def get_loaded_skills_context() -> str:
    """
    获取已加载 skills 的上下文
    
    将所有已加载的 skill 内容合并，用于注入系统提示词
    """
    if not _loaded_skills:
        return ""
    
    context_parts = ["\n\n=== LOADED SKILLS ===\n"]
    for skill_name, skill_data in _loaded_skills.items():
        metadata = skill_data["metadata"]
        content = skill_data["content"]
        name = metadata.get('name', skill_name)
        context_parts.append(f"\n--- {name} ---\n{content}\n")
    
    return "\n".join(context_parts)


# ============ Agent 核心 ============

def build_system_prompt() -> str:
    """
    构建系统提示词
    
    基础提示词 + 已加载 skills 的上下文
    """
    base_system = """You are a coding agent with skill loading capabilities.

AVAILABLE TOOLS:
1. read_file - Read file contents
2. write_file - Create or overwrite files  
3. edit_file - Modify existing files
4. list_skills - List all available skills in .qoder/skills/
5. load_skill - Load a specific skill to enhance your capabilities

SKILL SYSTEM:
- Skills are stored in .qoder/skills/<skill-name>/SKILL.md
- Each skill has YAML frontmatter (name, description) + markdown content
- Use list_skills to see available skills
- Use load_skill to load skills you need
- Loaded skills are injected into your system prompt

WORKFLOW:
1. If user mentions a specific domain (e.g., "write Python code"), check if relevant skills exist
2. Use list_skills to see available skills
3. Use load_skill to load relevant skills
4. Complete the task using the enhanced knowledge

IMPORTANT:
- Load skills proactively when relevant to the task
- Skills provide domain-specific knowledge and guidelines"""

    # 动态注入已加载的 skills
    skills_context = get_loaded_skills_context()
    
    return base_system + skills_context


# Agent 可用的工具列表
AGENT_TOOLS = [read_file, write_file, edit_file, list_skills, load_skill]


def run_agent_skill():
    """
    运行 Agent 主循环
    
    手动工具调用实现，支持 skills 的动态加载
    """
    history = []
    print("\033[32mAgent Ready with Skills Support (Type 'exit' to quit)\033[0m")
    print("\033[90mAvailable tools: read_file, write_file, edit_file, list_skills, load_skill\033[0m")
    print("\033[90mSkills directory: .qoder/skills/\033[0m\n")
    
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
            # 每次调用都重新构建系统提示词（包含最新加载的 skills）
            system_prompt = build_system_prompt()
            
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=history,
                config={
                    "tools": AGENT_TOOLS,
                    "system_instruction": system_prompt,
                    # 关键：禁用自动工具调用，让我们手动控制
                    "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True)
                }
            )
            
            # 检查是否有工具调用
            if response.candidates and response.candidates[0].content:
                content = response.candidates[0].content
                has_function_call = False
                
                if content.parts:
                    for part in content.parts:
                        # Gemini 使用 function_call 而不是 tool_call
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
                            elif tool_name == "list_skills":
                                result = list_skills()
                            elif tool_name == "load_skill":
                                result = load_skill(**tool_args)
                            else:
                                result = f"Error: Unknown tool {tool_name}"
                            
                            # 将模型的 function_call 添加到历史
                            history.append(content)
                            
                            # 构建 FunctionResponse 返回给模型
                            # 注意：Gemini 要求 function_response 作为 user 消息
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
                    # 没有工具调用，生成最终回复
                    if response.text:
                        print(f"\033[32mAgent: {response.text}\033[0m")
                    history.append(content)
                    break
            else:
                if response.text:
                    print(f"\033[32mAgent: {response.text}\033[0m")
                break
        else:
            print("\033[31mWarning: Max iterations reached\033[0m")


# ============ 示例 Skill 创建工具 ============

def create_example_skill():
    """
    创建一个示例 skill，用于演示
    """
    skill_dir = ".qoder/skills/python-style"
    os.makedirs(skill_dir, exist_ok=True)
    
    skill_content = """---
name: python-style
description: Python coding style guide for clean code
---

# Python Style Guide

## Naming Conventions

- Use `snake_case` for functions and variables
- Use `PascalCase` for class names
- Use `UPPER_CASE` for constants

## Code Structure

- Keep functions under 50 lines when possible
- Use type hints for function parameters
- Add docstrings for all public functions

## Example

```python
def calculate_total(items: list[dict]) -> float:
    \"\"\"Calculate total price of items.\"\"\"
    return sum(item["price"] for item in items)
```
"""
    
    skill_path = os.path.join(skill_dir, "SKILL.md")
    with open(skill_path, 'w', encoding='utf-8') as f:
        f.write(skill_content)
    
    print(f"\033[90mCreated example skill: {skill_path}\033[0m")


if __name__ == "__main__":
    # 创建示例 skill（如果不存在）
    create_example_skill()
    
    # 运行 Agent
    run_agent_skill()
