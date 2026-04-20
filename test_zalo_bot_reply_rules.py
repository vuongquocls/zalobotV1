import unittest
from unittest.mock import patch

import zalo_bot


class ZaloBotReplyRuleTests(unittest.TestCase):
    def test_group_replies_when_alias_is_visible(self):
        self.assertTrue(zalo_bot._should_reply("group", "@Nhân Viên Mới Yok Đôn em có thể làm gì?"))

    def test_group_replies_to_direct_bot_question_when_zalo_strips_mention(self):
        self.assertTrue(zalo_bot._should_reply("group", "em có thể làm gì?"))
        self.assertTrue(zalo_bot._should_reply("group", "nhiệm vụ của em là gì?"))

    def test_group_replies_to_direct_sheet_questions_when_zalo_strips_mention(self):
        self.assertTrue(zalo_bot._should_reply("group", "Cho anh biết hôm nay có nhiệm vụ nào cần thực hiện không?"))
        self.assertTrue(zalo_bot._should_reply("group", "3 ngày tới có việc nào?"))

    def test_group_does_not_reply_to_general_chat(self):
        self.assertFalse(zalo_bot._should_reply("group", "hôm nay trời nóng quá"))

    def test_hotrobai_command_payload_removes_duplicate_prefix(self):
        command = zalo_bot._extract_command("/hotrobai /hotrobai viết bài về chim quạ thông")

        self.assertEqual(command, ("hotrobai", "viết bài về chim quạ thông"))

    def test_sidebar_preview_command_is_used_as_message_source(self):
        command_text = zalo_bot._extract_command_text_from_sidebar({
            "title": "Quốc",
            "preview": "/hotrobai Trên đường hướng dẫn viên cứu hộ chim non",
            "rawText": "Quốc\n/hotrobai Trên đường hướng dẫn viên cứu hộ chim non",
            "isMinePreview": False,
        })

        self.assertEqual(command_text, "/hotrobai Trên đường hướng dẫn viên cứu hộ chim non")

    def test_sidebar_preview_ignores_own_command_preview(self):
        command_text = zalo_bot._extract_command_text_from_sidebar({
            "title": "Quốc",
            "preview": "Bạn: /hotrobai viết bài",
            "rawText": "Quốc\nBạn: /hotrobai viết bài",
            "isMinePreview": True,
        })

        self.assertEqual(command_text, "")


class ZaloBotCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_hotrobai_command_calls_llm_draft_helper(self):
        calls = {}

        async def fake_draft(payload: str, context: str = "") -> str:
            calls["payload"] = payload
            calls["context"] = context
            return "Bản nháp Facebook từ LLM"

        async def fake_send(_page, text: str) -> bool:
            calls["sent"] = text
            return True

        with (
            patch.object(zalo_bot, "draft_content_from_request", fake_draft),
            patch.object(zalo_bot, "_build_ai_context", return_value="context sheet"),
            patch.object(zalo_bot, "_send_message", fake_send),
        ):
            await zalo_bot._handle_command(object(), "hotrobai", "viết bài về chim non", "Quốc")

        self.assertEqual(calls["payload"], "viết bài về chim non")
        self.assertEqual(calls["context"], "context sheet")
        self.assertEqual(calls["sent"], "Bản nháp Facebook từ LLM")


if __name__ == "__main__":
    unittest.main()
