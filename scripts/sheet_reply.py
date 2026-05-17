"""Build Zalo replies from the Google Sheet using the existing bot logic."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from message_builder import (
    build_pending_tasks_message,
    build_today_tasks_message,
    build_upcoming_tasks_message,
)
from sheet_reader import (
    fetch_all_tasks,
    get_overdue_tasks,
    get_today_tasks,
    get_upcoming_tasks,
    get_unassigned_tasks,
)
from time_utils import local_now


def _task_list_message(title: str, tasks) -> str:
    now_str = local_now().strftime("%d/%m/%Y")
    if not tasks:
        return f"{title} - {now_str}: không có việc nào trong Google Sheet."

    lines = [f"{title} - {now_str}, có {len(tasks)} việc:"]
    for index, task in enumerate(tasks, start=1):
        lines.extend(
            [
                "",
                f"Việc {index}:",
                f"* Ngày đăng dự kiến: {task.due_date_raw or '(chưa rõ ngày)'}",
                f"* Chủ đề/Tiêu đề bài viết: {task.topic}",
                f"* Đơn vị/Cá nhân thực hiện: {task.assignee or '(chưa giao)'}",
                f"* Trạng thái: {task.status or '(chưa cập nhật)'}",
            ]
        )
    return "\n".join(lines)


def build_reply(intent: str) -> str:
    tasks = fetch_all_tasks()
    if intent == "today":
        return build_today_tasks_message(get_today_tasks(tasks))
    if intent == "upcoming":
        return build_upcoming_tasks_message(get_upcoming_tasks(tasks=tasks), days_ahead=3)
    if intent == "overdue":
        return _task_list_message("VIỆC QUÁ HẠN", get_overdue_tasks(tasks))
    if intent == "unassigned":
        return _task_list_message("VIỆC CHƯA GIAO NGƯỜI PHỤ TRÁCH", get_unassigned_tasks(tasks))
    if intent == "pending":
        return build_pending_tasks_message(tasks)
    raise ValueError(f"Unsupported intent: {intent}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Google Sheet based Zalo reply")
    parser.add_argument(
        "--intent",
        choices=("today", "upcoming", "overdue", "unassigned", "pending"),
        required=True,
    )
    args = parser.parse_args()
    print(build_reply(args.intent))


if __name__ == "__main__":
    main()
