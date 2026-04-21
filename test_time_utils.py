import unittest
from datetime import datetime

import time_utils
import zalo_bot


class TimezoneReminderTests(unittest.TestCase):
    def test_local_now_uses_configured_vietnam_timezone(self):
        now = time_utils.local_now()

        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.utcoffset().total_seconds(), 7 * 60 * 60)

    def test_reminder_time_is_evaluated_in_local_time(self):
        original_hour = zalo_bot.REMINDER_HOUR
        original_minute = zalo_bot.REMINDER_MINUTE
        try:
            zalo_bot.REMINDER_HOUR = 8
            zalo_bot.REMINDER_MINUTE = 0

            before = datetime(2026, 4, 21, 7, 59, tzinfo=time_utils.LOCAL_TZ)
            exact = datetime(2026, 4, 21, 8, 0, tzinfo=time_utils.LOCAL_TZ)

            self.assertFalse(zalo_bot._is_at_or_after_reminder_time(before))
            self.assertTrue(zalo_bot._is_at_or_after_reminder_time(exact))
        finally:
            zalo_bot.REMINDER_HOUR = original_hour
            zalo_bot.REMINDER_MINUTE = original_minute


if __name__ == "__main__":
    unittest.main()

