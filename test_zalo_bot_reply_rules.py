import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

import zalo_bot
from time_utils import LOCAL_TZ


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

    def test_group_conversation_window_replies_to_followup(self):
        self.assertTrue(
            zalo_bot._should_reply(
                "group",
                "mày chào các anh và tự giới thiệu đi",
                group_conversation_active=True,
            )
        )

    def test_group_conversation_window_still_ignores_general_chat(self):
        self.assertFalse(
            zalo_bot._should_reply(
                "group",
                "ôi đm, mày điên à",
                group_conversation_active=True,
            )
        )

    def test_group_followup_without_active_window_is_ignored(self):
        self.assertFalse(zalo_bot._should_reply("group", "mày chào các anh và tự giới thiệu đi"))

    def test_group_reminder_request_is_reply_worthy_without_mention(self):
        self.assertTrue(zalo_bot._should_reply("group", "nhắc anh Phương 08:00 sáng ngày 26/4/2026 cập nhật kế hoạch"))

    def test_parse_reminder_with_explicit_date_and_time(self):
        now = datetime(2026, 4, 25, 9, 0, tzinfo=LOCAL_TZ)

        reminder = zalo_bot._parse_custom_reminder_request(
            "nhắc anh Phương 08:00 sáng ngày 26/4/2026 cập nhật bổ sung kế hoạch vào Lịch đăng bài",
            "Truyền thông Yok Đôn",
            now=now,
        )

        self.assertEqual(reminder["target"], "anh Phương")
        self.assertEqual(reminder["task"], "cập nhật bổ sung kế hoạch vào Lịch đăng bài")
        self.assertTrue(reminder["due_at"].startswith("2026-04-26T08:00:00"))

    def test_parse_reminder_with_tomorrow_after_task(self):
        now = datetime(2026, 4, 25, 9, 0, tzinfo=LOCAL_TZ)

        reminder = zalo_bot._parse_custom_reminder_request(
            "nhắc anh Nguyên đăng bài vào 8:00 sáng mai",
            "Truyền thông Yok Đôn",
            now=now,
        )

        self.assertEqual(reminder["target"], "anh Nguyên")
        self.assertEqual(reminder["task"], "đăng bài")
        self.assertTrue(reminder["due_at"].startswith("2026-04-26T08:00:00"))

    def test_parse_reminder_with_only_time_uses_today_if_future(self):
        now = datetime(2026, 4, 25, 8, 0, tzinfo=LOCAL_TZ)

        reminder = zalo_bot._parse_custom_reminder_request(
            "nhắc anh Quốc 08:25 đón con",
            "Truyền thông Yok Đôn",
            now=now,
        )

        self.assertEqual(reminder["target"], "anh Quốc")
        self.assertEqual(reminder["task"], "đón con")
        self.assertTrue(reminder["due_at"].startswith("2026-04-25T08:25:00"))

    def test_parse_reminder_with_phone_call_task(self):
        now = datetime(2026, 4, 25, 9, 4, tzinfo=LOCAL_TZ)

        reminder = zalo_bot._parse_custom_reminder_request(
            "Nhắc anh Quốc gọi điện cho mẹ lúc 9:15",
            "Truyền thông Yok Đôn",
            now=now,
        )

        self.assertEqual(reminder["target"], "anh Quốc")
        self.assertEqual(reminder["task"], "gọi điện cho mẹ")
        self.assertTrue(reminder["due_at"].startswith("2026-04-25T09:15:00"))

    def test_parse_reminder_keeps_di_as_task_not_target(self):
        now = datetime(2026, 4, 25, 8, 0, tzinfo=LOCAL_TZ)

        reminder = zalo_bot._parse_custom_reminder_request(
            "Em nhắc anh Quốc 8:25 đi đón con nhé @Nhân Viên Mới Yok Đôn",
            "Truyền thông Yok Đôn",
            now=now,
        )

        self.assertEqual(reminder["target"], "anh Quốc")
        self.assertEqual(reminder["task"], "đi đón con")
        self.assertTrue(reminder["due_at"].startswith("2026-04-25T08:25:00"))

    def test_parse_reminder_accepts_short_a_title(self):
        now = datetime(2026, 4, 25, 9, 0, tzinfo=LOCAL_TZ)

        reminder = zalo_bot._parse_custom_reminder_request(
            "Nhớ nhắc a Quốc trước khi đi test coi còn nồng độ cồn không nha @Nhân Viên Mới Yok Đôn",
            "Truyền thông Yok Đôn",
            now=now,
        )

        self.assertEqual(reminder["target"], "anh Quốc")
        self.assertEqual(reminder["task"], "trước khi đi test coi còn nồng độ cồn không")
        self.assertTrue(reminder["due_at"].startswith("2026-04-26T08:00:00"))

    def test_parse_reminder_without_time_defaults_to_tomorrow_morning(self):
        now = datetime(2026, 4, 25, 9, 0, tzinfo=LOCAL_TZ)

        reminder = zalo_bot._parse_custom_reminder_request(
            "nhắc anh Nghĩa cập nhật link bài đã đăng vào Lịch",
            "Truyền thông Yok Đôn",
            now=now,
        )

        self.assertEqual(reminder["target"], "anh Nghĩa")
        self.assertEqual(reminder["task"], "cập nhật link bài đã đăng vào Lịch")
        self.assertTrue(reminder["due_at"].startswith("2026-04-26T08:00:00"))

    def test_due_custom_reminder_is_sent_to_saved_group(self):
        async def run_case():
            state = {
                "custom_reminders": [
                    {
                        "id": "rem-1",
                        "chat_name": "Truyền thông Yok Đôn",
                        "target": "anh Quốc",
                        "task": "đón con",
                        "due_at": "2026-04-25T08:25:00+07:00",
                        "sent": False,
                    }
                ]
            }
            sent_messages = []
            opened_chats = []

            async def fake_open(_page, chat_name):
                opened_chats.append(chat_name)
                return True

            async def fake_send(_page, text):
                sent_messages.append(text)
                return True

            with (
                patch.object(zalo_bot, "_load_runtime_state", return_value=state),
                patch.object(zalo_bot, "_save_runtime_state") as save_state,
                patch.object(zalo_bot, "local_now", return_value=datetime(2026, 4, 25, 8, 26, tzinfo=LOCAL_TZ)),
                patch.object(zalo_bot, "_open_chat_by_name", side_effect=fake_open),
                patch.object(zalo_bot, "_send_message", side_effect=fake_send),
            ):
                await zalo_bot._maybe_send_due_custom_reminders(AsyncMock())

            self.assertEqual(opened_chats, ["Truyền thông Yok Đôn"])
            self.assertEqual(sent_messages, ["anh Quốc ơi, em nhắc việc: đón con."])
            self.assertTrue(state["custom_reminders"][0]["sent"])
            save_state.assert_called_once()

        import asyncio

        asyncio.run(run_case())

    def test_due_custom_reminder_sends_without_reopening_when_already_in_chat(self):
        async def run_case():
            state = {
                "custom_reminders": [
                    {
                        "id": "rem-1",
                        "chat_name": "Truyền thông Yok Đôn",
                        "target": "anh Quốc",
                        "task": "đi đón con",
                        "due_at": "2026-04-25T08:25:00+07:00",
                        "sent": False,
                    }
                ]
            }
            sent_messages = []

            async def fake_send(_page, text):
                sent_messages.append(text)
                return True

            with (
                patch.object(zalo_bot, "_load_runtime_state", return_value=state),
                patch.object(zalo_bot, "_save_runtime_state") as save_state,
                patch.object(zalo_bot, "local_now", return_value=datetime(2026, 4, 25, 8, 26, tzinfo=LOCAL_TZ)),
                patch.object(
                    zalo_bot,
                    "_capture_chat_state",
                    return_value={"chatName": "Truyền\u00a0thông\u00a0Yok\u00a0Đôn", "hasComposer": True},
                ),
                patch.object(zalo_bot, "_open_chat_by_name", new_callable=AsyncMock) as open_chat,
                patch.object(zalo_bot, "_send_message", side_effect=fake_send),
            ):
                await zalo_bot._maybe_send_due_custom_reminders(AsyncMock())

            open_chat.assert_not_called()
            self.assertEqual(sent_messages, ["anh Quốc ơi, em nhắc việc: đi đón con."])
            self.assertTrue(state["custom_reminders"][0]["sent"])
            save_state.assert_called_once()

        import asyncio

        asyncio.run(run_case())

    def test_search_click_retries_after_dismissing_modal(self):
        async def run_case():
            first_input = AsyncMock()
            first_input.click.side_effect = zalo_bot.PlaywrightError("modal blocked")
            second_input = AsyncMock()

            with (
                patch.object(zalo_bot, "_dismiss_blocking_modal", new_callable=AsyncMock, return_value=True) as dismiss_modal,
                patch.object(zalo_bot, "_get_visible_locator", new_callable=AsyncMock, return_value=second_input),
            ):
                ok = await zalo_bot._click_search_input_with_modal_retry(AsyncMock(), first_input, "Truyền thông Yok Đôn")

            self.assertTrue(ok)
            dismiss_modal.assert_awaited_once()
            second_input.click.assert_awaited_once()

        import asyncio

        asyncio.run(run_case())

    def test_clear_sidebar_search_filter_removes_stale_query(self):
        async def run_case():
            search_input = AsyncMock()
            search_input.input_value.return_value = "Truyền thông Yok Đôn"
            page = AsyncMock()
            page.evaluate.return_value = False

            with patch.object(zalo_bot, "_get_visible_locator", new_callable=AsyncMock, return_value=search_input):
                cleared = await zalo_bot._clear_sidebar_search_filter(page)

            self.assertTrue(cleared)
            search_input.click.assert_awaited_once()
            search_input.fill.assert_awaited_once_with("")
            page.keyboard.press.assert_any_await("Escape")

        import asyncio

        asyncio.run(run_case())

    def test_clear_sidebar_search_filter_closes_search_mode(self):
        async def run_case():
            page = AsyncMock()
            page.evaluate.return_value = True

            with patch.object(zalo_bot, "_get_visible_locator", new_callable=AsyncMock) as get_visible:
                cleared = await zalo_bot._clear_sidebar_search_filter(page)

            self.assertTrue(cleared)
            page.evaluate.assert_awaited_once()
            get_visible.assert_not_awaited()

        import asyncio

        asyncio.run(run_case())

    def test_sidebar_signature_ignores_time_only_raw_text_changes(self):
        first = {
            "title": "Quốc",
            "preview": "chào em",
            "unreadCount": 1,
            "isMinePreview": False,
            "rawText": "Quốc\nchào em\nvài giây",
        }
        later = {
            **first,
            "rawText": "Quốc\nchào em\n1 phút",
        }

        self.assertEqual(zalo_bot._sidebar_signature(first), zalo_bot._sidebar_signature(later))

    def test_opened_sidebar_chat_must_match_expected_title(self):
        self.assertTrue(zalo_bot._chat_title_matches("Truyền thông Yok Đôn", "Truyền thông Yok Đôn"))
        self.assertFalse(zalo_bot._chat_title_matches("Quốc", "Truyền thông Yok Đôn"))

    def test_sidebar_heading_is_not_a_chat_target(self):
        self.assertTrue(zalo_bot._should_ignore_sidebar_chat({"title": "Liên hệ (4)", "preview": "", "rawText": "Liên hệ (4)"}))

    def test_zalo_pc_history_notice_is_not_a_chat_message(self):
        self.assertTrue(
            zalo_bot._should_ignore_sidebar_chat(
                {
                    "title": "Sử dụng Zalo PC để tìm tin nhắn trước ngày 09/04/2026.",
                    "preview": "",
                    "rawText": "Sử dụng Zalo PC để tìm tin nhắn trước ngày 09/04/2026.",
                }
            )
        )

    def test_sidebar_command_preview_is_not_a_chat_target(self):
        self.assertTrue(zalo_bot._should_ignore_sidebar_chat({"title": "/nhacviec", "preview": "", "rawText": "/nhacviec"}))

    def test_sidebar_sync_row_is_not_a_chat_target(self):
        self.assertTrue(
            zalo_bot._should_ignore_sidebar_chat(
                {"title": "Đồng bộ tin nhắn thành công", "preview": "", "rawText": "Đồng bộ tin nhắn thành công"}
            )
        )

    def test_select_sidebar_targets_dedupes_same_chat_title(self):
        chats = [
            {"title": "NĐ", "preview": "tin 1", "unreadCount": 1, "isMinePreview": False, "top": 10},
            {"title": "NĐ", "preview": "tin 2", "unreadCount": 1, "isMinePreview": False, "top": 50},
        ]

        changed, next_state = zalo_bot._select_sidebar_targets(chats, {}, True)

        self.assertEqual([chat["preview"] for chat in changed], ["tin 1"])
        self.assertEqual(list(next_state), ["nd"])

    def test_personal_group_greeting_request_is_detected(self):
        message = zalo_bot._extract_group_relay_message("Em hãy vào chào anh Ba 1 tiếng nhé")

        self.assertEqual(
            message,
            (
                "Em chào anh Ba, chào mừng anh Ba đến với nhóm Truyền thông "
                "của Vườn quốc gia Yok Đôn, anh có cần em hỗ trợ gì không ạ?"
            ),
        )

    def test_complex_group_greeting_extracts_target_not_whole_instruction(self):
        message = zalo_bot._extract_group_relay_message(
            "Em hãy vào chào anh Trương Văn Nghĩa và khen anh ấy Đẹp trai 1 tiếng nhé"
        )

        self.assertIn("Em chào anh Trương Văn Nghĩa", message)
        self.assertIn("phong độ", message)
        self.assertNotIn("và khen anh ấy", message)

    def test_plain_greeting_does_not_trigger_group_relay(self):
        self.assertEqual(zalo_bot._extract_group_relay_message("Chào anh nhé"), "")

    def test_freeform_group_relay_request_is_detected(self):
        message = zalo_bot._extract_group_relay_message("Em nhắn vào nhóm rằng Chiều nay họp lúc 15h nhé")

        self.assertEqual(message, "Chiều nay họp lúc 15h nhé")

    def test_group_intro_relay_request_is_detected(self):
        message = zalo_bot._extract_group_relay_message(
            "Mày vào nhóm và chào mọi người đi. Nhóm Truyền thông Yok Đôn"
        )

        self.assertIn("Em chào các anh/chị", message)
        self.assertIn("Nhân Viên Mới Yok Đôn", message)

    def test_group_relay_accepts_enter_group_then_message_pattern(self):
        message = zalo_bot._extract_group_relay_message("vào nhóm nhắn tin nhắn: Chúc các anh ngủ ngon")

        self.assertEqual(message, "Chúc các anh ngủ ngon")

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

    def test_group_conversation_window_opens_after_reply(self):
        async def run_case():
            page = AsyncMock()
            group_window = {}
            processed = []

            async def fake_process(_page, chat_name, chat_type, text, group_conversation_active=False):
                processed.append((chat_name, chat_type, text, group_conversation_active))

            with patch.object(zalo_bot, "_process_chat_message", side_effect=fake_process):
                handled = await zalo_bot._maybe_process_latest_message(
                    page,
                    "Truyền thông Yok Đôn",
                    "group",
                    ["@Nhân Viên Mới Yok Đôn ơi"],
                    {},
                    {},
                    only_if_reply_needed=True,
                    group_conversation_until=group_window,
                )

            self.assertTrue(handled)
            self.assertIn("Truyền thông Yok Đôn", group_window)
            self.assertEqual(processed[0][2], "@Nhân Viên Mới Yok Đôn ơi")

        import asyncio

        asyncio.run(run_case())

    def test_group_conversation_followup_reaches_natural_language_handler(self):
        async def run_case():
            page = AsyncMock()

            with patch.object(zalo_bot, "_handle_natural_language", new_callable=AsyncMock) as natural:
                await zalo_bot._process_chat_message(
                    page,
                    "Truyền thông Yok Đôn",
                    "group",
                    "mày chào các anh và tự giới thiệu đi",
                    group_conversation_active=True,
                )

            natural.assert_awaited_once()

        import asyncio

        asyncio.run(run_case())

    def test_complex_personal_group_relay_uses_llm_rewrite(self):
        async def run_case():
            sent_messages = []
            opened_chats = []

            async def fake_send(_page, text):
                sent_messages.append(text)
                return True

            async def fake_open(_page, chat_name):
                opened_chats.append(chat_name)
                return True

            async def fake_rewrite(_text, _fallback):
                return (
                    "Em chào anh Trương Văn Nghĩa ạ. "
                    "Hôm nay em xin phép khen anh một câu: anh rất phong độ và đẹp trai. "
                    "Anh cần em hỗ trợ gì cứ nhắn em nhé."
                )

            page = AsyncMock()
            page.wait_for_timeout = AsyncMock()
            with (
                patch.object(zalo_bot, "_send_message", side_effect=fake_send),
                patch.object(zalo_bot, "_open_chat_by_name", side_effect=fake_open),
                patch.object(zalo_bot, "rewrite_group_relay_message", side_effect=fake_rewrite),
            ):
                handled = await zalo_bot._handle_personal_group_relay(
                    page,
                    "Quốc",
                    "Em hãy vào chào anh Trương Văn Nghĩa và khen anh ấy Đẹp trai 1 tiếng nhé",
                )

            self.assertTrue(handled)
            self.assertEqual(sent_messages[0], "Dạ, em sẽ làm ngay.")
            self.assertIn("Em chào anh Trương Văn Nghĩa", sent_messages[1])
            self.assertIn("phong độ", sent_messages[1])
            self.assertNotIn("và khen anh ấy", sent_messages[1])
            self.assertEqual(opened_chats, [zalo_bot.ZALO_GROUP_NAME, "Quốc"])

        import asyncio

        asyncio.run(run_case())

    def test_unsafe_personal_group_relay_is_not_sent_to_group(self):
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
            with (
                patch.object(zalo_bot, "_send_message", side_effect=fake_send),
                patch.object(zalo_bot, "_open_chat_by_name", side_effect=fake_open),
            ):
                handled = await zalo_bot._handle_personal_group_relay(
                    page,
                    "Quốc",
                    "Em vào nhóm chào anh Ba và chửi anh ấy một câu nhé",
                )

            self.assertTrue(handled)
            self.assertIn("chưa gửi nội dung này vào nhóm", sent_messages[0])
            self.assertEqual(opened_chats, [])

        import asyncio

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
