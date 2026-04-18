"""
zalo_bot.py — Bot Zalo nhắc việc Truyền thông VQG Yok Đôn

Chạy trên Zalo Web qua Playwright.
- Chỉ trả lời khi được gọi đích danh (ví dụ: "Nhân Viên Mới Yok Đôn")
- Hiểu ngôn ngữ tự nhiên (không bắt buộc dùng lệnh /)
- Tự động nhắc việc theo lịch (mặc định 8h sáng)
- Đọc Google Sheet để lấy dữ liệu công việc
"""

import asyncio
import os
import re
import sys
import time
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
from ai_helper import draft_article, answer_question

# === Config ===
ZALO_URL = "https://chat.zalo.me/"
USER_DATA_DIR = "/tmp/zalo_reminder_profile"
os.makedirs(USER_DATA_DIR, exist_ok=True)

ZALO_GROUP_NAME = os.getenv("ZALO_GROUP_NAME", "")
REMINDER_HOUR = int(os.getenv("REMINDER_HOUR", "8"))
REMINDER_MINUTE = int(os.getenv("REMINDER_MINUTE", "0"))
DAYS_AHEAD = int(os.getenv("DAYS_AHEAD", "3"))

# === Tên bot — chỉ trả lời khi được gọi đích danh ===
# Có thể đặt nhiều tên, cách nhau bằng dấu phẩy
BOT_NAMES_RAW = os.getenv("BOT_NAME", "Nhân Viên Mới Yok Đôn")
BOT_NAMES = [n.strip().lower() for n in BOT_NAMES_RAW.split(",") if n.strip()]
# Tạo thêm biến thể viết tắt/không dấu tự động
import unicodedata
def _remove_accents(s: str) -> str:
    nfkd = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in nfkd if not unicodedata.combining(c))
BOT_NAMES_NORMALIZED = list(set(
    [n for n in BOT_NAMES]
    + [_remove_accents(n) for n in BOT_NAMES]
))

# Temp dir để tránh macOS chặn
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ["TMPDIR"] = os.path.join(BASE_DIR, ".tmp")
os.makedirs(os.environ["TMPDIR"], exist_ok=True)


def _normalize_text(text: str) -> str:
    """Chuẩn hóa text chat, bỏ timestamp cuối."""
    clean = re.sub(r'\n\d{1,2}:\d{2}$', '', (text or "").strip())
    return clean.strip()


def _build_signature(messages: list[str]) -> str:
    """Tạo chữ ký từ tin cuối để so sánh."""
    if not messages:
        return ""
    latest = _normalize_text(messages[-1])
    return re.sub(r'\s+', ' ', latest).strip().lower()


def _strip_zalo_mentions(text: str) -> str:
    """Xoá tag @mention của Zalo (dạng @Tên Người Dùng) ra khỏi text."""
    # Zalo @mention: @TenNguoiDung hoặc @Tên Người Dùng (cho đến dấu , hoặc cuối)
    cleaned = re.sub(r'@[\w\sÀ-ỹ]+?(?=[,!?.:\s]|$)', '', text)
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

    # Nhắc việc / lịch đăng bài
    nhac_kws = [
        'nhắc việc', 'nhac viec', 'có lịch', 'co lich', 'lịch đăng',
        'lich dang', 'hôm nay', 'hom nay', 'đăng bài', 'dang bai',
        'công việc', 'cong viec', 'việc gì', 'viec gi', 'có gì',
        'co gi', 'nhắc', 'nhac', 'deadline', 'hạn', 'han',
        'phải làm', 'phai lam', 'cần làm', 'can lam',
    ]
    if any(k in lower or k in lower_na for k in nhac_kws):
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

    # Help
    help_kws = ['hướng dẫn', 'huong dan', 'help', 'làm gì được', 'lam gi duoc', 'biết làm gì', 'biet lam gi']
    if any(k in lower or k in lower_na for k in help_kws):
        return 'help'

    # Mặc định: hỏi đáp tự do
    return 'hoidap'


async def _send_message(page, text: str):
    """Gửi tin nhắn vào khung chat hiện tại."""
    chat_input = page.locator(
        "#richInput, .chat-input, div[contenteditable='true'], #chatInput"
    ).first
    if await chat_input.count() > 0:
        await chat_input.click(force=True)
        await page.keyboard.insert_text(text)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        return True
    return False


