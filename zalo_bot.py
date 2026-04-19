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
    """Gửi tin nhắn — dùng cơ chế Paste 'như người thật' để qua mặt Zalo."""
    _log_event("reply.start", length=len(text))
    try:
        # Bước 1: Ép focus vào vùng composer (tọa độ chuẩn 1280x800)
        # Click vào khoảng giữa-dưới để đảm bảo ô nhập liệu nhận focus
        await page.mouse.click(640, 750) 
        await asyncio.sleep(0.5)
        
        # Bước 2: Xóa sạch composer cũ (phòng hờ tin nhắn cũ chưa gửi)
        await page.keyboard.press("Control+a")
        await page.keyboard.press("Delete")
        await asyncio.sleep(0.3)
        
        # Bước 3: Copy text vào clipboard ảo
        await page.evaluate("""
            (t) => {
                const ta = document.createElement('textarea');
                ta.value = t;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
        """, text)
        await asyncio.sleep(0.2)
        
        # Bước 4: Paste (Ctrl+V) — Thao tác này LUÔN trigger React State của Zalo
        await page.keyboard.press("Control+v")
        await asyncio.sleep(0.8)
        
        # Bước 5: Nhấn Enter để gửi
        await page.keyboard.press("Enter")
        
        # Bước 6: Click nút Gửi (biểu tượng máy bay) dự phòng (tọa độ 1240, 750)
        await page.mouse.click(1240, 750)
        
        _log_event("reply.sent", method="paste_mode")
        return True
    except Exception as e:
        _log_event("reply.failed", error=str(e))
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

async def _scan_for_red_badges(page):
    """'Con mắt chi phối': Quét sidebar tìm bất kỳ điểm ĐỎ nào (unread badges)."""
    return await page.evaluate("""
        () => {
            const results = [];
            // Sidebar chat thường nằm ở X: 70..350
            const els = document.querySelectorAll('div, span');
            for (const el of els) {
                const r = el.getBoundingClientRect();
                // Chỉ quét vùng sidebar
                if (r.left > 60 && r.left < 360 && r.top > 120 && r.top < 800) {
                    const style = window.getComputedStyle(el);
                    const bg = style.backgroundColor;
                    // Nhận diện 'Màu Đỏ' của Zalo (thường là rgb(255, 66, 78) hoặc tương tự)
                    // Logic: Red cao, Green/Blue thấp
                    const match = bg.match(/rgb\\((\\d+),\\s*(\\d+),\\s*(\\d+)\\)/);
                    if (match) {
                        const r_val = parseInt(match[1]);
                        const g_val = parseInt(match[2]);
                        const b_val = parseInt(match[3]);
                        if (r_val > 200 && g_val < 100 && b_val < 100) {
                            // Đây là unread badge! Lấy tọa độ tâm của ITEM chứa badge này
                            // Thường badge nhỏ, item to. Ta lấy cha của badge.
                            let parent = el.parentElement;
                            while (parent && parent.getBoundingClientRect().height < 40) {
                                parent = parent.parentElement;
                            }
                            if (parent) {
                                const pRect = parent.getBoundingClientRect();
                                results.push({
                                    x: pRect.left + pRect.width / 2,
                                    y: pRect.top + pRect.height / 2,
                                    text: el.innerText
                                });
                            }
                        }
                    }
                }
            }
            // Loại bỏ trùng lặp (nhiều element đỏ trong cùng 1 item)
            const unique = [];
            const seenY = new Set();
            for (const res of results) {
                const roundedY = Math.round(res.y / 10) * 10;
                if (!seenY.has(roundedY)) {
                    unique.push(res);
                    seenY.add(roundedY);
                }
            }
            return unique;
        }
    """)

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
    _log_event("bot.starting", version="Heuristic-Eye-Edition")
    async with async_playwright() as p:
        browser = await p.firefox.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=HEADLESS,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
        )
        page = browser.pages[0]
        await page.goto(ZALO_URL)
        await asyncio.sleep(5)
        
        last_processed_sig = {}

        while True:
            try:
                # 1. Quét tìm chấm đỏ unread
                badges = await _scan_for_red_badges(page)
                
                # Nếu không thấy badge nào, check chat ĐANG MỞ
                targets = badges if badges else [{"x": 640, "y": 400, "is_active": True}]
                
                for badge in targets:
                    if "is_active" not in badge:
                        # Click vào chat có chấm đỏ
                        await page.mouse.click(badge["x"], badge["y"])
                        await asyncio.sleep(1.5)
                    
                    state = await _capture_chat_state(page)
                    incoming = state.get("incomingMessages", [])
                    chat_name = state.get("chatName", "Unknown")
                    
                    if incoming:
                        latest = incoming[-1]
                        sig = f"{chat_name}:{latest}"
                        
                        if sig != last_processed_sig.get(chat_name):
                            _log_event("msg.new", chat=chat_name, text=latest)
                            await _handle_natural_language(page, latest, state.get("chatType", "personal"))
                            last_processed_sig[chat_name] = sig

                await asyncio.sleep(2)  # Check mỗi 2s để đảm bảo nhạy bén như mắt người
            except Exception as e:
                _log_event("main.loop.error", error=str(e))
                await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
