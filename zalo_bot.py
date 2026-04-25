"""
zalo_bot.py - Zalo bot cho nhom Truyen thong Yok Don.

Bot dam nhiem 4 nhom viec chinh:
- Doc Google Sheet va chu dong nhac viec moi ngay.
- Tra loi tin nhan ca nhan.
- Tra loi trong nhom khi duoc goi ten hoac dung lenh.
- Luu cac ghi nho nguoi dung day bot de lam ngu canh tra loi.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

import brain
from ai_helper import (
    draft_facebook_post_options,
    resolve_facebook_style,
    rewrite_group_relay_message,
)
from knowledge_store import add_learning, get_learning_context
from message_builder import (
    build_daily_reminder,
    build_no_work_message,
    build_pending_tasks_message,
    build_today_tasks_message,
    build_upcoming_tasks_message,
)
from sheet_reader import (
    fetch_all_tasks,
    get_overdue_tasks,
    get_sheet_public_url,
    get_today_tasks,
    get_unassigned_tasks,
    get_upcoming_tasks,
    is_today_empty,
)
from time_utils import LOCAL_TIMEZONE_NAME, local_now, local_today_key

load_dotenv()

ZALO_URL = "https://chat.zalo.me/"
BASE_DIR = Path(__file__).resolve().parent
USER_DATA_DIR = BASE_DIR / "zalo_profile"
BOT_STATE_FILE = BASE_DIR / "bot_runtime_state.json"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
ZALO_GROUP_NAME = os.getenv("ZALO_GROUP_NAME", "Truyen thong Yok Don").strip()
REMINDER_HOUR = int(os.getenv("REMINDER_HOUR", "8"))
REMINDER_MINUTE = int(os.getenv("REMINDER_MINUTE", "0"))
DAYS_AHEAD = int(os.getenv("DAYS_AHEAD", "3"))
REPLY_COOLDOWN_SECONDS = int(os.getenv("REPLY_COOLDOWN_SECONDS", "8"))
BROWSER_NAME = os.getenv("PLAYWRIGHT_BROWSER", "chromium").strip().lower()
CUSTOM_REMINDER_DEFAULT_HOUR = int(os.getenv("CUSTOM_REMINDER_DEFAULT_HOUR", "8"))
CUSTOM_REMINDER_DEFAULT_MINUTE = int(os.getenv("CUSTOM_REMINDER_DEFAULT_MINUTE", "0"))
CUSTOM_REMINDER_RETRY_SECONDS = int(os.getenv("CUSTOM_REMINDER_RETRY_SECONDS", "60"))

BOT_NAME_RAW = os.getenv("BOT_NAME", "Nhan Vien Moi Yok Don")
BOT_NAMES = [name.strip().lower() for name in BOT_NAME_RAW.split(",") if name.strip()]
if not BOT_NAMES:
    BOT_NAMES = ["nhan vien moi yok don"]
BOT_NAME_ALIASES_RAW = os.getenv("BOT_NAME_ALIASES", "bot ai")
BOT_NAME_ALIASES = [name.strip().lower() for name in BOT_NAME_ALIASES_RAW.split(",") if name.strip()]

ONBOARDING_PATTERNS = (
    "chào mừng đến với zalo pc",
    "chao mung den voi zalo pc",
    "khám phá những tiện ích",
    "trải nghiệm xuyên suốt",
    "dong bo tin nhan gan day",
    "đồng bộ tin nhắn gần đây",
    "zalo web của bạn hiện chưa có đầy đủ tin nhắn gần đây",
    "zalo web cua ban hien chua co day du tin nhan gan day",
)

SEARCH_INPUT_SELECTORS = [
    "#contact-search-input",
    "input[placeholder*='Tìm kiếm']",
    "input[placeholder*='Tim kiem']",
    "input[placeholder*='Search']",
]
CHAT_INPUT_SELECTORS = [
    "#richInput",
    "#chatInput",
    "[placeholder*='Nhập @']",
    "[placeholder*='tin nhắn tới']",
    "[placeholder*='tin nhan toi']",
    "[aria-label*='Nhập']",
    "[aria-label*='tin nhắn tới']",
    "[role='textbox']",
    "footer [contenteditable='true']",
    "div[contenteditable='true']",
]
LOGIN_READY_SELECTORS = SEARCH_INPUT_SELECTORS + ["div[data-id]"]
COMMAND_RE = re.compile(r"/(nhacviec|xemviec|hotrobai|lapkehoach|help|hoc|ghinho)\b(.*)", re.IGNORECASE | re.DOTALL)


def _log_event(event: str, **kwargs) -> None:
    entry = {
        "ts": local_now().isoformat(timespec="seconds"),
        "event": event,
        **kwargs,
    }
    print(json.dumps(entry, ensure_ascii=False), flush=True)


def _serialize_error(exc: Exception) -> dict:
    return {"type": type(exc).__name__, "message": str(exc)}


def _load_runtime_state() -> dict:
    if not BOT_STATE_FILE.exists():
        return {}
    try:
        return json.loads(BOT_STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_runtime_state(state: dict) -> None:
    BOT_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _today_key() -> str:
    return local_today_key()


def _is_at_or_after_reminder_time(now: datetime) -> bool:
    return (now.hour, now.minute) >= (REMINDER_HOUR, REMINDER_MINUTE)


def _platform_modifier() -> str:
    return "Meta" if sys.platform == "darwin" else "Control"


def _extract_command(text: str) -> tuple[str, str] | None:
    match = COMMAND_RE.search(text or "")
    if not match:
        return None
    command = match.group(1).strip().lower()
    payload = match.group(2).strip()
    return command, payload


def _strip_bot_mentions(text: str) -> str:
    cleaned = text or ""
    known_names = {
        *BOT_ALIASES,
        *BOT_NAMES,
        *BOT_NAME_ALIASES,
        "Nhân Viên Mới Yok Đôn",
        "Nhân Viên Mới",
        "Nhan Vien Moi Yok Don",
        "Nhan Vien Moi",
        "bot ai",
    }
    for alias in sorted(known_names, key=len, reverse=True):
        alias_text = alias.lstrip("@")
        if not alias_text:
            continue
        cleaned = re.sub(rf"@?\s*{re.escape(alias_text)}", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"@?\s*Nhân\s+Viên\s+Mới(?:\s+Yok\s+Đôn)?", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"@?\s*Nhan\s+Vien\s+Moi(?:\s+Yok\s+Don)?", " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    without_marks = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return without_marks.replace("đ", "d").replace("Đ", "D")


def _simplify_text(value: str) -> str:
    raw = _strip_accents(value or "").lower()
    raw = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _compact_text(value: str) -> str:
    return re.sub(r"[^a-z0-9@]+", "", _simplify_text(value))


def _build_bot_aliases() -> list[str]:
    aliases: set[str] = set()
    for name in [*BOT_NAMES, *BOT_NAME_ALIASES]:
        simplified = _simplify_text(name)
        if not simplified:
            continue
        aliases.add(simplified)
        aliases.add(f"@{simplified}")
        aliases.add(simplified.replace(" ", ""))
        if simplified.startswith("nhan vien moi "):
            aliases.add("nhan vien moi")
            aliases.add("@nhan vien moi")
    return sorted((alias for alias in aliases if len(alias) >= 4), key=len, reverse=True)


BOT_ALIASES = _build_bot_aliases()


def _find_bot_mention_alias(text: str) -> str:
    normalized = _simplify_text(text).replace("@ ", "@")
    if not normalized:
        return ""
    compact = _compact_text(normalized)
    for alias in BOT_ALIASES:
        alias_normalized = _simplify_text(alias).replace("@ ", "@")
        if alias_normalized and alias_normalized in normalized:
            return alias

        alias_compact = _compact_text(alias_normalized)
        if alias_compact and alias_compact in compact:
            return alias
    return ""


def _is_bot_mentioned(text: str) -> bool:
    return bool(_find_bot_mention_alias(text))


REMINDER_TASK_STARTERS = (
    "truoc",
    "truoc khi",
    "cap",
    "cap nhat",
    "dang",
    "dang bai",
    "di",
    "don",
    "bo sung",
    "lam",
    "gui",
    "goi",
    "goi dien",
    "nhan",
    "nhan tin",
    "bao",
    "bao lai",
    "chuan bi",
    "hop",
    "len",
    "kiem tra",
    "test",
)
REMINDER_TEMPORAL_FILLERS_RE = re.compile(
    r"^(?:sáng|sang|chiều|chieu|tối|toi|trưa|trua|ngày|ngay|mai|vào|vao|lúc|luc)\s+",
    re.IGNORECASE,
)


def _looks_like_custom_reminder_request(text: str) -> bool:
    if _extract_command(text):
        return False
    normalized = _simplify_text(_strip_bot_mentions(text))
    return bool(
        re.search(
            r"\b(?:nhac|nho\s+nhac|nho\s+em\s+nhac|em\s+nhac)\s+(?:anh|a|chi|co|chu|bac|em)\b",
            normalized,
        )
    )


def _parse_time_from_text(text: str) -> tuple[int | None, int | None, list[tuple[int, int]]]:
    spans: list[tuple[int, int]] = []
    match = re.search(r"\b(\d{1,2})(?::|h)(\d{0,2})\b", text or "", flags=re.IGNORECASE)
    if not match:
        return None, None, spans

    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None, None, spans

    normalized = _simplify_text(text)
    if any(word in normalized for word in ("chieu", "toi")) and 1 <= hour <= 11:
        hour += 12

    start, end = match.span()
    # Remove nearby Vietnamese time-of-day hints, e.g. "08:00 sáng".
    suffix = re.match(r"\s*(?:sáng|sang|chiều|chieu|tối|toi|trưa|trua)\b", text[end:], flags=re.IGNORECASE)
    if suffix:
        end += suffix.end()
    prefix = re.search(r"(?:vào|vao|lúc|luc)\s*$", text[:start], flags=re.IGNORECASE)
    if prefix:
        start = prefix.start()

    spans.append((start, end))
    return hour, minute, spans


def _parse_date_from_text(text: str, now: datetime) -> tuple[datetime.date | None, list[tuple[int, int]]]:
    spans: list[tuple[int, int]] = []
    match = re.search(
        r"(?:ngày|ngay)?\s*\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b",
        text or "",
        flags=re.IGNORECASE,
    )
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year_raw = match.group(3)
        year = int(year_raw) if year_raw else now.year
        if year < 100:
            year += 2000
        try:
            spans.append(match.span())
            return datetime(year, month, day, tzinfo=now.tzinfo).date(), spans
        except ValueError:
            return None, []

    relative = re.search(r"\b(?:sáng\s+mai|sang\s+mai|ngày\s+mai|ngay\s+mai|mai)\b", text or "", flags=re.IGNORECASE)
    if relative:
        spans.append(relative.span())
        return (now + timedelta(days=1)).date(), spans

    return None, spans


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    chunks = []
    cursor = 0
    for start, end in sorted(spans):
        chunks.append(text[cursor:start])
        cursor = max(cursor, end)
    chunks.append(text[cursor:])
    return re.sub(r"\s+", " ", "".join(chunks)).strip(" ,.;:-")


def _split_reminder_target_and_task(text_without_time: str) -> tuple[str, str]:
    words = (text_without_time or "").strip().split()
    if len(words) < 3:
        return "", ""

    first = _simplify_text(words[0])
    if first not in {"anh", "a", "chi", "co", "chu", "bac", "em"}:
        return "", ""

    boundary = len(words)
    for index in range(1, len(words)):
        one = _simplify_text(words[index])
        two = _simplify_text(" ".join(words[index : index + 2]))
        if one in REMINDER_TASK_STARTERS or two in REMINDER_TASK_STARTERS:
            boundary = index
            break

    if boundary <= 1 or boundary >= len(words):
        return "", ""

    target_words = words[:boundary]
    if _simplify_text(target_words[0]) == "a":
        target_words[0] = "anh"
    target = " ".join(target_words).strip(" ,.;:-")
    task = " ".join(words[boundary:]).strip(" ,.;:-")
    while True:
        updated = REMINDER_TEMPORAL_FILLERS_RE.sub("", task).strip(" ,.;:-")
        if updated == task:
            break
        task = updated
    task = re.sub(r"\s+(?:vào|vao|lúc|luc)$", "", task, flags=re.IGNORECASE).strip(" ,.;:-")
    while True:
        updated = re.sub(
            r"\s+(?:nhé|nhe|nha|ạ|giúp\s+em|giup\s+em)$",
            "",
            task,
            flags=re.IGNORECASE,
        ).strip(" ,.;:-")
        if updated == task:
            break
        task = updated
    return target, task


def _parse_custom_reminder_request(text: str, chat_name: str, now: datetime | None = None) -> dict | None:
    if not _looks_like_custom_reminder_request(text):
        return None

    now = now or local_now()
    cleaned = _strip_bot_mentions(text)
    match = re.search(r"\bnhắc\s+(.+)$|\bnhac\s+(.+)$", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return {"error": "missing_content"}

    reminder_body = (match.group(1) or match.group(2) or "").strip(" ,.;:-")
    hour, minute, time_spans = _parse_time_from_text(reminder_body)
    due_date, date_spans = _parse_date_from_text(reminder_body, now)
    body_without_time = _remove_spans(reminder_body, [*time_spans, *date_spans])
    target, task = _split_reminder_target_and_task(body_without_time)
    if not target or not task:
        return {"error": "missing_target_or_task"}

    if hour is None:
        hour = CUSTOM_REMINDER_DEFAULT_HOUR
        minute = CUSTOM_REMINDER_DEFAULT_MINUTE
    if minute is None:
        minute = 0

    if due_date is None:
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if time_spans and candidate > now:
            due_at = candidate
        else:
            due_at = candidate + timedelta(days=1)
    else:
        due_at = datetime.combine(due_date, datetime.min.time(), tzinfo=now.tzinfo).replace(
            hour=hour,
            minute=minute,
        )

    if due_at <= now:
        due_at = due_at + timedelta(days=1)

    created_at = now.isoformat(timespec="seconds")
    reminder_id = f"rem-{int(now.timestamp())}-{abs(hash((chat_name, target, task, due_at.isoformat()))) % 100000}"
    return {
        "id": reminder_id,
        "chat_name": chat_name or ZALO_GROUP_NAME,
        "target": target,
        "task": task,
        "due_at": due_at.isoformat(timespec="seconds"),
        "created_at": created_at,
        "source_text": text,
        "sent": False,
    }


def _format_reminder_due_at(value: str) -> str:
    due_at = datetime.fromisoformat(value)
    return due_at.strftime("%H:%M ngày %d/%m/%Y")


def _build_custom_reminder_confirmation(reminder: dict) -> str:
    return (
        "Em đã ghi nhớ.\n"
        f"- Sẽ nhắc: {reminder['target']}\n"
        f"- Lúc: {_format_reminder_due_at(reminder['due_at'])}\n"
        f"- Việc: {reminder['task']}"
    )


def _build_due_custom_reminder_message(reminder: dict) -> str:
    target = reminder.get("target", "Anh/Chị")
    task = reminder.get("task", "việc đã hẹn")
    return f"{target} ơi, em nhắc việc: {task}."


def _save_custom_reminder(reminder: dict) -> None:
    state = _load_runtime_state()
    reminders = state.setdefault("custom_reminders", [])
    reminders.append(reminder)
    _save_runtime_state(state)


def _is_group_text_directed_to_bot(text: str) -> bool:
    """Zalo native mentions can be stripped from bubble text; keep safe direct-ask fallback."""
    normalized = _simplify_text(text)
    if not normalized:
        return False

    direct_bot_questions = (
        "em co the lam gi",
        "em co the lam duoc gi",
        "em giup duoc gi",
        "em biet lam gi",
        "nhiem vu cua em",
        "vai tro cua em",
        "em la ai",
        "gioi thieu ve em",
        "hom nay co nhiem vu",
        "hom nay co viec",
        "hom nay can lam",
        "hom nay can thuc hien",
        "nhiem vu nao can thuc hien",
        "3 ngay toi",
        "ba ngay toi",
        "sap toi co viec",
        "sap den han",
    )
    return any(pattern in normalized for pattern in direct_bot_questions)


def _should_reply(chat_type: str, text: str) -> bool:
    if not text.strip():
        return False
    if _extract_command(text):
        return True
    if _looks_like_custom_reminder_request(text):
        return True
    if chat_type == "personal":
        return True
    matched_alias = _find_bot_mention_alias(text)
    if chat_type == "group" and matched_alias:
        _log_event("group.mention.matched", alias=matched_alias, text=(text or "")[:200])
    elif chat_type == "group" and _is_group_text_directed_to_bot(text):
        _log_event("group.directed.matched", text=(text or "")[:200])
        return True
    elif chat_type == "group":
        _log_event(
            "group.ignored",
            reason="no_bot_mention",
            aliases=BOT_ALIASES[:8],
            text=(text or "")[:200],
        )
    return bool(matched_alias)


def _build_help_message() -> str:
    sheet_url = get_sheet_public_url() or "(chua cau hinh Sheet)"
    return "\n".join(
        [
            "HUONG DAN SU DUNG BOT",
            "=" * 28,
            "",
            "/nhacviec - Doc Sheet va gui ban nhac viec hien tai.",
            "/xemviec - Liet ke cac viec chua xong.",
            "/lapkehoach - Nhac moi nguoi cap nhat ke hoach bai viet tiep theo.",
            "/hotrobai <yeu cau> - Du thao noi dung truyen thong.",
            "/hoc <dieu can nho> - Day bot mot ghi nho moi.",
            "/help - Xem lai huong dan.",
            "Nhac viec tu nhien: nhac anh Phuong 08:00 sang ngay 26/4/2026 cap nhat ke hoach.",
            "",
            f"Sheet hien tai: {sheet_url}",
        ]
    )


def _build_plan_request_message() -> str:
    sheet_url = get_sheet_public_url() or "(chua cau hinh Sheet)"
    return (
        "Các anh ơi, hãy lên kế hoạch các bài viết tiếp theo vào link: "
        f"{sheet_url} giúp em đi. Chỉ một chút thôi mà."
    )


def _clean_relay_target(value: str) -> str:
    target = re.split(
        r"\s+(?:một|mot|1)\s+tiếng\b|\s+(?:nhé|nhe|nha|giúp|giup|ạ|a)\b",
        (value or "").strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return target.strip(" .,!?:;")


def _clean_complex_relay_target(value: str) -> str:
    """Lay rieng ten nguoi/doi tuong, khong gom cac yeu cau phu nhu 'va khen...'."""
    target = _clean_relay_target(value)
    target = re.split(
        r"\s+(?:và|va|rồi|roi)\s+(?:khen|chúc|chuc|nhắc|nhac|mời|moi|nói|noi|báo|bao|cảm ơn|cam on|xin lỗi|xin loi)\b",
        target,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return target.strip(" .,!?:;")


def _pronoun_for_target(target: str) -> str:
    first_word = (target or "").strip().split(" ", 1)[0].lower()
    normalized = _simplify_text(first_word)
    if normalized in {"anh", "chi", "co", "chu", "bac", "em"}:
        return first_word
    return "Anh/Chị"


def _build_group_greeting_message(target: str) -> str:
    pronoun = _pronoun_for_target(target)
    return (
        f"Em chào {target}, chào mừng {target} đến với nhóm Truyền thông "
        f"của Vườn quốc gia Yok Đôn, {pronoun} có cần em hỗ trợ gì không ạ?"
    )


COMPLEX_RELAY_KEYWORDS = (
    "khen",
    "chuc mung",
    "chuc",
    "nhac",
    "moi",
    "cam on",
    "xin loi",
    "dong vien",
    "gioi thieu",
    "thong bao",
    "nhan tien",
    "bao giup",
)
UNSAFE_RELAY_KEYWORDS = (
    "chui",
    "chửi",
    "mắng",
    "đe dọa",
    "de doa",
    "dọa",
    "doa",
    "xuc pham",
    "xúc phạm",
    "mat day",
    "mất dạy",
)


def _looks_like_complex_relay(text: str, candidate_message: str = "") -> bool:
    normalized = _simplify_text(f"{text} {candidate_message}")
    return any(keyword in normalized for keyword in COMPLEX_RELAY_KEYWORDS)


def _looks_like_unsafe_relay(text: str) -> bool:
    normalized = _simplify_text(text)
    return any(keyword in normalized for keyword in UNSAFE_RELAY_KEYWORDS)


def _fallback_complex_greeting_message(target: str, request_text: str) -> str:
    pronoun = _pronoun_for_target(target)
    lines = [
        f"Em chào {target} ạ.",
    ]
    if "khen" in _simplify_text(request_text):
        lines.append(f"Em xin phép khen {pronoun} một câu: hôm nay {pronoun} rất phong độ và dễ mến.")
    lines.append(
        f"Chào mừng {pronoun} đến với nhóm Truyền thông của Vườn quốc gia Yok Đôn; "
        f"{pronoun} cần em hỗ trợ gì cứ nhắn em nhé."
    )
    return " ".join(lines)


def _extract_group_relay_request(text: str) -> dict | None:
    """Nhan dien yeu cau ca nhan de bot nhan sang nhom cau hinh san."""
    if not text or _extract_command(text):
        return None

    normalized = _simplify_text(text)
    if not normalized:
        return None

    if _looks_like_unsafe_relay(text):
        return {
            "blocked": True,
            "message": "Em chưa gửi nội dung này vào nhóm vì nội dung có thể gây mất thiện cảm. Anh điều chỉnh lại lời nhắn giúp em nhé.",
            "fallback": "",
            "needs_llm": False,
        }

    # Mau an toan: "em hay vao chao anh Ba 1 tieng nhe".
    greeting_trigger = re.search(
        r"\b(?:vao|sang|qua|toi)\s+(?:nhom\s+)?chao\b",
        normalized,
    )
    if greeting_trigger:
        match = re.search(
            r"(?:vào|vao|sang|qua|tới|toi)\s+(?:nhóm\s+|nhom\s+)?(?:chào|chao)\s+(.+)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            raw_target = match.group(1)
            target = _clean_complex_relay_target(raw_target)
            if target:
                simple_message = _build_group_greeting_message(target)
                complex_message = _fallback_complex_greeting_message(target, text)
                needs_llm = _looks_like_complex_relay(text, raw_target)
                return {
                    "blocked": False,
                    "message": simple_message,
                    "fallback": complex_message if needs_llm else simple_message,
                    "needs_llm": needs_llm,
                }

    # Mau an toan cho noi dung tu do: "nhan vao nhom rang <noi dung>".
    relay_trigger = re.search(
        r"\b(?:nhan|gui|noi|bao)\s+(?:tin\s+)?(?:vao|sang|toi|trong)\s+(?:nhom|group)\b",
        normalized,
    )
    if relay_trigger:
        match = re.search(
            r"(?:rằng|rang|là|la|:)\s*(.+)$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            message = match.group(1).strip(" \n\t\"'“”")
            if message:
                return {
                    "blocked": False,
                    "message": message,
                    "fallback": message,
                    "needs_llm": _looks_like_complex_relay(text, message),
                }

    return None


def _clean_group_relay_llm_output(value: str, fallback: str) -> str:
    cleaned = (value or "").strip().strip("\"'“”")
    cleaned = re.sub(r"(?i)^\s*(nội dung gửi nhóm|tin nhắn gửi nhóm)\s*:\s*", "", cleaned).strip()
    if not cleaned:
        return fallback
    if _looks_like_unsafe_relay(cleaned):
        return fallback
    if len(cleaned) > 700:
        return cleaned[:700].rsplit(" ", 1)[0].strip() + "..."
    return cleaned


async def _build_group_relay_message(text: str) -> dict | None:
    request = _extract_group_relay_request(text)
    if not request:
        return None
    if request.get("blocked"):
        return request
    if not request.get("needs_llm"):
        return request

    fallback = request.get("fallback") or request.get("message") or ""
    rewritten = await rewrite_group_relay_message(text, fallback)
    request["message"] = _clean_group_relay_llm_output(rewritten, fallback)
    return request


def _extract_group_relay_message(text: str) -> str:
    """Ham dong bo cho test/logic cu: tra ve cau fallback neu nhan dien duoc."""
    request = _extract_group_relay_request(text)
    if not request or request.get("blocked"):
        return ""
    return request.get("fallback") or request.get("message") or ""


def _normalize_text(value: str) -> str:
    return _simplify_text(value)


def _looks_like_onboarding_text(value: str) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return False
    return any(pattern in normalized for pattern in ONBOARDING_PATTERNS)


def _format_tasks_for_context(limit: int = 12) -> str:
    tasks = fetch_all_tasks()
    pending = [task for task in tasks if not task.is_completed]
    pending.sort(key=lambda task: task.due_date or datetime.max)

    lines = [f"Co {len(tasks)} dong cong viec, trong do {len(pending)} viec chua xong."]
    for task in pending[:limit]:
        due = task.due_date_raw or "chua ro ngay"
        assignee = task.assignee or "chua giao"
        status = task.status or "chua cap nhat"
        notes = task.notes or ""
        notes_part = f" | luu y: {notes}" if notes else ""
        lines.append(f"- [{due}] {task.topic} | phu trach: {assignee} | trang thai: {status}{notes_part}")

    if len(pending) > limit:
        lines.append(f"- Con {len(pending) - limit} viec chua xong khac.")
    return "\n".join(lines)


def _build_ai_context() -> str:
    sections = []

    try:
        sections.append("TOM TAT BANG CONG VIEC:")
        sections.append(_format_tasks_for_context())
    except Exception as exc:
        sections.append(f"Khong doc duoc Google Sheet: {exc}")

    learning_context = get_learning_context(limit=10)
    if learning_context:
        sections.append("")
        sections.append(learning_context)

    return "\n".join(section for section in sections if section).strip()


async def _get_visible_locator(page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() > 0 and await locator.is_visible():
                return locator
        except PlaywrightError:
            continue
    return None


async def _focus_chat_input(page):
    locator = await _get_visible_locator(page, CHAT_INPUT_SELECTORS)
    if locator:
        await locator.click()
        return locator
    return None


async def _dismiss_blocking_modal(page) -> bool:
    try:
        clicked = await page.evaluate(
            """
            () => {
                const normalize = (value) => (value || '')
                    .normalize('NFD')
                    .replace(/[\\u0300-\\u036f]/g, '')
                    .replace(/đ/g, 'd')
                    .replace(/Đ/g, 'D')
                    .toLowerCase()
                    .trim();
                const isVisible = (node) => {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    const rect = node.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 80 && rect.height > 40;
                };
                const modals = [...document.querySelectorAll('.zl-modal, [id^="zl-modal"], [class*="modal"]')]
                    .filter(isVisible)
                    .reverse();
                for (const modal of modals) {
                    const candidates = [...modal.querySelectorAll('button, [role="button"], div, span')]
                        .filter((node) => {
                            const rect = node.getBoundingClientRect();
                            const text = (node.innerText || node.textContent || '').trim();
                            return text && rect.width > 24 && rect.height > 16;
                        });
                    const preferred = candidates.find((node) => {
                        const text = normalize(node.innerText || node.textContent || '');
                        return /^(dong y|dong bo|dong bo ngay|tiep tuc|da hieu|ok|dong|bo qua|de sau|huy|cancel|later|skip)$/.test(text);
                    });
                    if (preferred) {
                        preferred.click();
                        return (preferred.innerText || preferred.textContent || '').trim() || 'modal_button';
                    }

                    const close = [...modal.querySelectorAll('[class*="close"], [aria-label*="close"], [aria-label*="đóng"], [data-id*="Close"]')]
                        .find((node) => {
                            const rect = node.getBoundingClientRect();
                            return rect.width > 8 && rect.height > 8;
                        });
                    if (close) {
                        close.click();
                        return 'modal_close';
                    }

                    // Zalo sometimes shows a modal layer without a reliable close button.
                    // Removing it is safer than letting it block all automation forever.
                    modal.remove();
                    return 'modal_removed';
                }
                return '';
            }
            """
        )
        if clicked:
            _log_event("modal.dismissed", action=clicked)
            await page.wait_for_timeout(1000)
            return True
    except Exception as exc:
        _log_event("modal.dismiss_error", error=_serialize_error(exc))
    return False


async def _click_search_input_with_modal_retry(page, search_input, chat_name: str) -> bool:
    try:
        await search_input.click(timeout=5000)
        return True
    except PlaywrightError as exc:
        _log_event("chat.open.search_click_blocked", chat=chat_name, error=_serialize_error(exc))

    dismissed = await _dismiss_blocking_modal(page)
    if not dismissed:
        _log_event("chat.open.failed", reason="search_click_blocked", chat=chat_name)
        return False

    search_input = await _get_visible_locator(page, SEARCH_INPUT_SELECTORS)
    if search_input is None:
        _log_event("chat.open.failed", reason="search_input_not_found_after_modal", chat=chat_name)
        return False

    try:
        await search_input.click(timeout=5000)
        return True
    except PlaywrightError as exc:
        _log_event("chat.open.failed", reason="search_click_retry_failed", chat=chat_name, error=_serialize_error(exc))
        return False


async def _clear_sidebar_search_filter(page) -> bool:
    search_input = await _get_visible_locator(page, SEARCH_INPUT_SELECTORS)
    if search_input is None:
        return False

    try:
        current_value = await search_input.input_value(timeout=1000)
    except Exception:
        current_value = ""

    if not current_value:
        return False

    try:
        await search_input.fill("")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)
        _log_event("search_filter.cleared", previous=current_value[:80])
        return True
    except Exception as exc:
        _log_event("search_filter.clear_error", error=_serialize_error(exc))
        return False


async def _maybe_click_sync_recent_messages(page) -> bool:
    candidates = [
        page.get_by_text("Nhấn để đồng bộ ngay"),
        page.get_by_text("Đồng bộ ngay"),
        page.get_by_text("Dong bo ngay"),
        page.get_by_text("Đồng bộ"),
    ]

    for locator in candidates:
        candidate = locator.first
        try:
            if await candidate.count() > 0 and await candidate.is_visible():
                await candidate.click()
                _log_event("sync.clicked")
                await page.wait_for_timeout(2000)
                await _dismiss_blocking_modal(page)

                follow_up_buttons = [
                    page.get_by_role("button", name="Đồng ý"),
                    page.get_by_role("button", name="Dong y"),
                    page.get_by_role("button", name="Đồng bộ"),
                    page.get_by_role("button", name="Đồng bộ ngay"),
                ]
                for button in follow_up_buttons:
                    follow_up = button.first
                    if await follow_up.count() > 0 and await follow_up.is_visible():
                        await follow_up.click()
                        _log_event("sync.confirmed")
                        await page.wait_for_timeout(2500)
                        break
                return True
        except PlaywrightError:
            continue
        except Exception as exc:
            _log_event("sync.error", error=_serialize_error(exc))
            return False
    return False


async def _send_message(page, text: str) -> bool:
    _log_event("reply.start", length=len(text))
    try:
        input_box = await _focus_chat_input(page)
        if input_box is None:
            raise RuntimeError("Khong tim thay o nhap tin nhan.")

        modifier = _platform_modifier()
        await input_box.click()
        try:
            await input_box.fill("")
            await input_box.fill(text)
            input_method = "locator.fill"
        except Exception:
            # Zalo Web occasionally exposes the composer as a custom contenteditable
            # where Playwright fill() is rejected. In that case, update the DOM and
            # dispatch input events so Zalo's internal state receives the full text.
            await input_box.evaluate(
                """
                (node, text) => {
                    node.focus();
                    if ('value' in node) {
                        node.value = text;
                    } else {
                        node.innerText = text;
                    }
                    node.dispatchEvent(new InputEvent('input', {
                        bubbles: true,
                        cancelable: true,
                        inputType: 'insertText',
                        data: text,
                    }));
                    node.dispatchEvent(new Event('change', { bubbles: true }));
                }
                """,
                text,
            )
            input_method = "dom.input"

        composer_text = await input_box.evaluate(
            """
            (node) => {
                if ('value' in node) return node.value || '';
                return node.innerText || node.textContent || '';
            }
            """
        )
        expected_tail = next((line for line in reversed(text.splitlines()) if line.strip()), "")
        if expected_tail and expected_tail not in composer_text:
            await page.keyboard.press(f"{modifier}+A")
            await page.keyboard.press("Delete")
            await page.wait_for_timeout(200)
            await page.keyboard.insert_text(text)
            input_method = f"{input_method}+keyboard.insert_text"
            composer_text = await input_box.evaluate(
                """
                (node) => {
                    if ('value' in node) return node.value || '';
                    return node.innerText || node.textContent || '';
                }
                """
            )

        await page.wait_for_timeout(300)
        await page.keyboard.press("Enter")
        _log_event("reply.success", preview=text[:80], input_method=input_method, composer_length=len(composer_text))
        return True
    except Exception as exc:
        _log_event("reply.error", error=_serialize_error(exc))
        return False


async def _capture_chat_state(page) -> dict:
    try:
        return await page.evaluate(
            """
            () => {
                const header = document.querySelector('header') || document.querySelector('[class*="header"]');
                const headerText = header ? header.innerText || '' : '';
                const headerLines = headerText
                    .split('\\n')
                    .map((line) => line.trim())
                    .filter(Boolean);

                const pageText = document.body.innerText || '';
                const onboardingPatterns = [
                    'Chào mừng đến với Zalo PC',
                    'Chao mung den voi Zalo PC',
                    'Khám phá những tiện ích',
                    'Trải nghiệm xuyên suốt',
                    'Đồng bộ tin nhắn gần đây',
                    'Dong bo tin nhan gan day',
                ];
                const isOnboarding = onboardingPatterns.some((pattern) => pageText.includes(pattern));

                const isVisible = (node) => {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = node.getBoundingClientRect();
                    return rect.width > 40 && rect.height > 10;
                };

                const composer = ['#richInput', '#chatInput', '[placeholder*="Nhập @"]', '[placeholder*="tin nhắn tới"]', '[placeholder*="tin nhan toi"]', '[role="textbox"]', 'footer [contenteditable="true"]', 'div[contenteditable="true"]']
                    .flatMap((selector) => [...document.querySelectorAll(selector)])
                    .find((node) => {
                        if (!isVisible(node)) return false;
                        const rect = node.getBoundingClientRect();
                        return rect.top > (window.innerHeight - 120) && rect.right > (window.innerWidth * 0.55);
                    });

                const root = document.querySelector('#chat-root') || document.body;
                const rootRect = root.getBoundingClientRect();
                const sidebarRight = Math.min(Math.max(window.innerWidth * 0.32, 320), 520);
                const mainLeft = sidebarRight;
                const centerX = mainLeft + (window.innerWidth - mainLeft) / 2;
                const composerTop = composer ? composer.getBoundingClientRect().top : window.innerHeight - 100;
                const normalizedHeader = headerText.toLowerCase();

                let chatType = 'unknown';
                if (normalizedHeader.includes('thành viên') || normalizedHeader.includes('thanh vien') || normalizedHeader.includes('members')) {
                    chatType = 'group';
                } else if (composer && !isOnboarding) {
                    chatType = 'personal';
                }

                const isUtilityLine = (value) => {
                    const text = (value || '').trim();
                    if (!text) return true;
                    if (/^\\d{1,3}$/.test(text)) return true;
                    if (/^\\d{1,2}:\\d{2}$/.test(text)) return true;
                    if (/\\d+\\s+(thành viên|thanh vien|members)$/i.test(text)) return true;
                    return false;
                };

                const chatName = headerLines.find((line) => !isUtilityLine(line)) || '';
                const normalizedChatName = chatName.toLowerCase();
                const isUtilityMessage = (value) => {
                    const text = (value || '').trim();
                    if (!text) return true;

                    const normalized = text.toLowerCase();
                    const lines = text.split('\\n').map((line) => line.trim()).filter(Boolean);
                    const looksLikeEmojiShortcut = (line) => {
                        if (/^\\/-[a-z0-9_-]+$/i.test(line)) return true;
                        if (/^[:;=8xX][-']?[)(DPpOo>/\\\\|]$/.test(line)) return true;
                        if (/^:-\\(\\($/.test(line)) return true;
                        if (/^:-[a-z]$/i.test(line)) return true;
                        return false;
                    };
                    if (lines.length >= 3 && lines.every(looksLikeEmojiShortcut)) return true;

                    if (isUtilityLine(text)) return true;
                    if (normalized === normalizedChatName) return true;
                    if (normalized === 'hôm nay' || normalized === 'hom nay') return true;
                    if (normalized === 'hôm qua' || normalized === 'hom qua') return true;
                    if (normalized === 'đã nhận' || normalized === 'da nhan') return true;
                    if (normalized.includes('đang soạn tin') || normalized.includes('dang soan tin')) return true;
                    if (normalized === 'tin nhắn' || normalized === 'tin nhan') return true;
                    if (normalized === 'tải về để xem lâu dài' || normalized === 'tai ve de xem lau dai') return true;
                    if (normalized.startsWith('sử dụng ứng dụng zalo pc') || normalized.startsWith('su dung ung dung zalo pc')) return true;
                    if (normalized.startsWith('sử dụng zalo pc để tìm tin nhắn trước ngày') || normalized.startsWith('su dung zalo pc de tim tin nhan truoc ngay')) return true;
                    if (normalized.startsWith('chào mừng đến với zalo pc') || normalized.startsWith('chao mung den voi zalo pc')) return true;
                    return false;
                };

                const nodes = [...document.querySelectorAll('div, span')]
                    .filter((el) => {
                        const rect = el.getBoundingClientRect();
                        if (rect.left < mainLeft + 12 || rect.right > window.innerWidth - 12) return false;
                        if (rect.width < 40 || rect.height < 14) return false;
                        const text = (el.innerText || '').trim();
                        const looksLikeCommand = /^\\/(nhacviec|xemviec|hotrobai|lapkehoach|help|hoc|ghinho)\\b/i.test(text);
                        if (!looksLikeCommand && rect.width > (window.innerWidth - mainLeft) * 0.78) return false;
                        if (rect.top < 90 || rect.bottom > composerTop - 10) return false;
                        return text && text.length < 3000;
                    })
                    .map((el) => {
                        const rect = el.getBoundingClientRect();
                        return {
                            text: (el.innerText || '').trim(),
                            top: rect.top,
                            left: rect.left,
                            isMe: rect.left > centerX,
                        };
                    })
                    .sort((a, b) => a.top - b.top);

                const unique = [];
                const seen = new Set();
                for (const item of nodes) {
                    const key = `${item.top}|${item.text}`;
                    if (!seen.has(key)) {
                        unique.push(item);
                        seen.add(key);
                    }
                }

                return {
                    chatName,
                    chatType,
                    isOnboarding,
                    incomingMessages: unique.filter((item) => !item.isMe && !isUtilityMessage(item.text)).map((item) => item.text).slice(-10),
                    visibleMessages: unique.map((item) => item.text).slice(-20),
                    hasComposer: Boolean(composer),
                };
            }
            """
        )
    except Exception as exc:
        _log_event("chat_state.error", error=_serialize_error(exc))
        return {}


async def _scan_for_red_badges(page) -> list[dict]:
    try:
        return await page.evaluate(
            """
            () => {
                const hits = [];
                for (const el of document.querySelectorAll('div, span')) {
                    const rect = el.getBoundingClientRect();
                    if (rect.left < 40 || rect.left > 760 || rect.top < 80 || rect.top > window.innerHeight - 20) continue;
                    const style = window.getComputedStyle(el);
                    const bg = style.backgroundColor || '';
                    const match = bg.match(/rgb\\((\\d+),\\s*(\\d+),\\s*(\\d+)\\)/);
                    if (!match) continue;

                    const r = Number(match[1]);
                    const g = Number(match[2]);
                    const b = Number(match[3]);
                    if (!(r > 200 && g < 120 && b < 120)) continue;

                    let parent = el.parentElement;
                    while (parent) {
                        const parentRect = parent.getBoundingClientRect();
                        if (parentRect.width > 220 && parentRect.height > 44) break;
                        parent = parent.parentElement;
                    }
                    if (!parent) continue;

                    const parentRect = parent.getBoundingClientRect();
                    if (parentRect.left > 760 || parentRect.width < 220 || parentRect.height < 44) continue;

                    hits.push({
                        x: Math.min(parentRect.left + 120, parentRect.right - 40),
                        y: parentRect.top + parentRect.height / 2,
                        width: parentRect.width,
                        text: (parent.innerText || '').trim().slice(0, 120),
                    });
                }

                const unique = [];
                const seen = new Set();
                for (const hit of hits) {
                    const key = `${Math.round(hit.x / 10)}:${Math.round(hit.y / 10)}`;
                    if (!seen.has(key)) {
                        seen.add(key);
                        unique.push(hit);
                    }
                }
                return unique;
            }
            """
        )
    except Exception as exc:
        _log_event("badge_scan.error", error=_serialize_error(exc))
        return []


async def _scan_sidebar_chats(page) -> list[dict]:
    try:
        return await page.evaluate(
            """
            () => {
                const sidebarRight = Math.min(Math.max(window.innerWidth * 0.32, 320), 520);
                const allNodes = [...document.querySelectorAll('div, li, a, button')];
                const rows = [];
                const ignoredExact = new Set([
                    'Tất cả',
                    'Chưa đọc',
                    'Ưu tiên',
                    'Khác',
                    'Phân loại',
                    'Đồng bộ ngay',
                ]);

                const isTimeLike = (line) => {
                    const value = (line || '').trim().toLowerCase();
                    return Boolean(
                        value.match(/^\\d{1,2}:\\d{2}$/) ||
                        value.match(/^\\d+\\s*(phút|giờ|ngày|tuần|tháng|nam|năm)$/) ||
                        value.includes('vài giây') ||
                        value.includes('hom qua') ||
                        value.includes('hôm qua')
                    );
                };

                const extractBadgeNumber = (node) => {
                    for (const child of node.querySelectorAll('*')) {
                        const text = (child.innerText || '').trim();
                        if (!/^\\d{1,3}$/.test(text)) continue;
                        const rect = child.getBoundingClientRect();
                        if (rect.width < 10 || rect.height < 10 || rect.left < sidebarRight - 90) continue;
                        const style = window.getComputedStyle(child);
                        const bg = style.backgroundColor || '';
                        const match = bg.match(/rgb\\((\\d+),\\s*(\\d+),\\s*(\\d+)\\)/);
                        if (!match) continue;
                        const r = Number(match[1]);
                        const g = Number(match[2]);
                        const b = Number(match[3]);
                        if (r > 180 && g < 140 && b < 140) {
                            return Number(text);
                        }
                    }
                    return 0;
                };

                for (const node of allNodes) {
                    const rect = node.getBoundingClientRect();
                    if (rect.left < 30 || rect.right > sidebarRight + 40) continue;
                    if (rect.top < 70 || rect.top > window.innerHeight - 40) continue;
                    if (rect.width < 160 || rect.height < 32 || rect.height > 140) continue;

                    const text = (node.innerText || '').trim();
                    if (!text || text.length > 300) continue;
                    if (text.includes('Chào mừng đến với Zalo PC')) continue;
                    if (text.includes('Đồng bộ tin nhắn gần đây')) continue;

                    const rawLines = text.split('\\n').map((line) => line.trim()).filter(Boolean);
                    const lines = rawLines.filter((line) => !ignoredExact.has(line));
                    if (!lines.length) continue;

                    const contentLines = lines.filter((line) => !isTimeLike(line) && !/^\\d{1,3}$/.test(line));
                    if (!contentLines.length) continue;

                    const title = contentLines[0];
                    const preview = contentLines.find((line, index) => index > 0) || "";
                    if (!title) continue;
                    if (title === 'Bạn:' || title === 'Ban:') continue;

                    rows.push({
                        title,
                        preview,
                        unreadCount: extractBadgeNumber(node),
                        isMinePreview: preview.startsWith('Bạn:') || preview.startsWith('Ban:'),
                        x: Math.min(rect.left + 110, rect.right - 40),
                        y: rect.top + rect.height / 2,
                        top: rect.top,
                        width: rect.width,
                        rawText: text.slice(0, 200),
                    });
                }

                rows.sort((a, b) => a.top - b.top || b.width - a.width);
                const byTitle = new Map();
                for (const row of rows) {
                    const normalizedTitle = row.title.toLowerCase().replace(/\\s+/g, ' ').trim();
                    const existing = byTitle.get(normalizedTitle);
                    if (
                        !existing ||
                        Number(row.unreadCount || 0) > Number(existing.unreadCount || 0) ||
                        (!existing.preview && row.preview)
                    ) {
                        byTitle.set(normalizedTitle, row);
                    }
                }
                return [...byTitle.values()].sort((a, b) => a.top - b.top || b.width - a.width);
            }
            """
        )
    except Exception as exc:
        _log_event("sidebar_scan.error", error=_serialize_error(exc))
        return []


async def _find_sidebar_chat_coordinates(page, chat_name: str) -> dict | None:
    return await page.evaluate(
        """
        (needle) => {
            const search = needle.toLowerCase().trim();
            if (!search) return null;

            const candidates = [];
            for (const el of document.querySelectorAll('div, span')) {
                const text = (el.innerText || '').trim();
                if (!text) continue;
                if (!text.toLowerCase().includes(search)) continue;

                const rect = el.getBoundingClientRect();
                if (rect.left < 40 || rect.left > 420) continue;
                if (rect.top < 80 || rect.top > window.innerHeight - 20) continue;
                if (rect.width < 40 || rect.height < 16) continue;

                candidates.push({
                    x: rect.left + Math.min(rect.width / 2, 80),
                    y: rect.top + rect.height / 2,
                    len: text.length,
                });
            }

            if (!candidates.length) return null;
            candidates.sort((a, b) => a.len - b.len);
            return candidates[0];
        }
        """,
        chat_name,
    )


async def _open_chat_by_name(page, chat_name: str) -> bool:
    await _dismiss_blocking_modal(page)
    search_input = await _get_visible_locator(page, SEARCH_INPUT_SELECTORS)
    if search_input is None:
        _log_event("chat.open.failed", reason="search_input_not_found", chat=chat_name)
        return False

    if not await _click_search_input_with_modal_retry(page, search_input, chat_name):
        return False
    await search_input.fill("")
    await search_input.fill(chat_name)
    await page.wait_for_timeout(1200)

    coords = await _find_sidebar_chat_coordinates(page, chat_name)
    if not coords:
        _log_event("chat.open.failed", reason="chat_not_found", chat=chat_name)
        return False

    await page.mouse.click(coords["x"], coords["y"])
    await page.wait_for_timeout(1200)
    await _clear_sidebar_search_filter(page)
    _log_event("chat.opened", chat=chat_name)
    return True


def _is_valid_chat_title(chat_name: str) -> bool:
    normalized = _normalize_text(chat_name)
    if not normalized:
        return False
    if _looks_like_onboarding_text(normalized):
        return False
    return normalized not in {"zalo", "zalo pc"}


def _should_ignore_sidebar_chat(chat: dict) -> bool:
    title = _normalize_text(chat.get("title", ""))
    preview = _normalize_text(chat.get("preview", ""))
    raw_text = _normalize_text(chat.get("rawText", ""))

    if not title:
        return True
    if title.startswith("/"):
        return True
    if title.startswith("lien he"):
        return True
    if title.startswith("dang dong bo tin nhan") or title.startswith("dong bo tin nhan"):
        return True
    if any(_looks_like_onboarding_text(value) for value in (title, preview, raw_text)):
        return True
    if "đồng bộ tin nhắn gần đây" in raw_text or "dong bo tin nhan gan day" in raw_text:
        return True
    if title in {"my documents", "chua co tin nhan"}:
        return True
    if raw_text.startswith("su dung ung dung zalo pc de tim tin nhan truoc ngay"):
        return True
    if raw_text.startswith("su dung zalo pc de tim tin nhan truoc ngay"):
        return True
    if title.startswith("su dung ung dung zalo pc de tim tin nhan truoc ngay"):
        return True
    if title.startswith("su dung zalo pc de tim tin nhan truoc ngay"):
        return True
    return False


def _sidebar_signature(chat: dict) -> str:
    preview = _normalize_text(chat.get("preview", ""))
    unread_count = chat.get("unreadCount", 0)
    is_mine = 1 if chat.get("isMinePreview") else 0
    # Khong dua rawText vao signature vi rawText thuong chua thoi gian
    # "vài giây/1 phút", lam bot tuong moi scan deu co tin moi.
    return f"{preview}|{unread_count}|{is_mine}"


def _chat_title_matches(expected: str, actual: str) -> bool:
    expected_normalized = _normalize_text(expected).rstrip(":")
    actual_normalized = _normalize_text(actual).rstrip(":")
    if not expected_normalized or not actual_normalized:
        return False
    return expected_normalized == actual_normalized


def _select_sidebar_targets(chats: list[dict], sidebar_state: dict, bootstrapped: bool) -> tuple[list[dict], dict]:
    next_state = dict(sidebar_state)
    candidates = []
    seen_titles = set()

    for chat in chats:
        if _should_ignore_sidebar_chat(chat):
            continue

        title = chat.get("title", "").strip()
        state_key = _normalize_text(title) or title
        if state_key in seen_titles:
            continue
        seen_titles.add(state_key)
        signature = _sidebar_signature(chat)
        previous_signature = next_state.get(state_key)
        next_state[state_key] = signature

        if not bootstrapped:
            continue

        if chat.get("isMinePreview"):
            continue

        if previous_signature is None:
            if chat.get("unreadCount", 0) > 0:
                candidates.append(chat)
            continue

        if signature != previous_signature:
            candidates.append(chat)

    candidates.sort(key=lambda item: (-int(item.get("unreadCount", 0)), item.get("top", 9999)))
    return candidates, next_state


def _pick_bootstrap_chat(chats: list[dict]) -> dict | None:
    valid_chats = [chat for chat in chats if not _should_ignore_sidebar_chat(chat)]
    if not valid_chats:
        return None

    valid_chats.sort(
        key=lambda item: (
            0 if int(item.get("unreadCount", 0)) > 0 else 1,
            0 if not item.get("isMinePreview") else 1,
            item.get("top", 9999),
        )
    )
    return valid_chats[0]


async def _open_sidebar_chat(page, chat: dict) -> bool:
    try:
        expected_title = chat.get("title", "")
        await page.mouse.click(chat["x"], chat["y"])
        await page.wait_for_timeout(900)
        state = await _capture_chat_state(page)
        current_name = state.get("chatName", "")
        if (
            state.get("hasComposer")
            and _is_valid_chat_title(current_name)
            and _chat_title_matches(expected_title, current_name)
        ):
            _log_event("chat.row.opened", expected=expected_title, actual=current_name, method="point")
            return True

        clicked = await page.evaluate(
            """
            ({ title, preview, fallbackX, fallbackY }) => {
                const sidebarRight = Math.min(Math.max(window.innerWidth * 0.32, 320), 520);

                const exactCandidates = [...document.querySelectorAll('div, span, p')]
                    .filter((el) => {
                        const text = (el.innerText || '').trim();
                        if (!text) return false;
                        if (text !== title && (!preview || text !== preview)) return false;
                        const rect = el.getBoundingClientRect();
                        if (rect.left < 20 || rect.right > sidebarRight + 40) return false;
                        if (rect.top < 70 || rect.bottom > window.innerHeight - 20) return false;
                        if (rect.width < 20 || rect.height < 12) return false;
                        return true;
                    })
                    .sort((a, b) => {
                        const ra = a.getBoundingClientRect();
                        const rb = b.getBoundingClientRect();
                        return (ra.width * ra.height) - (rb.width * rb.height);
                    });

                const clickElement = (el) => {
                    if (!el) return false;

                    let clickable = el;
                    while (clickable) {
                        const rect = clickable.getBoundingClientRect();
                        if (rect.width >= 180 && rect.height >= 36 && rect.right <= sidebarRight + 40) {
                            break;
                        }
                        clickable = clickable.parentElement;
                    }
                    clickable = clickable || el;

                    const rect = clickable.getBoundingClientRect();
                    const x = Math.min(rect.left + 120, rect.right - 30);
                    const y = rect.top + rect.height / 2;
                    const target = document.elementFromPoint(x, y) || clickable;
                    const finalEl = target.closest('a, button, [role="button"], div, span') || target;

                    for (const eventName of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        finalEl.dispatchEvent(new MouseEvent(eventName, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: x,
                            clientY: y,
                            button: 0,
                        }));
                    }
                    if (typeof finalEl.click === 'function') finalEl.click();
                    return true;
                };

                for (const candidate of exactCandidates) {
                    if (clickElement(candidate)) {
                        return { ok: true, method: 'dom_text', title };
                    }
                }

                const fallbackTarget = document.elementFromPoint(fallbackX, fallbackY);
                if (fallbackTarget) {
                    if (typeof fallbackTarget.click === 'function') fallbackTarget.click();
                    return { ok: true, method: 'point_fallback', title };
                }

                return { ok: false, method: 'none', title };
            }
            """,
            {
                "title": expected_title,
                "preview": chat.get("preview", ""),
                "fallbackX": chat["x"],
                "fallbackY": chat["y"],
            },
        )
        _log_event("chat.row.click_attempt", chat=expected_title, result=clicked)
        await page.wait_for_timeout(1200)

        state = await _capture_chat_state(page)
        current_name = state.get("chatName", "")
        if (
            state.get("hasComposer")
            and _is_valid_chat_title(current_name)
            and _chat_title_matches(expected_title, current_name)
        ):
            _log_event("chat.row.opened", expected=expected_title, actual=current_name)
            return True
        if state.get("hasComposer") and _is_valid_chat_title(current_name):
            _log_event("chat.row.mismatch", expected=expected_title, actual=current_name)

        await page.mouse.dblclick(chat["x"], chat["y"])
        await page.wait_for_timeout(1200)
        state = await _capture_chat_state(page)
        current_name = state.get("chatName", "")
        ok = (
            state.get("hasComposer")
            and _is_valid_chat_title(current_name)
            and _chat_title_matches(expected_title, current_name)
        )
        if ok:
            _log_event("chat.row.opened", expected=expected_title, actual=current_name, method="dblclick")
        else:
            _log_event(
                "chat.row.open_failed",
                expected=expected_title,
                actual=current_name,
                onboarding=bool(state.get("isOnboarding")),
            )
        return bool(ok)
    except Exception as exc:
        _log_event("chat.row.click_error", chat=chat.get("title", ""), error=_serialize_error(exc))
        return False


def _build_daily_message() -> str:
    tasks = fetch_all_tasks()
    today_tasks = get_today_tasks(tasks)
    overdue_tasks = get_overdue_tasks(tasks)
    upcoming_tasks = get_upcoming_tasks(days_ahead=DAYS_AHEAD, tasks=tasks)
    unassigned_tasks = get_unassigned_tasks(tasks)
    today_empty = is_today_empty(tasks)

    message = build_daily_reminder(
        today_tasks=today_tasks,
        overdue_tasks=overdue_tasks,
        upcoming_tasks=upcoming_tasks,
        unassigned_tasks=unassigned_tasks,
        today_is_empty=today_empty,
    )
    return message or build_no_work_message()


async def _send_group_reminder(page) -> bool:
    if not await _open_chat_by_name(page, ZALO_GROUP_NAME):
        return False

    message = _build_daily_message()
    ok = await _send_message(page, message)
    if ok:
        _log_event("reminder.sent", group=ZALO_GROUP_NAME)
    return ok


async def _maybe_send_scheduled_reminder(page) -> None:
    now = local_now()
    state = _load_runtime_state()
    already_sent_today = state.get("last_daily_reminder_date") == _today_key()

    should_send_now = _is_at_or_after_reminder_time(now)
    if already_sent_today or not should_send_now:
        return

    _log_event(
        "reminder.triggered",
        scheduled_for=f"{REMINDER_HOUR:02d}:{REMINDER_MINUTE:02d}",
        timezone=LOCAL_TIMEZONE_NAME,
        local_time=now.isoformat(timespec="seconds"),
    )
    if await _send_group_reminder(page):
        state["last_daily_reminder_date"] = _today_key()
        state["last_daily_reminder_sent_at"] = now.isoformat(timespec="seconds")
        _save_runtime_state(state)


async def _maybe_send_due_custom_reminders(page) -> None:
    now = local_now()
    state = _load_runtime_state()
    reminders = state.get("custom_reminders", [])
    if not isinstance(reminders, list) or not reminders:
        return

    changed = False
    for reminder in reminders:
        if reminder.get("sent"):
            continue

        try:
            due_at = datetime.fromisoformat(reminder.get("due_at", ""))
        except ValueError:
            reminder["sent"] = True
            reminder["error"] = "invalid_due_at"
            changed = True
            continue

        if due_at > now:
            continue

        last_attempt_raw = reminder.get("last_attempt_at")
        if last_attempt_raw:
            try:
                last_attempt_at = datetime.fromisoformat(last_attempt_raw)
                if (now - last_attempt_at).total_seconds() < CUSTOM_REMINDER_RETRY_SECONDS:
                    continue
            except ValueError:
                pass

        chat_name = reminder.get("chat_name") or ZALO_GROUP_NAME
        reminder["last_attempt_at"] = now.isoformat(timespec="seconds")
        changed = True
        _log_event(
            "custom_reminder.due",
            chat=chat_name,
            target=reminder.get("target", ""),
            task=(reminder.get("task", "") or "")[:120],
            due_at=reminder.get("due_at", ""),
        )

        current_state = await _capture_chat_state(page)
        if not isinstance(current_state, dict):
            current_state = {}
        current_chat = current_state.get("chatName") or current_state.get("chatTitle") or ""
        already_in_target_chat = (
            current_state.get("hasComposer")
            and current_chat
            and _chat_title_matches(chat_name, current_chat)
        )
        if already_in_target_chat:
            _log_event("custom_reminder.chat_ready", chat=chat_name)
        elif not await _open_chat_by_name(page, chat_name):
            _log_event("custom_reminder.error", reason="chat_open_failed", chat=chat_name)
            continue

        ok = await _send_message(page, _build_due_custom_reminder_message(reminder))
        if ok:
            reminder["sent"] = True
            reminder["sent_at"] = local_now().isoformat(timespec="seconds")
            _log_event("custom_reminder.sent", chat=chat_name, reminder_id=reminder.get("id", ""))
        else:
            _log_event("custom_reminder.error", reason="send_failed", chat=chat_name)

    if changed:
        _save_runtime_state(state)


async def _handle_command(page, command: str, payload: str, chat_name: str) -> None:
    try:
        if command == "help":
            await _send_message(page, _build_help_message())
            return

        if command == "hoc" or command == "ghinho":
            if not payload:
                await _send_message(page, "Cu phap: /hoc <dieu can ghi nho>")
                return

            entry = add_learning(payload, author="zalo_user", chat_name=chat_name)
            await _send_message(
                page,
                "Em da ghi nho.\n"
                f"- Thoi gian: {entry['created_at']}\n"
                f"- Noi dung: {entry['note']}",
            )
            return

        if command == "nhacviec":
            tasks = fetch_all_tasks()
            await _send_message(page, build_today_tasks_message(get_today_tasks(tasks)))
            return

        if command == "xemviec":
            tasks = fetch_all_tasks()
            await _send_message(page, build_pending_tasks_message(tasks))
            return

        if command == "lapkehoach":
            await _send_message(page, _build_plan_request_message())
            return

        if command == "hotrobai":
            if not payload:
                await _send_message(page, "Cu phap: /hotrobai <yeu cau can du thao>")
                return

            style = resolve_facebook_style(payload)
            context = _build_ai_context()
            _log_event(
                "command.hotrobai.llm_call",
                style=style,
                payload_len=len(payload),
                payload=payload[:200],
            )
            draft = await draft_facebook_post_options(payload, style=style, context=context)
            _log_event("command.hotrobai.llm_reply", reply_len=len(draft), preview=draft[:160])
            await _send_message(page, draft)
            return

        await _send_message(page, "Lenh chua duoc ho tro. Anh/Chị go /help de xem danh sach lenh.")
    except Exception as exc:
        _log_event("command.error", command=command, error=_serialize_error(exc))
        await _send_message(page, f"Em gap loi khi xu ly lenh /{command}. Anh/Chị thu lai giup em nhe.")


async def _handle_natural_language(page, text: str, chat_type: str) -> None:
    try:
        intent = brain.classify_intent(text, chat_type)
        _log_event("brain.intent", chat_type=chat_type, intent=intent, text=text[:200])

        if intent == "today_tasks":
            tasks = fetch_all_tasks()
            reply = build_today_tasks_message(get_today_tasks(tasks))
            _log_event("sheet.today.reply", count=reply.count("* Chủ đề/Tiêu đề bài viết:"))
            await _send_message(page, reply)
            return

        if intent == "upcoming_tasks":
            tasks = fetch_all_tasks()
            reply = build_upcoming_tasks_message(get_upcoming_tasks(days_ahead=DAYS_AHEAD, tasks=tasks), days_ahead=DAYS_AHEAD)
            _log_event("sheet.upcoming.reply", count=reply.count("* Chủ đề/Tiêu đề bài viết:"))
            await _send_message(page, reply)
            return

        context = _build_ai_context()
        reply = await brain.process_message(text, chat_type, context=context)
        if reply:
            await _send_message(page, reply)
    except Exception as exc:
        _log_event("ai.error", error=_serialize_error(exc))
        await _send_message(page, "Em dang gap loi AI tam thoi. Anh/Chị thu nhan lai sau it phut giup em nhe.")


async def _handle_custom_reminder_request(page, chat_name: str, text: str) -> bool:
    reminder = _parse_custom_reminder_request(text, chat_name)
    if not reminder:
        return False

    if reminder.get("error"):
        await _send_message(
            page,
            "Em hiểu Anh/Chị muốn em nhắc việc, nhưng em chưa tách được đủ người được nhắc, thời gian và nội dung việc. "
            "Anh/Chị nhắn theo mẫu: nhắc anh Phương 08:00 sáng ngày 26/4/2026 cập nhật kế hoạch vào Lịch đăng bài.",
        )
        _log_event("custom_reminder.parse_failed", chat=chat_name, text=text[:160], error=reminder.get("error"))
        return True

    _save_custom_reminder(reminder)
    _log_event(
        "custom_reminder.saved",
        chat=chat_name,
        target=reminder.get("target", ""),
        task=(reminder.get("task", "") or "")[:120],
        due_at=reminder.get("due_at", ""),
    )
    await _send_message(page, _build_custom_reminder_confirmation(reminder))
    return True


async def _handle_personal_group_relay(page, chat_name: str, text: str) -> bool:
    relay_request = await _build_group_relay_message(text)
    if not relay_request:
        return False

    if relay_request.get("blocked"):
        await _send_message(page, relay_request["message"])
        _log_event(
            "group_relay.blocked",
            from_chat=chat_name,
            reason="unsafe_content",
            text=text[:160],
        )
        return True

    relay_message = relay_request["message"]

    _log_event(
        "group_relay.detected",
        from_chat=chat_name,
        group=ZALO_GROUP_NAME,
        llm=bool(relay_request.get("needs_llm")),
        preview=relay_message[:160],
    )
    await _send_message(page, "Dạ, em sẽ làm ngay.")
    await page.wait_for_timeout(500)

    opened_group = await _open_chat_by_name(page, ZALO_GROUP_NAME)
    if not opened_group:
        _log_event("group_relay.error", reason="group_open_failed", group=ZALO_GROUP_NAME)
        await _send_message(page, f"Em chưa mở được nhóm {ZALO_GROUP_NAME} để gửi tin.")
        return True

    sent_to_group = await _send_message(page, relay_message)
    _log_event(
        "group_relay.sent" if sent_to_group else "group_relay.error",
        group=ZALO_GROUP_NAME,
        ok=sent_to_group,
        preview=relay_message[:160],
    )

    if chat_name and _is_valid_chat_title(chat_name) and _normalize_text(chat_name) != _normalize_text(ZALO_GROUP_NAME):
        returned = await _open_chat_by_name(page, chat_name)
        _log_event("group_relay.returned", chat=chat_name, ok=returned)
        if returned and not sent_to_group:
            await _send_message(page, "Em đã mở nhóm nhưng chưa gửi được tin. Anh thử lại giúp em nhé.")

    return True


async def _process_chat_message(page, chat_name: str, chat_type: str, text: str) -> None:
    command = _extract_command(text)
    if command:
        _log_event("command.detected", chat=chat_name, command=command[0])
        await _handle_command(page, command[0], command[1], chat_name)
        return

    if await _handle_custom_reminder_request(page, chat_name, text):
        return

    if chat_type == "personal" and await _handle_personal_group_relay(page, chat_name, text):
        return

    if _should_reply(chat_type, text):
        _log_event("ai.triggered", chat=chat_name, chat_type=chat_type)
        await _handle_natural_language(page, text, chat_type)


async def _maybe_process_latest_message(
    page,
    chat_name: str,
    chat_type: str,
    incoming_messages: list[str],
    last_processed_signature: dict[str, str],
    last_reply_time: dict[str, float],
    only_if_reply_needed: bool = False,
) -> bool:
    if not incoming_messages:
        return False

    latest_message = incoming_messages[-1]
    signature = f"{chat_name}:{latest_message}"
    if signature == last_processed_signature.get(chat_name):
        return False

    if only_if_reply_needed and not _should_reply(chat_type, latest_message):
        return False

    now_monotonic = time.monotonic()
    last_time = last_reply_time.get(chat_name, 0.0)
    if now_monotonic - last_time < REPLY_COOLDOWN_SECONDS:
        return False

    _log_event("msg.new", chat=chat_name, chat_type=chat_type, text=latest_message[:200])
    await _process_chat_message(page, chat_name, chat_type, latest_message)
    last_processed_signature[chat_name] = signature
    last_reply_time[chat_name] = now_monotonic
    return True


async def _detect_session_state(page) -> str:
    ready_locator = await _get_visible_locator(page, LOGIN_READY_SELECTORS)
    if ready_locator is not None:
        return "ready"

    qr_visible = await page.evaluate(
        """
        () => {
            const text = document.body.innerText || '';
            if (text.includes('Quét mã QR') || text.includes('Dang nhap')) return true;
            const canvas = document.querySelector('canvas');
            return Boolean(canvas);
        }
        """
    )
    return "login_required" if qr_visible else "unknown"


async def _launch_browser(playwright):
    launch_options = {
        "user_data_dir": str(USER_DATA_DIR),
        "headless": HEADLESS,
        "viewport": {"width": 1366, "height": 900},
    }

    if BROWSER_NAME == "firefox":
        browser_type = playwright.firefox
    else:
        browser_type = playwright.chromium
        launch_options["args"] = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ]

    return await browser_type.launch_persistent_context(**launch_options)


async def main() -> None:
    _log_event(
        "bot.start",
        browser=BROWSER_NAME,
        group=ZALO_GROUP_NAME,
        reminder_time=f"{REMINDER_HOUR:02d}:{REMINDER_MINUTE:02d}",
        days_ahead=DAYS_AHEAD,
        timezone=LOCAL_TIMEZONE_NAME,
    )

    async with async_playwright() as playwright:
        browser = await _launch_browser(playwright)
        page = browser.pages[0] if browser.pages else await browser.new_page()

        await page.goto(ZALO_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        last_processed_signature: dict[str, str] = {}
        last_reply_time: dict[str, float] = {}
        sidebar_state: dict[str, str] = {}
        active_chat_latest_seen: dict[str, str] = {}
        sidebar_bootstrapped = False
        last_session_state = ""
        last_sync_click_time = 0.0
        last_onboarding_recover_time = 0.0

        while True:
            try:
                session_state = await _detect_session_state(page)
                if session_state != last_session_state:
                    if session_state == "ready":
                        _log_event("session.ready")
                    elif session_state == "login_required":
                        _log_event("session.login_required")
                    else:
                        _log_event("session.unknown")
                    last_session_state = session_state

                if session_state != "ready":
                    await asyncio.sleep(5)
                    continue

                await _clear_sidebar_search_filter(page)
                await _maybe_send_scheduled_reminder(page)
                await _maybe_send_due_custom_reminders(page)

                sidebar_chats = await _scan_sidebar_chats(page)
                changed_chats, next_sidebar_state = _select_sidebar_targets(
                    sidebar_chats,
                    sidebar_state,
                    sidebar_bootstrapped,
                )
                sidebar_state = next_sidebar_state
                if not sidebar_bootstrapped and sidebar_chats:
                    sidebar_bootstrapped = True

                if sidebar_chats:
                    _log_event(
                        "sidebar.scan",
                        count=len(sidebar_chats),
                        first=sidebar_chats[0].get("title", ""),
                        titles=[chat.get("title", "") for chat in sidebar_chats[:5]],
                        changed=len(changed_chats),
                    )

                current_state = await _capture_chat_state(page)
                current_chat_name = current_state.get("chatName") or "Unknown"
                current_chat_type = current_state.get("chatType") or "unknown"
                current_incoming_messages = current_state.get("incomingMessages") or []
                current_has_composer = bool(current_state.get("hasComposer"))
                current_is_onboarding = bool(current_state.get("isOnboarding"))

                _log_event(
                    "chat.inspect",
                    chat=current_chat_name,
                    chat_type=current_chat_type,
                    incoming_count=len(current_incoming_messages),
                    has_composer=current_has_composer,
                    onboarding=current_is_onboarding,
                )

                if (
                    current_has_composer
                    and not current_is_onboarding
                    and _is_valid_chat_title(current_chat_name)
                    and current_incoming_messages
                ):
                    current_latest_message = current_incoming_messages[-1]
                    previous_current_message = active_chat_latest_seen.get(current_chat_name)
                    active_chat_latest_seen[current_chat_name] = current_latest_message
                    if previous_current_message is not None and current_latest_message != previous_current_message:
                        _log_event(
                            "current_chat.changed",
                            chat=current_chat_name,
                            chat_type=current_chat_type,
                            text=current_latest_message[:200],
                        )
                        await _maybe_process_latest_message(
                            page,
                            current_chat_name,
                            current_chat_type,
                            current_incoming_messages,
                            last_processed_signature,
                            last_reply_time,
                            only_if_reply_needed=True,
                        )

                if current_is_onboarding and time.monotonic() - last_sync_click_time > 120:
                    clicked_sync = await _maybe_click_sync_recent_messages(page)
                    if clicked_sync:
                        last_sync_click_time = time.monotonic()
                        await asyncio.sleep(1)

                if current_is_onboarding and not sidebar_chats and time.monotonic() - last_onboarding_recover_time > 60:
                    last_onboarding_recover_time = time.monotonic()
                    await _dismiss_blocking_modal(page)
                    recovered = await _open_chat_by_name(page, ZALO_GROUP_NAME)
                    _log_event("onboarding.recover", group=ZALO_GROUP_NAME, ok=recovered)
                    if recovered:
                        await asyncio.sleep(1)
                        continue

                fallback_targets = [
                    chat for chat in sidebar_chats
                    if not _should_ignore_sidebar_chat(chat) and int(chat.get("unreadCount", 0)) > 0 and not chat.get("isMinePreview")
                ]
                bootstrap_chat = _pick_bootstrap_chat(sidebar_chats)
                open_targets = changed_chats or (
                    fallback_targets[:1]
                    if fallback_targets and (current_is_onboarding or not current_has_composer or not _is_valid_chat_title(current_chat_name))
                    else ([bootstrap_chat] if bootstrap_chat and (current_is_onboarding or not current_has_composer or not _is_valid_chat_title(current_chat_name)) else [])
                )

                if open_targets:
                    sample_chat = open_targets[0]
                    _log_event(
                        "unread.detected",
                        sidebar_count=len(sidebar_chats),
                        changed_count=len(changed_chats),
                        sample=sample_chat.get("title", ""),
                        preview=sample_chat.get("preview", ""),
                    )

                for chat in open_targets:
                    if not await _open_sidebar_chat(page, chat):
                        continue

                    state = await _capture_chat_state(page)
                    chat_name = state.get("chatName") or chat.get("title", "Unknown")
                    chat_type = state.get("chatType") or "unknown"
                    incoming_messages = state.get("incomingMessages") or []
                    has_composer = bool(state.get("hasComposer"))
                    is_onboarding = bool(state.get("isOnboarding"))

                    _log_event(
                        "chat.inspect",
                        chat=chat_name,
                        chat_type=chat_type,
                        incoming_count=len(incoming_messages),
                        has_composer=has_composer,
                        onboarding=is_onboarding,
                    )

                    if not has_composer or is_onboarding or not incoming_messages:
                        continue

                    active_chat_latest_seen[chat_name] = incoming_messages[-1]
                    await _maybe_process_latest_message(
                        page,
                        chat_name,
                        chat_type,
                        incoming_messages,
                        last_processed_signature,
                        last_reply_time,
                        only_if_reply_needed=False,
                    )

                await asyncio.sleep(2)
            except Exception as exc:
                _log_event("main.loop.error", error=_serialize_error(exc))
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
