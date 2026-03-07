import os
import sys
from typing import Callable
from mcp.server.fastmcp import FastMCP
import importlib
import inspect

class RunaMCP:
    """
    An MCP Server that can dynamically generate, read, modify, and save 
    new MCP server scripts to the integrations folder for persistent use.
    """

    def __init__(self, name: str = "RunaMCP", integrations_dir: str = "integrations"):
        self.mcp = FastMCP(name)
        self.integrations_dir = integrations_dir
        
        # Ensure the integrations directory exists
        os.makedirs(self.integrations_dir, exist_ok=True)

        # Register the tools that allow the server to upgrade the system
        self._register_meta_tools()

    def _register_meta_tools(self):
        """
        Registers the tools that allow the server to create and modify tools.
        """

        @self.mcp.tool()
        def list_integration_files() -> list[str]:
            """
            Lists all current python scripts in the integrations folder.
            """
            if not os.path.exists(self.integrations_dir):
                return []
            return [f for f in os.listdir(self.integrations_dir) if f.endswith('.py')]
        
        @self.mcp.tool()
        def search_pypi_packages(query: str, max_results: int = 5) -> str:
            """
            Searches the Python Package Index (PyPI) for libraries based on natural language or keywords.
            Use this to find external libraries to accomplish tasks you don't currently have tools for.
            """
            import urllib.request
            import urllib.parse
            import re
            
            try:
                # Format the search URL
                url = f"https://pypi.org/search/?q={urllib.parse.quote(query)}"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                
                with urllib.request.urlopen(req) as response:
                    html = response.read().decode('utf-8')
                
                # Regex to extract the package snippet from PyPI's HTML structure
                pattern = r'<span class="package-snippet__name">([^<]+)</span>.*?<span class="package-snippet__version">([^<]+)</span>.*?<p class="package-snippet__description">([^<]*)</p>'
                matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
                
                if not matches:
                    return f"No packages found on PyPI for query: '{query}'"
                
                results = ["Found the following packages on PyPI:"]
                for i, match in enumerate(matches[:max_results]):
                    name, version, desc = [m.strip() for m in match]
                    results.append(f"{i+1}. Package: '{name}' (v{version}) - Description: {desc}")
                
                return "\n".join(results)
                
            except Exception as e:
                return f"Error searching PyPI: {str(e)}"
        
        @self.mcp.tool()
        def read_installed_module_code(module_name: str) -> str:
            """
            Reads the actual source code of an installed Python module or package.
            Use this to inspect library internals, verify available methods, or debug failed imports.
            
            Args:
                module_name: The dot-separated module path (e.g., 'os', 'mcp.server.fastmcp', 'requests.models').
            """
            try:
                # Dynamically import the requested module
                module = importlib.import_module(module_name)
                
                # Attempt to retrieve the source code
                source = inspect.getsource(module)
                return source
                
            except ModuleNotFoundError:
                return f"Error: Module '{module_name}' is not installed or cannot be found in the current environment."
                
            except TypeError:
                # This exception triggers if the target is a built-in module (C extension) 
                # where raw Python source code is not available.
                try:
                    file_path = inspect.getfile(module)
                    return f"Error: '{module_name}' is a compiled/built-in module. Source code cannot be read directly as text. File located at: {file_path}"
                except TypeError:
                    return f"Error: '{module_name}' is a built-in module (like 'sys'). Source code is not accessible."
                    
            except Exception as e:
                return f"Error reading module '{module_name}': {str(e)}"

        @self.mcp.tool()
        def read_server_code(server_name: str) -> str:
            """
            Reads the content of an existing MCP server script. 
            Use this to understand existing code before making modifications.
            """
            if server_name == "autoupgrade" or server_name == os.path.splitext(os.path.basename(__file__))[0]:
                return f"Error: Read access to the core '{server_name}' file is restricted."
                
            file_path = os.path.join(self.integrations_dir, f"{server_name}.py")
            
            if not os.path.exists(file_path):
                return f"Error: File '{server_name}.py' does not exist."
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                return f"Error reading file: {str(e)}"

        @self.mcp.tool()
        def generate_server_code(tool_name: str, tool_description: str) -> str:
            """
            Generates a template for a new standalone FastMCP server script, equipped with auto-install capabilities.
            """
            code = f'''import os
import sys
import subprocess

# Auto-installer for tool dependencies
while True:
    try:
        from mcp.server.fastmcp import FastMCP
        # Add your required module imports here
        break
    except ModuleNotFoundError as e:
        missing_module = e.name
        try:
            print(f"[Auto-Install] Missing dependency '{{missing_module}}'. Installing...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", missing_module])
        except subprocess.CalledProcessError:
            print(f"Failed to install {{missing_module}}")
            sys.exit(1)

mcp = FastMCP("{tool_name}")

@mcp.tool()
def {tool_name}_execute(query: str) -> str:
    """Auto-generated tool for: {tool_description}"""
    # Implement actual logic here
    return f"Execution of {tool_name} with query: {{query}}"

if __name__ == "__main__":
    mcp.run(transport="stdio")
'''
            return code

        @self.mcp.tool()
        def save_and_deploy_tool(server_name: str, code: str) -> str:
            """
            Saves or overwrites the provided Python code as a script in the integrations folder.
            
            Args:
                server_name: The name of the file (without .py extension).
                code: The full Python source code to save.
            """
            if not server_name.isidentifier():
                return f"Error: '{server_name}' is not a valid filename/identifier."
                
            # Strict safeguard against modifying the autoupgrade file or the runtime file
            if server_name == "autoupgrade" or server_name == os.path.splitext(os.path.basename(__file__))[0]:
                return f"Error: Modification of the core '{server_name}' file is strictly prohibited."
                
            if not code:
                return "Error: No code provided."
            
            # Construct the safe file path
            file_name = f"{server_name}.py"
            file_path = os.path.join(self.integrations_dir, file_name)
            
            try:
                # Write the generated code to the integrations folder
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(code)
                
                return f"Success! Tool server saved to {file_path}. It will be picked up by the auto-client on next refresh."
            except Exception as e:
                return f"Error saving file: {str(e)}"

    def run(self):
        """Runs the main self-refining server on stdio."""
        self.mcp.run(transport="stdio")

if __name__ == "__main__":
    # Initialize the Self-Refining Server
    server = RunaMCP(name="RunaMCP")
    server.run()