async def _navigate_to_group(page, group_name: str) -> bool:
    """Tìm và mở nhóm Zalo theo tên — nhiều cách fallback."""
    if not group_name:
        print("⚠️ Chưa cấu hình ZALO_GROUP_NAME trong .env")
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
                    print(f"✅ Đã mở nhóm (sidebar): {group_name}")
                    return True
            except:
                continue
    except:
        pass

    # === Cách 2: Dùng ô tìm kiếm ===
    search_selectors = [
        "input[placeholder*='Tìm kiếm']",
        "input[placeholder*='Search']",
        "input[placeholder*='tìm']",
        "input[type='text'][class*='search']",
        "#contact-search-input",
    ]
    search_input = None
    for sel in search_selectors:
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
                        print(f"✅ Đã mở nhóm (tìm kiếm): {group_name}")
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
            print(f"⚠️ Lỗi khi tìm kiếm: {e}")

    print(f"⚠️ Không tìm thấy nhóm: {group_name}")
    print(f"   Bot sẽ lắng nghe tất cả các chat có tin nhắn chưa đọc.")
    return False


async def _do_reminder(page) -> bool:
    """Thực hiện nhắc việc: đọc Sheet → build message → gửi."""
    try:
        print("📊 Đang đọc Google Sheet...")
        all_tasks = fetch_all_tasks()

        if not all_tasks:
            msg = build_sheet_empty_message()
            await _send_message(page, msg)
            print("📤 Đã gửi thông báo Sheet trống.")
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
            print("📤 Đã gửi nhắc: Sheet trống cho hôm nay.")
            return True

        msg = build_daily_reminder(today, overdue, upcoming, unassigned, today_is_empty=today_empty)
        if msg is None:
            msg = build_no_work_message()

        await _send_message(page, msg)
        print(f"📤 Đã gửi nhắc việc ({len(today)} hôm nay / {len(overdue)} quá hạn / {len(upcoming)} sắp tới)")
        return True

    except Exception as e:
        print(f"❌ Lỗi khi nhắc việc: {e}")
        import traceback
        traceback.print_exc()
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


async def _handle_natural_language(page, text: str, recent_bot_replies: list[str]):
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
        # Hỏi đáp tự do — gửi kèm context từ Sheet
        try:
            all_tasks = fetch_all_tasks()
            context_parts = []
            for t in all_tasks:
                context_parts.append(
                    f"[{t.due_date_raw}] {t.topic} | {t.assignee or '?'} | {t.status or '?'}"
                )
            context = "\n".join(context_parts)
            result = await answer_question(text, context)
            if len(result) > 3500:
                result = result[:3500] + "\n\n(Đã rút gọn)"
            await _send_message(page, result)
            recent_bot_replies.append(re.sub(r'\W+', '', result).lower())
        except Exception as e:
            await _send_message(page, f"Em gặp lỗi khi trả lời: {e}")


