import json
import sqlite3
from typing import Any, Optional

from nonebot import get_driver, on_command
from nonebot.adapters import Event

from ..config import Config
from ..lib.api import api_request
from ..lib.utils import get_active_binding, build_headers


user_signin = on_command("签到")


@user_signin.handle()
async def handle_user_signin(event: Event) -> None:
	user_id = str(event.get_user_id())
	binding = get_active_binding(user_id)
	if not binding:
		return

	result = await api_request("POST", "/api/endfield/attendance", headers=build_headers(binding["framework_token"]))
	if isinstance(result, dict) and result.get("code") == 0:
		data = result.get("data")
		if isinstance(data, dict) and data.get("already_signed") is True:
			await user_signin.finish("今日已完成森空岛签到")
		await user_signin.finish("森空岛签到成功")
