import unittest
from datetime import datetime, timedelta

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
            notes="Khởi động tuyến Storytelling mùa khô",
            link="https://yokdon.example/bua-com-voi-giua-rung",
            row_number=7,
        )

        reply = message_builder.build_today_tasks_message([task])

        self.assertIn(f"HÔM NAY, ngày {datetime.now().strftime('%d/%m/%Y')}, có 1 việc:", reply)
        self.assertIn("* Chủ đề/Tiêu đề bài viết: Câu chuyện Kiểm lâm: Bữa cơm vội giữa rừng mùa khô hanh", reply)
        self.assertIn("* Đơn vị/Cá nhân thực hiện: Hạt KL (A. Hòa, A. Nguyên)", reply)
        self.assertIn("* Trạng thái: Đang thu thập tư liệu", reply)
        self.assertIn("* Link bài viết: https://yokdon.example/bua-com-voi-giua-rung", reply)
        self.assertNotIn("* Lưu ý:", reply)
        self.assertNotIn("Khởi động tuyến Storytelling mùa khô", reply)
        self.assertIn(f"* Link theo dõi: {get_sheet_public_url()}", reply)

    def test_upcoming_tasks_message_uses_sheet_data(self):
        due = datetime.now() + timedelta(days=1)
        task = Task(
            month="4",
            due_date=due,
            due_date_raw=due.strftime("%d/%m/%Y"),
            content_group="Câu chuyện bảo tồn",
            topic="Theo dấu voi rừng Yok Đôn",
            channel="Fanpage",
            format_type="Bài viết",
            assignee="TT GDMT&DV",
            status="Đang chuẩn bị",
            notes="",
            link="https://yokdon.example/voi-rung",
            row_number=8,
        )

        reply = message_builder.build_upcoming_tasks_message([task], days_ahead=3)

        self.assertIn("TRONG 3 NGÀY TỚI", reply)
        self.assertIn(f"* Ngày đăng dự kiến: {due.strftime('%d/%m/%Y')}", reply)
        self.assertIn("* Chủ đề/Tiêu đề bài viết: Theo dấu voi rừng Yok Đôn", reply)
        self.assertIn("* Đơn vị/Cá nhân thực hiện: TT GDMT&DV", reply)
        self.assertIn("* Trạng thái: Đang chuẩn bị", reply)
        self.assertIn("* Link bài viết: https://yokdon.example/voi-rung", reply)
        self.assertNotIn("* Lưu ý:", reply)

    def test_pending_tasks_message_uses_required_field_format(self):
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
            notes="Không đưa ghi chú vào tin nhắn",
            link="",
            row_number=7,
        )

        reply = message_builder.build_pending_tasks_message([task])

        self.assertIn("DANH SÁCH VIỆC CHƯA XONG", reply)
        self.assertIn("* Ngày đăng dự kiến:", reply)
        self.assertIn("* Chủ đề/Tiêu đề bài viết: Câu chuyện Kiểm lâm: Bữa cơm vội giữa rừng mùa khô hanh", reply)
        self.assertIn("* Đơn vị/Cá nhân thực hiện: Hạt KL (A. Hòa, A. Nguyên)", reply)
        self.assertIn("* Trạng thái: Đang thu thập tư liệu", reply)
        self.assertIn("* Link bài viết:", reply)
        self.assertNotIn("* Lưu ý:", reply)
        self.assertNotIn("Không đưa ghi chú vào tin nhắn", reply)
        self.assertIn(f"* Link theo dõi: {get_sheet_public_url()}", reply)


if __name__ == "__main__":
    unittest.main()
