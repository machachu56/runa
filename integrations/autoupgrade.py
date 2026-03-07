import os
import sys
from typing import Callable
from mcp.server.fastmcp import FastMCP

class RunaMCP:
    """
    An MCP Server that can dynamically generate, read, modify, and save 
    new MCP server scripts to the integrations folder for persistent use.
    """

    def __init__(self, name: str = "RunaMCP", integrations_dir: str = "integrations"):
        self.mcp = FastMCP(name)
        self.integrations_dir = integrations_dir
        
        # Ensure the integrations and cloned_repos directories exist
        os.makedirs(self.integrations_dir, exist_ok=True)
        os.makedirs("cloned_repos", exist_ok=True)

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
        def search_github_python_libraries(query: str, max_results: int = 20) -> str:
            """
            Searches GitHub for Python repositories based on natural language or keywords.
            Use this to find external libraries to accomplish tasks you don't currently have tools for.
            Results are sorted by stars to prioritize popular, community-trusted repositories.
            """
            import urllib.request
            import urllib.parse
            import json
            
            try:
                encoded_query = urllib.parse.quote(f"{query} language:python")
                url = f"https://api.github.com/search/repositories?q={encoded_query}&sort=stars&order=desc&per_page={max_results}"
                
                req = urllib.request.Request(url, headers={'User-Agent': 'Runa-Autonomous-Agent'})
                
                with urllib.request.urlopen(req) as response:
                    data = json.loads(response.read().decode('utf-8'))
                
                items = data.get("items", [])
                
                if not items:
                    return f"No Python repositories found on GitHub for query: '{query}'"
                
                results = ["Found the following Python repositories on GitHub (sorted by stars):"]
                for i, repo in enumerate(items):
                    name = repo.get("full_name", "Unknown")
                    stars = repo.get("stargazers_count", 0)
                    desc = repo.get("description", "No description provided.")
                    repo_url = repo.get("html_url", "No URL")
                    
                    results.append(f"{i+1}. Repository: '{name}' (⭐ {stars} stars)\n   Description: {desc}\n   URL: {repo_url}")
                
                return "\n\n".join(results)
                
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    return "Error: GitHub API rate limit exceeded. Please wait a minute before trying again."
                return f"HTTP Error searching GitHub: {e.code} - {e.reason}"
            except Exception as e:
                return f"Error searching GitHub: {str(e)}"
            
        @self.mcp.tool()
        def clone_github_repository(repo_url: str) -> str:
            """
            Downloads and extracts a GitHub repository to a local 'cloned_repos' directory to inspect its source code.
            Use this to download libraries you want to analyze before building a tool.
            """
            import os
            import urllib.request
            import zipfile
            import io
            import shutil

            if not repo_url.startswith("https://github.com/"):
                return "Error: Invalid GitHub URL."
            
            clean_url = repo_url.rstrip("/")
            if clean_url.endswith('.git'):
                clean_url = clean_url[:-4]
                
            parts = clean_url.split('/')
            if len(parts) < 2:
                return "Error: Cannot parse owner and repository name from URL."
                
            owner, repo_name = parts[-2], parts[-1]
            target_dir = os.path.join("cloned_repos", repo_name)
            
            # If already cloned, skip and return success
            if os.path.exists(target_dir):
                return (f"Repository already exists at '{target_dir}'.\n\n"
                        f"Next step: Use `list_directory` on '{target_dir}' to see its files.")
            
            print(f"[System] Downloading repository {owner}/{repo_name} via GitHub API...")
            
            # Use GitHub API to get the zipball of the default branch
            zip_url = f"https://api.github.com/repos/{owner}/{repo_name}/zipball"
            req = urllib.request.Request(zip_url, headers={'User-Agent': 'Runa-Autonomous-Agent'})
            
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    with zipfile.ZipFile(io.BytesIO(response.read())) as z:
                        # Extract to a temporary folder first
                        temp_extract_dir = os.path.join("cloned_repos", f"{repo_name}_temp")
                        z.extractall(temp_extract_dir)
                        
                        # GitHub zips put everything inside a root folder named like 'owner-repo-commitHash'
                        extracted_items = os.listdir(temp_extract_dir)
                        if not extracted_items:
                            return "Error: Downloaded zip archive is empty."
                            
                        extracted_root = os.path.join(temp_extract_dir, extracted_items[0])
                        
                        # Rename the crazy hash folder to our clean target_dir name
                        os.rename(extracted_root, target_dir)
                        
                        # Cleanup the temp directory
                        os.rmdir(temp_extract_dir)

                return (f"Successfully downloaded '{repo_name}' into directory '{target_dir}'.\n\n"
                        f"Next step: Use `list_directory` on '{target_dir}' to see its files, "
                        f"then use `read_local_file` to read the README.md or relevant .py files.")
                        
            except urllib.error.HTTPError as e:
                return f"HTTP Error downloading repository: {e.code} - {e.reason}. The repository might be private or deleted."
            except Exception as e:
                # Cleanup partially extracted files if it fails mid-way
                if os.path.exists(target_dir):
                    shutil.rmtree(target_dir, ignore_errors=True)
                return f"Error downloading and extracting repository: {str(e)}"

        @self.mcp.tool()
        def list_directory(dir_path: str) -> str:
            """
            Lists all files and folders in a given local directory.
            Use this to navigate cloned repositories to find the source code.
            """
            import os
            if not os.path.exists(dir_path):
                return f"Error: Path '{dir_path}' does not exist."
            try:
                items = os.listdir(dir_path)
                return f"Contents of {dir_path}:\n" + "\n".join([f"- {item}" for item in items])
            except Exception as e:
                return f"Error listing directory: {e}"

        @self.mcp.tool()
        def read_local_file(file_path: str) -> str:
            """
            Reads the content of any local text or python file.
            Use this to inspect source code or README.md files inside cloned repositories.
            """
            import os
            if not os.path.exists(file_path):
                return f"Error: File '{file_path}' does not exist."
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Truncate string so we don't blow up the LLM's context window with massive files
                    if len(content) > 15000:
                        return content[:15000] + "\n\n...[FILE TRUNCATED DUE TO LENGTH]..."
                    return content
            except UnicodeDecodeError:
                return "Error: File is not a readable text file (binary/image/etc)."
            except Exception as e:
                return f"Error reading file: {e}"

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
            # REDIRECT PRINT TO STDERR
            print(f"[Auto-Install] Missing dependency '{{missing_module}}'. Installing...", file=sys.stderr)
            
            # REDIRECT SUBPROCESS OUTPUT TO STDERR
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", missing_module],
                stdout=sys.stderr, 
                stderr=sys.stderr
            )
        except subprocess.CalledProcessError:
            print(f"Failed to install {{missing_module}}", file=sys.stderr)
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