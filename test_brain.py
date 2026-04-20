import unittest

import brain


class BrainIntentTests(unittest.TestCase):
    def test_capabilities_intent(self):
        text = "Em hãy giới thiệu về em cho anh biết. Em có thể làm được gì?"
        self.assertEqual(brain.classify_intent(text), "capabilities")

    def test_today_tasks_intent(self):
        self.assertEqual(brain.classify_intent("việc hôm nay có gì?"), "today_tasks")

    def test_upcoming_tasks_intent(self):
        self.assertEqual(brain.classify_intent("3 ngày tới có việc nào?"), "upcoming_tasks")

    def test_draft_content_intent(self):
        self.assertEqual(brain.classify_intent("soạn giúp bài về voi Yok Đôn"), "draft_content")

    def test_sensitive_intent(self):
        self.assertEqual(brain.classify_intent("có bình luận tiêu cực thì xử lý sao?"), "sensitive")

    def test_capability_reply_is_role_specific(self):
        reply = brain.build_capability_reply()
        self.assertIn("Nhân Viên Mới Yok Đôn", reply)
        self.assertIn("Google Sheet", reply)
        self.assertIn("Dự thảo", reply)
        self.assertNotIn("tập trung cao độ", reply.lower())


if __name__ == "__main__":
    unittest.main()
