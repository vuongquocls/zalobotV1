import 'dotenv/config';

function requireEnv(key: string): string {
  const val = process.env[key];
  if (!val) throw new Error(`Missing required environment variable: ${key}`);
  return val;
}

function optionalNumberEnv(key: string, fallback: number): number {
  const val = process.env[key]?.trim();
  return val ? Number(val) : fallback;
}

const telegramGroupId = Number(requireEnv('TG_GROUP_ID'));

export const config = {
  telegram: {
    token:   requireEnv('TG_TOKEN'),
    groupId: telegramGroupId,
    approvalGroupId: optionalNumberEnv('TG_APPROVAL_GROUP_ID', telegramGroupId),
    approverUserIds: (process.env.TG_APPROVER_USER_IDS ?? '')
      .split(',')
      .map(v => v.trim())
      .filter(Boolean),
  },
  zalo: {
    credentialsPath: process.env.ZALO_CREDENTIALS_PATH ?? './credentials.json',
    digestTargetGroupId: process.env.ZALO_DIGEST_TARGET_GROUP_ID ?? '45373282205285418',
    digestTargetGroupName: process.env.ZALO_DIGEST_TARGET_GROUP_NAME ?? process.env.ZALO_GROUP_NAME ?? 'Truyền thông Yok Đôn',
    botAliases: (process.env.ZALO_BOT_ALIASES ?? 'lâm,lam,nhân viên mới yok đôn,nhan vien moi yok don,hermes,zalo bot,bot')
      .split(',')
      .map(v => v.trim())
      .filter(Boolean),
  },
  hermes: {
    coreUrl: (process.env.HERMES_CORE_URL ?? '').replace(/\/+$/, ''),
    timeoutMs: Number(process.env.HERMES_CORE_TIMEOUT_MS ?? 8000),
    publish: {
      pythonBin: process.env.HERMES_PUBLISH_PYTHON ?? 'python3',
      scriptPath: process.env.HERMES_PUBLISH_SCRIPT_PATH ?? '/srv/yokdon-telegram/hermes/shared-tools/publish_sheet_row.py',
      home: process.env.HERMES_PUBLISH_HOME ?? '/srv/yokdon-telegram/hermes/fb-publisher',
      googleServiceAccountFile: process.env.HERMES_PUBLISH_GOOGLE_SERVICE_ACCOUNT_FILE
        ?? '/srv/yokdon-telegram/hermes/fb-publisher/google_key.json',
      sheetId: process.env.HERMES_PUBLISH_SHEET_ID ?? process.env.QUOC01_CONTENT_SHEET_ID,
      timeoutMs: Number(process.env.HERMES_PUBLISH_TIMEOUT_MS ?? 240000),
    },
    sheetWrite: {
      pythonBin: process.env.HERMES_SHEET_WRITE_PYTHON ?? process.env.HERMES_PUBLISH_PYTHON ?? 'python3',
      scriptPath: process.env.HERMES_SHEET_WRITE_SCRIPT_PATH ?? 'scripts/sheet_write_draft.py',
      home: process.env.HERMES_SHEET_WRITE_HOME ?? '/srv/yokdon-telegram/hermes/quoc01',
      googleServiceAccountFile: process.env.HERMES_SHEET_WRITE_GOOGLE_SERVICE_ACCOUNT_FILE
        ?? '/srv/yokdon-telegram/hermes/quoc01/google_key.json',
      sheetId: process.env.HERMES_SHEET_WRITE_DEFAULT_SHEET_ID
        ?? process.env.QUOC01_CONTENT_SHEET_ID
        ?? process.env.HERMES_PUBLISH_SHEET_ID,
      timeoutMs: Number(process.env.HERMES_SHEET_WRITE_TIMEOUT_MS ?? 120000),
    },
  },
  dataDir: process.env.DATA_DIR ?? './data',
} as const;
