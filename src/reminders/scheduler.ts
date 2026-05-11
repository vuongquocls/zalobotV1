import { ThreadType } from 'zca-js';
import type { ZaloAPI } from '../zalo/types.js';
import { formatVietnamDateTime } from './parser.js';
import { reminderStore, type ZaloReminder } from './store.js';

const SCAN_INTERVAL_MS = Number(process.env.ZALO_REMINDER_SCAN_INTERVAL_MS ?? 15_000);
const MAX_ATTEMPTS = Number(process.env.ZALO_REMINDER_MAX_ATTEMPTS ?? 3);

let schedulerStarted = false;
let scanRunning = false;

function reminderMessage(reminder: ZaloReminder): string {
  return [
    `⏰ Nhắc hẹn: ${reminder.text}`,
    '',
    `Anh đã hẹn em nhắc lúc ${formatVietnamDateTime(new Date(reminder.remindAtIso))} (giờ Việt Nam).`,
  ].join('\n');
}

async function deliverReminder(api: ZaloAPI, reminder: ZaloReminder): Promise<void> {
  const nowIso = new Date().toISOString();
  try {
    await api.sendMessage(
      { msg: reminderMessage(reminder) },
      reminder.zaloId,
      reminder.threadType === 1 ? ThreadType.Group : ThreadType.User,
    );
    reminderStore.update(reminder.id, {
      status: 'sent',
      sentAtIso: nowIso,
      lastAttemptAtIso: nowIso,
      attempts: reminder.attempts + 1,
      lastError: undefined,
    });
    console.log(`[Reminder] sent id=${reminder.id} zaloId=${reminder.zaloId}`);
  } catch (err) {
    const attempts = reminder.attempts + 1;
    const message = err instanceof Error ? err.message : String(err);
    reminderStore.update(reminder.id, {
      status: attempts >= MAX_ATTEMPTS ? 'failed' : 'pending',
      attempts,
      lastAttemptAtIso: nowIso,
      lastError: message,
    });
    console.warn(`[Reminder] failed id=${reminder.id} attempt=${attempts}: ${message}`);
  }
}

async function scanDueReminders(api: ZaloAPI): Promise<void> {
  if (scanRunning) return;
  scanRunning = true;
  try {
    const due = reminderStore.pendingDue();
    for (const reminder of due) {
      await deliverReminder(api, reminder);
    }
  } finally {
    scanRunning = false;
  }
}

export function startZaloReminderScheduler(api: ZaloAPI): void {
  if (schedulerStarted) return;
  schedulerStarted = true;
  void scanDueReminders(api);
  setInterval(() => {
    void scanDueReminders(api);
  }, SCAN_INTERVAL_MS);
  console.log(`[Reminder] scheduler started intervalMs=${SCAN_INTERVAL_MS}`);
}
