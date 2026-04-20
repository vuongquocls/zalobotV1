"""
message_builder.py — Format tin nhắn nhắc việc cho Zalo

Tin nhắn text thuần (không markdown) vì Zalo Web không render markdown.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sheet_reader import get_sheet_public_url

if TYPE_CHECKING:
    from sheet_reader import Task


def _sheet_url() -> str:
    return get_sheet_public_url() or "(chua cau hinh link Sheet)"


def _format_date(dt: datetime | None, raw: str = "") -> str:
    if dt:
        return dt.strftime("%d/%m")
    return raw or "??"


def _task_line(task: "Task", show_status: bool = True) -> str:
    """Format 1 dòng task."""
    date_str = _format_date(task.due_date, task.due_date_raw)
    assignee = task.assignee or "(chưa giao)"
    parts = [f"  [{date_str}] {task.topic}"]
    parts.append(f"    → Phụ trách: {assignee}")
    if show_status and task.status:
        parts.append(f"    → Trạng thái: {task.status}")
    return "\n".join(parts)


def build_today_empty_message() -> str:
    """Tin nhắn khi hôm nay không có nội dung nào trong Sheet."""
    now_str = datetime.now().strftime("%d/%m/%Y")
    return (
        f"NHẮC VIỆC TRUYỀN THÔNG - {now_str}\n"
        f"{'=' * 36}\n\n"
        f"Hôm nay ({now_str}) chưa có nội dung nào trong Bảng kế hoạch!\n\n"
        "Anh/chị vui lòng cập nhật kế hoạch truyền thông vào Sheet giúp em nhé.\n\n"
        f"Link: {_sheet_url()}"
    )


def build_today_tasks_message(today_tasks: list["Task"]) -> str:
    """Format cau tra loi khi nguoi dung hoi rieng viec hom nay."""
    now_str = datetime.now().strftime("%d/%m/%Y")
    if not today_tasks:
        return (
            f"HÔM NAY, ngày {now_str}, không có việc nào trong Google Sheet.\n"
            f"* Link theo dõi: {_sheet_url()}"
        )

    lines = [
        f"HÔM NAY, ngày {now_str}, có {len(today_tasks)} việc:",
    ]
    sorted_tasks = sorted(today_tasks, key=lambda task: task.row_number)

    for index, task in enumerate(sorted_tasks, start=1):
        if len(sorted_tasks) > 1:
            lines.append("")
            lines.append(f"Việc {index}:")

        lines.append(f"* Chủ đề/Tiêu đề bài viết: {task.topic}")
        lines.append(f"* Đơn vị/Cá nhân thực hiện: {task.assignee or '(chưa giao)'}")
        lines.append(f"* Trạng thái: {task.status or '(chưa cập nhật)'}")
        lines.append("* Lưu ý: ")
        lines.append(f"* Link theo dõi: {_sheet_url()}")

    return "\n".join(lines)


def build_upcoming_tasks_message(upcoming_tasks: list["Task"], days_ahead: int = 3) -> str:
    """Format cau tra loi khi nguoi dung hoi viec sap toi."""
    now = datetime.now()
    start_str = now.strftime("%d/%m/%Y")
    end_str = datetime.fromordinal(now.date().toordinal() + days_ahead).strftime("%d/%m/%Y")
    if not upcoming_tasks:
        return (
            f"TRONG {days_ahead} NGÀY TỚI, từ ngày {start_str} đến {end_str}, không có việc nào trong Google Sheet.\n"
            f"* Link theo dõi: {_sheet_url()}"
        )

    lines = [
        f"TRONG {days_ahead} NGÀY TỚI, từ ngày {start_str} đến {end_str}, có {len(upcoming_tasks)} việc:",
    ]
    sorted_tasks = sorted(upcoming_tasks, key=lambda task: (task.due_date or datetime.max, task.row_number))

    for index, task in enumerate(sorted_tasks, start=1):
        if len(sorted_tasks) > 1:
            lines.append("")
            lines.append(f"Việc {index}:")

        lines.append(f"* Ngày đăng dự kiến: {task.due_date_raw or '(chưa rõ ngày)'}")
        lines.append(f"* Chủ đề/Tiêu đề bài viết: {task.topic}")
        lines.append(f"* Đơn vị/Cá nhân thực hiện: {task.assignee or '(chưa giao)'}")
        lines.append(f"* Trạng thái: {task.status or '(chưa cập nhật)'}")
        lines.append("* Lưu ý: ")
        lines.append(f"* Link theo dõi: {_sheet_url()}")

    return "\n".join(lines)


def build_daily_reminder(
    today_tasks: list["Task"],
    overdue_tasks: list["Task"],
    upcoming_tasks: list["Task"],
    unassigned_tasks: list["Task"],
    today_is_empty: bool = False,
) -> str | None:
    """Xây dựng tin nhắn nhắc việc hàng ngày. Trả None nếu không có gì cần nhắc."""

    sections: list[str] = []
    now_str = datetime.now().strftime("%d/%m/%Y")

    # Header
    sections.append(f"NHẮC VIỆC TRUYỀN THÔNG - {now_str}")
    sections.append("=" * 36)

    has_content = False

    # Hôm nay trống — nhắc mọi người điền Sheet
    if today_is_empty:
        has_content = True
        sections.append("")
        sections.append(f"Hôm nay ({now_str}) CHƯA CÓ nội dung nào trong Sheet!")
        sections.append("Anh/chị vui lòng cập nhật kế hoạch vào Bảng giúp em.")

    # Quá hạn
    if overdue_tasks:
        has_content = True
        sections.append("")
        sections.append(f"QUÁ HẠN ({len(overdue_tasks)} việc):")
        for t in overdue_tasks:
            sections.append(_task_line(t))

    # Hôm nay
    if today_tasks:
        has_content = True
        sections.append("")
        sections.append(f"HÔM NAY ({len(today_tasks)} việc):")
        for t in today_tasks:
            sections.append(_task_line(t))

    # Sắp đến hạn
    if upcoming_tasks:
        has_content = True
        sections.append("")
        sections.append(f"SẮP ĐẾN HẠN ({len(upcoming_tasks)} việc):")
        for t in upcoming_tasks:
            sections.append(_task_line(t))

    # Chưa giao
    if unassigned_tasks:
        has_content = True
        sections.append("")
        sections.append(f"CHƯA GIAO ({len(unassigned_tasks)} việc):")
        for t in unassigned_tasks:
            sections.append(_task_line(t, show_status=False))
        sections.append("")
        sections.append("Anh/chị điền tên người phụ trách vào Sheet giúp em nhé!")

    if not has_content:
        return None

    # Ghi chú Google Sheet
    sections.append("")
    sections.append(f"Xem chi tiết: {_sheet_url()}")

    return "\n".join(sections)


def build_no_work_message() -> str:
    """Tin nhắn khi Sheet trống hoặc không có task nào cần nhắc."""
    now_str = datetime.now().strftime("%d/%m/%Y")
    return (
        f"NHẮC VIỆC TRUYỀN THÔNG - {now_str}\n"
        f"{'=' * 36}\n\n"
        "Hiện tại chưa có công việc nào cần nhắc.\n"
        "Mọi người nhớ cập nhật tiến độ vào Sheet nhé!\n\n"
        f"Xem Sheet: {_sheet_url()}"
    )


def build_sheet_empty_message() -> str:
    """Tin nhắn khi Sheet chưa có dữ liệu cho kỳ này."""
    now_str = datetime.now().strftime("%d/%m/%Y")
    return (
        f"NHẮC VIỆC TRUYỀN THÔNG - {now_str}\n"
        f"{'=' * 36}\n\n"
        "Sheet chưa có nội dung cho kỳ này.\n"
        "Anh/chị vui lòng điền kế hoạch truyền thông vào Sheet!\n\n"
        f"Link: {_sheet_url()}"
    )


def build_task_detail(task: "Task") -> str:
    """Format chi tiết 1 task để gửi khi hỏi cụ thể."""
    lines = [
        f"CHI TIẾT CÔNG VIỆC (dòng {task.row_number})",
        "-" * 30,
        f"Chủ đề: {task.topic}",
        f"Nhóm nội dung: {task.content_group}",
        f"Ngày đăng dự kiến: {task.due_date_raw}",
        f"Kênh: {task.channel}",
        f"Định dạng: {task.format_type}",
        f"Phụ trách: {task.assignee or '(chưa giao)'}",
        f"Trạng thái: {task.status or '(chưa cập nhật)'}",
    ]
    if task.link:
        lines.append(f"Link: {task.link}")
    return "\n".join(lines)


def build_pending_tasks_message(tasks: list["Task"]) -> str:
    """Danh sach cac viec chua xong de tra loi lenh /xemviec."""
    now_str = datetime.now().strftime("%d/%m/%Y")
    sections = [
        f"DANH SACH VIEC CHUA XONG - {now_str}",
        "=" * 36,
    ]

    pending_tasks = [task for task in tasks if not task.is_completed]
    if not pending_tasks:
        sections.append("")
        sections.append("Khong co viec nao dang mo.")
        sections.append(f"Xem Sheet: {_sheet_url()}")
        return "\n".join(sections)

    pending_tasks.sort(key=lambda task: task.due_date or datetime.max)
    for task in pending_tasks[:20]:
        sections.append("")
        sections.append(_task_line(task))

    if len(pending_tasks) > 20:
        sections.append("")
        sections.append(f"Con {len(pending_tasks) - 20} viec khac trong Sheet.")

    sections.append("")
    sections.append(f"Xem Sheet: {_sheet_url()}")
    return "\n".join(sections)
