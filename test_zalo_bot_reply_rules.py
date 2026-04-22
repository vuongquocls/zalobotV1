import unittest
from unittest.mock import AsyncMock, patch

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

    def test_personal_group_greeting_request_is_detected(self):
        message = zalo_bot._extract_group_relay_message("Em hãy vào chào anh Ba 1 tiếng nhé")

        self.assertEqual(
            message,
            (
                "Em chào anh Ba, chào mừng anh Ba đến với nhóm Truyền thông "
                "của Vườn quốc gia Yok Đôn, anh có cần em hỗ trợ gì không ạ?"
            ),
        )

    def test_plain_greeting_does_not_trigger_group_relay(self):
        self.assertEqual(zalo_bot._extract_group_relay_message("Chào anh nhé"), "")

    def test_freeform_group_relay_request_is_detected(self):
        message = zalo_bot._extract_group_relay_message("Em nhắn vào nhóm rằng Chiều nay họp lúc 15h nhé")

        self.assertEqual(message, "Chiều nay họp lúc 15h nhé")

    def test_personal_group_relay_opens_group_and_returns_to_personal_chat(self):
        async def run_case():
            sent_messages = []
            opened_chats = []

            async def fake_send(_page, text):
                sent_messages.append(text)
                return True

            async def fake_open(_page, chat_name):
                opened_chats.append(chat_name)
                return True

            page = AsyncMock()
            page.wait_for_timeout = AsyncMock()
            with (
                patch.object(zalo_bot, "_send_message", side_effect=fake_send),
                patch.object(zalo_bot, "_open_chat_by_name", side_effect=fake_open),
            ):
                handled = await zalo_bot._handle_personal_group_relay(
                    page,
                    "Quốc",
                    "Em hãy vào chào anh Ba 1 tiếng nhé",
                )

            self.assertTrue(handled)
            self.assertEqual(sent_messages[0], "Dạ, em sẽ làm ngay.")
            self.assertIn("Em chào anh Ba", sent_messages[1])
            self.assertEqual(opened_chats, [zalo_bot.ZALO_GROUP_NAME, "Quốc"])

        import asyncio

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
