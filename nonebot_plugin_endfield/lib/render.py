import io
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
from PIL import Image, ImageDraw, ImageFont


logger = logging.getLogger("nonebot")

_FONT_INIT_LOCK = threading.Lock()
_FONT_INIT_DONE = False
_FALLBACK_FONT_FILES = {
    "regular": (
        "NotoSansCJKsc-Regular.otf",
        "https://gh-proxy.org/https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf",
    ),
    "bold": (
        "NotoSansCJKsc-Bold.otf",
        "https://gh-proxy.org/https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Bold.otf",
    ),
}


def _get_font_cache_dir() -> Path:
    return Path(__file__).resolve().parent / "fonts"


def _get_fallback_font_candidates(bold: bool) -> list[Path]:
    font_dir = _get_font_cache_dir()
    regular_name, _ = _FALLBACK_FONT_FILES["regular"]
    bold_name, _ = _FALLBACK_FONT_FILES["bold"]
    if bold:
        return [font_dir / bold_name, font_dir / regular_name]
    return [font_dir / regular_name, font_dir / bold_name]


def _ensure_fallback_fonts() -> None:
    global _FONT_INIT_DONE
    if _FONT_INIT_DONE:
        return

    with _FONT_INIT_LOCK:
        if _FONT_INIT_DONE:
            return

        font_dir = _get_font_cache_dir()
        font_dir.mkdir(parents=True, exist_ok=True)

        for _, (filename, url) in _FALLBACK_FONT_FILES.items():
            font_path = font_dir / filename
            if font_path.exists() and font_path.stat().st_size > 1024:
                continue
            try:
                response = httpx.get(url, timeout=20.0)
                response.raise_for_status()
                font_path.write_bytes(response.content)
            except Exception as e:
                logger.warning(f"fallback font download failed: {filename}, error={e}")

        _FONT_INIT_DONE = True


def _pick_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue

    _ensure_fallback_fonts()
    for path in _get_fallback_font_candidates(bold=False):
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _pick_bold_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue

    _ensure_fallback_fonts()
    for path in _get_fallback_font_candidates(bold=True):
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _normalize_url(url: str) -> str:
    return (url or "").strip()


def _safe_json_loads(raw: Any) -> Any:
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _wrap_text_by_pixel(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    if not text:
        return [""]

    wrapped: List[str] = []
    for raw_line in text.splitlines() or [""]:
        line = raw_line
        if not line:
            wrapped.append("")
            continue

        current = ""
        for ch in line:
            candidate = current + ch
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
                continue
            if current:
                wrapped.append(current)
            current = ch
        wrapped.append(current)
    return wrapped


def _download_image(url: str) -> Image.Image | None:
    normalized = _normalize_url(url)
    if not normalized:
        return None
    try:
        response = httpx.get(normalized, timeout=10.0)
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content)).convert("RGB")
        return image
    except Exception:
        return None


