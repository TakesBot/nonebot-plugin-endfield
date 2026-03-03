from nonebot import on_command
from nonebot.rule import to_me
from ..lib.api import api_request

health_check = on_command("check", rule=to_me())

@health_check.handle()
async def handle_health_check():
    result = api_request("GET", "/health")
    await health_check.finish(f"API Health Check Result: {result}")