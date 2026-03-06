import asyncio
import os
import sys
import json
import re
from contextlib import AsyncExitStack
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from openai import AsyncOpenAI

SYSTEM_PROMPT = """You are an autonomous AI engineering assistant. Your goal is to accomplish the task given by the user.

CRITICAL INSTRUCTIONS:
1. THINK STEP-BY-STEP: Before taking action, outline the logical steps needed to accomplish the task.
2. USE TOOLS NATIVELY: You have access to a dynamically updating set of tools. You MUST use the native JSON tool calling format provided by the API. 
   **DO NOT** write raw XML tags like `<tool_call>`, `<function>`, or markdown code blocks for tools. Use the actual function calling mechanism.
3. SELF-EVOLVE: If you are asked to perform a task but cannot find a suitable tool, you MUST write a new Python MCP server script to accomplish it.
    - Call the `generate_server_code` tool to get a template.
    - Implement the logic.
    - Call `save_and_deploy_tool` to write it to the system.
    - Once deployed, the client will auto-load it, and you can call your newly created tool in the next step.
4. EXCLUDE TEMP FILES: When generating scripts that interact with the file system, ignore temporary files, caches (like __pycache__), and hidden version control directories (like .git).
5. Output final results clearly once the task is complete.
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
        self.exit_stack = AsyncExitStack()
        
        # Configure OpenAI compatible client
        self.llm = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )
        self.model = "your-local-model-name" # Make sure this is a model good at coding/tools (e.g. Qwen2.5-Coder or Llama-3.1)

    def _find_server_scripts(self) -> list[str]:
        if not os.path.exists(self.integrations_dir):
            os.makedirs(self.integrations_dir, exist_ok=True)

        scripts = []
        for root, dirs, files in os.walk(self.integrations_dir):
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
            if server_name in self.sessions:
                continue 
            
            new_servers_found = True
            print(f"[System] Booting new server: '{server_name}'...")
            
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
                
                self.sessions[server_name] = session
                
                response = await session.list_tools()
                for tool in response.tools:
                    self.tool_registry[tool.name] = server_name
                    self.mcp_tools[tool.name] = tool
                    
                print(f"[+] Connected to '{server_name}' ({len(response.tools)} tools)")
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
                temperature=0.1 # Lowered temp so it hallucinates less formatting
            )

            message = response.choices[0].message
            messages.append(message)

            content_text = message.content or ""
            if content_text:
                print(f"\n[Agent Thought]\n{content_text}")

            # Check if the model actually triggered the API's tool feature
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        args = {} # Fallback if model gives bad JSON
                        
                    result = await self.execute_tool(tool_call.function.name, args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": result
                    })
                continue # Loop again so the agent can read the tool result

            # If no native tool calls, check if the model hallucinated fake XML tools
            if "<tool_call>" in content_text or "<function>" in content_text:
                print("\n[System Warning] Model attempted to use text-based XML tools instead of native JSON.")
                # Force the model to retry
                messages.append({
                    "role": "user",
                    "content": "SYSTEM ERROR: You attempted to call a tool using raw text/XML tags. You MUST use the proper JSON tool calling format provided by the API. Please try again."
                })
                continue # Loop again to give the model a second chance

            # If no tool calls and no fake XML, the agent considers the task finished
            print("\n[System] Task Complete or No More Actions.")
            break

    async def run(self):
        async with self.exit_stack:
            await self.connect_to_new_servers()
            await self.run_agent_loop()