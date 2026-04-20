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
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

import brain
from ai_helper import draft_content_from_request
from knowledge_store import add_learning, get_learning_context
from message_builder import (
    build_daily_reminder,
    build_no_work_message,
    build_pending_tasks_message,
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

BOT_NAME_RAW = os.getenv("BOT_NAME", "Nhan Vien Moi Yok Don")
BOT_NAMES = [name.strip().lower() for name in BOT_NAME_RAW.split(",") if name.strip()]
if not BOT_NAMES:
    BOT_NAMES = ["nhan vien moi yok don"]

SEARCH_INPUT_SELECTORS = [
    "#contact-search-input",
    "input[placeholder*='Tìm kiếm']",
    "input[placeholder*='Tim kiem']",
    "input[placeholder*='Search']",
]
CHAT_INPUT_SELECTORS = [
    "#richInput",
    "#chatInput",
    "footer [contenteditable='true']",
    "div[contenteditable='true']",
]
LOGIN_READY_SELECTORS = SEARCH_INPUT_SELECTORS + ["div[data-id]"]
COMMAND_RE = re.compile(r"/(nhacviec|xemviec|hotrobai|help|hoc|ghinho)\b(.*)", re.IGNORECASE | re.DOTALL)


def _log_event(event: str, **kwargs) -> None:
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
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
    return datetime.now().strftime("%Y-%m-%d")


def _platform_modifier() -> str:
    return "Meta" if sys.platform == "darwin" else "Control"


def _extract_command(text: str) -> tuple[str, str] | None:
    match = COMMAND_RE.search(text or "")
    if not match:
        return None
    command = match.group(1).strip().lower()
    payload = match.group(2).strip()
    return command, payload


def _is_bot_mentioned(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    return any(name in normalized for name in BOT_NAMES)


def _should_reply(chat_type: str, text: str) -> bool:
    if not text.strip():
        return False
    if _extract_command(text):
        return True
    if chat_type == "personal":
        return True
    return _is_bot_mentioned(text)


def _build_help_message() -> str:
    sheet_url = get_sheet_public_url() or "(chua cau hinh Sheet)"
    return "\n".join(
        [
            "HUONG DAN SU DUNG BOT",
            "=" * 28,
            "",
            "/nhacviec - Doc Sheet va gui ban nhac viec hien tai.",
            "/xemviec - Liet ke cac viec chua xong.",
            "/hotrobai <yeu cau> - Du thao noi dung truyen thong.",
            "/hoc <dieu can nho> - Day bot mot ghi nho moi.",
            "/help - Xem lai huong dan.",
            "",
            f"Sheet hien tai: {sheet_url}",
        ]
    )


def _format_tasks_for_context(limit: int = 12) -> str:
    tasks = fetch_all_tasks()
    pending = [task for task in tasks if not task.is_completed]
    pending.sort(key=lambda task: task.due_date or datetime.max)

    lines = [f"Co {len(tasks)} dong cong viec, trong do {len(pending)} viec chua xong."]
    for task in pending[:limit]:
        due = task.due_date_raw or "chua ro ngay"
        assignee = task.assignee or "chua giao"
        status = task.status or "chua cap nhat"
        lines.append(f"- [{due}] {task.topic} | phu trach: {assignee} | trang thai: {status}")

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


async def _send_message(page, text: str) -> bool:
    _log_event("reply.start", length=len(text))
    try:
        input_box = await _focus_chat_input(page)
        if input_box is None:
            raise RuntimeError("Khong tim thay o nhap tin nhan.")

        modifier = _platform_modifier()
        await page.keyboard.press(f"{modifier}+A")
        await page.keyboard.press("Delete")
        await page.wait_for_timeout(200)

        await page.evaluate(
            """
            (messageText) => {
                const input = ['#richInput', '#chatInput', 'footer [contenteditable="true"]', 'div[contenteditable="true"]']
                    .map((selector) => document.querySelector(selector))
                    .find(Boolean);

                if (!input) return false;

                input.focus();
                const selection = window.getSelection();
                if (selection) {
                    selection.removeAllRanges();
                    const range = document.createRange();
                    range.selectNodeContents(input);
                    selection.addRange(range);
                    document.execCommand('delete', false);
                }

                document.execCommand('insertText', false, messageText);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                return true;
            }
            """,
            text,
        )
        await page.wait_for_timeout(300)
        await page.keyboard.press("Enter")
        _log_event("reply.success", preview=text[:80])
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

                const composer = ['#richInput', '#chatInput', 'footer [contenteditable="true"]', 'div[contenteditable="true"]']
                    .map((selector) => document.querySelector(selector))
                    .find((node) => node && node.offsetParent !== null);

                const root = document.querySelector('#chat-root') || document.body;
                const rootRect = root.getBoundingClientRect();
                const centerX = rootRect.left + rootRect.width / 2;

                let chatType = 'unknown';
                if (headerText.includes('thành viên') || headerText.includes('thanh vien') || headerText.includes('members')) {
                    chatType = 'group';
                } else if (composer) {
                    chatType = 'personal';
                }

                const nodes = [...document.querySelectorAll('div, span')]
                    .filter((el) => {
                        const rect = el.getBoundingClientRect();
                        if (rect.width < 30 || rect.height < 12) return false;
                        if (rect.top < 80 || rect.top > window.innerHeight - 80) return false;
                        const text = (el.innerText || '').trim();
                        return text && text.length < 800;
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
                    chatName: (headerText.split('\\n')[0] || '').trim(),
                    chatType,
                    incomingMessages: unique.filter((item) => !item.isMe).map((item) => item.text).slice(-10),
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
                    if (rect.left < 50 || rect.left > 360 || rect.top < 100 || rect.top > window.innerHeight - 20) continue;
                    const style = window.getComputedStyle(el);
                    const bg = style.backgroundColor || '';
                    const match = bg.match(/rgb\\((\\d+),\\s*(\\d+),\\s*(\\d+)\\)/);
                    if (!match) continue;

                    const r = Number(match[1]);
                    const g = Number(match[2]);
                    const b = Number(match[3]);
                    if (!(r > 200 && g < 120 && b < 120)) continue;

                    let parent = el.parentElement;
                    while (parent && parent.getBoundingClientRect().height < 40) {
                        parent = parent.parentElement;
                    }
                    if (!parent) continue;

                    const parentRect = parent.getBoundingClientRect();
                    hits.push({
                        x: parentRect.left + parentRect.width / 2,
                        y: parentRect.top + parentRect.height / 2,
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
    search_input = await _get_visible_locator(page, SEARCH_INPUT_SELECTORS)
    if search_input is None:
        _log_event("chat.open.failed", reason="search_input_not_found", chat=chat_name)
        return False

    await search_input.click()
    await search_input.fill("")
    await search_input.fill(chat_name)
    await page.wait_for_timeout(1200)

    coords = await _find_sidebar_chat_coordinates(page, chat_name)
    if not coords:
        _log_event("chat.open.failed", reason="chat_not_found", chat=chat_name)
        return False

    await page.mouse.click(coords["x"], coords["y"])
    await page.wait_for_timeout(1200)
    _log_event("chat.opened", chat=chat_name)
    return True


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
    now = datetime.now()
    state = _load_runtime_state()
    already_sent_today = state.get("last_daily_reminder_date") == _today_key()

    should_send_now = (now.hour, now.minute) >= (REMINDER_HOUR, REMINDER_MINUTE)
    if already_sent_today or not should_send_now:
        return

    _log_event("reminder.triggered", scheduled_for=f"{REMINDER_HOUR:02d}:{REMINDER_MINUTE:02d}")
    if await _send_group_reminder(page):
        state["last_daily_reminder_date"] = _today_key()
        state["last_daily_reminder_sent_at"] = now.isoformat(timespec="seconds")
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
            await _send_message(page, _build_daily_message())
            return

        if command == "xemviec":
            tasks = fetch_all_tasks()
            await _send_message(page, build_pending_tasks_message(tasks))
            return

        if command == "hotrobai":
            if not payload:
                await _send_message(page, "Cu phap: /hotrobai <yeu cau can du thao>")
                return

            context = _build_ai_context()
            draft = await draft_content_from_request(payload, context=context)
            await _send_message(page, draft)
            return

        await _send_message(page, "Lenh chua duoc ho tro. Anh/Chị go /help de xem danh sach lenh.")
    except Exception as exc:
        _log_event("command.error", command=command, error=_serialize_error(exc))
        await _send_message(page, f"Em gap loi khi xu ly lenh /{command}: {exc}")


async def _handle_natural_language(page, text: str, chat_type: str) -> None:
    try:
        context = _build_ai_context()
        reply = await brain.process_message(text, chat_type, context=context)
        if reply:
            await _send_message(page, reply)
    except Exception as exc:
        _log_event("ai.error", error=_serialize_error(exc))
        await _send_message(page, f"Em dang gap loi AI: {exc}")


async def _process_chat_message(page, chat_name: str, chat_type: str, text: str) -> None:
    command = _extract_command(text)
    if command:
        _log_event("command.detected", chat=chat_name, command=command[0])
        await _handle_command(page, command[0], command[1], chat_name)
        return

    if _should_reply(chat_type, text):
        _log_event("ai.triggered", chat=chat_name, chat_type=chat_type)
        await _handle_natural_language(page, text, chat_type)


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
    )

    async with async_playwright() as playwright:
        browser = await _launch_browser(playwright)
        page = browser.pages[0] if browser.pages else await browser.new_page()

        await page.goto(ZALO_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        last_processed_signature: dict[str, str] = {}
        last_reply_time: dict[str, float] = {}
        last_session_state = ""

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

                await _maybe_send_scheduled_reminder(page)

                badges = await _scan_for_red_badges(page)
                targets = badges if badges else [{"x": 640, "y": 320, "is_active": True}]

                for target in targets:
                    if "is_active" not in target:
                        await page.mouse.click(target["x"], target["y"])
                        await page.wait_for_timeout(1200)

                    state = await _capture_chat_state(page)
                    chat_name = state.get("chatName") or "Unknown"
                    chat_type = state.get("chatType") or "unknown"
                    incoming_messages = state.get("incomingMessages") or []

                    if not incoming_messages:
                        continue

                    latest_message = incoming_messages[-1]
                    signature = f"{chat_name}:{latest_message}"
                    if signature == last_processed_signature.get(chat_name):
                        continue

                    now_monotonic = time.monotonic()
                    last_time = last_reply_time.get(chat_name, 0.0)
                    if now_monotonic - last_time < REPLY_COOLDOWN_SECONDS:
                        continue

                    _log_event("msg.new", chat=chat_name, chat_type=chat_type, text=latest_message[:200])
                    await _process_chat_message(page, chat_name, chat_type, latest_message)
                    last_processed_signature[chat_name] = signature
                    last_reply_time[chat_name] = now_monotonic

                await asyncio.sleep(2)
            except Exception as exc:
                _log_event("main.loop.error", error=_serialize_error(exc))
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
