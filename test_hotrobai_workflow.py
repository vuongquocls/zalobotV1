import unittest
from unittest.mock import AsyncMock, patch

import ai_helper
import zalo_bot


class HotroBaiWorkflowTests(unittest.TestCase):
    def test_detect_facebook_style(self):
        self.assertEqual(ai_helper.detect_facebook_style("viết vui vẻ về chim non"), "vui vẻ")
        self.assertEqual(ai_helper.detect_facebook_style("viết cảm xúc mạnh về rừng"), "cảm xúc mạnh")
        self.assertEqual(ai_helper.detect_facebook_style("viết nghiêm túc về bảo tồn"), "nghiêm túc")
        self.assertEqual(ai_helper.detect_facebook_style("viết theo hướng khoa học"), "khoa học")

    def test_missing_style_gets_clarifying_question(self):
        reply = ai_helper.build_facebook_style_question("Trên đường HDV cứu hộ chim non Quạ Thông")

        self.assertIn("Anh muốn em viết theo phong cách nào", reply)
        self.assertIn("vui vẻ, cảm xúc mạnh, nghiêm túc hay khoa học", reply)
        self.assertIn("Trên đường HDV cứu hộ chim non Quạ Thông", reply)

    def test_missing_style_resolves_to_yokdon_default(self):
        style = ai_helper.resolve_facebook_style(
            "Viết bài đăng facebook về nội dung Vườn quốc gia Yok Đôn đã thành lập nhóm truyền thông, hôm nay ra mắt"
        )

        self.assertIn("Yok Đôn", style)
        self.assertIn("3 phương án", style)

    def test_facebook_prompt_uses_yokdon_style_guide(self):
        prompt = ai_helper._build_facebook_options_prompt(
            "viết cảm xúc mạnh về chim non Quạ Thông",
            "cảm xúc mạnh",
            context="TOM TAT BANG CONG VIEC",
        )

        self.assertIn("BẢN GHI NHỚ YOK ĐÔN CONTENT", prompt)
        self.assertIn("Mộc mạc, tự nhiên, gần gũi", prompt)
        self.assertIn("Không ai báo tin, nhưng rừng biết.", prompt)
        self.assertIn("Tạo đúng 3 phương án", prompt)
        self.assertIn("không phải một câu trả lời chatbot chung chung", prompt)
        self.assertIn("Tránh văn mẫu sáo rỗng", prompt)
        self.assertIn("TOM TAT BANG CONG VIEC", prompt)

    def test_hotrobai_command_is_supported(self):
        self.assertEqual(
            zalo_bot._extract_command("/hotrobai cảm xúc mạnh - chim non Quạ Thông"),
            ("hotrobai", "cảm xúc mạnh - chim non Quạ Thông"),
        )

    def test_hotrobai_long_request_is_command_not_today_tasks(self):
        text = (
            "/hotrobai Viết bài đăng facebook về nội dung Vườn quốc gia Yok Đôn "
            "đã thành lập nhóm truyền thông, hôm nay ra mắt và triển khai nhiệm vụ "
            "Dự và chỉ đạo có ông Huỳnh Nghĩa Hiệp, PGĐ Vườn."
        )

        command = zalo_bot._extract_command(text)

        self.assertIsNotNone(command)
        self.assertEqual(command[0], "hotrobai")

    def test_hotrobai_without_style_calls_llm(self):
        async def run_case():
            sent_messages = []

            async def fake_send(_page, text):
                sent_messages.append(text)
                return True

            async def fake_draft(request_text, style, context=""):
                self.assertIn("hôm nay ra mắt", request_text)
                self.assertIn("Yok Đôn", style)
                return "Em xin phép gửi Anh/Chị 3 phương án để chọn."

            with (
                patch.object(zalo_bot, "_send_message", side_effect=fake_send),
                patch.object(zalo_bot, "_build_ai_context", return_value="TOM TAT SHEET"),
                patch.object(zalo_bot, "draft_facebook_post_options", side_effect=fake_draft),
            ):
                await zalo_bot._handle_command(
                    AsyncMock(),
                    "hotrobai",
                    (
                        "Viết bài đăng facebook về nội dung Vườn quốc gia Yok Đôn "
                        "đã thành lập nhóm truyền thông, hôm nay ra mắt"
                    ),
                    "Truyền thông Yok Đôn",
                )

            self.assertEqual(sent_messages, ["Em xin phép gửi Anh/Chị 3 phương án để chọn."])

        import asyncio

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
