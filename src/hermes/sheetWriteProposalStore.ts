import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import path from 'path';

import { config } from '../config.js';
import type { PendingHermesPostApprovalAction } from './approvalStore.js';

export interface PendingSheetWriteProposal {
  id: string;
  zaloId: string;
  threadType: 0 | 1;
  chatName: string;
  senderId: string;
  senderName: string;
  originalText: string;
  approvedText: string;
  action: PendingHermesPostApprovalAction;
  createdAt: string;
}

type ProposalData = Record<string, PendingSheetWriteProposal>;

const filePath = path.join(config.dataDir, 'sheet_write_proposals.json');
const TTL_MS = Number(process.env.HERMES_SHEET_WRITE_PROPOSAL_TTL_MS ?? 24 * 60 * 60 * 1000);

function load(): ProposalData {
  if (!existsSync(filePath)) return {};
  try {
    return JSON.parse(readFileSync(filePath, 'utf8')) as ProposalData;
  } catch {
    return {};
  }
}

function saveAll(data: ProposalData): void {
  mkdirSync(config.dataDir, { recursive: true });
  writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf8');
}

function isFresh(entry: PendingSheetWriteProposal): boolean {
  return Date.now() - new Date(entry.createdAt).getTime() <= TTL_MS;
}

export const sheetWriteProposalStore = {
  save(entry: PendingSheetWriteProposal): void {
    const data = load();
    for (const [id, current] of Object.entries(data)) {
      if (!isFresh(current) || (current.zaloId === entry.zaloId && current.threadType === entry.threadType)) {
        delete data[id];
      }
    }
    data[entry.id] = entry;
    saveAll(data);
  },

  latest(zaloId: string, threadType: 0 | 1): PendingSheetWriteProposal | undefined {
    const data = load();
    let changed = false;
    const candidates: PendingSheetWriteProposal[] = [];
    for (const [id, entry] of Object.entries(data)) {
      if (!isFresh(entry)) {
        delete data[id];
        changed = true;
        continue;
      }
      if (entry.zaloId === zaloId && entry.threadType === threadType) {
        candidates.push(entry);
      }
    }
    if (changed) saveAll(data);
    return candidates.sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0];
  },

  remove(id: string): void {
    const data = load();
    if (data[id]) {
      delete data[id];
      saveAll(data);
    }
  },
};
