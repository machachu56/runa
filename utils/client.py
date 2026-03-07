import asyncio
import os
import sys
import json
import re
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from openai import AsyncOpenAI
import datetime

current_time = datetime.datetime.now().strftime("%d %B %Y, %H:%M:%S")

# PROMPT UPDATED: See Step 3 for the new Standard vs Complex task logic.
SYSTEM_PROMPT = f"""You are an autonomous AI engineering assistant. Your goal is to accomplish the task given by the user and create new tools if you're unable to provide the information the user is asking for.
Today is {current_time}
CRITICAL INSTRUCTIONS:
1. THINK STEP-BY-STEP: Before taking action, outline the logical steps needed to accomplish the task.
2. USE TOOLS NATIVELY: You have access to a dynamically updating set of tools. You MUST use the native JSON tool calling format provided by the API. 
   **DO NOT** write raw XML tags like `<tool_call>`, `<function>`, or markdown code blocks for tools. Use the actual function calling mechanism.
3. SELF-EVOLVE & FIX EXISTING TOOLS: If you need a new capability or if a tool execution fails, assess the complexity:
    - FIRST: Call `list_integration_files` to check if a relevant script already exists.
    - STANDARD/LOCAL TASKS: If the task involves local OS interactions (e.g., file creation, desktop wallpaper, moving files) or easily written scripts using Python's standard libraries (`os`, `sys`, `ctypes`, `shutil`, `pathlib`), DO NOT search GitHub. Write the tool directly using `generate_server_code` and deploy it with `save_and_deploy_tool`.
    - COMPLEX/EXTERNAL TASKS: If the task requires heavy external integrations, web APIs, or parsing complex formats, call `search_github_python_libraries` using ONLY essential keywords (e.g., search "duckduckgo" instead of the full context).
    - EXPLORE AND LEARN: If you cloned a repo, use `list_directory` to explore its structure, then `read_local_file` to read the `README.md` and relevant `.py` files to learn its usage.
    - TOOL GENERATION: Finally, use `save_and_deploy_tool` to build your tool. The generated template handles `pip install` when the tool boots up.
4. CACHE-FILES: When analyzing files or generating scripts, always ignore temporary files and caches (like `__pycache__`) and residuals.
5. CORRELATE MULTIPLE SOURCES: When gathering data from different tool calls, scripts, or files, actively cross-reference and synthesize the information. Do not treat tool outputs in isolation.
6. DEPENDENCIES: Newly generated tools include a top-level `while True` try/except block for imports. If your tool needs external pip packages, place the `import` statements INSIDE that try block so they are automatically resolved at runtime. Make sure all print statements in the auto-installer redirect to sys.stderr!
7. Output final results clearly once the task is complete.
"""

