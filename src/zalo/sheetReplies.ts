import { execFile } from 'child_process';
import { existsSync } from 'fs';
import path from 'path';
import { promisify } from 'util';

const execFileAsync = promisify(execFile);

export type SheetReplyIntent = 'today' | 'upcoming' | 'overdue' | 'unassigned' | 'pending';

function normalize(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/đ/g, 'd')
    .replace(/[^a-z0-9/@#\s]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function includesAny(text: string, patterns: string[]): boolean {
  return patterns.some(pattern => text.includes(pattern));
}

export function classifySheetReplyIntent(text: string): SheetReplyIntent | undefined {
  const body = normalize(text);
  if (!body) return undefined;

  const mentionsSheet = includesAny(body, [
    'google sheet',
    'sheet',
    'bang tinh',
    'bang ke hoach',
    'lich google',
    'lich dang',
    'lich truyen thong',
  ]);
  const mentionsWork = includesAny(body, [
    'viec',
    'nhiem vu',
    'ke hoach',
    'lich',
    'bai viet',
    'viet bai',
    'dang bai',
    'phu trach',
    'nguoi viet',
    'nguoi thuc hien',
  ]);

  if (!mentionsSheet && !mentionsWork) return undefined;

  if (includesAny(body, ['qua han', 'tre han', 'cham tien do', 'chua xong'])) return 'overdue';
  if (includesAny(body, ['chua giao', 'ai phu trach', 'nguoi phu trach'])) return 'unassigned';
  if (includesAny(body, ['3 ngay', 'ba ngay', 'sap toi', 'toi day', 'tuan nay', 'sap den han'])) return 'upcoming';
  if (includesAny(body, ['hom nay', 'ngay nay', 'today', 'nguoi viet', 'ai la nguoi viet'])) return 'today';
  if (includesAny(body, ['danh sach', 'xem viec', 'viec nao', 'co viec'])) return 'pending';

  return mentionsSheet ? 'pending' : undefined;
}

export function isClearSheetReplyRequest(text: string): boolean {
  return classifySheetReplyIntent(text) !== undefined;
}

export async function buildSheetReply(text: string): Promise<string | undefined> {
  const intent = classifySheetReplyIntent(text);
  if (!intent) return undefined;

  const localVenvPython = path.resolve(process.cwd(), '.venv/bin/python');
  const pythonBin = process.env.ZALO_SHEET_REPLY_PYTHON
    ?? process.env.PYTHON_BIN
    ?? (existsSync(localVenvPython) ? localVenvPython : 'python3');
  const scriptPath = process.env.ZALO_SHEET_REPLY_SCRIPT ?? path.resolve(process.cwd(), 'scripts/sheet_reply.py');
  const { stdout } = await execFileAsync(pythonBin, [scriptPath, '--intent', intent], {
    cwd: process.cwd(),
    timeout: Number(process.env.ZALO_SHEET_REPLY_TIMEOUT_MS ?? 45000),
    maxBuffer: Number(process.env.ZALO_SHEET_REPLY_MAX_BUFFER ?? 1024 * 1024),
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
    },
  });

  return stdout.trim() || undefined;
}