async def main():
    print("🚀 Khởi động Zalo Work Reminder Bot...")
    print(f"🏷️  Tên bot: {BOT_NAMES_RAW}")
    print(f"📋 Google Sheet: {os.getenv('GOOGLE_SHEET_ID', '(chưa cấu hình)')}")
    print(f"⏰ Nhắc tự động: {REMINDER_HOUR:02d}:{REMINDER_MINUTE:02d}")
    print(f"👥 Nhóm Zalo: {ZALO_GROUP_NAME or '(chưa cấu hình)'}")
    print()

    recent_bot_replies: list[str] = []
    last_reminder_date: str = ""

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--window-position=0,0",
            ],
            no_viewport=True,
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.bring_to_front()

        print("🌐 Đang mở Zalo Web...")
        await page.goto(ZALO_URL)

        # Chờ đăng nhập
        login_indicator = "input[placeholder*='Tìm kiếm'], input[placeholder*='Search'], .msg-item, div[data-id]"
        try:
            await page.wait_for_selector(login_indicator, timeout=10000)
            print("✅ Đã đăng nhập Zalo!")

            # Dọn popup
            try:
                restore = page.locator(
                    "div[role='alertdialog'] button, button:has-text('Khôi phục'), button:has-text('Restore')"
                ).first
                if await restore.count() > 0:
                    await restore.click(timeout=2000)
            except:
                pass
        except:
            os.system(
                'osascript -e \'display notification "Hãy quét mã QR trên cửa sổ Chrome!" '
                'with title "Zalo Bot" sound name "Glass"\''
            )
            print("=" * 50)
            print("⚠️  HÃY QUÉT MÃ QR TRÊN CỬA SỔ CHROME!")
            print("⚠️  Anh có 5 PHÚT để quét...")
            print("=" * 50)
            await page.wait_for_selector(login_indicator, timeout=300000)
            print("✅ Đã đăng nhập sau khi quét QR!")

        # Thử mở nhóm Zalo đã cấu hình
        if ZALO_GROUP_NAME:
            await asyncio.sleep(2)
            await _navigate_to_group(page, ZALO_GROUP_NAME)

        print("🤖 Bot đang lắng nghe...")

        # Tracking
        replied_signatures: set[str] = set()
        last_seen_user_message_by_chat: dict[str, str] = {}
        last_processed_signature_by_chat: dict[str, str] = {}
        scan_counter = 0  # Đếm vòng lặp để quét unread định kỳ

        async def _find_unread_sidebar_indices() -> list[int]:
            """Dùng JS tìm tất cả sidebar items có badge chưa đọc."""
            try:
                indices = await page.evaluate("""
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
                            // Tìm badge chưa đọc: thường là một element nhỏ chứa số
                            const badges = item.querySelectorAll(
                                '[class*="unread"], [class*="badge"], ' +
                                '[class*="count"], span.num'
                            );
                            for (const b of badges) {
                                const text = b.textContent.trim();
                                // Badge chứa số (1, 2, 3...) hoặc có class unread
                                if (/^\\d+$/.test(text) || 
                                    b.className.includes('unread') ||
                                    b.className.includes('badge')) {
                                    results.push(idx);
                                    break;
                                }
                            }
                        });
                        return results;
                    }
                """)
                return indices or []
            except:
                return []

        async def _get_chat_info(page_obj) -> tuple[str, bool]:
            """Lấy tên và loại chat (group/personal) từ header hiện tại."""
            chat_key = "__active__"
            is_group = True  # Mặc định giả định là group để an toàn
            try:
                # Dùng JS để lấy header info (nhanh + chính xác hơn)
                info = await page_obj.evaluate("""
                    () => {
                        // Tìm header chat
                        const headerEl = document.querySelector(
                            '[class*="chat-name"], [class*="conv-name"], ' +
                            '.chat-box-header, [class*="header-info"]'
                        );
                        const name = headerEl ? headerEl.textContent.trim().split('\\n')[0] : '';
                        
                        // Tìm subtitle (chứa "X thành viên" cho group)
                        const subtitleEl = document.querySelector(
                            '[class*="header-subtitle"], [class*="chat-sub"], ' +
                            '[class*="member-count"], [class*="group-member"]'
                        );
                        const subtitle = subtitleEl ? subtitleEl.textContent.trim() : '';
                        
                        // Tìm toàn bộ header area
                        const headerArea = document.querySelector(
                            '.chat-box-header, header, [class*="chat-header"]'
                        );
                        const fullHeader = headerArea ? headerArea.textContent : '';
                        
                        return { name, subtitle, fullHeader };
                    }
                """)
                if info.get("name"):
                    chat_key = info["name"][:50]  # giới hạn length
                
                full = (info.get("subtitle", "") + " " + info.get("fullHeader", "")).lower()
                if "thành viên" in full or "members" in full or "nhóm" in full:
                    is_group = True
                else:
                    is_group = False
            except:
                pass
            return chat_key, is_group

        async def _read_current_chat_messages() -> list[str]:
            """Đọc tin nhắn từ chat đang mở."""
            msgs = await page.locator(
                "div.card--text, div.chat-message, span.text, "
                "div.message-content, [class*='message-text']"
            ).all()
            context_msgs: list[str] = []
            for m in list(msgs)[-15:]:
                try:
                    text = await m.inner_text()
                    if text.strip():
                        context_msgs.append(text.strip())
                except:
                    pass
            return context_msgs

        async def _process_chat(
            is_unread_click: bool,
            recent_bot_replies: list[str],
        ):
            """Xử lý tin nhắn trong chat đang mở."""
            context_msgs = await _read_current_chat_messages()
            if not context_msgs:
                return

            chat_key, is_group = await _get_chat_info(page)

            # Lọc bỏ tin hệ thống và tin bot
            valid_msgs: list[str] = []
            for text in context_msgs:
                clean = _normalize_text(text)
                norm = re.sub(r'\W+', '', clean).lower()

                if "Tải về để xem" in text and "KB" in text:
                    continue

                is_bot = False
                for prev in recent_bot_replies[-30:]:
                    if norm == prev:
                        is_bot = True
                        break
                    if len(norm) >= 20 and len(prev) >= 20:
                        if str(norm)[:20] == str(prev)[:20]:
                            is_bot = True
                            break
                if is_bot:
                    continue
                valid_msgs.append(text)

            if not valid_msgs:
                return

            sig = _build_signature(valid_msgs)
            latest = valid_msgs[-1]

            # Khởi tạo lần đầu cho chat này
            is_first_seen = chat_key not in last_seen_user_message_by_chat
            if is_first_seen:
                last_seen_user_message_by_chat[chat_key] = sig
                if not is_unread_click:
                    return  # chat đang mở lần đầu → ghi nhận nhưng bỏ qua tin cũ

            # Không có tin mới → bỏ qua
            if (not is_first_seen) and last_seen_user_message_by_chat.get(chat_key) == sig:
                return
            if last_processed_signature_by_chat.get(chat_key) == sig:
                return

            last_seen_user_message_by_chat[chat_key] = sig
            clean_latest = _normalize_text(latest).strip()

            # 1. Lệnh / (luôn xử lý)
            if clean_latest.startswith("/"):
                print(f"\n📩 [{chat_key}] Lệnh: {clean_latest}")
                last_processed_signature_by_chat[chat_key] = sig
                replied_signatures.add(sig)
                await _handle_command(page, clean_latest, recent_bot_replies)

            # 2. Phản hồi nội dung
            else:
                mentioned, remainder = _detect_mention(clean_latest)

                # Phản hồi nếu:
                # (a) Được gọi tên (Group/Personal đều được)
                # (b) Hoặc là chat cá nhân (không cần gọi tên)
                should_respond = mentioned or (not is_group)

                if should_respond:
                    if mentioned:
                        print(f"\n📩 [{chat_key}] Được gọi tên: {clean_latest}")
                    else:
                        print(f"\n📩 [{chat_key}] Chat cá nhân: {clean_latest}")
                        remainder = clean_latest

                    last_processed_signature_by_chat[chat_key] = sig
                    replied_signatures.add(sig)
                    await _handle_natural_language(
                        page, remainder, recent_bot_replies
                    )
                # else: không gọi tên trong group → im lặng

        # ===== VÒNG LẶP CHÍNH =====
        while True:
            try:
                # === Kiểm tra nhắc tự động theo lịch ===
                now = datetime.now()
                today_key = now.strftime("%Y-%m-%d")
                if (
                    now.hour == REMINDER_HOUR
                    and now.minute == REMINDER_MINUTE
                    and today_key != last_reminder_date
                ):
                    print(f"\n⏰ Đến giờ nhắc việc tự động ({now.strftime('%H:%M')})...")
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
                except:
                    pass

                # === 1. Đọc tin nhắn từ chat đang mở ===
                await _process_chat(
                    is_unread_click=False,
                    recent_bot_replies=recent_bot_replies,
                )

                # === 2. Mỗi 5 vòng, quét sidebar tìm chat chưa đọc ===
                scan_counter += 1
                if scan_counter >= 5:
                    scan_counter = 0

                    unread_indices = await _find_unread_sidebar_indices()

                    if unread_indices:
                        print(f"🔍 Có {len(unread_indices)} chat chưa đọc")

                        for idx in unread_indices:
                            try:
                                # Click vào sidebar item có badge
                                items = await page.locator(
                                    '[id*="conversation-list"] > div, '
                                    '.conv-list > div, '
                                    'div[class*="conv-item"], '
                                    'div.msg-item'
                                ).all()

                                if idx < len(items):
                                    await items[idx].click(force=True)
                                    await asyncio.sleep(1.5)

                                    await _process_chat(
                                        is_unread_click=True,
                                        recent_bot_replies=recent_bot_replies,
                                    )
                            except Exception as e:
                                print(f"⚠️ Lỗi quét chat [{idx}]: {e}")
                                continue

                        # Quay lại nhóm chính sau khi xử lý xong
                        if ZALO_GROUP_NAME:
                            await _navigate_to_group(page, ZALO_GROUP_NAME)

            except Exception as e:
                print(f"⚠️ Lỗi vòng lặp (thử lại sau 3s): {e}")

            await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Đã tắt Zalo Work Reminder Bot.")
