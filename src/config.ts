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
    botAliases: (process.env.ZALO_BOT_ALIASES ?? 'hermes,zalo bot,bot')
      .split(',')
      .map(v => v.trim())
      .filter(Boolean),
  },
  hermes: {
    coreUrl: (process.env.HERMES_CORE_URL ?? '').replace(/\/+$/, ''),
    timeoutMs: Number(process.env.HERMES_CORE_TIMEOUT_MS ?? 8000),
  },
  dataDir: process.env.DATA_DIR ?? './data',
} as const;
