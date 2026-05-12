import { escapeHtml } from '../utils/format.js';
import type { PendingHermesApproval } from './approvalStore.js';

export function formatHermesApprovalMessage(entry: PendingHermesApproval): string {
  const reason = entry.reason ? `\n\n<b>Lý do cần duyệt:</b>\n${escapeHtml(entry.reason)}` : '';
  const postAction = entry.postApprovalAction
    ? [
      '',
      '<b>Thao tác sau khi duyệt:</b>',
      escapeHtml(entry.postApprovalAction.label),
      'Bot sẽ chạy thao tác này sau khi anh bấm “Duyệt gửi Zalo”, rồi gửi kết quả về Zalo.',
    ].join('\n')
    : '';
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
    '',
    '<b>Cách sửa trước khi gửi:</b>',
    'Reply trực tiếp vào tin này bằng bản trả lời đã sửa. Bot sẽ cập nhật dự thảo, rồi anh bấm “Duyệt gửi Zalo”.',
    postAction,
    reason,
  ].join('\n');
}

export function formatHermesAuditLog(title: string, body: string): string {
  return `<b>${escapeHtml(title)}</b>\n${escapeHtml(body)}`;
}
