import unittest

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
        self.assertIn("TOM TAT BANG CONG VIEC", prompt)

    def test_hotrobai_command_is_supported(self):
        self.assertEqual(
            zalo_bot._extract_command("/hotrobai cảm xúc mạnh - chim non Quạ Thông"),
            ("hotrobai", "cảm xúc mạnh - chim non Quạ Thông"),
        )


if __name__ == "__main__":
    unittest.main()