def _extract_announce_blocks(data: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    title = str(data.get("title") or "Endfield 最新公告")

    text_map: Dict[str, str] = {}
    for item in data.get("texts") or []:
        if isinstance(item, dict):
            text_map[str(item.get("id", ""))] = str(item.get("content") or "")

    image_map: Dict[str, str] = {}
    for item in data.get("images") or []:
        if isinstance(item, dict):
            image_map[str(item.get("id", ""))] = _normalize_url(str(item.get("url") or ""))

    blocks: List[Dict[str, Any]] = []

    format_obj = _safe_json_loads(data.get("format"))
    format_data = format_obj.get("data") if isinstance(format_obj, dict) else None
    if isinstance(format_data, list):
        for node in format_data:
            if not isinstance(node, dict):
                continue
            node_type = node.get("type")

            if node_type == "image":
                image_id = str(node.get("imageId") or "")
                url = image_map.get(image_id, "")
                if url:
                    blocks.append({"type": "image", "url": url})
                continue

            if node_type == "paragraph":
                contents = node.get("contents")
                if not isinstance(contents, list):
                    continue
                paragraph_text = ""
                for content in contents:
                    if not isinstance(content, dict):
                        continue
                    if content.get("type") == "text":
                        content_id = str(content.get("contentId") or "")
                        paragraph_text += text_map.get(content_id, "")
                if paragraph_text:
                    blocks.append({"type": "text", "text": paragraph_text})

    if not blocks:
        for image_url in image_map.values():
            if image_url:
                blocks.append({"type": "image", "url": image_url})
        for text in text_map.values():
            if text:
                blocks.append({"type": "text", "text": text})

    if not blocks:
        blocks.append({"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)})

    return title, blocks


def _format_publish_time(ts: Any) -> str:
    try:
        timestamp = int(ts)
        if timestamp <= 0:
            return "未知"
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "未知"

def render_announce_data_image(payload: Dict[str, Any]) -> bytes:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = {"content": payload}

    title, blocks = _extract_announce_blocks(data)

    title_font = _pick_bold_font(36)
    text_font = _pick_font(20)
    meta_font = _pick_font(18)
    publish_text = f"公告发布时间：{_format_publish_time(data.get('published_at_ts'))}"

    padding = 24
    width = 980
    content_width = width - padding * 2
    line_height = 30
    block_gap = 14
    title_height = 56
    meta_bbox = meta_font.getbbox(publish_text)
    meta_text_height = max(18, meta_bbox[3] - meta_bbox[1])
    footer_height = meta_text_height + 10
    note_height = 30

    temp = Image.new("RGB", (width, 10), "white")
    temp_draw = ImageDraw.Draw(temp)

    prepared_blocks: List[Dict[str, Any]] = []
    total_height = padding + title_height

    for block in blocks:
        if block.get("type") == "text":
            text = str(block.get("text") or "")
            lines = _wrap_text_by_pixel(temp_draw, text, text_font, content_width)
            block_height = max(line_height, len(lines) * line_height)
            prepared_blocks.append({"type": "text", "lines": lines, "height": block_height})
            total_height += block_height + block_gap
            continue

        if block.get("type") == "image":
            image = _download_image(str(block.get("url") or ""))
            if image is None:
                fallback = ["[图片加载失败]"]
                block_height = line_height
                prepared_blocks.append({"type": "text", "lines": fallback, "height": block_height})
                total_height += block_height + block_gap
                continue

            scale = content_width / image.width if image.width > content_width else 1.0
            resized_width = int(image.width * scale)
            resized_height = int(image.height * scale)
            resized = image.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
            prepared_blocks.append({"type": "image", "image": resized, "height": resized_height})
            total_height += resized_height + block_gap

    if prepared_blocks:
        total_height -= block_gap

    max_height = 12000
    estimated_height = total_height + padding + footer_height
    overflow = estimated_height > max_height
    height = min(max_height, max(estimated_height, padding * 2 + title_height + footer_height))

    # 使用“最大可用高度”做正文布局，并固定预留截断提示区域，避免后续挤压底部信息
    content_bottom = max_height - padding - meta_text_height - 8 - note_height - 6

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((padding, padding), title, fill="#111111", font=title_font)

    y = padding + title_height
    did_truncate = False
    for index, block in enumerate(prepared_blocks):
        if y >= content_bottom:
            did_truncate = True
            break

        if block["type"] == "text":
            for line in block["lines"]:
                if y + line_height > content_bottom:
                    did_truncate = True
                    break
                draw.text((padding, y), line, fill="#222222", font=text_font)
                y += line_height
            if did_truncate:
                break
            if index < len(prepared_blocks) - 1:
                y += block_gap
            continue

        if block["type"] == "image":
            block_image: Image.Image = block["image"]
            if y + block_image.height > content_bottom:
                did_truncate = True
                break
            image.paste(block_image, (padding, y))
            y += block_image.height
            if index < len(prepared_blocks) - 1:
                y += block_gap

    note_y = y
    if overflow or did_truncate:
        note = "内容过长，已截断显示。"
        note_y = max(padding + title_height, y)
        draw.text((padding, note_y), note, fill="#aa0000", font=text_font)
        content_end = note_y + note_height
    else:
        content_end = y

    footer_y = content_end + 8
    final_height = min(max_height, footer_y + meta_text_height + padding)

    draw.text((padding, footer_y), publish_text, fill="#666666", font=meta_font)

    if final_height < height:
        image = image.crop((0, 0, width, final_height))

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _render_report_image(
    title: str,
    sections: List[Tuple[str, List[str]]],
    subtitle: str = "",
    footer: str = "",
    width: int = 1080,
) -> bytes:
    title_font = _pick_bold_font(42)
    subtitle_font = _pick_font(22)
    section_title_font = _pick_bold_font(30)
    text_font = _pick_font(22)
    footer_font = _pick_font(18)

    padding = 28
    section_gap = 20
    line_height = 34
    content_width = width - padding * 2

    temp = Image.new("RGB", (width, 32), "white")
    temp_draw = ImageDraw.Draw(temp)

    title_h = max(48, title_font.getbbox("终末地")[3] - title_font.getbbox("终末地")[1])
    subtitle_h = 0
    subtitle_lines: List[str] = []
    if subtitle:
        subtitle_lines = _wrap_text_by_pixel(temp_draw, subtitle, subtitle_font, content_width)
        subtitle_h = max(1, len(subtitle_lines)) * line_height

    prepared: List[Tuple[str, List[str], int]] = []
    total_h = padding + title_h + (10 if subtitle_h else 0) + subtitle_h + 12
    for sec_title, sec_lines in sections:
        wrapped_lines: List[str] = []
        for line in sec_lines:
            wrapped_lines.extend(_wrap_text_by_pixel(temp_draw, str(line), text_font, content_width))
        sec_h = line_height + max(1, len(wrapped_lines)) * line_height
        prepared.append((sec_title, wrapped_lines, sec_h))
        total_h += sec_h + section_gap

    footer_h = 0
    footer_lines: List[str] = []
    if footer:
        footer_lines = _wrap_text_by_pixel(temp_draw, footer, footer_font, content_width)
        footer_h = max(1, len(footer_lines)) * 28 + 6
        total_h += footer_h

    total_h += padding
    max_h = 12000
    height = min(max_h, max(360, total_h))

    image = Image.new("RGB", (width, height), "#f7f8fa")
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((14, 14, width - 14, height - 14), radius=20, fill="#ffffff", outline="#eceff3", width=2)
    draw.text((padding, padding), title, fill="#111111", font=title_font)

    y = padding + title_h + 10
    for line in subtitle_lines:
        draw.text((padding, y), line, fill="#4a5568", font=subtitle_font)
        y += line_height

    if subtitle_lines:
        y += 6

    for sec_title, sec_lines, _ in prepared:
        if y + line_height >= height - padding:
            break
        draw.rounded_rectangle((padding - 4, y - 2, width - padding + 4, y + 40), radius=10, fill="#f3f6fb")
        draw.text((padding + 8, y + 4), sec_title, fill="#1f2937", font=section_title_font)
        y += line_height + 8
        for line in sec_lines:
            if y + line_height >= height - padding:
                break
            draw.text((padding + 4, y), line, fill="#222222", font=text_font)
            y += line_height
        y += section_gap

    if footer_lines and y + footer_h < height - padding + 6:
        draw.line((padding, y, width - padding, y), fill="#e5e7eb", width=2)
        y += 10
        for line in footer_lines:
            draw.text((padding, y), line, fill="#6b7280", font=footer_font)
            y += 28

    if y + padding < height:
        image = image.crop((0, 0, width, y + padding))

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def render_gacha_records_image(cache_data: Dict[str, Any], page: int = 1) -> bytes:
    stats = (cache_data.get("stats_data") or {}).get("stats") or {}
    sections: List[Tuple[str, List[str]]] = []

    pool_defs = (
        ("standard", "常驻角色"),
        ("beginner", "新手池"),
        ("weapon", "武器池"),
        ("limited", "限定角色"),
    )
    for key, label in pool_defs:
        pools = cache_data.get("records_by_pool") or {}
        rows = pools.get(key) if isinstance(pools.get(key), list) else []
        sorted_rows = sorted(
            rows,
            key=lambda x: (
                -(int(x.get("seq_id")) if str(x.get("seq_id", "")).isdigit() else 0),
                -(int(x.get("gacha_ts") or 0)),
            ),
        )
        total = len(sorted_rows)
        pages = max(1, (total + 9) // 10)
        current = max(1, min(page, pages))
        start = (current - 1) * 10
        picked = sorted_rows[start : start + 10]

        lines = [f"共 {total} 抽（第 {current}/{pages} 页）"]
        if picked:
            for idx, r in enumerate(picked, start=1):
                rarity = int(r.get("rarity") or 0)
                name = r.get("char_name") or r.get("item_name") or "未知"
                lines.append(f"{start + idx}. ★{rarity} {name}")
        else:
            lines.append("暂无记录")
        sections.append((label, lines))

    subtitle = (
        f"总抽数：{stats.get('total_count', 0)} | 六星：{stats.get('star6_count', 0)} | "
        f"五星：{stats.get('star5_count', 0)} | 四星：{stats.get('star4_count', 0)}"
    )
    updated_at = cache_data.get("updated_at")
    footer = ""
    if updated_at:
        try:
            footer = f"缓存时间：{datetime.fromtimestamp(float(updated_at) / 1000).strftime('%Y-%m-%d %H:%M:%S')}"
        except Exception:
            footer = ""
    return _render_report_image("终末地 抽卡记录", sections, subtitle=subtitle, footer=footer)


def render_gacha_analysis_image(stats_data: Dict[str, Any], cache_data: Dict[str, Any]) -> bytes:
    pool_stats = stats_data.get("pool_stats") or {}
    user_info = stats_data.get("user_info") or {}
    overall_stats = stats_data.get("stats") or {}
    records_by_pool = cache_data.get("records_by_pool") or {}

    def _to_int(v: Any) -> int:
        try:
            return int(v or 0)
        except Exception:
            return 0

    def _to_bool(v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("1", "true", "yes")
        return bool(v)

    def _avg_cost(total: int, star6: int) -> str:
        if star6 <= 0:
            return "-"
        return str(round(total / star6))

    def _sort_record_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def _seq(r: Dict[str, Any]) -> int:
            try:
                return int(r.get("seq_id") or 0)
            except Exception:
                return 0

        def _ts(r: Dict[str, Any]) -> int:
            try:
                return int(r.get("gacha_ts") or 0)
            except Exception:
                return 0

        return sorted(rows, key=lambda x: (_ts(x), _seq(x)))

    def _group_pool_rows(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            pool_name = str(row.get("pool_name") or "未知")
            grouped.setdefault(pool_name, []).append(row)
        return grouped

    def _build_timeline_rows(rows: List[Dict[str, Any]], *, max_pity: int) -> Dict[str, Any]:
        sorted_rows = _sort_record_rows(rows)  # 旧 -> 新
        paid_rows = [row for row in sorted_rows if not _to_bool(row.get("is_free"))]
        free_rows = [row for row in sorted_rows if _to_bool(row.get("is_free"))]

        def _segment_timeline(source_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            # 每抽+1；出6星时换行并重置
            segments: List[Dict[str, Any]] = []
            count = 0
            for row in source_rows:
                count += 1
                if _to_int(row.get("rarity")) == 6:
                    name = str(row.get("char_name") or row.get("item_name") or "6星")
                    segments.append({"count": count, "name": name, "is_pity": False})
                    count = 0
            if count > 0:
                segments.append({"count": count, "name": "已垫", "is_pity": True})
            return segments

        timeline_old_to_new = _segment_timeline(paid_rows)

        # 画图从上到下，故反转后满足“旧->新从下往上”
        timeline_for_draw = list(reversed(timeline_old_to_new))

        # 免费抽卡与付费段共用同一分段逻辑，确保免费出6星也换行
        free_timeline_old_to_new = _segment_timeline(free_rows)
        free_timeline_for_draw = list(reversed(free_timeline_old_to_new))

        def _ts(v: Dict[str, Any]) -> int:
            try:
                return int(v.get("gacha_ts") or 0)
            except Exception:
                return 0
        pool_sort_ts = min((_ts(r) for r in sorted_rows), default=0)

        return {
            "timeline": timeline_for_draw,
            "paid_total": len(paid_rows),
            "free_total": len(free_rows),
            "free_timeline": free_timeline_for_draw,
            "max_pity": max_pity,
            "sort_ts": pool_sort_ts,
        }

    def _build_pool_cards(pool_key: str, max_pity: int) -> List[Dict[str, Any]]:
        rows = records_by_pool.get(pool_key)
        if not isinstance(rows, list):
            return []
        grouped = _group_pool_rows(rows)
        cards: List[Dict[str, Any]] = []
        for pool_name, pool_rows in grouped.items():
            timeline_data = _build_timeline_rows(pool_rows, max_pity=max_pity)
            cards.append(
                {
                    "pool_name": pool_name,
                    "timeline": timeline_data["timeline"],
                    "paid_total": timeline_data["paid_total"],
                    "free_total": timeline_data["free_total"],
                    "free_timeline": timeline_data["free_timeline"],
                    "max_pity": timeline_data["max_pity"],
                    "sort_ts": timeline_data["sort_ts"],
                }
            )
        # 最新卡池在上（时间倒序）
        cards.sort(key=lambda x: (-(x.get("sort_ts") or 0), x["pool_name"]))
        return cards

    limited_cards = _build_pool_cards("limited", 120)
    weapon_cards = _build_pool_cards("weapon", 40)
    standard_cards = _build_pool_cards("standard", 80) + _build_pool_cards("beginner", 80)

    def _pool_stat(name1: str, name2: str) -> Dict[str, Any]:
        return (pool_stats.get(name1) or pool_stats.get(name2) or {})

    limited_stat = _pool_stat("limited_char", "limited")
    standard_stat = _pool_stat("standard_char", "standard")
    beginner_stat = _pool_stat("beginner_char", "beginner")
    weapon_stat = _pool_stat("weapon", "weapon")

    limited_total = _to_int(limited_stat.get("total") or limited_stat.get("total_count"))
    limited_6 = _to_int(limited_stat.get("star6") or limited_stat.get("star6_count"))
    weapon_total = _to_int(weapon_stat.get("total") or weapon_stat.get("total_count"))
    weapon_6 = _to_int(weapon_stat.get("star6") or weapon_stat.get("star6_count"))
    standard_total = _to_int(standard_stat.get("total") or standard_stat.get("total_count")) + _to_int(beginner_stat.get("total") or beginner_stat.get("total_count"))
    standard_6 = _to_int(standard_stat.get("star6") or standard_stat.get("star6_count")) + _to_int(beginner_stat.get("star6") or beginner_stat.get("star6_count"))

    width = 1500
    bg = Image.new("RGB", (width, 7600), "#eef1f5")
    draw = ImageDraw.Draw(bg)

    title_font = _pick_bold_font(44)
    subtitle_font = _pick_font(24)
    user_font = _pick_bold_font(26)
    uid_font = _pick_font(19)
    stat_label_font = _pick_bold_font(18)
    stat_value_font = _pick_bold_font(40)
    section_title_font = _pick_bold_font(28)
    pool_title_font = _pick_bold_font(22)
    metric_font = _pick_font(18)
    bar_text_font = _pick_bold_font(15)
    footer_font = _pick_font(18)

    pad_x = 18
    y = 16

    def _rr(x1: int, y1: int, x2: int, y2: int, radius: int = 12, fill: str = "#fff", outline: str | None = None, width_line: int = 1) -> None:
        draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=fill, outline=outline, width=width_line)

    def _bar_color(count: int, max_pity: int, is_pity: bool) -> str:
        if is_pity:
            return "#4b5563"
        ratio = (count / max(1, max_pity)) * 100
        if ratio < 50:
            return "#16a34a"
        if ratio < 80:
            return "#ca8a04"
        return "#dc2626"

    def _hex_luma(color: str) -> float:
        c = (color or "").strip().lstrip("#")
        if len(c) != 6:
            return 0.0
        try:
            r = int(c[0:2], 16)
            g = int(c[2:4], 16)
            b = int(c[4:6], 16)
            return 0.2126 * r + 0.7152 * g + 0.0722 * b
        except Exception:
            return 0.0

    def _bar_text_colors(fill_color: str) -> Tuple[str, str]:
        # 深色底用浅字，浅色底用深字，并加描边保证灰底可读性
        if _hex_luma(fill_color) < 145:
            return "#f8fafc", "#0f172a"
        return "#0f172a", "#f8fafc"

    # 顶部栏（高对比）
    top_h = 102
    _rr(pad_x, y, width - pad_x, y + top_h, radius=12, fill="#ffffff", outline="#cfd8e3", width_line=2)
    nick = str(user_info.get("nickname") or user_info.get("game_uid") or "未知")
    uid = str(user_info.get("game_uid") or "-")
    avatar_x = pad_x + 16
    avatar_y = y + 18
    avatar_size = 66
    _rr(avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size, radius=10, fill="#d1d5db", outline="#9ca3af")
    avatar_candidates = [
        str(user_info.get("avatar") or "").strip(),
        str(user_info.get("avatar_url") or "").strip(),
        str(user_info.get("avatarUrl") or "").strip(),
        str(user_info.get("head_url") or "").strip(),
        str(user_info.get("headUrl") or "").strip(),
    ]
    qq_user_id = str(cache_data.get("user_id") or "").strip()
    if qq_user_id:
        avatar_candidates.append(f"https://q1.qlogo.cn/g?b=qq&nk={qq_user_id}&s=100")
    avatar_img = None
    for avatar_url in avatar_candidates:
        if not avatar_url:
            continue
        avatar_img = _download_image(avatar_url)
        if avatar_img is not None:
            break
    if avatar_img is not None:
        avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
        mask = Image.new("L", (avatar_size, avatar_size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle((0, 0, avatar_size, avatar_size), radius=10, fill=255)
        bg.paste(avatar_img, (avatar_x, avatar_y), mask)
    draw.text((avatar_x + avatar_size + 14, avatar_y + 5), nick, fill="#111827", font=user_font)
    draw.text((avatar_x + avatar_size + 14, avatar_y + 42), f"UID {uid}", fill="#374151", font=uid_font)

    title = "抽卡分析"
    title_w = int(draw.textlength(title, font=title_font))
    draw.text(((width - title_w) // 2, y + 12), title, fill="#0f172a", font=title_font)
    subtitle = "终末地寻访统计概览"
    subtitle_w = int(draw.textlength(subtitle, font=subtitle_font))
    draw.text(((width - subtitle_w) // 2, y + 62), subtitle, fill="#334155", font=subtitle_font)
    y += top_h + 12

    # 统计卡（深色字）
    card_gap = 10
    cards = 5
    card_w = (width - pad_x * 2 - card_gap * (cards - 1)) // cards
    card_h = 104
    card_specs = [
        ("总抽数", f"{_to_int(overall_stats.get('total_count'))}", "#ffffff", "#111827"),
        ("6星 / 5星 / 4星", f"{_to_int(overall_stats.get('star6_count'))}/{_to_int(overall_stats.get('star5_count'))}/{_to_int(overall_stats.get('star4_count'))}", "#f3f4f6", "#111827"),
        ("特许寻访 · 平均出红", _avg_cost(limited_total, limited_6), "#fee2e2", "#991b1b"),
        ("武器池 · 平均出红", _avg_cost(weapon_total, weapon_6), "#fef3c7", "#92400e"),
        ("常驻寻访 · 平均出红", _avg_cost(standard_total, standard_6), "#dbeafe", "#1e3a8a"),
    ]
    x = pad_x
    for label, value, color, value_color in card_specs:
        _rr(x, y, x + card_w, y + card_h, radius=12, fill=color, outline="#d1d5db")
        draw.text((x + 12, y + 12), label, fill="#111827", font=stat_label_font)
        vw = int(draw.textlength(value, font=stat_value_font))
        draw.text((x + (card_w - vw) // 2, y + 46), value, fill=value_color, font=stat_value_font)
        x += card_w + card_gap
    y += card_h + 12

    updated_at = cache_data.get("updated_at")
    time_text = ""
    if updated_at:
        try:
            time_text = datetime.fromtimestamp(float(updated_at) / 1000).strftime("%Y-%m-%d %H:%M")
        except Exception:
            time_text = ""
    if time_text:
        draw.text((pad_x + 2, y), f"更新时间 {time_text}", fill="#334155", font=uid_font)
    draw.text((width - 370, y), "刷新：发送: /终末地同步抽卡记录", fill="#111827", font=uid_font)
    y += 36

    # 三列池组
    col_gap = 10
    col_w = (width - pad_x * 2 - col_gap * 2) // 3
    columns = [
        ("特许寻访", limited_cards),
        ("武器池", weapon_cards),
        ("常驻寻访", standard_cards),
    ]

    def _estimate_col_height(cards_data: List[Dict[str, Any]]) -> int:
        base = 70
        for card in cards_data:
            rows = card.get("timeline") or []
            free_rows = card.get("free_timeline") or []
            line_h = len(rows) * 34
            free_h = (10 + len(free_rows) * 34) if card.get("free_total", 0) > 0 else 0
            base += 92 + line_h + free_h + 14
        return max(base + 16, 260)

    col_outer_h = max(_estimate_col_height(c[1]) for c in columns) + 10
    col_heights: List[int] = []

    for col_idx, (group_name, cards_data) in enumerate(columns):
        cx = pad_x + col_idx * (col_w + col_gap)
        cy = y
        _rr(cx, cy, cx + col_w, cy + col_outer_h, radius=12, fill="#ffffff", outline="#cfd8e3", width_line=2)
        draw.text((cx + 18, cy + 16), group_name, fill="#0f172a", font=section_title_font)
        draw.line((cx + 16, cy + 56, cx + col_w - 16, cy + 56), fill="#dbe3ef", width=2)
        cy += 66

        if not cards_data:
            draw.text((cx + 18, cy + 6), "暂无记录", fill="#6b7280", font=metric_font)
            cy += 30

        for card in cards_data:
            pool_name = str(card.get("pool_name") or "未知")
            timeline = card.get("timeline") or []
            paid_total = _to_int(card.get("paid_total"))
            max_pity = _to_int(card.get("max_pity")) or 80
            free_total = _to_int(card.get("free_total"))
            free_timeline = card.get("free_timeline") or []

            box_h = 92 + len(timeline) * 34 + ((10 + len(free_timeline) * 34) if free_total > 0 else 0)
            _rr(cx + 10, cy, cx + col_w - 10, cy + box_h, radius=10, fill="#f8fafc", outline="#d1d9e6")
            draw.text((cx + 20, cy + 10), pool_name, fill="#0f172a", font=pool_title_font)
            draw.text((cx + 20, cy + 44), f"合计 {paid_total} 抽", fill="#1f2937", font=metric_font)

            row_y = cy + 70
            bar_x = cx + 20
            bar_w = col_w - 68
            bar_h = 25

            for row in timeline:
                count = _to_int(row.get("count"))
                name = str(row.get("name") or "")
                is_pity = bool(row.get("is_pity"))

                _rr(bar_x, row_y, bar_x + bar_w, row_y + bar_h, radius=12, fill="#dbe2eb")
                fill_w = max(46, min(bar_w, int(bar_w * (count / max(1, max_pity)))))
                fill_color = _bar_color(count, max_pity, is_pity)
                _rr(bar_x, row_y, bar_x + fill_w, row_y + bar_h, radius=12, fill=fill_color)
                label = f"已垫 {count}" if is_pity else f"{count}抽 {name}"
                if draw.textlength(label, font=bar_text_font) > bar_w - 12:
                    label = (label[:14] + "...") if len(label) > 17 else label
                tw = int(draw.textlength(label, font=bar_text_font))
                text_fill, text_stroke = _bar_text_colors(fill_color)
                draw.text(
                    (bar_x + max(8, (bar_w - tw) // 2), row_y + 4),
                    label,
                    fill=text_fill,
                    font=bar_text_font,
                    stroke_width=1,
                    stroke_fill=text_stroke,
                )
                row_y += 34

            # 免费十连/免费抽：按正常条形展示，仅在视觉上与付费段分隔
            if free_total > 0:
                row_y += 16
                for free_row in free_timeline:
                    free_count = _to_int(free_row.get("count"))
                    free_name = str(free_row.get("name") or "")
                    free_is_pity = bool(free_row.get("is_pity"))

                    _rr(bar_x, row_y, bar_x + bar_w, row_y + bar_h, radius=12, fill="#dbe2eb")
                    free_fill_w = max(46, min(bar_w, int(bar_w * (free_count / 10))))
                    free_fill_color = _bar_color(free_count, 10, free_is_pity)
                    _rr(bar_x, row_y, bar_x + free_fill_w, row_y + bar_h, radius=12, fill=free_fill_color)

                    free_text = f"免费{free_count}抽"
                    if not free_is_pity and free_name:
                        free_text = f"免费{free_count}抽-{free_name}"
                    tw = int(draw.textlength(free_text, font=bar_text_font))
                    free_text_fill, free_text_stroke = _bar_text_colors(free_fill_color)
                    draw.text(
                        (bar_x + max(8, (bar_w - tw) // 2), row_y + 4),
                        free_text,
                        fill=free_text_fill,
                        font=bar_text_font,
                        stroke_width=1,
                        stroke_fill=free_text_stroke,
                    )
                    row_y += 34

            cy += box_h + 10

        col_heights.append(cy + 12)

    y = max(col_heights) + 4 if col_heights else y + 500
    footer_text = "Generated by nonebot-plugin-endfield"
    tw = int(draw.textlength(footer_text, font=footer_font))
    draw.text(((width - tw) // 2, y), footer_text, fill="#334155", font=footer_font)

    final_h = min(bg.height, y + 36)
    bg = bg.crop((0, 0, width, final_h))
    buf = io.BytesIO()
    bg.save(buf, format="PNG")
    return buf.getvalue()


def render_gacha_global_stats_image(stats_data: Dict[str, Any], keyword: str = "") -> bytes:
    s = stats_data.get("stats") or stats_data
    by_channel = s.get("by_channel") or {}
    by_type = s.get("by_type") or {}

    def _fmt(v: Any, ndigits: int = 2) -> str:
        try:
            return f"{float(v):.{ndigits}f}"
        except Exception:
            return "-"

    current_pool = s.get("current_pool") or {}
    up_name = current_pool.get("up_char_name") or "-"
    up_weapon = current_pool.get("up_weapon_name") or "-"

    sections: List[Tuple[str, List[str]]] = []
    for key, label in (("beginner", "新手池"), ("standard", "常驻池"), ("weapon", "武器池"), ("limited", "限定池")):
        item = by_type.get(key) or {}
        total = int(item.get("total") or 0)
        star6 = int(item.get("star6") or 0)
        star5 = int(item.get("star5") or 0)
        star4 = int(item.get("star4") or 0)
        avg = _fmt(item.get("avg_pity"), 1)
        rate = (star6 / total * 100) if total > 0 else 0
        sections.append(
            (
                label,
                [
                    f"总抽数：{total}",
                    f"六星：{star6} | 五星：{star5} | 四星：{star4}",
                    f"出红率：{rate:.2f}% | 均出：{avg} 抽",
                ],
            )
        )

    official = by_channel.get("official")
    bilibili = by_channel.get("bilibili")
    if isinstance(official, dict):
        sections.append(
            (
                "官服",
                [
                    f"统计用户：{official.get('total_users', 0)}",
                    f"总抽数：{official.get('total_pulls', 0)}",
                    f"平均出红：{_fmt(official.get('avg_pity'))} 抽",
                ],
            )
        )
    if isinstance(bilibili, dict):
        sections.append(
            (
                "B服",
                [
                    f"统计用户：{bilibili.get('total_users', 0)}",
                    f"总抽数：{bilibili.get('total_pulls', 0)}",
                    f"平均出红：{_fmt(bilibili.get('avg_pity'))} 抽",
                ],
            )
        )

    subtitle = (
        f"总抽数：{s.get('total_pulls', 0)} | 统计用户：{s.get('total_users', 0)} | 平均出红：{_fmt(s.get('avg_pity'))} 抽\n"
        f"六星：{s.get('star6_total', 0)} | 五星：{s.get('star5_total', 0)} | 四星：{s.get('star4_total', 0)}\n"
        f"当期UP角色：{up_name} | UP武器：{up_weapon}"
    )
    footer = f"查询池：{keyword}" if keyword else ""
    return _render_report_image("终末地 全服抽卡统计", sections, subtitle=subtitle, footer=footer)
