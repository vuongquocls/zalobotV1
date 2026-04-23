import unittest
from datetime import date, datetime
from unittest.mock import patch

from sheet_reader import Task, get_overdue_tasks, get_upcoming_tasks


def make_task(status: str, due_date: datetime, link: str = "") -> Task:
    return Task(
        month="4",
        due_date=due_date,
        due_date_raw=due_date.strftime("%d/%m/%Y"),
        content_group="Truyen thong",
        topic=f"Bai viet {status or 'chua cap nhat'}",
        channel="Fanpage",
        format_type="Bai viet",
        assignee="Phong TCHC",
        status=status,
        notes="",
        link=link,
        row_number=2,
    )


class SheetReaderStatusTests(unittest.TestCase):
    def test_da_thuc_hien_is_completed_and_not_overdue(self):
        task = make_task("Đã thực hiện", datetime(2026, 4, 20))

        with patch("sheet_reader.local_today", return_value=date(2026, 4, 23)):
            self.assertTrue(task.is_completed)
            self.assertEqual(get_overdue_tasks([task]), [])

    def test_completed_article_link_marks_task_completed(self):
        task = make_task("", datetime(2026, 4, 20), link="https://facebook.com/yokdon/posts/1")

        with patch("sheet_reader.local_today", return_value=date(2026, 4, 23)):
            self.assertTrue(task.is_completed)
            self.assertEqual(get_overdue_tasks([task]), [])

    def test_da_len_lich_without_article_link_is_not_completed(self):
        task = make_task("Đã lên lịch", datetime(2026, 4, 20))

        with patch("sheet_reader.local_today", return_value=date(2026, 4, 23)):
            self.assertFalse(task.is_completed)
            self.assertEqual(get_overdue_tasks([task]), [task])

    def test_completed_future_task_is_not_in_upcoming(self):
        task = make_task("Đã thực hiện", datetime(2026, 4, 24))

        with patch("sheet_reader.local_today", return_value=date(2026, 4, 23)):
            self.assertEqual(get_upcoming_tasks(3, [task]), [])


if __name__ == "__main__":
    unittest.main()
