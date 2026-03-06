import os
import sys
from typing import Callable
from mcp.server.fastmcp import FastMCP

class RunaMCP:
    """
    An MCP Server that can dynamically generate and save new MCP server scripts
    to the integrations folder for persistent use.
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
        Registers the tools that allow the server to create new tools.
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
        def generate_server_code(tool_name: str, tool_description: str) -> str:
            """
            Generates a template for a new standalone FastMCP server script.
            """
            # Fixed the f-string by removing the curly braces around @mcp.tool()
            code = f'''from mcp.server.fastmcp import FastMCP

mcp = FastMCP("{tool_name}")

@mcp.tool()
def {tool_name}_execute(query: str) -> str:
    """Auto-generated tool for: {tool_description}"""
    # TODO: Implement actual logic here
    return f"Execution of {tool_name} with query: {{query}}"

if __name__ == "__main__":
    mcp.run(transport="stdio")
'''
            return code

        @self.mcp.tool()
        def save_and_deploy_tool(server_name: str, code: str) -> str:
            """
            Saves the provided Python code as a new script in the integrations folder.
            
            Args:
                server_name: The name of the file (without .py extension).
                code: The full Python source code to save.
            """
            if not server_name.isidentifier():
                return f"Error: '{server_name}' is not a valid filename/identifier."
                
            if not code:
                return "Error: No code provided."
            
            # Construct the safe file path
            file_name = f"{server_name}.py"
            file_path = os.path.join(self.integrations_dir, file_name)
            
            try:
                # Write the generated code to the integrations folder
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(code)
                
                return f"Success! New tool server saved to {file_path}. It will be picked up by the auto-client on next refresh."
            except Exception as e:
                return f"Error saving file: {str(e)}"

    def run(self):
        """Runs the main self-refining server on stdio."""
        self.mcp.run(transport="stdio")

if __name__ == "__main__":
    # Initialize the Self-Refining Server
    server = RunaMCP(name="RunaMCP")
    server.run()