import asyncio
import os
import sys
import json
import re
from contextlib import AsyncExitStack
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from openai import AsyncOpenAI
import datetime

current_time = datetime.datetime.now().strftime("%d %B %Y, %H:%M:%S")

SYSTEM_PROMPT = f"""You are an autonomous AI engineering assistant. Your goal is to accomplish the task given by the user and create new tools if you're unable to provide the information the user is asking for.
Today is {current_time}
CRITICAL INSTRUCTIONS:
1. THINK STEP-BY-STEP: Before taking action, outline the logical steps needed to accomplish the task.
2. USE TOOLS NATIVELY: You have access to a dynamically updating set of tools. You MUST use the native JSON tool calling format provided by the API. 
   **DO NOT** write raw XML tags like `<tool_call>`, `<function>`, or markdown code blocks for tools. Use the actual function calling mechanism.
3. SELF-EVOLVE & FIX EXISTING TOOLS: If you need a new capability or if a tool execution fails:
    - FIRST: Call `list_integration_files` to check if a relevant script already exists.
    - IF A TOOL FAILS DUE TO LIBRARY/API ERRORS: Immediately call `read_installed_module_code` to inspect the actual installed library source code. Rely on the real environment's code rather than your pre-trained knowledge to fix the API usage.
    - IF AN EXISTING TOOL FAILS: Do not create a duplicate file (e.g., `tool_v2.py`). Instead, call `read_server_code` to read the failing script, find the bug, and use `save_and_deploy_tool` to OVERWRITE and fix the exact same file.
    - IF NO TOOL EXISTS: Call `generate_server_code` to get a template, implement the logic, and call `save_and_deploy_tool` to create it.
4. CACHE-FILES: Always ignore temporary files, caches (like `__pycache__`), and hidden version control folders.
5. CORRELATE MULTIPLE SOURCES: When gathering data from different tool calls, scripts, or files, actively cross-reference and synthesize the information. Do not treat tool outputs in isolation. Piece the data together to form a complete, accurate picture and resolve any discrepancies before taking your next step.
6. DEPENDENCIES: Newly generated tools include a top-level `while True` try/except block for imports. If your tool needs external pip packages, place the `import` statements INSIDE that try block so they are automatically resolved at runtime.
7. Output final results clearly once the task is complete.
"""

class AutonomousMCPClient:
    def __init__(self, base_url, task: str, api_key = "x", integrations_dir: str = "integrations"):
        self.integrations_dir = integrations_dir
        self.task = task
        self.base_url = base_url
        self.api_key = api_key
        self.sessions = {}       
        self.tool_registry = {}  
        self.mcp_tools = {}
        self.script_mtimes = {}      
        self.exit_stack = AsyncExitStack()
        
        # Configure OpenAI compatible client
        self.llm = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )
        self.model = "your-local-model-name" 

    def _find_server_scripts(self) -> list[str]:
        if not os.path.exists(self.integrations_dir):
            os.makedirs(self.integrations_dir, exist_ok=True)

        scripts = []
        for root, dirs, files in os.walk(self.integrations_dir):
            # Ignore hidden directories (like .git) and caches
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
            for file in files:
                if file.endswith('.py') and not file.startswith('.'):
                    scripts.append(os.path.join(root, file))
        return scripts

    async def connect_to_new_servers(self):
        scripts = self._find_server_scripts()
        new_servers_found = False

        for script_path in scripts:
            server_name = os.path.basename(script_path).replace('.py', '')
            current_mtime = os.path.getmtime(script_path)
            
            # Check if server is running AND hasn't been modified
            if server_name in self.sessions:
                last_mtime = self.script_mtimes.get(server_name, 0)
                if current_mtime <= last_mtime:
                    continue # Skip only if the file hasn't changed
                else:
                    print(f"[System] Detected updates in '{server_name}'. Reloading...")
                    new_servers_found = True
            else:
                print(f"[System] Booting new server: '{server_name}'...")
                new_servers_found = True
            
            server_params = StdioServerParameters(
                command=sys.executable,
                args=[script_path],
                env=os.environ.copy()
            )

            try:
                stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
                read, write = stdio_transport
                
                session = await self.exit_stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                
                # Update our dictionaries with the new session and the latest modification time
                self.sessions[server_name] = session
                self.script_mtimes[server_name] = current_mtime
                
                response = await session.list_tools()
                for tool in response.tools:
                    self.tool_registry[tool.name] = server_name
                    self.mcp_tools[tool.name] = tool
                    
                print(f"[+] Successfully connected to '{server_name}' ({len(response.tools)} tools)")
            except Exception as e:
                print(f"[-] Failed to connect to '{server_name}': {e}")
                
        return new_servers_found

    def get_openai_tools_schema(self) -> list[dict]:
        openai_tools = []
        for tool_name, tool in self.mcp_tools.items():
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema
                }
            })
        return openai_tools

    async def execute_tool(self, tool_name: str, args_dict: dict) -> str:
        if tool_name not in self.tool_registry:
            return f"Error: Tool '{tool_name}' not found."

        server_name = self.tool_registry[tool_name]
        session = self.sessions[server_name]

        print(f"[Agent] Calling tool '{tool_name}' with args: {args_dict}")
        try:
            result = await session.call_tool(tool_name, arguments=args_dict)
            text_outputs = [content.text for content in result.content if content.type == "text"]
            output = "\n".join(text_outputs)
            print(f"[Tool Result] {output}")
            return output
        except Exception as e:
            error_msg = f"Error executing {tool_name}: {str(e)}"
            print(f"[-] {error_msg}")
            return error_msg

    async def run_agent_loop(self):
        print(f"\n--- Starting Autonomous Task ---\nTask: {self.task}\n")
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self.task}
        ]

        while True:
            await self.connect_to_new_servers()
            tools_schema = self.get_openai_tools_schema()

            print("[System] Waiting for LLM thinking...")
            
            response = await self.llm.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools_schema if tools_schema else None,
                temperature=0.1 
            )

            message = response.choices[0].message
            messages.append(message)

            content_text = message.content or ""
            if content_text:
                print(f"\n[Agent Thought]\n{content_text}")

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        args = {} 
                        
                    result = await self.execute_tool(tool_call.function.name, args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": result
                    })
                continue 

            if "<tool_call>" in content_text or "<function>" in content_text:
                print("\n[System Warning] Model attempted to use text-based XML tools instead of native JSON.")
                messages.append({
                    "role": "user",
                    "content": "SYSTEM ERROR: You attempted to call a tool using raw text/XML tags. You MUST use the proper JSON tool calling format provided by the API. Please try again."
                })
                continue 

            print("\n[System] Task Complete or No More Actions.")
            break

    async def run(self):
        async with self.exit_stack:
            await self.connect_to_new_servers()
            await self.run_agent_loop()