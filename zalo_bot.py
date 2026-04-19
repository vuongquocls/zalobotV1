"""
zalo_bot.py (Refactored) — Bot Yok Đôn Lite & Strong
Chạy trên VPS Linux qua Playwright với cơ chế Visual Heuristic và Stealth.
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

# Modules nội bộ
from sheet_reader import (fetch_all_tasks, get_today_tasks, get_upcoming_tasks, 
                         get_overdue_tasks, get_unassigned_tasks, is_today_empty)
from message_builder import (build_daily_reminder, build_sheet_empty_message, 
                            build_today_empty_message)
import brain
from ai_helper import answer_question

# === Config ===
ZALO_URL = "https://chat.zalo.me/"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USER_DATA_DIR = os.path.join(BASE_DIR, "zalo_profile")
os.makedirs(USER_DATA_DIR, exist_ok=True)
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
ZALO_GROUP_NAME = os.getenv("ZALO_GROUP_NAME", "Truyền thông Yok Đôn")

# Thể thức chuyên gia: Nhân Viên Mới Yok Đôn
BOT_HINT = "Nhân Viên Mới Yok Đôn"
REPLY_COOLDOWN_SECONDS = 8
REMINDER_HOUR = int(os.getenv("REMINDER_HOUR", "8"))
REMINDER_MINUTE = int(os.getenv("REMINDER_MINUTE", "0"))

# === Selectors (Visual Heuristic fallback) ===
LOGIN_INDICATOR_SELECTORS = ["#contact-search-input", "input[placeholder*='Tìm kiếm']", "div[data-id]"]
CHAT_INPUT_SELECTORS = ["#richInput", "#chatInput", "footer [contenteditable='true']", "div[contenteditable='true']"]

def _log_event(event: str, **kwargs):
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, **kwargs}
    print(json.dumps(entry, ensure_ascii=False))

def _serialize_error(exc):
    return {"type": type(exc).__name__, "message": str(exc)}

async def _send_message(page, text: str):
    """Gửi tin nhắn bằng nhiều chiến lược (bypass composer ẩn)."""
    
    # === Chiến lược 1: Tìm TẤT CẢ contenteditable trong DOM (kể cả ẩn) ===
    composer_info = await page.evaluate("""
        () => {
            const all = document.querySelectorAll('[contenteditable="true"], textarea, #richInput, #chatInput');
            const results = [];
            for (const el of all) {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                results.push({
                    tag: el.tagName,
                    id: el.id,
                    cls: el.className.substring(0, 80),
                    w: r.width, h: r.height,
                    visible: style.display !== 'none' && style.visibility !== 'hidden' && r.width > 0,
                    display: style.display,
                    visibility: style.visibility
                });
            }
            return results;
        }
    """)
    _log_event("composer.scan", found=len(composer_info), details=composer_info)
    
    # === Chiến lược 2: Nếu tìm thấy composer (dù ẩn) → ép hiện và dùng ===
    if composer_info:
        sent = await page.evaluate("""
            (text) => {
                const editors = document.querySelectorAll('[contenteditable="true"], textarea, #richInput, #chatInput');
                for (const el of editors) {
                    // Ép hiện element nếu bị ẩn
                    el.style.display = 'block';
                    el.style.visibility = 'visible';
                    el.style.opacity = '1';
                    el.style.height = 'auto';
                    el.style.minHeight = '30px';
                    el.style.position = 'relative';
                    el.style.zIndex = '99999';
                    
                    // Focus và nhập nội dung
                    el.focus();
                    el.innerHTML = text;
                    el.textContent = text;
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }
                return false;
            }
        """, text)
        
        if sent:
            await asyncio.sleep(0.3)
            await page.keyboard.press("Enter")
            _log_event("reply.sent", method="force_composer")
            return True
    
    # === Chiến lược 3: Keyboard injection — gõ trực tiếp không cần composer ===
    _log_event("reply.fallback", method="keyboard_inject")
    try:
        # Click vào giữa vùng chat để focus
        await page.mouse.click(600, 500)
        await asyncio.sleep(0.3)
        
        # Tab nhiều lần để tìm composer (nếu tồn tại nhưng không focus được)
        for _ in range(5):
            await page.keyboard.press("Tab")
            await asyncio.sleep(0.1)
        
        # Thử gõ trực tiếp
        await page.keyboard.insert_text(text)
        await asyncio.sleep(0.3)
        await page.keyboard.press("Enter")
        _log_event("reply.sent", method="keyboard_tab")
        return True
    except Exception as e:
        _log_event("reply.keyboard_fail", error=_serialize_error(e))
    
    # === Chiến lược 4: Clipboard paste ===
    try:
        await page.evaluate(f'navigator.clipboard.writeText({json.dumps(text)})')
        await page.keyboard.press("Control+V")
        await asyncio.sleep(0.3)
        await page.keyboard.press("Enter")
        _log_event("reply.sent", method="clipboard")
        return True
    except Exception as e:
        _log_event("reply.all_failed", error=_serialize_error(e))
        return False

async def _capture_chat_state(page):
    """Trích xuất trạng thái chat (Visual Heuristic). Tối ưu hoá cho VPS."""
    try:
        return await page.evaluate("""
            (groupName) => {
                const root = document.querySelector('#chat-root') || document.body;
                const rRect = root.getBoundingClientRect();
                const centerX = rRect.left + rRect.width / 2;
                
                // 1. Tìm Header & Chat Name
                const header = document.querySelector('header') || document.querySelector('[class*="header"]');
                const headerText = header ? header.innerText : '';
                
                // 2. Tìm Composer
                const composer = ['#richInput', '#chatInput', '[contenteditable="true"]']
                    .map(s => document.querySelector(s))
                    .find(e => e && e.getBoundingClientRect().height > 20);
                
                // 3. Phân loại Group vs Personal
                let type = 'unknown';
                if (headerText.includes('thành viên') || headerText.includes('members')) type = 'group';
                else if (composer) type = 'personal';
                
                // 4. Lấy messages mới nhất (Lọc tin nhắn của Bot bằng vị trí căn phải)
                const msgs = [...document.querySelectorAll('div, span')]
                    .filter(el => {
                        const r = el.getBoundingClientRect();
                        return r.height > 10 && r.width > 20 && r.top > 100 && r.top < (composer ? composer.getBoundingClientRect().top : 9999);
                    })
                    .map(el => {
                        const r = el.getBoundingClientRect();
                        return { text: el.innerText, isMe: r.left > centerX, top: r.top };
                    })
                    .filter(m => m.text && m.text.length < 500)
                    .sort((a,b) => a.top - b.top);
                
                // Trả về data gọn nhẹ
                return {
                    chatName: headerText.split('\\n')[0] || '',
                    chatType: type,
                    hasComposer: !!composer,
                    messages: msgs.map(m => m.text).slice(-15),
                    incomingMessages: msgs.filter(m => !m.isMe).map(m => m.text).slice(-10)
                };
            }
        """, ZALO_GROUP_NAME)
    except:
        return {}

async def _find_unread_sidebar(page):
    """Tìm index các chat chưa đọc bằng toạ độ hình học."""
    return await page.evaluate("""
        () => {
            const sidebar = Array.from(document.querySelectorAll('div'))
                .find(d => {
                    const r = d.getBoundingClientRect();
                    return r.left < 50 && r.width > 200 && r.width < 450 && r.height > 400;
                });
            if (!sidebar) return [];
            
            const items = Array.from(sidebar.children).filter(c => c.getBoundingClientRect().height > 40);
            return items.map((it, idx) => {
                // Phổ rộng: badge đỏ, emoji báo unread, hoặc class name chứa unread/count
                const hasBadge = !!it.querySelector('[class*="unread"], [class*="badge"], [class*="count"], .cnt, .v-badge');
                const hasUnreadSymbol = it.innerText.includes('●') || it.innerText.includes('○');
                return (hasBadge || hasUnreadSymbol) ? idx : -1;
            }).filter(i => i !== -1);
        }
    """)

async def _click_sidebar(page, idx):
    """Click vào sidebar bằng toạ độ chuột thực."""
    res = await page.evaluate("""
        (targetIdx) => {
            const sidebar = Array.from(document.querySelectorAll('div'))
                .find(d => {
                    const r = d.getBoundingClientRect();
                    return r.left < 50 && r.width > 200 && r.height > 400;
                });
            const items = sidebar ? Array.from(sidebar.children).filter(c => c.getBoundingClientRect().height > 40) : [];
            const it = items[targetIdx];
            if (!it) return null;
            const r = it.getBoundingClientRect();
            return { x: r.left + r.width/2, y: r.top + r.height/2 };
        }
    """, idx)
    if res:
        await page.mouse.click(res['x'], res['y'])
        await asyncio.sleep(1)

async def _navigate_to_group(page, name):
    """Mở nhóm bằng cách tìm kiếm và click kết quả đầu tiên."""
    if not name: return False
    try:
        await page.mouse.click(150, 40) # Click vùng search search
        await page.keyboard.type(name, delay=50)
        await asyncio.sleep(2)
        # Click kết quả đầu tiên trong danh sách search
        await page.mouse.click(200, 150)
        await asyncio.sleep(1)
        return True
    except:
        return False

async def _handle_natural_language(page, text, chat_type):
    """Phản hồi bằng AI dựa trên não bộ Quy chế Yok Đôn."""
    try:
        # Prompt hệ thống đã được nạp trong brain.py
        reply = await answer_question(text, chat_type)
        if reply:
            await _send_message(page, reply)
    except Exception as e:
        _log_event("ai.error", error=_serialize_error(e))

async def main():
    _log_event("bot.starting", version="Firefox-Edition")
    async with async_playwright() as p:
        # FIREFOX — tránh bị Zalo phát hiện "Chrome for Testing"
        browser = await p.firefox.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=HEADLESS,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
            locale="vi-VN",
        )
        page = browser.pages[0]
        await page.goto(ZALO_URL)
        
        # Chờ login
        await asyncio.sleep(5)
        _log_event("session.wait", help="Vui lòng quét mã QR nếu chưa login")
        
        last_reminder_day = ""
        last_processed_sig = {}
        last_reply_time = {}

        while True:
            try:
                now = datetime.now()
                # 1. Nhắc việc định kỳ (8h)
                if now.hour == REMINDER_HOUR and now.minute == REMINDER_MINUTE and now.strftime("%D") != last_reminder_day:
                    await _navigate_to_group(page, ZALO_GROUP_NAME)
                    all_tasks = fetch_all_tasks()
                    msg = build_daily_reminder(all_tasks) # Simplified for this demo
                    await _send_message(page, msg)
                    last_reminder_day = now.strftime("%D")

                # 2. Xử lý tin chưa đọc từ Sidebar
                unreads = await _find_unread_sidebar(page)
                
                # Check thêm chat ĐANG MỞ hiện tại (tránh việc noVNC mở sẵn làm mất badge)
                targets = list(unreads)
                if not targets:
                    targets = [999] # 999 là mã giả để báo hiệu "check active chat"
                
                for idx in targets:
                    if idx != 999:
                        await _click_sidebar(page, idx)
                    
                    state = await _capture_chat_state(page)
                    incoming = state.get("incomingMessages", [])
                    
                    if incoming:
                        latest = incoming[-1]
                        chat_key = state.get("chatName", "temp")
                        
                        # Log vắn tắt để debug
                        _log_event("chat.capture", name=chat_key, last_msg=latest[:30], type=state["chatType"])
                        
                        # Điều kiện trả lời: Group có tag bot, hoặc chat cá nhân
                        is_personal = state["chatType"] == "personal"
                        has_hint = BOT_HINT.lower() in latest.lower()
                        should_reply = is_personal or has_hint
                        
                        # Cooldown & Dedupe
                        sig = hash(latest)
                        if should_reply and last_processed_sig.get(chat_key) != sig:
                            if time.time() - last_reply_time.get(chat_key, 0) > REPLY_COOLDOWN_SECONDS:
                                await _handle_natural_language(page, latest, state["chatType"])
                                last_processed_sig[chat_key] = sig
                                last_reply_time[chat_key] = time.time()

                await asyncio.sleep(5) # Poll mỗi 5s
            except Exception as e:
                _log_event("main.error", error=_serialize_error(e))
                await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
