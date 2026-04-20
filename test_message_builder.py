import unittest
from datetime import datetime

import message_builder
from sheet_reader import Task, get_sheet_public_url


class MessageBuilderTests(unittest.TestCase):
    def test_today_tasks_message_uses_required_format(self):
        task = Task(
            month="4",
            due_date=datetime.now(),
            due_date_raw=datetime.now().strftime("%d/%m/%Y"),
            content_group="Câu chuyện Kiểm lâm",
            topic="Câu chuyện Kiểm lâm: Bữa cơm vội giữa rừng mùa khô hanh",
            channel="Fanpage",
            format_type="Bài viết",
            assignee="Hạt KL (A. Hòa, A. Nguyên)",
            status="Đang thu thập tư liệu",
            link="",
            row_number=7,
        )

        reply = message_builder.build_today_tasks_message([task])

        self.assertIn(f"HÔM NAY, ngày {datetime.now().strftime('%d/%m/%Y')}, có 1 việc:", reply)
        self.assertIn("* Chủ đề/Tiêu đề bài viết: Câu chuyện Kiểm lâm: Bữa cơm vội giữa rừng mùa khô hanh", reply)
        self.assertIn("* Đơn vị/Cá nhân thực hiện: Hạt KL (A. Hòa, A. Nguyên)", reply)
        self.assertIn("* Trạng thái: Đang thu thập tư liệu", reply)
        self.assertIn("* Lưu ý: ", reply)
        self.assertIn(f"* Link theo dõi: {get_sheet_public_url()}", reply)


if __name__ == "__main__":
    unittest.main()
