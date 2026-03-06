import base64
import asyncio
import time

from nonebot import on_command, get_driver, logger
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.rule import to_me
from ..config import Config
from ..lib.api import api_request
from ..lib.render import render_announce_data_image


get_last_announce = on_command("终末地公告")


_ANNOUNCE_CACHE_TTL_SECONDS = 300
_announce_image_cache: dict[str, tuple[float, str]] = {}


def _build_announce_cache_key(result: dict) -> str:
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        return ""
    item_id = str(data.get("item_id") or "").strip()
    pub_ts = str(data.get("published_at_ts") or "").strip()
    title = str(data.get("title") or "").strip()
    return "|".join([item_id, pub_ts, title])


@get_last_announce.handle()
async def handle_get_last_announce():
    cfg = Config()
    driver = get_driver()
    api_key = getattr(driver.config, "endfield_api_key", None) or cfg.endfield_api_key
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    logger.info(f"Using headers for API request: {headers}")
    result = await api_request("GET", "/api/announcements/latest", headers=headers or None)
    if result is None:
        await get_last_announce.finish("获取公告失败，请检查 endfield_api_key 和 endfield_api_baseurl 配置并查看日志。")

    data = result.get("data") if isinstance(result, dict) else None
    item_id = data.get("item_id") if isinstance(data, dict) else None
    origin_link = f"https://www.skland.com/article?id={item_id}" if item_id else None

    cache_key = _build_announce_cache_key(result)
    now = time.time()
    image_b64 = ""
    if cache_key:
        cached = _announce_image_cache.get(cache_key)
        if cached and cached[0] > now:
            image_b64 = cached[1]

    if not image_b64:
        image_bytes = await asyncio.to_thread(render_announce_data_image, result)
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        if cache_key:
            _announce_image_cache[cache_key] = (now + _ANNOUNCE_CACHE_TTL_SECONDS, image_b64)

    if _announce_image_cache:
        expired = [k for k, v in _announce_image_cache.items() if v[0] <= now]
        for k in expired:
            _announce_image_cache.pop(k, None)
    if origin_link:
        await get_last_announce.finish(
            MessageSegment.image(f"base64://{image_b64}")
            + MessageSegment.text(f"原文链接：{origin_link}")
        )
    await get_last_announce.finish(MessageSegment.image(f"base64://{image_b64}"))