"""
sheet_reader.py — Đọc Google Sheet "Bảng theo dõi tiến độ Truyền thông VQG Yok Đôn 2026"

Dùng cách tải CSV trực tiếp từ Google Sheet (không cần Service Account).
Sheet phải được share "Anyone with the link" hoặc "public".

Cấu trúc sheet (Sheet 1):
  A: Thời gian (Tháng)
  B: Ngày đăng dự kiến (dd/mm/yyyy)
  C: Nhóm nội dung
  D: Chủ đề/Tiêu đề bài viết
  E: Kênh đăng tải
  F: Định dạng bài viết
  G: Đơn vị/Cá nhân thực hiện
  H: Trạng thái
  I: Link bài viết/Tài liệu thô
"""

from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

GOOGLE_SHEET_SOURCE_URL = os.getenv("GOOGLE_SHEET_SOURCE_URL", "").strip()


def _extract_sheet_url(raw_url: str) -> str:
    """Lay URL Google Sheet that su tu docs.google.com, ke ca khi link dau vao la redirect.zalo.me."""
    if not raw_url:
        return ""

    parsed = urlparse(raw_url)
    if "docs.google.com" in parsed.netloc:
        return raw_url

    if "redirect.zalo.me" in parsed.netloc:
        query = parse_qs(parsed.query)
        continue_values = query.get("continue", [])
        if continue_values:
            return unquote(continue_values[0]).strip()

    return raw_url


def _extract_sheet_id(sheet_url: str) -> str:
    match = sheet_url.split("/d/")
    if len(match) < 2:
        return ""
    return match[1].split("/", 1)[0].strip()


def _extract_gid(sheet_url: str) -> str:
    parsed = urlparse(sheet_url)
    query = parse_qs(parsed.query)
    gid_values = query.get("gid", [])
    if gid_values and gid_values[0].strip():
        return gid_values[0].strip()

    if parsed.fragment.startswith("gid="):
        return parsed.fragment.replace("gid=", "", 1).strip()

    return ""


SHEET_PUBLIC_URL = _extract_sheet_url(GOOGLE_SHEET_SOURCE_URL)
SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip() or _extract_sheet_id(SHEET_PUBLIC_URL)
SHEET_GID = os.getenv("GOOGLE_SHEET_GID", "").strip() or _extract_gid(SHEET_PUBLIC_URL) or "0"

# Mapping cột (0-indexed)
COL_MONTH = 0
COL_DATE = 1
COL_GROUP = 2
COL_TOPIC = 3
COL_CHANNEL = 4
COL_FORMAT = 5
COL_ASSIGNEE = 6
COL_STATUS = 7
COL_NOTES = 8
COL_LINK = 9


@dataclass
class Task:
    month: str
    due_date: Optional[datetime]
    due_date_raw: str
    content_group: str
    topic: str
    channel: str
    format_type: str
    assignee: str
    status: str
    notes: str
    link: str
    row_number: int

    @property
    def is_completed(self) -> bool:
        s = self.status.lower().strip()
        return any(k in s for k in ("hoàn thành", "hoan thanh", "xong", "done"))

    @property
    def is_not_started(self) -> bool:
        s = self.status.lower().strip()
        return any(k in s for k in ("chưa bắt đầu", "chua bat dau")) or not s

    @property
    def has_assignee(self) -> bool:
        return bool(self.assignee.strip())


def _parse_date(raw: str) -> Optional[datetime]:
    """Parse date dd/mm/yyyy hoặc d/m/yyyy."""
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _fetch_csv() -> list[list[str]]:
    """Tải Google Sheet dưới dạng CSV (không cần auth, sheet phải public/shared)."""
    if not SHEET_ID:
        raise ValueError(
            "Chua xac dinh duoc GOOGLE_SHEET_ID. "
            "Hay khai bao GOOGLE_SHEET_ID hoac GOOGLE_SHEET_SOURCE_URL."
        )
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={SHEET_GID}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    text = resp.content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    return list(reader)


def get_sheet_public_url() -> str:
    """Tra ve link Sheet de gui cho nguoi dung."""
    if SHEET_PUBLIC_URL:
        return SHEET_PUBLIC_URL
    if SHEET_ID:
        return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?gid={SHEET_GID}#gid={SHEET_GID}"
    return ""


