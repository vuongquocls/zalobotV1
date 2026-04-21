import unittest

import zalo_bot


class ZaloBotReplyRuleTests(unittest.TestCase):
    def test_group_replies_when_alias_is_visible(self):
        self.assertTrue(zalo_bot._should_reply("group", "@Nhân Viên Mới Yok Đôn em có thể làm gì?"))

    def test_lapkehoach_command_is_supported(self):
        self.assertEqual(zalo_bot._extract_command("/lapkehoach"), ("lapkehoach", ""))
        self.assertTrue(zalo_bot._should_reply("group", "/lapkehoach"))

    def test_lapkehoach_message_uses_sheet_link(self):
        reply = zalo_bot._build_plan_request_message()

        self.assertIn("Các anh ơi, hãy lên kế hoạch các bài viết tiếp theo vào link:", reply)
        self.assertIn("https://docs.google.com/spreadsheets/d/1tdgynCsD8b3JjptyAvXNbZtnF5Ng6ChaFxQO4uHDYK8", reply)
        self.assertIn("giúp em đi. Chỉ một chút thôi mà.", reply)

    def test_group_replies_to_direct_bot_question_when_zalo_strips_mention(self):
        self.assertTrue(zalo_bot._should_reply("group", "em có thể làm gì?"))
        self.assertTrue(zalo_bot._should_reply("group", "nhiệm vụ của em là gì?"))

    def test_group_replies_to_direct_sheet_questions_when_zalo_strips_mention(self):
        self.assertTrue(zalo_bot._should_reply("group", "Cho anh biết hôm nay có nhiệm vụ nào cần thực hiện không?"))
        self.assertTrue(zalo_bot._should_reply("group", "3 ngày tới có việc nào?"))

    def test_group_does_not_reply_to_general_chat(self):
        self.assertFalse(zalo_bot._should_reply("group", "hôm nay trời nóng quá"))


if __name__ == "__main__":
    unittest.main()
