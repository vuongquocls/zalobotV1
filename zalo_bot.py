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


def _should_reply(chat_type: str, text: str) -> bool:
    if not text.strip():
        return False
    if _extract_command(text):
        return True
    if chat_type == "personal":
        return True
    matched_alias = _find_bot_mention_alias(text)
    if chat_type == "group" and matched_alias:
        _log_event("group.mention.matched", alias=matched_alias, text=(text or "")[:200])
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
            "/hotrobai <yeu cau> - Du thao noi dung truyen thong.",
            "/hoc <dieu can nho> - Day bot mot ghi nho moi.",
            "/help - Xem lai huong dan.",
            "",
            f"Sheet hien tai: {sheet_url}",
        ]
    )


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
        tag_name = (await input_box.evaluate("(node) => node.tagName || ''")).upper()
        if tag_name in {"INPUT", "TEXTAREA"}:
            await input_box.fill("")
            await input_box.fill(text)
        else:
            await page.keyboard.press(f"{modifier}+A")
            await page.keyboard.press("Delete")
            await page.wait_for_timeout(200)

            inserted = await page.evaluate(
            """
            (messageText) => {
                const input = ['#richInput', '#chatInput', '[placeholder*="Nhập @"]', '[placeholder*="tin nhắn tới"]', '[placeholder*="tin nhan toi"]', '[role="textbox"]', 'footer [contenteditable="true"]', 'div[contenteditable="true"]']
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
            if not inserted:
                await input_box.fill(text)
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
                    if (normalized === 'tin nhắn' || normalized === 'tin nhan') return true;
                    if (normalized === 'tải về để xem lâu dài' || normalized === 'tai ve de xem lau dai') return true;
                    if (normalized.startsWith('sử dụng ứng dụng zalo pc') || normalized.startsWith('su dung ung dung zalo pc')) return true;
                    if (normalized.startsWith('chào mừng đến với zalo pc') || normalized.startsWith('chao mung den voi zalo pc')) return true;
                    return false;
                };

                const nodes = [...document.querySelectorAll('div, span')]
                    .filter((el) => {
                        const rect = el.getBoundingClientRect();
                        if (rect.left < mainLeft + 12 || rect.right > window.innerWidth - 12) return false;
                        if (rect.width < 40 || rect.height < 14) return false;
                        if (rect.width > (window.innerWidth - mainLeft) * 0.78) return false;
                        if (rect.top < 90 || rect.bottom > composerTop - 10) return false;
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
                const unique = [];
                const seen = new Set();
                for (const row of rows) {
                    const key = `${Math.round(row.y / 10)}`;
                    const normalizedTitle = row.title.toLowerCase();
                    if (!seen.has(key + ':' + normalizedTitle)) {
                        seen.add(key + ':' + normalizedTitle);
                        unique.push(row);
                    }
                }
                return unique;
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
    if any(_looks_like_onboarding_text(value) for value in (title, preview, raw_text)):
        return True
    if "đồng bộ tin nhắn gần đây" in raw_text or "dong bo tin nhan gan day" in raw_text:
        return True
    if title in {"my documents", "chua co tin nhan"}:
        return True
    if raw_text.startswith("su dung ung dung zalo pc de tim tin nhan truoc ngay"):
        return True
    if title.startswith("su dung ung dung zalo pc de tim tin nhan truoc ngay"):
        return True
    return False


def _sidebar_signature(chat: dict) -> str:
    preview = chat.get("preview", "")
    unread_count = chat.get("unreadCount", 0)
    raw_text = chat.get("rawText", "")
    return f"{preview}|{unread_count}|{raw_text}"


def _select_sidebar_targets(chats: list[dict], sidebar_state: dict, bootstrapped: bool) -> tuple[list[dict], dict]:
    next_state = dict(sidebar_state)
    candidates = []

    for chat in chats:
        if _should_ignore_sidebar_chat(chat):
            continue

        title = chat.get("title", "").strip()
        signature = _sidebar_signature(chat)
        previous_signature = next_state.get(title)
        next_state[title] = signature

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
                "title": chat.get("title", ""),
                "preview": chat.get("preview", ""),
                "fallbackX": chat["x"],
                "fallbackY": chat["y"],
            },
        )
        _log_event("chat.row.click_attempt", chat=chat.get("title", ""), result=clicked)
        await page.wait_for_timeout(1200)

        state = await _capture_chat_state(page)
        current_name = state.get("chatName", "")
        if state.get("hasComposer") and _is_valid_chat_title(current_name):
            _log_event("chat.row.opened", expected=chat.get("title", ""), actual=current_name)
            return True

        await page.mouse.dblclick(chat["x"], chat["y"])
        await page.wait_for_timeout(1200)
        state = await _capture_chat_state(page)
        current_name = state.get("chatName", "")
        ok = state.get("hasComposer") and _is_valid_chat_title(current_name)
        if ok:
            _log_event("chat.row.opened", expected=chat.get("title", ""), actual=current_name, method="dblclick")
        else:
            _log_event(
                "chat.row.open_failed",
                expected=chat.get("title", ""),
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
        await _send_message(page, f"Em gap loi khi xu ly lenh /{command}. Anh/Chị thu lai giup em nhe.")


async def _handle_natural_language(page, text: str, chat_type: str) -> None:
    try:
        intent = brain.classify_intent(text, chat_type)
        _log_event("brain.intent", chat_type=chat_type, intent=intent, text=text[:200])
        context = _build_ai_context()
        reply = await brain.process_message(text, chat_type, context=context)
        if reply:
            await _send_message(page, reply)
    except Exception as exc:
        _log_event("ai.error", error=_serialize_error(exc))
        await _send_message(page, "Em dang gap loi AI tam thoi. Anh/Chị thu nhan lai sau it phut giup em nhe.")


async def _process_chat_message(page, chat_name: str, chat_type: str, text: str) -> None:
    command = _extract_command(text)
    if command:
        _log_event("command.detected", chat=chat_name, command=command[0])
        await _handle_command(page, command[0], command[1], chat_name)
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

                if current_is_onboarding:
                    clicked_sync = await _maybe_click_sync_recent_messages(page)
                    if clicked_sync:
                        await asyncio.sleep(1)

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