class AutonomousMCPClient:
    def __init__(self, base_url, model, task: str, api_key = "x", integrations_dir: str = "integrations"):
        self.integrations_dir = integrations_dir
        self.task = task
        self.base_url = base_url
        self.api_key = api_key
        
        self.sessions = {}       
        self.tool_registry = {}  
        self.mcp_tools = {}
        self.script_mtimes = {}      
        
        # Task-based management to avoid anyio context crashes
        self.server_tasks = {} 
        self.server_shutdown_events = {} 
        
        # Configure OpenAI compatible client
        self.llm = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )
        self.model = model

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

    async def _diagnose_script(self, script_path: str) -> str | None:
        """Runs the script briefly to catch syntax, import, or boot errors."""
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, script_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Send empty EOF to stdin. A healthy MCP server will exit cleanly.
            stdout, stderr = await asyncio.wait_for(proc.communicate(input=b""), timeout=5.0)
            
            # If it crashed, extract the Python traceback
            if proc.returncode != 0:
                err_text = stderr.decode('utf-8').strip()
                return err_text if err_text else "Unknown crash (Return code non-zero)"
            
            # Check for stdout pollution
            out_text = stdout.decode('utf-8').strip()
            if out_text and not out_text.startswith('{'):
                return f"STDOUT POLLUTION DETECTED: The script printed non-JSON text to stdout, breaking the MCP protocol.\nPrinted text: {out_text}\nFix: Redirect all print statements to sys.stderr."
                
            return None # The script is healthy!
            
        except asyncio.TimeoutError:
            proc.kill()
            return "Timeout: The script took too long to boot or got stuck in an infinite loop."
        except Exception as e:
            return f"Diagnostic execution failed: {str(e)}"

    async def _run_server(self, server_name: str, script_path: str, current_mtime: float):
        """Runs a single MCP server in a dedicated background task."""
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[script_path],
            env=os.environ.copy()
        )
        
        shutdown_event = asyncio.Event()
        self.server_shutdown_events[server_name] = shutdown_event
        
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    
                    self.sessions[server_name] = session
                    self.script_mtimes[server_name] = current_mtime
                    
                    response = await session.list_tools()
                    for tool in response.tools:
                        self.tool_registry[tool.name] = server_name
                        self.mcp_tools[tool.name] = tool
                        
                    print(f"[+] Successfully connected to '{server_name}' ({len(response.tools)} tools)")
                    
                    await shutdown_event.wait()
                    
        except Exception as e:
            print(f"[-] Server '{server_name}' stopped or crashed: {e}")
        finally:
            self.mcp_tools = {name: tool for name, tool in self.mcp_tools.items() 
                              if self.tool_registry.get(name) != server_name}
            if server_name in self.sessions:
                del self.sessions[server_name]

    async def connect_to_new_servers(self) -> list[str]:
        scripts = self._find_server_scripts()
        boot_errors = []

        for script_path in scripts:
            server_name = os.path.basename(script_path).replace('.py', '')
            current_mtime = os.path.getmtime(script_path)
            
            if server_name in self.sessions:
                last_mtime = self.script_mtimes.get(server_name, 0)
                if current_mtime <= last_mtime:
                    continue 
                else:
                    print(f"[System] Detected updates in '{server_name}'. Reloading...")
                    if server_name in self.server_shutdown_events:
                        self.server_shutdown_events[server_name].set()
                        await asyncio.sleep(0.5) 
            else:
                print(f"[System] Booting new server: '{server_name}'...")
            
            # --- DIAGNOSTIC CHECK ---
            error_output = await self._diagnose_script(script_path)
            if error_output:
                err_msg = f"Failed to boot tool '{server_name}'. Error log:\n{error_output}"
                print(f"[-] {err_msg}")
                boot_errors.append(err_msg)
                
                # Mark as checked so we don't infinitely retry booting a broken script
                self.script_mtimes[server_name] = current_mtime
                continue 

            # If healthy, spawn the task
            task = asyncio.create_task(self._run_server(server_name, script_path, current_mtime))
            self.server_tasks[server_name] = task
                
        return boot_errors

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
        
        if server_name not in self.sessions:
            await asyncio.sleep(0.5)
            if server_name not in self.sessions:
                return f"Error: Server '{server_name}' is not running or crashed during boot."

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
            boot_errors = await self.connect_to_new_servers()
            
            # Inject crash logs back into the AI's mind so it can fix its own bad code
            for error in boot_errors:
                messages.append({
                    "role": "user",
                    "content": f"SYSTEM ALERT: A tool server you created failed to start. Please analyze the error and update the code to fix it.\n\nDetails:\n{error}"
                })

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
        try:
            await self.connect_to_new_servers()
            await self.run_agent_loop()
        finally:
            for event in self.server_shutdown_events.values():
                event.set()
                
            tasks_to_await = [t for t in self.server_tasks.values() if not t.done()]
            if tasks_to_await:
                await asyncio.gather(*tasks_to_await, return_exceptions=True)
            print("[System] All MCP servers shut down cleanly.")