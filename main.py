from client import AutonomousMCPClient
import asyncio

USER_TASK = "Search on duckduckgo when was Clair Obscur Expedition 33 released. Use the 'ddgs' search library"
client = AutonomousMCPClient(task=USER_TASK, base_url="http://127.0.0.1:8080/v1", api_key="x", integrations_dir="integrations")
asyncio.run(client.run())