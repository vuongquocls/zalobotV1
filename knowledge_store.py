"""
knowledge_store.py - Luu cac ghi nho do nguoi dung day cho bot.

Muc tieu:
- Don gian, de sao luu, de doc khi can kiem tra.
- Khong phu thuoc database.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MEMORY_FILE = BASE_DIR / "bot_memory.json"


def _read_store() -> dict:
    if not MEMORY_FILE.exists():
        return {"notes": []}

    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"notes": []}


def _write_store(data: dict) -> None:
    MEMORY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_learning(note: str, author: str = "", chat_name: str = "") -> dict:
    clean_note = note.strip()
    if not clean_note:
        raise ValueError("Ghi nho khong duoc de trong.")

    store = _read_store()
    entry = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "author": author.strip(),
        "chat_name": chat_name.strip(),
        "note": clean_note,
    }
    store.setdefault("notes", []).append(entry)
    _write_store(store)
    return entry


def list_learning(limit: int = 10) -> list[dict]:
    notes = _read_store().get("notes", [])
    return notes[-limit:]


def get_learning_context(limit: int = 10) -> str:
    notes = list_learning(limit=limit)
    if not notes:
        return ""

    lines = ["GHI NHO NGUOI DUNG DA DAY BOT:"]
    for item in notes:
        prefix = item.get("created_at", "")
        author = item.get("author", "").strip()
        chat_name = item.get("chat_name", "").strip()

        meta_parts = [part for part in (prefix, author, chat_name) if part]
        meta = " | ".join(meta_parts)
        if meta:
            lines.append(f"- ({meta}) {item.get('note', '')}")
        else:
            lines.append(f"- {item.get('note', '')}")

    return "\n".join(lines)