def _rows_to_tasks(rows: list[list[str]]) -> list[Task]:
    """Chuyển danh sách row thành danh sách Task, bỏ header."""
    tasks = []
    for i, row in enumerate(rows):
        if i == 0:
            continue  # skip header
        # Pad row để đủ 10 cột (thêm cột Lưu ý)
        padded = row + [""] * (10 - len(row))
        due_raw = padded[COL_DATE].strip()
        tasks.append(Task(
            month=padded[COL_MONTH].strip(),
            due_date=_parse_date(due_raw),
            due_date_raw=due_raw,
            content_group=padded[COL_GROUP].strip(),
            topic=padded[COL_TOPIC].strip(),
            channel=padded[COL_CHANNEL].strip(),
            format_type=padded[COL_FORMAT].strip(),
            assignee=padded[COL_ASSIGNEE].strip(),
            status=padded[COL_STATUS].strip(),
            notes=padded[COL_NOTES].strip(),
            link=padded[COL_LINK].strip(),
            row_number=i + 1,  # 1-based row number in the sheet
        ))
    return [t for t in tasks if t.topic]  # bỏ dòng trống


def fetch_all_tasks() -> list[Task]:
    """Lấy toàn bộ task từ Google Sheet."""
    rows = _fetch_csv()
    return _rows_to_tasks(rows)


def get_today_tasks(tasks: list[Task] | None = None) -> list[Task]:
    """Lấy các task có ngày đăng dự kiến là hôm nay."""
    if tasks is None:
        tasks = fetch_all_tasks()
    today = datetime.now().date()
    return [t for t in tasks if t.due_date and t.due_date.date() == today]


def get_upcoming_tasks(days_ahead: int = 3, tasks: list[Task] | None = None) -> list[Task]:
    """Lấy các task trong N ngày tới (không tính quá hạn, không tính đã xong)."""
    if tasks is None:
        tasks = fetch_all_tasks()
    today = datetime.now().date()
    deadline = today + timedelta(days=days_ahead)
    results = []
    for t in tasks:
        if t.is_completed:
            continue
        if t.due_date and today < t.due_date.date() <= deadline:
            results.append(t)
    return results


def get_overdue_tasks(tasks: list[Task] | None = None) -> list[Task]:
    """Lấy các task quá hạn chưa hoàn thành."""
    if tasks is None:
        tasks = fetch_all_tasks()
    today = datetime.now().date()
    return [
        t for t in tasks
        if t.due_date and t.due_date.date() < today and not t.is_completed
    ]


def get_unassigned_tasks(tasks: list[Task] | None = None) -> list[Task]:
    """Lấy các task chưa có ai được giao."""
    if tasks is None:
        tasks = fetch_all_tasks()
    return [t for t in tasks if not t.has_assignee and not t.is_completed]


def is_today_empty(tasks: list[Task] | None = None) -> bool:
    """Kiểm tra hôm nay có task nào trong Sheet không.
    
    True = hôm nay KHÔNG có task nào ở Sheet (cần nhắc mọi người điền).
    """
    if tasks is None:
        tasks = fetch_all_tasks()
    today = datetime.now().date()
    for t in tasks:
        if t.due_date and t.due_date.date() == today:
            return False
    return True


# === CLI test ===
if __name__ == "__main__":
    print("📊 Đang đọc Google Sheet (CSV export)...")
    try:
        all_tasks = fetch_all_tasks()
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        raise

    print(f"✅ Tổng cộng {len(all_tasks)} task.\n")

    today = get_today_tasks(all_tasks)
    print(f"📅 Hôm nay ({datetime.now().strftime('%d/%m/%Y')}): {len(today)} task")
    for t in today:
        print(f"   - [{t.status}] {t.topic} → {t.assignee or '(chưa giao)'}")

    if is_today_empty(all_tasks):
        print("   ⚠️ Hôm nay chưa có nội dung nào trên Sheet!")

    upcoming = get_upcoming_tasks(tasks=all_tasks)
    print(f"\n⏰ Sắp đến hạn (3 ngày): {len(upcoming)} task")
    for t in upcoming:
        print(f"   - [{t.due_date_raw}] {t.topic} → {t.assignee or '(chưa giao)'}")

    overdue = get_overdue_tasks(all_tasks)
    print(f"\n🚨 Quá hạn: {len(overdue)} task")
    for t in overdue:
        print(f"   - [{t.due_date_raw}] {t.topic} → {t.assignee or '(chưa giao)'}")

    unassigned = get_unassigned_tasks(all_tasks)
    print(f"\n❓ Chưa giao: {len(unassigned)} task")
    for t in unassigned:
        print(f"   - [{t.due_date_raw}] {t.topic}")
