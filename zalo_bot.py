"""
zalo_bot.py — Bot Zalo nhắc việc Truyền thông VQG Yok Đôn

Chạy trên Zalo Web qua Playwright.
- Tự động nhắc việc theo lịch (mặc định 8h sáng)
- Lắng nghe lệnh /nhacviec, /hotrobai trong nhóm Zalo
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
    """Tìm và mở nhóm Zalo theo tên."""
    if not group_name:
        print("⚠️ Chưa cấu hình ZALO_GROUP_NAME trong .env")
        return False

    # Tìm trong danh sách chat
    search_input = page.locator(
        "input[placeholder*='Tìm kiếm'], input[placeholder*='Search']"
    ).first
    if await search_input.count() > 0:
        await search_input.click(force=True)
        await search_input.fill(group_name)
        await asyncio.sleep(2)

        # Click kết quả đầu tiên
        result = page.locator(f"div.msg-item:has-text('{group_name}')").first
        if await result.count() > 0:
            await result.click(force=True)
            await asyncio.sleep(1)
            # Xoá text tìm kiếm
            await search_input.clear()
            await page.keyboard.press("Escape")
            print(f"✅ Đã mở nhóm: {group_name}")
            return True

        # Thử bấm kết quả tìm kiếm khác
        any_result = page.locator(".search-item, .conv-search-item, [class*='search-result']").first
        if await any_result.count() > 0:
            await any_result.click(force=True)
            await asyncio.sleep(1)
            await search_input.clear()
            await page.keyboard.press("Escape")
            print(f"✅ Đã mở nhóm (tìm kiếm): {group_name}")
            return True

        await page.keyboard.press("Escape")

    print(f"⚠️ Không tìm thấy nhóm: {group_name}")
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
        help_text = (
            "BOT NHẮC VIỆC TRUYỀN THÔNG\n"
            "=" * 30 + "\n\n"
            "Các lệnh:\n"
            "/nhacviec — Nhắc việc ngay (đọc Sheet)\n"
            "/xemviec — Xem danh sách việc chưa xong\n"
            "/hotrobai [mô tả] — AI gợi ý nội dung bài viết\n"
            "/help — Xem hướng dẫn này\n\n"
            "Bot tự động nhắc mỗi ngày lúc "
            f"{REMINDER_HOUR:02d}:{REMINDER_MINUTE:02d}."
        )
        await _send_message(page, help_text)
        return


async def main():
    print("🚀 Khởi động Zalo Work Reminder Bot...")
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
        last_seen_signature = ""

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
                    # Mở nhóm trước khi gửi
                    if ZALO_GROUP_NAME:
                        await _navigate_to_group(page, ZALO_GROUP_NAME)
                        await asyncio.sleep(1)
                    await _do_reminder(page)
                    last_reminder_date = today_key

                # === Dọn popup quảng cáo ===
                try:
                    await page.evaluate(
                        'document.querySelectorAll(".zl-mini-notification, .ReactModal__Overlay, '
                        '[class*=\\"notification\\"]").forEach(e => e.style.display="none")'
                    )
                except:
                    pass

                # === Đọc tin nhắn mới ===
                msgs = await page.locator(
                    "div.card--text, div.chat-message, span.text, div.message-content, [class*='message-text']"
                ).all()

                if msgs:
                    context_msgs: list[str] = []
                    msgs_list = list(msgs)[-10:]
                    for m in msgs_list:
                        try:
                            text = await m.inner_text()
                            if text.strip():
                                context_msgs.append(text.strip())
                        except:
                            pass

                    if context_msgs:
                        # Lọc bỏ tin nhắn hệ thống và tin bot
                        valid_msgs: list[str] = []
                        for text in context_msgs:
                            clean = _normalize_text(text)
                            norm = re.sub(r'\W+', '', clean).lower()

                            # Bỏ tin hệ thống Zalo
                            if "Tải về để xem" in text and "KB" in text:
                                continue

                            # Bỏ tin bot đã gửi
                            is_bot = False
                            for prev in recent_bot_replies[-20:]:
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

                        if valid_msgs:
                            sig = _build_signature(valid_msgs)
                            latest = valid_msgs[-1]

                            # Chỉ xử lý nếu có tin mới
                            if sig and sig != last_seen_signature and sig not in replied_signatures:
                                # Kiểm tra có phải lệnh không
                                clean_latest = _normalize_text(latest).strip()
                                if clean_latest.startswith("/"):
                                    print(f"\n📩 Lệnh mới: {clean_latest}")
                                    last_seen_signature = sig
                                    replied_signatures.add(sig)
                                    await _handle_command(page, clean_latest, recent_bot_replies)
                                else:
                                    # Chỉ cập nhật signature, không phản hồi tin thường
                                    last_seen_signature = sig

            except Exception as e:
                print(f"⚠️ Lỗi vòng lặp (thử lại sau 3s): {e}")

            await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Đã tắt Zalo Work Reminder Bot.")
