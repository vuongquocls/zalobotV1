"""
zalo_bot.py — Bot Zalo nhắc việc Truyền thông VQG Yok Đôn

Chạy trên Zalo Web qua Playwright.
- Chỉ trả lời khi được gọi đích danh (ví dụ: "Nhân Viên Mới Yok Đôn")
- Hiểu ngôn ngữ tự nhiên (không bắt buộc dùng lệnh /)
- Tự động nhắc việc theo lịch (mặc định 8h sáng)
- Đọc Google Sheet để lấy dữ liệu công việc
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime

from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

# Import các module nội bộ
from sheet_reader import (
    fetch_all_tasks,
    get_today_tasks,
    get_upcoming_tasks,
    get_overdue_tasks,
    get_unassigned_tasks,
    is_today_empty,
)
from message_builder import (
    build_daily_reminder,
    build_no_work_message,
    build_sheet_empty_message,
    build_today_empty_message,
    build_task_detail,
)
import brain
from ai_helper import draft_article, answer_question

# === Config ===
ZALO_URL = "https://chat.zalo.me/"
# Thay /tmp bằng thư mục trong project để session không bị xoá khi reboot
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USER_DATA_DIR = os.path.join(BASE_DIR, "zalo_profile")
os.makedirs(USER_DATA_DIR, exist_ok=True)
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"

ZALO_GROUP_NAME = os.getenv("ZALO_GROUP_NAME", "")
REMINDER_HOUR = int(os.getenv("REMINDER_HOUR", "8"))
REMINDER_MINUTE = int(os.getenv("REMINDER_MINUTE", "0"))
DAYS_AHEAD = int(os.getenv("DAYS_AHEAD", "3"))
BUILD_ID = os.getenv("APP_BUILD_ID", "").strip()

if not BUILD_ID:
    try:
        BUILD_ID = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR,
            text=True,
        ).strip()
    except Exception:
        BUILD_ID = "unknown"

LOGIN_INDICATOR_SELECTORS = [
    "input[placeholder*='Tìm kiếm']",
    "input[placeholder*='Search']",
    ".msg-item",
    "div[data-id]",
]
SEARCH_SELECTORS = [
    "input[placeholder*='Tìm kiếm']",
    "input[placeholder*='Search']",
    "input[placeholder*='tìm']",
    "input[type='text'][class*='search']",
    "#contact-search-input",
]
CHAT_INPUT_SELECTORS = [
    "#richInput",
    "#chatInput",
    "footer [contenteditable='true']",
    "div[contenteditable='true'][role='textbox']",
    "div[contenteditable='true']",
    "textarea",
]
SIDEBAR_ITEM_SELECTORS = [
    "[id*='conversation-list'] > div",
    ".conv-list > div",
    "div[class*='conv-item']",
    "div.msg-item",
]
UNREAD_BADGE_SELECTORS = [
    "[class*='unread']",
    "[class*='badge']",
    "[class*='count']",
    "span.num",
]

# === Tên bot — chỉ trả lời khi được gọi đích danh ===
# Có thể đặt nhiều tên, cách nhau bằng dấu phẩy
BOT_NAMES_RAW = os.getenv("BOT_NAME", "Nhân Viên Mới Yok Đôn")
BOT_NAMES = [n.strip().lower() for n in BOT_NAMES_RAW.split(",") if n.strip()]
# Tạo thêm biến thể viết tắt/không dấu tự động
import unicodedata
def _remove_accents(s: str) -> str:
    nfkd = unicodedata.normalize('NFKD', s)
    stripped = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.replace("đ", "d").replace("Đ", "D")
BOT_NAMES_NORMALIZED = list(set(
    [n for n in BOT_NAMES]
    + [_remove_accents(n) for n in BOT_NAMES]
))

# Temp dir để tránh macOS chặn
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ["TMPDIR"] = os.path.join(BASE_DIR, ".tmp")
os.makedirs(os.environ["TMPDIR"], exist_ok=True)


def _preview_text(text: str, limit: int = 120) -> str:
    value = re.sub(r"\s+", " ", (text or "").strip())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _serialize_error(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def _log_event(event: str, **fields):
    payload = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "event": event,
    }
    for key, value in fields.items():
        if isinstance(value, str):
            payload[key] = _preview_text(value, 300)
        else:
            payload[key] = value
    print(json.dumps(payload, ensure_ascii=False))


def _normalize_text(text: str) -> str:
    """Chuẩn hóa text chat, bỏ timestamp cuối."""
    clean = re.sub(r'\n\d{1,2}:\d{2}$', '', (text or "").strip())
    return clean.strip()


def _build_signature(messages: list[str]) -> str:
    """Tạo chữ ký từ tối đa 3 tin cuối để không bỏ sót tin trùng nội dung."""
    normalized = []
    for message in messages[-3:]:
        clean = re.sub(r'\s+', ' ', _normalize_text(message)).strip().lower()
        if clean:
            normalized.append(clean)
    return " || ".join(normalized)


def _classify_ignored_message(
    text: str,
    *,
    chat_state: dict | None = None,
    recent_bot_replies: list[str] | None = None,
) -> str | None:
    """Trả về reason nếu text không phải tin nhắn người dùng hợp lệ."""
    clean = _normalize_text(text)
    lower = clean.lower()
    compact = re.sub(r'\s+', ' ', lower).strip()

    if not compact:
        return "empty_text"
    if len(compact) <= 2 and compact not in {"ok", "uh", "ừ", "ờ"}:
        return "too_short_noise"
    if re.fullmatch(r'\d{1,2}:\d{2}', compact):
        return "timestamp_only"

    typing_markers = [
        "đang soạn tin trên máy tính",
        "đang nhập",
        "typing",
        "is typing",
        "soạn tin",
    ]
    if any(marker in compact for marker in typing_markers):
        return "typing_indicator"

    # Markers chỉ match khi tin ngắn (< 40 ký tự) để tránh lọc nhầm tin thật
    system_markers_strict = [
        "tải về để xem",
        "xem thêm tin nhắn",
        "tin nhắn đã được thu hồi",
        "đã tham gia nhóm",
        "đã rời nhóm",
        "đã tạo nhóm",
        "đã đổi tên nhóm",
        "đã ghim",
        "đã bỏ ghim",
        "đã thay đổi",
        "vừa truy cập",
        "vừa hoạt động",
        "đang hoạt động",
        "last seen",
        "reacted",
        "đã bày tỏ cảm xúc",
        "trả lời bằng biểu tượng cảm xúc",
        "đã gửi một tệp",
        "đã gửi ảnh",
        "đã gửi video",
        "đã gửi sticker",
        "đã gọi",
        "cuộc gọi",
    ]
    # Chỉ coi là system text nếu tin ngắn (< 60 ký tự)
    # Tin dài hơn có thể là tin thật chứa cụm từ trùng marker
    if len(compact) < 40 and any(marker in compact for marker in system_markers_strict):
        return "system_or_status_text"
    # "online" riêng: chỉ match nếu TIN CHỈ CÓ 1 từ "online"
    if compact == "online":
        return "system_or_status_text"

    banner_markers = [
        "nhắn tin cho",
        "bắt đầu cuộc trò chuyện",
        "zalo web",
        "truy cập https://zalo.me",
    ]
    if any(marker in compact for marker in banner_markers):
        return "ui_banner_text"

    if chat_state:
        active_sidebar = _normalize_text(chat_state.get("activeSidebarText", ""))
        if active_sidebar and compact == active_sidebar.lower():
            return "sidebar_preview_text"

        header_texts = [
            _normalize_text(value).lower()
            for value in chat_state.get("headerTexts", [])
            if _normalize_text(value)
        ]
        if compact in header_texts:
            return "header_text"

    if recent_bot_replies:
        norm = re.sub(r'\W+', '', clean).lower()
        for prev in recent_bot_replies[-30:]:
            if norm == prev:
                return "bot_reply_echo"
            if len(norm) >= 20 and len(prev) >= 20 and norm[:20] == prev[:20]:
                return "bot_reply_echo"
            # Substring matching: nếu tin chat là 1 phần của reply bot → echo
            if len(norm) >= 10 and norm in prev:
                return "bot_reply_echo"

    # Chặn BOT header lặp lại
    bot_header_markers = [
        "bot nhắc việc truyền thông",
        "bot nhac viec truyen thong",
        "nhắc việc truyền thông -",
        "nhac viec truyen thong -",
    ]
    if any(marker in compact for marker in bot_header_markers):
        return "bot_reply_echo"

    return None


def _strip_zalo_mentions(text: str) -> str:
    """Xoá tag @mention của Zalo (dạng @Tên Người Dùng) ra khỏi text."""
    cleaned = text or ""
    variants = list(dict.fromkeys(BOT_NAMES + [BOT_NAMES_RAW] + [_remove_accents(n) for n in BOT_NAMES + [BOT_NAMES_RAW]]))
    for variant in variants:
        if not variant:
            continue
        cleaned = re.sub(
            r'(?i)@\s*' + re.escape(variant) + r'(?=[,!?.:]|\s|$)',
            '',
            cleaned,
        )
    return re.sub(r'\s{2,}', ' ', cleaned).strip()


def _detect_mention(text: str) -> tuple[bool, str]:
    """Kiểm tra tin nhắn có gọi tên bot không.

    Hỗ trợ:
    - Gọi thẳng: "Nhân Viên Mới Yok Đôn, hôm nay..."
    - Gọi với ê/ơi: "Ê Nhân Viên Mới Yok Đôn, hôm nay..."
    - Zalo @mention: "@Nhân Viên Mới Yok Đôn hôm nay..."
    - Kết hợp: "Ê Nhân Viên Mới Yok Đôn @Nhân Viên Mới Yok Đôn, hôm nay..."

    Returns:
        (is_mentioned, message_without_bot_name)
    """
    # Bước 1: Xoá @mention tags trước
    cleaned = _strip_zalo_mentions(text)
    mention_stripped = cleaned != (text or "").strip()
    lower = cleaned.lower().strip()
    lower_no_accent = _remove_accents(lower)

    for name in BOT_NAMES_NORMALIZED:
        # Tìm tên bot ở bất kỳ đâu trong câu
        patterns = [
            re.compile(r'[êeơ]\s+' + re.escape(name), re.IGNORECASE),
            re.compile(re.escape(name), re.IGNORECASE),
        ]
        for pat in patterns:
            target = lower_no_accent if _remove_accents(name) == name else lower
            if pat.search(target):
                # Bóc phần nội dung thực (bỏ tên bot + tiền tố)
                remainder = cleaned
                for orig_name_variant in BOT_NAMES + [BOT_NAMES_RAW]:
                    remainder = re.sub(
                        r'(?i)[êeơ]\s+' + re.escape(orig_name_variant) + r'[,!?.:\s]*',
                        '', remainder
                    )
                    remainder = re.sub(
                        r'(?i)' + re.escape(orig_name_variant) + r'[,!?.:\s]*',
                        '', remainder
                    )
                    # Cả dạng không dấu
                    remainder = re.sub(
                        r'(?i)[eeơ]\s+' + re.escape(_remove_accents(orig_name_variant)) + r'[,!?.:\s]*',
                        '', remainder
                    )
                    remainder = re.sub(
                        r'(?i)' + re.escape(_remove_accents(orig_name_variant)) + r'[,!?.:\s]*',
                        '', remainder
                    )
                remainder = remainder.strip().lstrip(',!?.:').strip()
                if remainder:
                    return True, remainder
                # Nếu sau khi bỏ tên hết text → vẫn detected nhưng hỏi mặc định
                return True, "hôm nay có việc gì không?"

    if mention_stripped:
        remainder = re.sub(r'(?i)^[êeơ]\s*[,!?.:]*\s*', '', cleaned).strip()
        remainder = remainder.lstrip(',!?.:').strip()
        return True, remainder or "hôm nay có việc gì không?"

    # Kiểm tra thêm: nếu text gốc (trước khi strip @) có chứa @TenBot
    original_lower = text.lower()
    for name in BOT_NAMES:
        if f'@{name}' in original_lower or f'@ {name}' in original_lower:
            remainder = _strip_zalo_mentions(text)
            for orig_name_variant in BOT_NAMES + [BOT_NAMES_RAW]:
                remainder = re.sub(
                    r'(?i)[êeơ]\s+' + re.escape(orig_name_variant) + r'[,!?.:\s]*',
                    '', remainder
                )
                remainder = re.sub(
                    r'(?i)' + re.escape(orig_name_variant) + r'[,!?.:\s]*',
                    '', remainder
                )
            remainder = remainder.strip().lstrip(',!?.:').strip()
            return True, remainder or "hôm nay có việc gì không?"

    return False, text


def _detect_intent(text: str) -> str:
    """Phát hiện ý định từ câu hỏi tự nhiên.

    Returns: 'nhacviec' | 'xemviec' | 'hotrobai' | 'help' | 'hoidap'
    """
    lower = text.lower()
    lower_na = _remove_accents(lower)

    # Help — kiểm tra TRƯỚC nhacviec để tránh 'có gì' match nhầm
    help_kws = [
        'hướng dẫn', 'huong dan', 'help', 'làm gì được', 'lam gi duoc',
        'biết làm gì', 'biet lam gi', 'có thể làm gì', 'co the lam gi',
        'làm được gì', 'lam duoc gi', 'có gì', 'co gi',
        'chức năng', 'chuc nang', 'dùng sao', 'dung sao',
    ]
    if any(k in lower or k in lower_na for k in help_kws):
        return 'help'

    # Nhắc việc / lịch đăng bài
    nhac_kws = [
        'nhắc việc', 'nhac viec', 'có lịch', 'co lich', 'lịch đăng',
        'lich dang', 'đăng bài', 'dang bai',
        'công việc', 'cong viec', 'việc gì', 'viec gi',
        'nhắc', 'nhac', 'deadline', 'phải làm', 'phai lam',
        'cần làm', 'can lam',
    ]
    # 'hôm nay' chỉ match khi đi kèm từ liên quan đến việc
    hom_nay_context = ['việc', 'viec', 'lịch', 'lich', 'đăng', 'dang', 'làm', 'lam', 'bài', 'bai']
    has_hom_nay = 'hôm nay' in lower or 'hom nay' in lower_na
    has_work_context = any(ctx in lower or ctx in lower_na for ctx in hom_nay_context)
    if any(k in lower or k in lower_na for k in nhac_kws):
        return 'nhacviec'
    if has_hom_nay and has_work_context:
        return 'nhacviec'

    # Xem danh sách
    xem_kws = [
        'xem việc', 'xem viec', 'danh sách', 'danh sach', 'liệt kê',
        'liet ke', 'list', 'bao nhiêu việc', 'bao nhieu viec',
    ]
    if any(k in lower or k in lower_na for k in xem_kws):
        return 'xemviec'

    # Hỗ trợ viết bài
    bai_kws = [
        'viết bài', 'viet bai', 'soạn bài', 'soan bai', 'gợi ý',
        'goi y', 'nội dung', 'noi dung', 'caption', 'kịch bản',
        'kich ban', 'hỗ trợ bài', 'ho tro bai', 'giúp viết', 'giup viet',
    ]
    if any(k in lower or k in lower_na for k in bai_kws):
        return 'hotrobai'

    # Mặc định: hỏi đáp tự do
    return 'hoidap'


async def _send_message(page, text: str):
    """Gửi tin nhắn vào khung chat hiện tại."""
    _log_event("reply.invoke", text_preview=text, length=len(text))
    try:
        focus_result = await page.evaluate(
            """
            ({ selectors }) => {
                const visible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return (
                        rect.width > 40 &&
                        rect.height > 16 &&
                        rect.bottom > 0 &&
                        rect.right > 0 &&
                        style.visibility !== 'hidden' &&
                        style.display !== 'none'
                    );
                };

                const candidates = [];
                for (const selector of selectors) {
                    for (const el of document.querySelectorAll(selector)) {
                        if (!visible(el)) continue;
                        const rect = el.getBoundingClientRect();
                        if (rect.top < window.innerHeight * 0.35) continue;
                        candidates.push({
                            el,
                            selector,
                            score: rect.top + rect.width,
                            top: Math.round(rect.top),
                            left: Math.round(rect.left),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        });
                    }
                }

                candidates.sort((a, b) => b.score - a.score);
                const chosen = candidates[0];
                if (!chosen) {
                    return { ok: false, reason: 'chat_input_not_found', candidateCount: 0 };
                }

                chosen.el.scrollIntoView({ block: 'center' });
                chosen.el.focus();
                chosen.el.click?.();
                return {
                    ok: true,
                    selector: chosen.selector,
                    candidateCount: candidates.length,
                    rect: {
                        top: chosen.top,
                        left: chosen.left,
                        width: chosen.width,
                        height: chosen.height,
                    },
                    tagName: chosen.el.tagName,
                };
            }
            """,
            {"selectors": CHAT_INPUT_SELECTORS},
        )
    except Exception as exc:
        _log_event("reply.error", stage="focus_input", error=_serialize_error(exc))
        return False

    if not focus_result.get("ok"):
        _log_event("reply.error", stage="focus_input", **focus_result)
        return False

    try:
        await page.keyboard.insert_text(text)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        _log_event("reply.success", input_selector=focus_result.get("selector"), input_meta=focus_result)
        return True
    except Exception as exc:
        _log_event(
            "reply.error",
            stage="submit",
            error=_serialize_error(exc),
            input_meta=focus_result,
        )
        return False


async def _detect_session_state(page) -> str:
    """Phát hiện trạng thái session hiện tại của Zalo Web."""
    try:
        for sel in LOGIN_INDICATOR_SELECTORS:
            if await page.locator(sel).count() > 0:
                return "ready"
        body_text = await page.locator("body").inner_text()
    except Exception:
        return "unknown"

    body_lower = body_text.lower()
    login_markers = [
        "đăng nhập tài khoản zalo",
        "đăng nhập qua mã qr",
        "chi dùng để đăng nhập",
        "zalo trên máy tính",
        "quét mã qr",
    ]
    if any(marker in body_lower for marker in login_markers):
        return "login_required"
    return "unknown"


async def _capture_chat_state(page) -> dict:
    """Đọc trạng thái chat hiện tại theo DOM thực tế, hạn chế phụ thuộc class name của Zalo."""
    try:
        state = await page.evaluate(
            r"""
            ({ groupName, inputSelectors, sidebarSelectors }) => {
                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                const lower = (value) => normalize(value).toLowerCase();
                const visible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return (
                        rect.width > 24 &&
                        rect.height > 12 &&
                        rect.bottom > 0 &&
                        rect.right > 0 &&
                        style.display !== 'none' &&
                        style.visibility !== 'hidden'
                    );
                };

                const inputCandidates = [];
                for (const selector of inputSelectors) {
                    for (const el of document.querySelectorAll(selector)) {
                        if (!visible(el)) continue;
                        const rect = el.getBoundingClientRect();
                        if (rect.top < window.innerHeight * 0.35) continue;
                        inputCandidates.push({
                            el,
                            selector,
                            rect,
                            score: rect.top + rect.width,
                        });
                    }
                }
                inputCandidates.sort((a, b) => b.score - a.score);
                const composer = inputCandidates[0]?.el || null;
                const composerRect = composer ? composer.getBoundingClientRect() : null;

                let root = composer || document.body;
                if (composer) {
                    let probe = composer;
                    let bestRoot = null;
                    while (probe && probe.parentElement) {
                        probe = probe.parentElement;
                        const rect = probe.getBoundingClientRect();
                        if (
                            rect.width < Math.min(window.innerWidth * 0.35, 420) ||
                            rect.height < Math.min(window.innerHeight * 0.50, 360)
                        ) {
                            continue;
                        }
                        if (
                            rect.width >= window.innerWidth * 0.97 &&
                            rect.height >= window.innerHeight * 0.97
                        ) {
                            continue;
                        }
                        bestRoot = probe;
                    }
                    if (bestRoot) {
                        root = bestRoot;
                    }
                }

                const rootRect = root.getBoundingClientRect();
                const headerCutoff = rootRect.top + Math.min(170, Math.max(90, rootRect.height * 0.2));
                const headerSeen = new Set();
                const headerTexts = [];
                const elements = root.querySelectorAll('div, span, p, h1, h2, h3, a');
                for (const el of elements) {
                    if (!visible(el)) continue;
                    if (composer && composer.contains(el)) continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.top > headerCutoff || rect.bottom < rootRect.top) continue;
                    const text = normalize(el.innerText || el.textContent || '');
                    if (!text || text.length > 140) continue;
                    if (headerSeen.has(text)) continue;
                    headerSeen.add(text);
                    headerTexts.push(text);
                    if (headerTexts.length >= 8) break;
                }

                const activeCandidates = [];
                for (const selector of sidebarSelectors) {
                    for (const el of document.querySelectorAll(selector)) {
                        if (!visible(el)) continue;
                        const rect = el.getBoundingClientRect();
                        if (rect.right > window.innerWidth * 0.45) continue;
                        const cls = typeof el.className === 'string' ? el.className.toLowerCase() : '';
                        const selected =
                            el.getAttribute('aria-selected') === 'true' ||
                            el.getAttribute('data-active') === 'true' ||
                            ['active', 'selected', 'current', 'focus'].some((token) => cls.includes(token));
                        if (!selected) continue;
                        const text = normalize(el.innerText || el.textContent || '');
                        if (!text) continue;
                        activeCandidates.push({ text, rectLeft: rect.left, rectTop: rect.top });
                    }
                }
                activeCandidates.sort((a, b) => a.rectTop - b.rectTop || a.rectLeft - b.rectLeft);
                const activeSidebarText = activeCandidates[0]?.text || '';
                const activeSidebarName = normalize(activeSidebarText.split('\\n')[0] || '');

                const chatName =
                    headerTexts.find((text) => !/(thành viên|members|đang nhập|online|last seen|typing)/i.test(text) && text.length <= 90) ||
                    activeSidebarName ||
                    '';

                const fullHeader = headerTexts.join(' | ');
                let chatType = 'unknown';
                let classificationReason = 'unknown';
                const headerLower = lower(fullHeader);
                if (groupName && lower(chatName).includes(lower(groupName))) {
                    chatType = 'group';
                    classificationReason = 'matched_configured_group_name';
                }
                if (/(thành viên|members|nhóm|group)/i.test(headerLower)) {
                    chatType = 'group';
                    classificationReason = 'header_contains_group_marker';
                } else if (chatType !== 'group' && chatName && composer) {
                    chatType = 'personal';
                    classificationReason = activeSidebarName ? 'sidebar_or_header_name_without_group_marker' : 'header_name_without_group_marker';
                } else if (chatType !== 'group' && composer && activeSidebarName && !headerLower.includes('thành viên')) {
                    chatType = 'personal';
                    classificationReason = 'active_sidebar_name_without_group_marker';
                }

                const messages = [];
                const messageSeen = new Set();
                const messageTop = headerCutoff + 4;
                const messageBottom = composerRect ? composerRect.top - 4 : rootRect.bottom - 4;
                const chatCenterX = rootRect.left + rootRect.width * 0.5;
                for (const el of elements) {
                    if (!visible(el)) continue;
                    if (composer && composer.contains(el)) continue;
                    if (el.closest('button,[role="button"],nav,aside,header,footer')) continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.top < messageTop || rect.bottom > messageBottom) continue;
                    if (rect.width < 28 || rect.height < 10) continue;
                    if (rect.left < rootRect.left + Math.min(28, rootRect.width * 0.04)) continue;
                    const text = normalize(el.innerText || el.textContent || '');
                    if (!text || text.length > 1000) continue;
                    if (/^\d{1,2}:\d{2}$/.test(text)) continue;
                    if (headerSeen.has(text)) continue;
                    const dedupeKey = `${Math.round(rect.top)}:${Math.round(rect.left)}:${text}`;
                    if (messageSeen.has(dedupeKey)) continue;
                    messageSeen.add(dedupeKey);
                    
                    const isMe = (rect.right > rootRect.left + rootRect.width * 0.7);
                    
                    messages.push({
                        text,
                        top: Math.round(rect.top),
                        left: Math.round(rect.left),
                        isMe,
                    });
                }

                messages.sort((a, b) => (a.top - b.top) || (a.left - b.left));
                const incomingMessages = [];
                const allFlattened = [];
                for (const item of messages) {
                    if (allFlattened[allFlattened.length - 1] === item.text) continue;
                    allFlattened.push(item.text);
                    if (!item.isMe) {
                        incomingMessages.push(item.text);
                    }
                }

                return {
                    hasComposer: Boolean(composer),
                    composerSelector: inputCandidates[0]?.selector || null,
                    composerCount: inputCandidates.length,
                    chatName,
                    chatType,
                    classificationReason,
                    fullHeader,
                    headerTexts,
                    activeSidebarText,
                    activeSidebarName,
                    messages: allFlattened.slice(-20),
                    incomingMessages: incomingMessages.slice(-20),
                    rootRect: {
                        top: Math.round(rootRect.top),
                        left: Math.round(rootRect.left),
                        width: Math.round(rootRect.width),
                        height: Math.round(rootRect.height),
                    },
                    composerRect: composerRect
                        ? {
                              top: Math.round(composerRect.top),
                              left: Math.round(composerRect.left),
                              width: Math.round(composerRect.width),
                              height: Math.round(composerRect.height),
                          }
                        : null,
                };
            }
            """,
            {
                "groupName": ZALO_GROUP_NAME,
                "inputSelectors": CHAT_INPUT_SELECTORS,
                "sidebarSelectors": SIDEBAR_ITEM_SELECTORS,
            },
        )
        return state or {}
    except Exception as exc:
        _log_event("exception", scope="capture_chat_state", error=_serialize_error(exc))
        return {}


async def _navigate_to_group(page, group_name: str) -> bool:
    """Tìm và mở nhóm Zalo theo tên — nhiều cách fallback."""
    if not group_name:
        _log_event("group.navigate.skip", reason="missing_group_name")
        return False

    # === Cách 1: Click trực tiếp từ sidebar nếu nhóm đang hiện ===
    try:
        sidebar_items = await page.locator(
            "div[class*='conv-item'], div.msg-item, div[data-id]"
        ).all()
        for item in sidebar_items:
            try:
                item_text = await item.inner_text()
                if group_name.lower() in item_text.lower():
                    await item.click(force=True)
                    await asyncio.sleep(1)
                    _log_event("group.navigate.success", method="sidebar", group_name=group_name)
                    return True
            except Exception:
                continue
    except Exception as exc:
        _log_event("exception", scope="navigate_group.sidebar", error=_serialize_error(exc))

    # === Cách 2: Dùng ô tìm kiếm ===
    search_input = None
    for sel in SEARCH_SELECTORS:
        loc = page.locator(sel).first
        if await loc.count() > 0:
            search_input = loc
            break

    if search_input:
        try:
            await search_input.click(force=True)
            await asyncio.sleep(0.5)
            await search_input.fill(group_name)
            await asyncio.sleep(3)  # Chờ lâu hơn cho kết quả tìm kiếm

            # Thử nhiều selector kết quả
            result_selectors = [
                f"text='{group_name}'",
                f"div:has-text('{group_name}')",
                ".search-item",
                "[class*='search-result']",
                "[class*='conv-item']",
                ".msg-item",
            ]
            for sel in result_selectors:
                try:
                    result = page.locator(sel).first
                    if await result.count() > 0:
                        await result.click(force=True)
                        await asyncio.sleep(1)
                        # Đóng ô tìm kiếm
                        try:
                            await search_input.clear()
                        except:
                            pass
                        try:
                            await page.keyboard.press("Escape")
                        except:
                            pass
                        _log_event("group.navigate.success", method="search", group_name=group_name, selector=sel)
                        return True
                except:
                    continue

            # Đóng ô tìm kiếm nếu không tìm thấy
            try:
                await search_input.clear()
                await page.keyboard.press("Escape")
            except:
                pass
        except Exception as e:
            _log_event("exception", scope="navigate_group.search", error=_serialize_error(e))

    _log_event("group.navigate.miss", group_name=group_name)
    return False


async def _do_reminder(page) -> bool:
    """Thực hiện nhắc việc: đọc Sheet → build message → gửi."""
    try:
        _log_event("reminder.start", group_name=ZALO_GROUP_NAME)
        all_tasks = fetch_all_tasks()

        if not all_tasks:
            msg = build_sheet_empty_message()
            await _send_message(page, msg)
            _log_event("reminder.sent", variant="sheet_empty")
            return True

        today = get_today_tasks(all_tasks)
        overdue = get_overdue_tasks(all_tasks)
        upcoming = get_upcoming_tasks(days_ahead=DAYS_AHEAD, tasks=all_tasks)
        unassigned = get_unassigned_tasks(all_tasks)
        today_empty = is_today_empty(all_tasks)

        # Nếu hôm nay không có task nào trong Sheet → nhắc riêng
        if today_empty and not overdue and not upcoming and not unassigned:
            msg = build_today_empty_message()
            await _send_message(page, msg)
            _log_event("reminder.sent", variant="today_empty")
            return True

        msg = build_daily_reminder(today, overdue, upcoming, unassigned, today_is_empty=today_empty)
        if msg is None:
            msg = build_no_work_message()

        await _send_message(page, msg)
        _log_event(
            "reminder.sent",
            variant="daily",
            today=len(today),
            overdue=len(overdue),
            upcoming=len(upcoming),
            unassigned=len(unassigned),
        )
        return True

    except Exception as e:
        _log_event("exception", scope="do_reminder", error=_serialize_error(e), traceback=traceback.format_exc())
        return False


async def _handle_command(page, text: str, recent_bot_replies: list[str]):
    """Xử lý lệnh từ chat."""
    lower = text.lower().strip()

    # === /nhacviec ===
    if lower.startswith("/nhacviec") or lower.startswith("/nhac viec"):
        await _do_reminder(page)
        return

    # === /hotrobai ===
    if lower.startswith("/hotrobai") or lower.startswith("/ho tro bai"):
        extra = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""

        try:
            all_tasks = fetch_all_tasks()
            # Tìm task chưa xong gần nhất
            pending = [t for t in all_tasks if not t.is_completed]
            if not pending:
                await _send_message(page, "Hiện không có task nào chưa hoàn thành để hỗ trợ viết bài.")
                return

            # Nếu extra chứa từ khóa liên quan đến task cụ thể → tìm task đó
            target_task = None
            if extra:
                for t in pending:
                    if extra.lower() in t.topic.lower() or extra.lower() in t.content_group.lower():
                        target_task = t
                        break
            if not target_task:
                target_task = pending[0]

            await _send_message(page, f"Đang gợi ý nội dung cho: {target_task.topic}...")
            result = await draft_article(target_task, extra)

            # Cắt bớt nếu quá dài cho Zalo
            if len(result) > 3500:
                result = result[:3500] + "\n\n(Nội dung đã được rút gọn)"

            await _send_message(page, result)
            recent_bot_replies.append(re.sub(r'\W+', '', result).lower())

        except Exception as e:
            await _send_message(page, f"Lỗi khi hỗ trợ viết bài: {e}")
        return

    # === /xemviec ===
    if lower.startswith("/xemviec") or lower.startswith("/xem viec"):
        try:
            all_tasks = fetch_all_tasks()
            pending = [t for t in all_tasks if not t.is_completed]
            if not pending:
                await _send_message(page, "Không có task nào đang chờ xử lý.")
                return

            lines = [f"DANH SÁCH CÔNG VIỆC ({len(pending)} việc chưa xong):"]
            lines.append("-" * 30)
            for t in pending:
                status_icon = "🟡" if t.status else "⚪"
                lines.append(f"{status_icon} [{t.due_date_raw}] {t.topic}")
                lines.append(f"   → {t.assignee or '(chưa giao)'} | {t.status or '(chưa cập nhật)'}")

            await _send_message(page, "\n".join(lines))
        except Exception as e:
            await _send_message(page, f"Lỗi: {e}")
        return

    # === /help ===
    if lower.startswith("/help") or lower.startswith("/huongdan"):
        bot_display = BOT_NAMES_RAW.split(',')[0].strip()
        help_text = (
            f"BOT NHẮC VIỆC TRUYỀN THÔNG ({bot_display})\n"
            "=" * 36 + "\n\n"
            f"Gọi tên em ({bot_display}) để hỏi, ví dụ:\n"
            f"  Ê {bot_display}, hôm nay có lịch đăng bài không?\n"
            f"  {bot_display}, giúp viết bài về kiểm lâm\n\n"
            "Hoặc dùng lệnh tắt:\n"
            "/nhacviec — Nhắc việc ngay (đọc Sheet)\n"
            "/xemviec — Xem danh sách việc chưa xong\n"
            "/hotrobai [mô tả] — AI gợi ý nội dung bài viết\n"
            "/help — Xem hướng dẫn này\n\n"
            "Bot tự động nhắc mỗi ngày lúc "
            f"{REMINDER_HOUR:02d}:{REMINDER_MINUTE:02d}."
        )
        await _send_message(page, help_text)
        return


async def _handle_natural_language(page, text: str, recent_bot_replies: list[str], chat_type: str = "unknown", chat_name: str = ""):
    """Xử lý câu hỏi tự nhiên (không phải lệnh /)."""
    intent = _detect_intent(text)

    if intent == 'nhacviec':
        await _do_reminder(page)
    elif intent == 'xemviec':
        await _handle_command(page, '/xemviec', recent_bot_replies)
    elif intent == 'hotrobai':
        await _handle_command(page, f'/hotrobai {text}', recent_bot_replies)
    elif intent == 'help':
        await _handle_command(page, '/help', recent_bot_replies)
    else:
        # Hỏi đáp tự do — sử dụng "não bộ" thông minh (Hermes Style)
        try:
            all_tasks = fetch_all_tasks()
            context_parts = []
            for t in all_tasks:
                context_parts.append(
                    f"[{t.due_date_raw}] {t.topic} | {t.assignee or '?'} | {t.status or '?'}"
                )
            context = "\n".join(context_parts)
            
            # Gọi "não bộ" thông minh
            result = await brain.process_message(text, chat_type, context)
            
            if len(result) > 4000:
                result = result[:4000] + "\n\n(Đã rút gọn)"
            
            await _send_message(page, result)
            recent_bot_replies.append(re.sub(r'\W+', '', result).lower())
        except Exception as e:
            _log_event("exception", scope="brain_process", error=str(e))
            await _send_message(page, f"Em gặp lỗi khi suy nghĩ: {e}")


async def main():
    _log_event(
        "bot.start",
        bot_names=BOT_NAMES_RAW,
        google_sheet_id=os.getenv("GOOGLE_SHEET_ID", ""),
        reminder_time=f"{REMINDER_HOUR:02d}:{REMINDER_MINUTE:02d}",
        group_name=ZALO_GROUP_NAME,
        headless=HEADLESS,
        user_data_dir=USER_DATA_DIR,
        build_id=BUILD_ID,
    )

    recent_bot_replies: list[str] = []
    last_reminder_date: str = ""

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-size=1280,800",
            ],
            viewport={"width": 1280, "height": 800},
            no_viewport=False,
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.bring_to_front()
        page.on("pageerror", lambda exc: _log_event("page.error", error=str(exc)))
        page.on(
            "console",
            lambda msg: _log_event("page.console", level=msg.type, text=msg.text)
            if msg.type in {"error", "warning"}
            else None,
        )

        _log_event("browser.ready", page_count=len(browser.pages))
        await page.goto(ZALO_URL)

        # Chờ đăng nhập
        login_indicator = ", ".join(LOGIN_INDICATOR_SELECTORS)
        session_state = await _detect_session_state(page)
        _log_event("session.restore", state=session_state, url=page.url)
        try:
            await page.wait_for_selector(login_indicator, timeout=10000)
            _log_event("session.ready", state="ready")
        except Exception:
            _log_event("session.login_required", state="login_required")
            
            # Vòng lặp chờ đăng nhập & cập nhật mã QR
            start_time = time.time()
            max_wait = 300  # 5 phút
            
            while time.time() - start_time < max_wait:
                if HEADLESS:
                    # Chờ mã QR hiện ra
                    await asyncio.sleep(2)
                    qr_path = os.path.join(BASE_DIR, "qr_code.png")
                    
                    # Thử chụp riêng vùng mã QR cho rõ nét
                    try:
                        # Zalo Web dùng canvas cho QR code
                        qr_locator = page.locator("canvas, .qr-code, [class*='qr-code']").first
                        if await qr_locator.count() > 0:
                            await qr_locator.screenshot(path=qr_path)
                            _log_event("session.qr.updated", mode="canvas", path=qr_path)
                        else:
                            await page.screenshot(path=qr_path, clip={"x": 400, "y": 150, "width": 500, "height": 500})
                            _log_event("session.qr.updated", mode="clip", path=qr_path)
                    except Exception:
                        await page.screenshot(path=qr_path)
                        _log_event("session.qr.updated", mode="full_page", path=qr_path)
                
                # Check xem đã login chưa
                try:
                    # Chờ ngắn xem locator tìm kiếm có hiện ra không
                    await page.wait_for_selector(login_indicator, timeout=30000) 
                    _log_event("session.ready", state="ready_after_qr")
                    break
                except Exception:
                    # Nếu chưa login, lặp lại để chụp mã QR mới
                    pass
            else:
                _log_event("session.timeout", wait_seconds=max_wait)
                sys.exit(1)
        
        # Dọn popup sau khi login
        try:
            restore = page.locator(
                "div[role='alertdialog'] button, button:has-text('Khôi phục'), button:has-text('Restore')"
            ).first
            if await restore.count() > 0:
                await restore.click(timeout=2000)
                _log_event("popup.dismissed", kind="restore_session")
        except Exception as exc:
            _log_event("exception", scope="dismiss_restore_popup", error=_serialize_error(exc))
            pass

        # Thử mở nhóm Zalo đã cấu hình
        if ZALO_GROUP_NAME:
            await asyncio.sleep(2)
            await _navigate_to_group(page, ZALO_GROUP_NAME)

        chat_state = await _capture_chat_state(page)
        _log_event(
            "chat.ready",
            chat_name=chat_state.get("chatName"),
            chat_type=chat_state.get("chatType"),
            classification_reason=chat_state.get("classificationReason"),
            message_count=len(chat_state.get("messages", [])),
            composer=chat_state.get("composerSelector"),
            header=chat_state.get("fullHeader"),
            active_sidebar=chat_state.get("activeSidebarName"),
        )

        # Tracking
        replied_signatures: set[str] = set()
        last_seen_user_message_by_chat: dict[str, str] = {}
        last_processed_signature_by_chat: dict[str, str] = {}
        last_reply_time_by_chat: dict[str, float] = {}  # Cooldown chống spam
        REPLY_COOLDOWN_SECONDS = 8  # Tối thiểu 8 giây giữa 2 lần reply cùng chat
        scan_counter = 0  # Đếm vòng lặp để quét unread định kỳ
        health_counter = 0

        async def _find_unread_sidebar_indices() -> list[int]:
            """Dùng JS tìm tất cả sidebar items có badge chưa đọc."""
            try:
                indices = await page.evaluate(r"""
                    () => {
                        const results = [];
                        // Tìm tất cả conversation items trong sidebar
                        const items = document.querySelectorAll(
                            '[id*="conversation-list"] > div, ' +
                            '.conv-list > div, ' +
                            'div[class*="conv-item"], ' +
                            'div.msg-item'
                        );
                        items.forEach((item, idx) => {
                            // Tìm badge chưa đọc: có thể là dot hoặc số
                            const badges = item.querySelectorAll(
                                '.unread-badge, .count-badge, [class*="unread"], [class*="badge"], ' +
                                '[class*="count"], span.num, .dot-unread, .dot'
                            );
                            for (const b of badges) {
                                const text = (b.textContent || '').trim();
                                const className = typeof b.className === 'string' ? b.className : '';
                                const style = window.getComputedStyle(b);
                                const isRed = style.backgroundColor.includes('rgb(255,') || style.backgroundColor.includes('rgb(244,');

                                if (/^\d+$/.test(text) || 
                                    className.includes('unread') ||
                                    className.includes('badge') ||
                                    isRed) {
                                    results.push(idx);
                                    break;
                                }
                            }
                        });
                        return results;
                    }
                """)
                return indices or []
            except Exception as exc:
                _log_event("exception", scope="find_unread_sidebar_indices", error=_serialize_error(exc))
                return []

        async def _process_chat(
            is_unread_click: bool,
            recent_bot_replies: list[str],
        ):
            """Xử lý tin nhắn trong chat đang mở."""
            chat_state = await _capture_chat_state(page)
            # Ưu tiên dùng incomingMessages (chỉ tin người khác gửi)
            context_msgs = chat_state.get("incomingMessages") or chat_state.get("messages", [])
            if not context_msgs:
                return

            chat_key = (chat_state.get("chatName") or "__active__")[:80]
            chat_type = chat_state.get("chatType") or "unknown"
            is_group = chat_type == "group"
            _log_event(
                "chat.classified",
                chat_key=chat_key,
                chat_type=chat_type,
                classification_reason=chat_state.get("classificationReason"),
                header=chat_state.get("fullHeader"),
                composer=chat_state.get("composerSelector"),
                active_sidebar=chat_state.get("activeSidebarName"),
                message_count=len(context_msgs),
            )

            # Lọc bỏ tin hệ thống và tin bot
            valid_msgs: list[str] = []
            for text in context_msgs:
                ignore_reason = _classify_ignored_message(
                    text,
                    chat_state=chat_state,
                    recent_bot_replies=recent_bot_replies,
                )
                if ignore_reason:
                    _log_event(
                        "message.ignored",
                        chat_key=chat_key,
                        chat_type=chat_type,
                        reason=ignore_reason,
                        text=text,
                    )
                    continue
                valid_msgs.append(text)

            if not valid_msgs:
                _log_event(
                    "message.skip",
                    chat_key=chat_key,
                    chat_type=chat_type,
                    reason="no_valid_message_after_filter",
                )
                return

            sig = _build_signature(valid_msgs)
            latest = valid_msgs[-1]

            # Khởi tạo lần đầu cho chat này
            is_first_seen = chat_key not in last_seen_user_message_by_chat
            if is_first_seen:
                last_seen_user_message_by_chat[chat_key] = sig
                if not is_unread_click:
                    _log_event(
                        "message.skip",
                        chat_key=chat_key,
                        reason="first_seen_active_chat_baseline",
                        chat_type=chat_type,
                        signature=sig,
                    )
                    return  # chat đang mở lần đầu → ghi nhận nhưng bỏ qua tin cũ
                else:
                    _log_event(
                        "message.first_seen_unread",
                        chat_key=chat_key,
                        chat_type=chat_type,
                        signature=sig,
                    )
                    # Unread click: phải xử lý ngay, KHÔNG return

            # Không có tin mới → bỏ qua
            if (not is_first_seen) and last_seen_user_message_by_chat.get(chat_key) == sig:
                _log_event(
                    "message.skip",
                    chat_key=chat_key,
                    chat_type=chat_type,
                    reason="duplicate_signature_already_seen",
                    signature=sig,
                )
                return
            if last_processed_signature_by_chat.get(chat_key) == sig:
                _log_event(
                    "message.skip",
                    chat_key=chat_key,
                    chat_type=chat_type,
                    reason="duplicate_signature_already_processed",
                    signature=sig,
                )
                return

            last_seen_user_message_by_chat[chat_key] = sig
            clean_latest = _normalize_text(latest).strip()
            _log_event(
                "message.detected",
                chat_key=chat_key,
                chat_type=chat_type,
                signature=sig,
                text=clean_latest,
                is_unread_click=is_unread_click,
            )

            # 1. Lệnh / (luôn xử lý)
            if clean_latest.startswith("/"):
                _log_event("message.parsed", chat_key=chat_key, parse_type="command", text=clean_latest)
                last_processed_signature_by_chat[chat_key] = sig
                replied_signatures.add(sig)
                try:
                    _log_event("decision.respond", chat_key=chat_key, decision=True, reason="command")
                    await _handle_command(page, clean_latest, recent_bot_replies)
                except Exception as exc:
                    _log_event("exception", scope="process_chat.command", error=_serialize_error(exc), traceback=traceback.format_exc())
                    raise

            # 2. Phản hồi nội dung
            else:
                mentioned, remainder = _detect_mention(clean_latest)
                response_reason = "mention" if mentioned else ("personal" if chat_type == "personal" else "ignored")
                _log_event(
                    "message.parsed",
                    chat_key=chat_key,
                    parse_type="natural_language",
                    mentioned=mentioned,
                    chat_type=chat_type,
                    group_name=ZALO_GROUP_NAME,
                    parsed_text=remainder if mentioned else clean_latest,
                )

                # Phản hồi nếu:
                # (a) Được gọi tên (Group/Personal đều được)
                # (b) Hoặc là chat cá nhân (không cần gọi tên)
                should_respond = mentioned or (chat_type == "personal")
                _log_event(
                    "decision.respond",
                    chat_key=chat_key,
                    decision=should_respond,
                    reason=response_reason,
                    chat_type=chat_type,
                    classification_reason=chat_state.get("classificationReason"),
                )

                if should_respond:
                    # Cooldown chống spam: không reply 2 lần liên tiếp trong 8 giây
                    now_ts = time.time()
                    last_reply = last_reply_time_by_chat.get(chat_key, 0)
                    if now_ts - last_reply < REPLY_COOLDOWN_SECONDS:
                        _log_event(
                            "message.skip",
                            chat_key=chat_key,
                            reason="cooldown_active",
                            seconds_since_last=round(now_ts - last_reply, 1),
                        )
                        return

                    if not mentioned:
                        remainder = clean_latest

                    last_processed_signature_by_chat[chat_key] = sig
                    replied_signatures.add(sig)
                    last_reply_time_by_chat[chat_key] = time.time()
                    try:
                        await _handle_natural_language(
                            page, remainder, recent_bot_replies, chat_type, chat_key
                        )
                    except Exception as exc:
                        _log_event("exception", scope="process_chat.natural_language", error=_serialize_error(exc), traceback=traceback.format_exc())
                        raise
                # else: không gọi tên trong group → im lặng

        # ===== VÒNG LẶP CHÍNH =====
        while True:
            try:
                health_counter += 1
                # === Kiểm tra nhắc tự động theo lịch ===
                now = datetime.now()
                today_key = now.strftime("%Y-%m-%d")
                if (
                    now.hour == REMINDER_HOUR
                    and now.minute == REMINDER_MINUTE
                    and today_key != last_reminder_date
                ):
                    _log_event("reminder.schedule_due", now=now.isoformat(timespec="seconds"))
                    if ZALO_GROUP_NAME:
                        await _navigate_to_group(page, ZALO_GROUP_NAME)
                        await asyncio.sleep(1)
                    await _do_reminder(page)
                    last_reminder_date = today_key

                # === Dọn popup quảng cáo ===
                try:
                    await page.evaluate(
                        'document.querySelectorAll(".zl-mini-notification, .ReactModal__Overlay, '
                        '[class*=\\"notification\\"]\").forEach(e => e.style.display="none")'
                    )
                except Exception:
                    pass

                if health_counter % 20 == 0:
                    session_state = await _detect_session_state(page)
                    _log_event("session.healthcheck", state=session_state, url=page.url)

                # === 1. Đọc tin nhắn từ chat đang mở ===
                await _process_chat(
                    is_unread_click=False,
                    recent_bot_replies=recent_bot_replies,
                )

                # === 2. Mỗi 5 vòng, quét sidebar tìm chat chưa đọc ===
                scan_counter += 1
                if scan_counter >= 2:
                    scan_counter = 0

                    unread_indices = await _find_unread_sidebar_indices()

                    if unread_indices:
                        _log_event("sidebar.unread_found", count=len(unread_indices), indices=unread_indices)

                        for idx in unread_indices:
                            try:
                                # Click vào sidebar item có badge
                                items = await page.locator(
                                    ", ".join(SIDEBAR_ITEM_SELECTORS)
                                ).all()

                                if idx < len(items):
                                    await items[idx].click(force=True)
                                    await asyncio.sleep(1.5)

                                    await _process_chat(
                                        is_unread_click=True,
                                        recent_bot_replies=recent_bot_replies,
                                    )
                            except Exception as e:
                                _log_event("exception", scope="scan_unread_chat", chat_index=idx, error=_serialize_error(e))
                                continue

                        # Quay lại nhóm chính sau khi xử lý xong
                        if ZALO_GROUP_NAME:
                            await _navigate_to_group(page, ZALO_GROUP_NAME)

            except Exception as e:
                _log_event("exception", scope="main_loop", error=_serialize_error(e), traceback=traceback.format_exc())

            await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Đã tắt Zalo Work Reminder Bot.")
