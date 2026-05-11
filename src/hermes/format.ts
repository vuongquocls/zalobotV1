import { escapeHtml } from '../utils/format.js';
import type { PendingHermesApproval } from './approvalStore.js';

export function formatHermesApprovalMessage(entry: PendingHermesApproval): string {
  const reason = entry.reason ? `\n\n<b>Lý do cần duyệt:</b>\n${escapeHtml(entry.reason)}` : '';
  return [
    '🧠 <b>Hermes cần anh duyệt trước khi trả lời Zalo</b>',
    '',
    `<b>Nơi nhận:</b> ${escapeHtml(entry.chatName)}`,
    `<b>Người hỏi:</b> ${escapeHtml(entry.senderName)}`,
    `<b>Mã duyệt:</b> <code>${escapeHtml(entry.approvalId)}</code>`,
    '',
    '<b>Tin Zalo:</b>',
    escapeHtml(entry.originalText),
    '',
    '<b>Dự thảo trả lời:</b>',
    escapeHtml(entry.replyText),
    reason,
  ].join('\n');
}

export function formatHermesAuditLog(title: string, body: string): string {
  return `<b>${escapeHtml(title)}</b>\n${escapeHtml(body)}`;
}

