import { escapeHtml } from '../utils/format.js';
import type { PendingHermesApproval } from './approvalStore.js';

export function formatHermesApprovalMessage(entry: PendingHermesApproval): string {
  const reason = entry.reason ? `\n\n<b>Lý do cần duyệt:</b>\n${escapeHtml(entry.reason)}` : '';
  const isSheetWrite = entry.postApprovalAction?.type === 'google_sheet_write_draft';
  const isSheetProposal = entry.deferredPostApprovalAction?.type === 'google_sheet_write_draft';
  const draftLabel = isSheetWrite || isSheetProposal ? 'Dự thảo nội dung đề xuất:' : 'Dự thảo trả lời:';
  const editHelp = isSheetWrite
    ? 'Reply trực tiếp vào tin này bằng nội dung đã sửa. Bot sẽ cập nhật bản ghi Sheet, rồi anh bấm “Duyệt gửi Zalo”.'
    : isSheetProposal
      ? 'Reply trực tiếp vào tin này để sửa đề xuất gửi về Zalo. Nút “Duyệt gửi Zalo” chỉ gửi đề xuất về Zalo, chưa ghi Sheet.'
    : 'Reply trực tiếp vào tin này bằng bản trả lời đã sửa. Bot sẽ cập nhật dự thảo, rồi anh bấm “Duyệt gửi Zalo”.';
  const postAction = entry.postApprovalAction
    ? [
      '',
      '<b>Thao tác sau khi duyệt:</b>',
      escapeHtml(entry.postApprovalAction.label),
      'Bot sẽ chạy thao tác này sau khi anh bấm “Duyệt gửi Zalo”, rồi gửi kết quả về Zalo.',
    ].join('\n')
    : entry.deferredPostApprovalAction
      ? [
        '',
        '<b>Thao tác sau bước này:</b>',
        escapeHtml(entry.deferredPostApprovalAction.label),
        'Nút “Duyệt gửi Zalo” chỉ gửi đề xuất về Zalo. Nếu người dùng đồng ý sau đó, bot mới tạo yêu cầu duyệt ghi Sheet riêng.',
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
    `<b>${draftLabel}</b>`,
    escapeHtml(entry.replyText),
    '',
    '<b>Cách sửa trước khi gửi:</b>',
    editHelp,
    postAction,
    reason,
  ].join('\n');
}

export function formatHermesAuditLog(title: string, body: string): string {
  return `<b>${escapeHtml(title)}</b>\n${escapeHtml(body)}`;
}
