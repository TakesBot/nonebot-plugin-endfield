import httpx
import logging
from nonebot import get_driver
from ..config import Config


def _build_url(path: str) -> str:
    driver = get_driver()
    base = getattr(driver.config, "endfield_api_baseurl", None)
    if not base:
        default_base = Config().endfield_api_baseurl
        logging.getLogger("nonebot").info(
            f"endfield_api_baseurl not set in driver.config, using default from config.py: {default_base!r}"
        )
        base = default_base
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not base.endswith("/") and not path.startswith("/"):
        return base + "/" + path
    if base.endswith("/") and path.startswith("/"):
        return base[:-1] + path
    return base + path


def api_request(method: str, path: str, headers: dict = None, data: dict = None):
    url = _build_url(path)
    if not (url.startswith("http://") or url.startswith("https://")):
        logging.getLogger("nonebot").warning(f"Invalid API URL constructed: {url!r}; aborting request")
        return None

    try:
        response = httpx.request(method, url, headers=headers, json=data, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.getLogger("nonebot").warning(f"HTTP error occurred: {e}")
        return None