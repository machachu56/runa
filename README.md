# runa

Runa is a self-evolving AI framework that automatically creates and integrates new tools and skills at runtime by using MCP server. Instead of relying on a static, pre-defined toolset, Runa dynamically writes the code it needs to solve novel problems, continuously expanding its own capabilities.

---

## Installation

Clone the repository and install the required dependencies:

```bash
git clone [https://github.com/machachu56/runa.git](https://github.com/machachu56/runa.git)
cd runa
pip install -r requirements.txt
```

## Usage

Runa uses an autonomous client that you can configure with a specific objective, an API endpoint, and a directory for its tools.

`main.py` file example.

Uses an OpenAI Compatible API as the LLM provider.

```python
import asyncio
from client import AutonomousMCPClient

# 1. Define the task you want the AI to solve
USER_TASK = "Obtain the Public IPv4 address of the PC's connection."

# 2. Initialize the autonomous client
client = AutonomousMCPClient(
    task=USER_TASK, 
    base_url="[http://IP:PORT/v1](http://example.com:8080/v1)", # Point to your local or remote LLM API
    api_key="API_KEY", # Optional
    integrations_dir="integrations"         # Directory where runtime skills/tools are stored
)

# 3. Execute the agent asynchronously
if __name__ == "__main__":
    asyncio.run(client.run())