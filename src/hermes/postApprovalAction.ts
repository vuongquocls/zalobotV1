import { execFile } from 'child_process';
import { promisify } from 'util';

import { config } from '../config.js';
import type { PendingHermesPostApprovalAction } from './approvalStore.js';

const execFileAsync = promisify(execFile);

export interface PostApprovalActionResult {
  telegramSummary: string;
  zaloMessage: string;
}

interface PublishRowOutput {
  ok?: boolean;
  error?: string;
  row?: number;
  topic?: string;
  result?: {
    id?: string;
    link?: string;
  };
  published_at?: string;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function normalizeVietnamese(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function extractSheetRow(text: string): number | undefined {
  const direct = text.match(/(?:dòng|dong|row|hàng|hang)\s*[:#-]?\s*(\d{1,5})/i);
  if (!direct) return undefined;
  const row = Number(direct[1]);
  return Number.isInteger(row) && row > 1 ? row : undefined;
}

export function inferPostApprovalAction(text: string): PendingHermesPostApprovalAction | undefined {
  const row = extractSheetRow(text);
  if (!row) return undefined;

  const normalized = normalizeVietnamese(text);
  const publishBeforeRow = /\b(dang|publish|len bai|day bai)\b.{0,80}\b(dong|row|hang)\b/.test(normalized);
  const assistantAskedToPublish =
    /\b(hay|giup|nho|lam|bot|hermes)\b.{0,80}\b(dang|publish|len bai|day bai)\b/.test(normalized)
    || /\bcho\s+(em\s+)?(dang|publish|len bai|day bai)\b/.test(normalized);
  const destinationHint = /\b(facebook|fanpage|fb|page)\b/.test(normalized);
  const contentPublishHint = /\b(dang bai|len bai|dang fanpage|dang facebook|dang fb|publish)\b/.test(normalized);
  const questionIntent = /\b(ai|cho biet|doc|xem|tom tat|ngay nao|don vi nao|trach nhiem)\b/.test(normalized);
  const startsAsCommand = /^(hay|giup|nho|lam|bot|hermes|dang|publish|len bai|day bai|cho dang|cho em dang)\b/.test(normalized);

  if (questionIntent && !startsAsCommand) {
    return undefined;
  }
  if (!(publishBeforeRow || assistantAskedToPublish) || !(destinationHint || contentPublishHint)) {
    return undefined;
  }

  return {
    type: 'facebook_publish_sheet_row',
    row,
    label: `Đăng bài Facebook từ Sheet dòng ${row} và tự ghi link bài đăng về Sheet`,
  };
}

function parsePublishOutput(stdout: string): PublishRowOutput {
  const trimmed = stdout.trim();
  try {
    return JSON.parse(trimmed) as PublishRowOutput;
  } catch {
    const start = trimmed.indexOf('{');
    const end = trimmed.lastIndexOf('}');
    if (start >= 0 && end > start) {
      return JSON.parse(trimmed.slice(start, end + 1)) as PublishRowOutput;
    }
    throw new Error(`Không đọc được kết quả publish: ${trimmed.slice(0, 500)}`);
  }
}

async function executeFacebookPublishSheetRow(
  action: PendingHermesPostApprovalAction,
): Promise<PostApprovalActionResult> {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    HERMES_HOME: config.hermes.publish.home,
    GOOGLE_SERVICE_ACCOUNT_FILE: config.hermes.publish.googleServiceAccountFile,
  };
  if (config.hermes.publish.sheetId) {
    env.QUOC01_CONTENT_SHEET_ID = config.hermes.publish.sheetId;
  }

  const { stdout, stderr } = await execFileAsync(
    config.hermes.publish.pythonBin,
    [
      config.hermes.publish.scriptPath,
      'publish-row',
      '--row',
      String(action.row),
      '--commit',
    ],
    {
      env,
      timeout: config.hermes.publish.timeoutMs,
      maxBuffer: 1024 * 1024 * 8,
    },
  );

  const output = parsePublishOutput(String(stdout));
  if (!output.ok) {
    throw new Error(output.error || String(stderr).trim() || 'Publish không thành công.');
  }

  const link = output.result?.link;
  const postId = output.result?.id;
  const topic = output.topic?.trim();
  const publishedAt = output.published_at;
  const zaloLines = [
    '✅ Đã đăng bài lên Fanpage và cập nhật link vào Google Sheet.',
    `Dòng Sheet: ${output.row ?? action.row}`,
    topic ? `Chủ đề: ${topic}` : undefined,
    link ? `Link bài đăng: ${link}` : undefined,
    publishedAt ? `Thời gian đăng: ${publishedAt}` : undefined,
  ].filter((line): line is string => Boolean(line));

  const telegramLines = [
    '✅ <b>Đã duyệt, đăng Fanpage và cập nhật Sheet</b>',
    '',
    `<b>Dòng Sheet:</b> ${output.row ?? action.row}`,
    topic ? `<b>Chủ đề:</b> ${escapeHtml(topic)}` : undefined,
    link ? `<b>Link:</b> ${escapeHtml(link)}` : undefined,
    postId ? `<b>Post ID:</b> ${escapeHtml(postId)}` : undefined,
    publishedAt ? `<b>Thời gian đăng:</b> ${escapeHtml(publishedAt)}` : undefined,
  ].filter((line): line is string => Boolean(line));

  return {
    telegramSummary: telegramLines.join('\n'),
    zaloMessage: zaloLines.join('\n'),
  };
}

export async function executePostApprovalAction(
  action: PendingHermesPostApprovalAction,
): Promise<PostApprovalActionResult> {
  if (action.type === 'facebook_publish_sheet_row') {
    return executeFacebookPublishSheetRow(action);
  }
  throw new Error(`Unsupported post approval action: ${action.type}`);
}
