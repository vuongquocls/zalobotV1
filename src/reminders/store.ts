import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import path from 'path';
import { config } from '../config.js';

export type ReminderStatus = 'pending' | 'sent' | 'failed';

export interface ZaloReminder {
  id: string;
  zaloId: string;
  threadType: 0 | 1;
  chatName: string;
  senderId: string;
  senderName: string;
  text: string;
  remindAtIso: string;
  createdAtIso: string;
  status: ReminderStatus;
  attempts: number;
  sentAtIso?: string;
  lastAttemptAtIso?: string;
  lastError?: string;
}

const filePath = path.join(config.dataDir, 'zalo_reminders.json');

function ensureDataDir(): void {
  mkdirSync(config.dataDir, { recursive: true });
}

function readAll(): ZaloReminder[] {
  ensureDataDir();
  if (!existsSync(filePath)) return [];
  try {
    const data = JSON.parse(readFileSync(filePath, 'utf-8')) as unknown;
    return Array.isArray(data) ? data.filter(isReminder) : [];
  } catch {
    return [];
  }
}

function writeAll(reminders: ZaloReminder[]): void {
  ensureDataDir();
  writeFileSync(filePath, JSON.stringify(reminders, null, 2), 'utf-8');
}

function isReminder(value: unknown): value is ZaloReminder {
  if (!value || typeof value !== 'object') return false;
  const item = value as Partial<ZaloReminder>;
  return typeof item.id === 'string'
    && typeof item.zaloId === 'string'
    && (item.threadType === 0 || item.threadType === 1)
    && typeof item.text === 'string'
    && typeof item.remindAtIso === 'string'
    && (item.status === 'pending' || item.status === 'sent' || item.status === 'failed');
}

export const reminderStore = {
  add(reminder: ZaloReminder): void {
    const reminders = readAll();
    reminders.push(reminder);
    writeAll(reminders);
  },

  all(): ZaloReminder[] {
    return readAll();
  },

  pendingDue(now = new Date()): ZaloReminder[] {
    const nowMs = now.getTime();
    return readAll().filter(reminder => {
      if (reminder.status !== 'pending') return false;
      const dueMs = Date.parse(reminder.remindAtIso);
      if (!Number.isFinite(dueMs) || dueMs > nowMs) return false;
      if (!reminder.lastAttemptAtIso) return true;
      return nowMs - Date.parse(reminder.lastAttemptAtIso) >= 60_000;
    });
  },

  update(id: string, patch: Partial<ZaloReminder>): void {
    const reminders = readAll();
    const index = reminders.findIndex(reminder => reminder.id === id);
    if (index < 0) return;
    reminders[index] = { ...reminders[index]!, ...patch };
    writeAll(reminders);
  },
};
