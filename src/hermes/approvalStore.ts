import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import path from 'path';

import { config } from '../config.js';

export interface PendingHermesPostApprovalAction {
  type: 'facebook_publish_sheet_row' | 'google_sheet_write_draft';
  row: number;
  label: string;
  sheetId?: string;
  worksheetGid?: string;
  targetDate?: string;
  topic?: string;
}

export interface PendingHermesApproval {
  approvalId: string;
  requestId: string;
  zaloId: string;
  threadType: 0 | 1;
  chatName: string;
  senderId: string;
  senderName: string;
  originalText: string;
  replyText: string;
  reason?: string;
  createdAt: string;
  telegramMessageId?: number;
  postApprovalAction?: PendingHermesPostApprovalAction;
}

type ApprovalData = Record<string, PendingHermesApproval>;

const filePath = path.join(config.dataDir, 'hermes_approvals.json');

function load(): ApprovalData {
  if (!existsSync(filePath)) return {};
  try {
    return JSON.parse(readFileSync(filePath, 'utf8')) as ApprovalData;
  } catch {
    return {};
  }
}

function saveAll(data: ApprovalData): void {
  mkdirSync(config.dataDir, { recursive: true });
  writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf8');
}

export const hermesApprovalStore = {
  save(entry: PendingHermesApproval): void {
    const data = load();
    data[entry.approvalId] = entry;
    saveAll(data);
  },

  get(approvalId: string): PendingHermesApproval | undefined {
    return load()[approvalId];
  },

  getByTelegramMessageId(messageId: number): PendingHermesApproval | undefined {
    return Object.values(load()).find(entry => entry.telegramMessageId === messageId);
  },

  remove(approvalId: string): PendingHermesApproval | undefined {
    const data = load();
    const entry = data[approvalId];
    if (!entry) return undefined;
    delete data[approvalId];
    saveAll(data);
    return entry;
  },
};
