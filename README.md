# runa

Runa is a self-evolving AI framework that automatically creates and integrates new tools and skills at runtime by using MCP servers. Instead of relying on a static, pre-defined toolset, Runa dynamically writes the code it needs to solve novel problems by browsing GitHub repos, continuously expanding its own capabilities and creating new tools to be used.

Runa has been tested with Qwen3.5-9B, a consumer-friendly LLM that you can run locally.
---

## **WARNING**

**Runa operates autonomously and has the ability to write code, modify your system, and dynamically install Python packages.** > 
Because it searches for and executes logic on the fly, it may install unwanted, deprecated, or potentially insecure third-party libraries without human intervention. 

By using this software, you acknowledge and agree that:
* You are running this framework entirely at your own risk.
* The creator/maintainer of this repository is **NOT** responsible or liable for any damages, data loss, security breaches, or system corruption caused by the use of this tool or the libraries it chooses to install.
* It is highly recommended to run Runa exclusively within a strictly isolated environment, such as a Docker container, a dedicated Virtual Machine, or a restricted sandbox.

---

## Installation

Clone the repository and install the required dependencies:

```bash
git clone https://github.com/machachu56/runa.git
cd runa
pip install -r requirements.txt
```

## Usage

Runa uses an autonomous client that you can configure with a specific objective, an API endpoint where the LLM is running, and a directory for its tools.

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
    model="Qwen3.5-9B-Q5_K_M.gguf",
    base_url="http://IP:PORT/v1", # Point to your local or remote OpenAI Compatible LLM API
    api_key="API_KEY", # Optional
    integrations_dir="integrations"         # Directory where runtime skills/tools are stored
)

# 3. Execute the agent asynchronously
if __name__ == "__main__":
    asyncio.run(client.run())