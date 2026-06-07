import assert from 'node:assert/strict';
import test from 'node:test';

import { formatVietnamDateTime, parseReminderRequest } from '../dist/reminders/parser.js';

test('parses "thu 7 tuan sau" from a Sunday in Vietnam time', () => {
  const now = new Date('2026-06-07T08:48:00.000Z'); // 15:48 07/06/2026 in Vietnam.

  const reminder = parseReminderRequest(
    'tạo nhắc hẹn cho anh nội dung: Chở má đi mua giày. Thời gian: Lúc 19:30 thứ 7 tuần sau',
    now,
  );

  assert.ok(reminder);
  assert.equal(reminder.text, 'Chở má đi mua giày');
  assert.equal(reminder.remindAt.toISOString(), '2026-06-13T12:30:00.000Z');
  assert.equal(formatVietnamDateTime(reminder.remindAt), '19:30 thứ Bảy, ngày 13/06/2026');
});

test('moves an unqualified weekday to the next occurrence when today already passed', () => {
  const now = new Date('2026-06-13T13:00:00.000Z'); // 20:00 Saturday in Vietnam.

  const reminder = parseReminderRequest('nhắc anh lúc 19:30 thứ 7 mua giày', now);

  assert.ok(reminder);
  assert.equal(reminder.remindAt.toISOString(), '2026-06-20T12:30:00.000Z');
});
