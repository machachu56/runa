from client import AutonomousMCPClient
import asyncio

USER_TASK = "Obtain the Public IPv4 address of the PC's connection."
client = AutonomousMCPClient(task=USER_TASK, base_url="http://192.168.99.2:8080/v1", api_key="x", integrations_dir="integrations")
asyncio.run(client.run())