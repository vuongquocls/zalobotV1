import { tgBot } from '../telegram/bot.js';
import { config } from '../config.js';
import { formatHermesApprovalMessage } from './format.js';
import type { PendingHermesApproval } from './approvalStore.js';
import { hermesApprovalTargetStore } from './approvalTargets.js';

export interface HermesApprovalDeliveryResult {
  chatId: number;
  messageId: number;
}

function configuredApprovalChatIds(): number[] {
  const dynamicTargets = hermesApprovalTargetStore.all().map(target => target.chatId);
  const staticTargets = config.telegram.approverUserIds
    .map(id => Number(id))
    .filter(id => Number.isFinite(id));
  return [...new Set([...dynamicTargets, ...staticTargets])];
}

export async function sendHermesApprovalRequest(
  approval: PendingHermesApproval,
): Promise<HermesApprovalDeliveryResult> {
  const chatIds = configuredApprovalChatIds();
  if (chatIds.length === 0) {
    throw new Error('No Telegram approval DM target configured. Send /duyet_here to the Telegram bot in a private chat.');
  }

  const errors: string[] = [];
  for (const chatId of chatIds) {
    try {
      const sent = await tgBot.telegram.sendMessage(
        chatId,
        formatHermesApprovalMessage(approval),
        {
          parse_mode: 'HTML',
          reply_markup: {
            inline_keyboard: [[
              { text: 'Duyệt gửi Zalo', callback_data: `ha:a:${approval.approvalId}` },
              { text: 'Từ chối', callback_data: `ha:r:${approval.approvalId}` },
            ]],
          },
        },
      );
      return { chatId, messageId: sent.message_id };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      errors.push(`${chatId}: ${message}`);
    }
  }

  throw new Error(`Failed to send Telegram approval DM: ${errors.join('; ')}`);
}
