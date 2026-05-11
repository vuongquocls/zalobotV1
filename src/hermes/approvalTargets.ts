import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import path from 'path';

import { config } from '../config.js';

export interface HermesApprovalTarget {
  chatId: number;
  userId: string;
  name?: string;
  updatedAt: string;
}

const filePath = path.join(config.dataDir, 'hermes_approval_targets.json');

function load(): HermesApprovalTarget[] {
  if (!existsSync(filePath)) return [];
  try {
    const parsed = JSON.parse(readFileSync(filePath, 'utf8')) as HermesApprovalTarget[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveAll(targets: HermesApprovalTarget[]): void {
  mkdirSync(config.dataDir, { recursive: true });
  writeFileSync(filePath, JSON.stringify(targets, null, 2), 'utf8');
}

export const hermesApprovalTargetStore = {
  all(): HermesApprovalTarget[] {
    return load();
  },

  upsert(target: Omit<HermesApprovalTarget, 'updatedAt'>): HermesApprovalTarget {
    const targets = load().filter(existing => existing.chatId !== target.chatId);
    const saved = { ...target, updatedAt: new Date().toISOString() };
    targets.push(saved);
    saveAll(targets);
    return saved;
  },
};
