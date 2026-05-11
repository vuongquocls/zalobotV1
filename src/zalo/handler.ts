import { ThreadType } from 'zca-js';
import { createReadStream } from 'fs';
import { readFile, stat } from 'fs/promises';
import path from 'path';
import QRCode from 'qrcode';
import { randomUUID } from 'crypto';

import type { ZaloAPI, ZaloMessage, ZaloMediaContent, ZaloGroupInfoResponse } from './types.js';
import { ZALO_MSG_TYPES } from './types.js';
import { store } from '../store.js';
import { tgBot } from '../telegram/bot.js';
import { config } from '../config.js';
import { downloadToTemp, cleanTemp } from '../utils/media.js';
import { applyMentionsHtml, formatGroupMsgHtml, formatGroupMsg, groupCaption, topicName, truncate, escapeHtml } from '../utils/format.js';
import { msgStore, userCache, pollStore, sentMsgStore, zaloAlbumStore, type ZaloQuoteData } from '../store.js';
import { decideWithHermes } from '../hermes/connector.js';
import { shouldRouteZaloTextToHermes } from '../hermes/routing.js';
import { hermesApprovalStore } from '../hermes/approvalStore.js';
import { formatHermesAuditLog } from '../hermes/format.js';
import { sendHermesApprovalRequest } from '../hermes/approvalDelivery.js';
import type { HermesDecision, HermesZaloSourceFile } from '../hermes/types.js';
import { formatVietnamDateTime, isReminderCapabilityQuestion, parseReminderRequest } from '../reminders/parser.js';
import { startZaloReminderScheduler } from '../reminders/scheduler.js';
import { reminderStore } from '../reminders/store.js';

let telegramForumUnavailable = false;

// ── Bank card HTML parser ────────────────────────────────────────────────────
interface BankCardInfo {
  bankName: string;
  accountNumber: string;
  holderName?: string;
  vietqr: string;
}

function parseBankCardHtml(html: string): BankCardInfo | null {
  const ptags = [...html.matchAll(/<p[^>]*>([^<]+)<\/p>/g)]
    .map(m => m[1].trim()).filter(t => t.length > 0);

  const normalised = html.replace(/&amp;/g, '&');
  const contentMatch = normalised.match(/content=([^&"< ]+)/);
  if (!contentMatch) return null;
  const vietqr = decodeURIComponent(contentMatch[1]);

  // p-tag order from Zalo HTML: [BIN, BankName, AccountNumber, HolderName?, ...]
  const numericTags = ptags.filter(t => /^\d+$/.test(t));
  const textTags    = ptags.filter(t => !/^\d+$/.test(t));

  const accountNumber = numericTags.find(t => t.length !== 6) ?? numericTags[1] ?? numericTags[0] ?? '';
  const bankName      = textTags[0] ?? '';
  const holderName    = textTags[1]?.trim() || undefined;

  if (!vietqr) return null;
  return { bankName, accountNumber, holderName, vietqr };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Fetch group member list and populate `userCache` so mention resolution works
 * immediately even before any group message is received.
 */
async function populateGroupMemberCache(api: ZaloAPI, groupId: string): Promise<void> {
  try {
    const info = await api.getGroupInfo(groupId) as {
      gridInfoMap?: Record<string, {
        memVerList?: string[];
        totalMember?: number;
      }>;
    };
    const groupData = info?.gridInfoMap?.[groupId];
    if (!groupData) {
      console.warn(`[Zalo] getGroupInfo: no data for group ${groupId}`);
      return;
    }

    // memVerList entries are "uid_version" — extract UIDs
    const uids = (groupData.memVerList ?? [])
      .map(s => s.split('_')[0])
      .filter(Boolean);
    if (uids.length === 0) {
      console.warn(`[Zalo] group ${groupId}: empty memVerList (totalMember=${groupData.totalMember})`);
      return;
    }

    // Batch-fetch display names (getUserInfo accepts up to ~50 per call)
    const BATCH = 50;
    let saved = 0;
    for (let i = 0; i < uids.length; i += BATCH) {
      const batch = uids.slice(i, i + BATCH);
      const resp = await api.getUserInfo(batch) as {
        changed_profiles?: Record<string, { displayName?: string; zaloName?: string }>;
        unchanged_profiles?: Record<string, unknown>;
      };
      const profiles = resp?.changed_profiles ?? {};
      // unchanged_profiles also has profile data
      const unchanged = resp?.unchanged_profiles ?? {};
      for (const uid of batch) {
        const p = (profiles[uid] ?? unchanged[uid]) as { displayName?: string; zaloName?: string } | undefined;
        const name = p?.displayName?.trim() || p?.zaloName?.trim();
        if (uid && name) { userCache.save(uid, name); saved++; }
      }
    }
    console.log(`[Zalo] Cached ${saved}/${uids.length} members for group ${groupId}`);
  } catch (err) {
    console.warn(`[Zalo] populateGroupMemberCache failed for ${groupId}:`, err);
  }
}

async function getOrCreateTopic(
  zaloId: string,
  type: 0 | 1,
  displayName: string,
  avatarUrl?: string,
): Promise<number | undefined> {
  if (telegramForumUnavailable) return undefined;

  const existing = store.getTopicByZalo(zaloId, type);
  if (existing !== undefined) return existing;

  const name  = topicName(displayName, type);
  const color = type === ThreadType.Group ? 0xFF93B2 : 0x6FB9F0;

  let topic: Awaited<ReturnType<typeof tgBot.telegram.createForumTopic>>;
  try {
    topic = await tgBot.telegram.createForumTopic(
      config.telegram.groupId,
      name,
      { icon_color: color },
    );
  } catch (err) {
    const description = (err as { response?: { description?: string } }).response?.description
      ?? (err instanceof Error ? err.message : '');
    if (description.includes('chat is not a forum')) {
      telegramForumUnavailable = true;
      console.warn('[Zalo→TG] Telegram group is not a forum; forwarding to the main chat. Reply to bridged messages to send back to Zalo.');
      return undefined;
    }
    throw err;
  }

  const topicId = topic.message_thread_id;
  store.set({ topicId, zaloId, type, name: displayName });
  console.log(`[Zalo→TG] New topic: "${name}" (topicId=${topicId})`);

  // Pin group avatar as the first message in the topic
  if (type === 1 /* Group */ && avatarUrl) {
    try {
      const localPath = await downloadToTemp(avatarUrl, `avatar_${Date.now()}.jpg`);
      const stream = createReadStream(localPath);
      const avatarMsg = await tgBot.telegram.sendPhoto(
        config.telegram.groupId,
        { source: stream },
        {
          message_thread_id: topicId,
          caption: `🖼 Ảnh đại diện nhóm <b>${escapeHtml(displayName)}</b>`,
          parse_mode: 'HTML',
        },
      );
      await cleanTemp(localPath);
      try {
        await tgBot.telegram.pinChatMessage(config.telegram.groupId, avatarMsg.message_id, { disable_notification: true });
      } catch { /* pinning requires admin rights */ }
    } catch (avatarErr) {
      console.warn(`[Zalo→TG] Failed to pin group avatar for ${displayName}:`, avatarErr);
    }
  }

  return topicId;
}

/**
 * Parse `content` field which is either a JSON string, a plain string, or
 * already an object. Returns a normalised `ZaloMediaContent` object.
 */
function parseContent(raw: string | ZaloMediaContent | Record<string, unknown>): {
  text: string | null;
  media: ZaloMediaContent;
} {
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw) as ZaloMediaContent;
      return { text: null, media: parsed };
    } catch {
      // plain text string
      return { text: raw, media: {} };
    }
  }
  return { text: null, media: raw as ZaloMediaContent };
}

// ── Poll helpers ─────────────────────────────────────────────────────────────

import type { PollOptions } from 'zca-js';

function buildScoreText(header: string, options: Pick<PollOptions, 'content' | 'votes'>[], closed: boolean): string {
  const total = options.reduce((s, o) => s + (o.votes ?? 0), 0);
  const lines = options.map(o => {
    const pct = total > 0 ? Math.round((o.votes / total) * 100) : 0;
    const bar = '█'.repeat(Math.round(pct / 10)) + '░'.repeat(10 - Math.round(pct / 10));
    return `${escapeHtml(o.content)}\n  ${bar} ${o.votes} phiếu (${pct}%)`;
  });
  const status = closed ? ' <i>[Đã đóng]</i>' : '';
  return `📊 <b>${escapeHtml(header)}</b>${status}\n\nTổng: ${total} phiếu\n\n${lines.join('\n\n')}`;
}

// ── Main handler ─────────────────────────────────────────────────────────────

/** Track which groups already had their member cache populated this session. */
const _memberCacheLoaded = new Set<string>();
const RECENT_LINK_TTL_MS = 30 * 60 * 1000;
const RECENT_FILE_TTL_MS = 30 * 60 * 1000;
const MAX_HERMES_FILE_BYTES = Number(process.env.HERMES_SOURCE_FILE_MAX_BYTES ?? 2 * 1024 * 1024);
const recentZaloLinks = new Map<string, { url: string; title?: string; createdAt: number }>();
const recentZaloFiles = new Map<string, { file: HermesZaloSourceFile; createdAt: number }>();

function saveRecentZaloLink(zaloId: string, url: string, title?: string): void {
  recentZaloLinks.set(zaloId, { url, title, createdAt: Date.now() });
}

function withRecentZaloLinkContext(zaloId: string, body: string): string {
  if (/https?:\/\//i.test(body)) return body;
  const recent = recentZaloLinks.get(zaloId);
  if (!recent) return body;
  if (Date.now() - recent.createdAt > RECENT_LINK_TTL_MS) {
    recentZaloLinks.delete(zaloId);
    return body;
  }
  return [
    body,
    '',
    '[Ngữ cảnh link Zalo vừa gửi trước đó]',
    `URL: ${recent.url}`,
    recent.title ? `Tiêu đề: ${recent.title}` : '',
  ].filter(Boolean).join('\n');
}

function guessMimeType(fileName: string): string | undefined {
  const ext = path.extname(fileName).toLowerCase();
  const mimes: Record<string, string> = {
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.csv': 'text/csv',
    '.txt': 'text/plain',
    '.json': 'application/json',
    '.pdf': 'application/pdf',
    '.xls': 'application/vnd.ms-excel',
    '.doc': 'application/msword',
  };
  return mimes[ext];
}

async function buildHermesSourceFile(localPath: string, fileName: string): Promise<HermesZaloSourceFile | null> {
  const info = await stat(localPath);
  if (info.size > MAX_HERMES_FILE_BYTES) {
    console.warn(`[Hermes] Source file too large for inline reading: ${fileName} (${info.size} bytes)`);
    return null;
  }
  const data = await readFile(localPath);
  return {
    name: fileName,
    mimeType: guessMimeType(fileName),
    contentBase64: data.toString('base64'),
  };
}

function saveRecentZaloFile(zaloId: string, file: HermesZaloSourceFile): void {
  recentZaloFiles.set(zaloId, { file, createdAt: Date.now() });
}

function getRecentZaloFiles(zaloId: string): HermesZaloSourceFile[] | undefined {
  const recent = recentZaloFiles.get(zaloId);
  if (!recent) return undefined;
  if (Date.now() - recent.createdAt > RECENT_FILE_TTL_MS) {
    recentZaloFiles.delete(zaloId);
    return undefined;
  }
  return [recent.file];
}

async function sendHermesDecisionToZalo(
  api: ZaloAPI,
  decision: HermesDecision,
  context: {
    requestId: string;
    zaloId: string;
    type: 0 | 1;
    displayName: string;
    senderId: string;
    senderName: string;
    originalText: string;
  },
): Promise<boolean> {
  if (decision.decision === 'auto_reply' && decision.replyText?.trim()) {
    const zaloThreadType = context.type === ThreadType.Group ? ThreadType.Group : ThreadType.User;
    await api.sendMessage({ msg: decision.replyText.trim() }, context.zaloId, zaloThreadType);
    console.log(`[Hermes] auto_reply sent to Zalo requestId=${decision.requestId ?? context.requestId}`);
    await tgBot.telegram.sendMessage(
      config.telegram.approvalGroupId,
      formatHermesAuditLog(
        '🧠 Hermes đã tự trả lời Zalo',
        `Nơi nhận: ${context.displayName}\nNgười hỏi: ${context.senderName}\nTin hỏi: ${context.originalText}\n\nTrả lời:\n${decision.replyText.trim()}`,
      ),
      { parse_mode: 'HTML' },
    ).catch(() => undefined);
    return true;
  }

  if (decision.decision === 'needs_approval' && decision.replyText?.trim()) {
    const approvalId = `ha_${randomUUID().replace(/-/g, '').slice(0, 10)}`;
    const approval = {
      approvalId,
      requestId: decision.requestId ?? context.requestId,
      zaloId: context.zaloId,
      threadType: context.type,
      chatName: context.displayName,
      senderId: context.senderId,
      senderName: context.senderName,
      originalText: context.originalText,
      replyText: decision.replyText.trim(),
      reason: decision.reason ?? decision.approvalPrompt,
      createdAt: new Date().toISOString(),
    };
    hermesApprovalStore.save(approval);
    try {
      const sent = await sendHermesApprovalRequest(approval);
      hermesApprovalStore.save({ ...approval, telegramMessageId: sent.messageId });
      console.log(`[Hermes] approval requested approvalId=${approvalId} requestId=${approval.requestId} chatId=${sent.chatId}`);
      return true;
    } catch (approvalErr) {
      hermesApprovalStore.remove(approvalId);
      console.warn('[Hermes] Failed to send approval request:', approvalErr);
      if (context.type === ThreadType.User) {
        await api.sendMessage(
          { msg: 'Em đã nhận tin này, nhưng nội dung cần anh Quốc duyệt và kênh duyệt Telegram đang lỗi. Em đã ghi nhận để xử lý lại.' },
          context.zaloId,
          ThreadType.User,
        );
        return true;
      }
    }
  }

  if (decision.decision === 'ignore') {
    console.log(`[Hermes] ignored Zalo message requestId=${decision.requestId ?? context.requestId}`);
    return true;
  }

  return false;
}

export function setupZaloHandler(api: ZaloAPI): void {
  startZaloReminderScheduler(api);

  // Pre-populate userCache for all existing group topics on startup
  for (const entry of store.all()) {
    if (entry.type === 1 /* Group */) {
      void populateGroupMemberCache(api, entry.zaloId);
      _memberCacheLoaded.add(entry.zaloId);
    }
  }

  api.listener.on('message', async (msg: ZaloMessage) => {
    try {
      if (msg.isSelf) return;

      const zaloId     = msg.threadId;
      const type       = msg.type as 0 | 1;
      const senderName = msg.data.dName ?? msg.data.uidFrom;
      const msgType    = msg.data.msgType ?? ZALO_MSG_TYPES.TEXT;

      // Pre-populate member cache the first time we see a new group
      if (type === 1 && !_memberCacheLoaded.has(zaloId)) {
        _memberCacheLoaded.add(zaloId);
        void populateGroupMemberCache(api, zaloId);
      }

      // Keep userCache up-to-date so TG→Zalo mention resolution works
      userCache.save(msg.data.uidFrom, senderName);

      // Resolve group name
      let displayName = senderName;
      let groupAvatarUrl: string | undefined;
      if (type === ThreadType.Group) {
        try {
          const info = await api.getGroupInfo(zaloId) as ZaloGroupInfoResponse;
          displayName = info?.gridInfoMap?.[zaloId]?.name ?? senderName;
          groupAvatarUrl = info?.gridInfoMap?.[zaloId]?.avt;
        } catch { /* non-fatal */ }
      }

      // Build quote data + mapping helper — saved after every successful TG send
      const zaloMsgIds = msg.data.realMsgId && msg.data.realMsgId !== msg.data.msgId
        ? [msg.data.msgId, msg.data.realMsgId]
        : [msg.data.msgId];
      const zaloQuoteData: ZaloQuoteData = {
        msgId:    msg.data.msgId,
        cliMsgId: msg.data.cliMsgId ?? '',
        uidFrom:  msg.data.uidFrom,
        ts:       msg.data.ts,
        msgType:  msgType,
        content:  msg.data.content as string | Record<string, unknown>,
        ttl:      msg.data.ttl ?? 0,
        zaloId,
        threadType: type,
      };

      const { text, media } = parseContent(msg.data.content);

      let bridgeContext: {
        topicId: number | undefined;
        tgBase: {
          message_thread_id?: number;
          reply_parameters?: { message_id: number; allow_sending_without_reply: boolean };
        };
        tgOpts: {
          parse_mode: 'HTML';
          caption?: string;
          message_thread_id?: number;
          reply_parameters?: { message_id: number; allow_sending_without_reply: boolean };
        };
        saveTgMapping: (sent: { message_id: number }) => void;
      } | null = null;

      const getBridgeContext = async () => {
        if (bridgeContext) return bridgeContext;

        const topicId = await getOrCreateTopic(zaloId, type, displayName, groupAvatarUrl);

        let tgReplyMsgId: number | undefined;
        if (msg.data.quote) {
          const globalId = String(msg.data.quote.globalMsgId);
          // Primary: messages received from Zalo and forwarded to TG
          // Fallback: messages we sent from TG to Zalo (reverse lookup)
          tgReplyMsgId = msgStore.getTgMsgId(globalId) ?? sentMsgStore.getByZaloMsgId(globalId);
        }

        const tgBase: {
          message_thread_id?: number;
          reply_parameters?: { message_id: number; allow_sending_without_reply: boolean };
        } = {};
        if (topicId !== undefined) {
          tgBase.message_thread_id = topicId;
        }
        if (tgReplyMsgId !== undefined) {
          tgBase.reply_parameters = { message_id: tgReplyMsgId, allow_sending_without_reply: true };
        }

        const caption = type === ThreadType.Group ? groupCaption(senderName) : undefined;
        const tgOpts = { ...tgBase, parse_mode: 'HTML' as const, caption };
        const saveTgMapping = (sent: { message_id: number }) => {
          msgStore.save(sent.message_id, zaloMsgIds, zaloQuoteData);
        };

        bridgeContext = { topicId, tgBase, tgOpts, saveTgMapping };
        return bridgeContext;
      };

      // ── 1. Plain text ──────────────────────────────────────────────────────
      if (msgType === ZALO_MSG_TYPES.TEXT || (text !== null)) {
        const body = text ?? (typeof msg.data.content === 'string' ? msg.data.content : '');
        if (!body.trim()) return;

        const hermesRoute = shouldRouteZaloTextToHermes(body, type);
        console.log(`[Hermes] route_check type=${type} route=${hermesRoute.route} alias=${hermesRoute.invokedByAlias} sender="${senderName}" chat="${displayName}" text="${truncate(body, 120)}"`);
        if (hermesRoute.route) {
          if (isReminderCapabilityQuestion(body)) {
            await api.sendMessage(
              {
                msg: [
                  'Có anh. Anh có thể nhắn kiểu: "Em nhắc anh sáng mai đi chạy bộ vào lúc 05:00".',
                  'Em sẽ lưu lịch và tự gửi tin nhắc lại đúng giờ Việt Nam, kể cả bot có restart giữa chừng.',
                ].join('\n'),
              },
              zaloId,
              type === ThreadType.Group ? ThreadType.Group : ThreadType.User,
            );
            return;
          }

          const reminder = parseReminderRequest(body);
          if (reminder) {
            const reminderId = `zr_${randomUUID().replace(/-/g, '').slice(0, 12)}`;
            reminderStore.add({
              id: reminderId,
              zaloId,
              threadType: type,
              chatName: displayName,
              senderId: msg.data.uidFrom,
              senderName,
              text: reminder.text,
              remindAtIso: reminder.remindAt.toISOString(),
              createdAtIso: new Date().toISOString(),
              status: 'pending',
              attempts: 0,
            });
            await api.sendMessage(
              {
                msg: [
                  `✅ Em đã đặt lịch nhắc: ${reminder.text}`,
                  `Thời gian: ${formatVietnamDateTime(reminder.remindAt)} (giờ Việt Nam).`,
                ].join('\n'),
              },
              zaloId,
              type === ThreadType.Group ? ThreadType.Group : ThreadType.User,
            );
            await tgBot.telegram.sendMessage(
              config.telegram.approvalGroupId,
              formatHermesAuditLog(
                '⏰ Zalo đã đặt lịch nhắc',
                `Mã: ${reminderId}\nNơi nhận: ${displayName}\nNgười đặt: ${senderName}\nNội dung: ${reminder.text}\nThời gian: ${formatVietnamDateTime(reminder.remindAt)} (giờ Việt Nam)`,
              ),
              { parse_mode: 'HTML' },
            ).catch(() => undefined);
            return;
          }

          const hermesBody = withRecentZaloLinkContext(zaloId, body);
          const sourceFiles = getRecentZaloFiles(zaloId);
          const requestId = `zalo_${randomUUID().replace(/-/g, '').slice(0, 12)}`;
          let decision: Awaited<ReturnType<typeof decideWithHermes>>;
          try {
            decision = await decideWithHermes({
              requestId,
              channel: 'zalo',
              chat: { id: zaloId, type, name: displayName },
              sender: { id: msg.data.uidFrom, name: senderName },
              message: {
                text: hermesBody,
                msgId: msg.data.msgId,
                timestamp: msg.data.ts,
              },
              routing: {
                isDirectChat: type === ThreadType.User,
                invokedByAlias: hermesRoute.invokedByAlias,
              },
              sourceFiles,
            });
          } catch (hermesErr) {
            console.error(`[Hermes] decision failed requestId=${requestId}:`, hermesErr);
            if (type === ThreadType.User) {
              await api.sendMessage(
                { msg: 'Em đã nhận tin nhưng đang lỗi kết nối Hermes. Anh thử nhắn lại giúp em sau ít phút nhé.' },
                zaloId,
                ThreadType.User,
              );
              return;
            }
            throw hermesErr;
          }

          const handled = await sendHermesDecisionToZalo(api, decision, {
            requestId,
            zaloId,
            type,
            displayName,
            senderId: msg.data.uidFrom,
            senderName,
            originalText: sourceFiles?.length
              ? `${hermesBody}\n\n[Đính kèm gần nhất: ${sourceFiles.map(file => file.name).join(', ')}]`
              : hermesBody,
          });
          if (handled) {
            return;
          }
        }

        const { tgBase, saveTgMapping } = await getBridgeContext();
        const mentions = msg.data.mentions;
        const bodyHtml = mentions?.length
          ? applyMentionsHtml(truncate(body), mentions)
          : escapeHtml(truncate(body));
        const tgText = type === ThreadType.Group
          ? formatGroupMsgHtml(senderName, bodyHtml)
          : bodyHtml;
        const sent = await tgBot.telegram.sendMessage(
          config.telegram.groupId,
          tgText,
          { ...tgBase, parse_mode: 'HTML' },
        );
        saveTgMapping(sent);
        return;
      }

      // ── 2. Photo / Image ───────────────────────────────────────────────────
      if (msgType === ZALO_MSG_TYPES.PHOTO) {
        const { topicId, tgBase } = await getBridgeContext();
        // prefer HD from params, fall back to href
        let url = media.href;
        if (media.params) {
          try {
            const p = JSON.parse(media.params) as { hd?: string };
            if (p.hd) url = p.hd;
          } catch { /* ignore */ }
        }
        if (!url) { console.warn('[ZaloHandler] Photo: no URL found in content:', media); return; }

        // Caption attached to the photo by the sender (Zalo stores it in description)
        const photoCaption = media.description?.trim() || undefined;

        const childnumber: number = (media as { childnumber?: number }).childnumber ?? 0;
        const albumKey = `${zaloId}:${msg.data.uidFrom}`;

        // If childnumber > 0 OR there's already a buffer for this key → album mode
        const hasBuffer = (typeof zaloAlbumStore as unknown as { _has?: (k: string) => boolean })._has?.(albumKey);
        void hasBuffer; // unused, we detect via the add callback

        zaloAlbumStore.add(
          albumKey,
          url,
          zaloMsgIds[0],
          { senderName, topicId, tgBase, zaloQuote: zaloQuoteData },
          async (buf) => {
            if (buf.urls.length === 1) {
              // Single photo — send normally
              const singleUrl = buf.urls[0]!;
              const localPath = await downloadToTemp(singleUrl, `photo_${Date.now()}.jpg`);
              const stream = createReadStream(localPath);
              try {
                const sent = await tgBot.telegram.sendPhoto(
                  config.telegram.groupId,
                  { source: stream },
                  {
                    ...buf.tgBase,
                    parse_mode: 'HTML' as const,
                    caption: type === ThreadType.Group
                      ? photoCaption
                        ? `${groupCaption(buf.senderName)}
${escapeHtml(photoCaption)}`
                        : groupCaption(buf.senderName)
                      : photoCaption ? escapeHtml(photoCaption) : undefined,
                  },
                );
                msgStore.save(sent.message_id, buf.zaloMsgIds, {
                  msgId: buf.zaloMsgIds[0]!,
                  cliMsgId: '',
                  uidFrom: msg.data.uidFrom,
                  ts: msg.data.ts,
                  msgType,
                  content: msg.data.content as string | Record<string, unknown>,
                  ttl: msg.data.ttl ?? 0,
                  zaloId,
                  threadType: type,
                });
              } finally { await cleanTemp(localPath); }
            } else {
              // Multi-photo album — download all and send as media group
              const localPaths: string[] = [];
              try {
                for (const u of buf.urls) {
                  localPaths.push(await downloadToTemp(u, `photo_${Date.now()}.jpg`));
                }
                const captionText = type === ThreadType.Group
                  ? photoCaption
                    ? `${groupCaption(buf.senderName)}
${escapeHtml(photoCaption)}`
                    : groupCaption(buf.senderName)
                  : photoCaption ? escapeHtml(photoCaption) : undefined;
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                const mediaItems: any[] = localPaths.map((lp, i) => ({
                  type: 'photo',
                  media: { source: createReadStream(lp) },
                  ...(i === 0 && captionText ? { caption: captionText, parse_mode: 'HTML' } : {}),
                }));
                const sentMsgs = await tgBot.telegram.sendMediaGroup(
                  config.telegram.groupId,
                  mediaItems,
                  (buf.topicId !== undefined ? { message_thread_id: buf.topicId } : {}) as Parameters<typeof tgBot.telegram.sendMediaGroup>[2],
                );
                // Save mapping for first photo (for reply chain)
                if (sentMsgs.length > 0) {
                  msgStore.save(sentMsgs[0]!.message_id, buf.zaloMsgIds, {
                    msgId: buf.zaloMsgIds[0]!,
                    cliMsgId: '',
                    uidFrom: msg.data.uidFrom,
                    ts: msg.data.ts,
                    msgType,
                    content: msg.data.content as string | Record<string, unknown>,
                    ttl: msg.data.ttl ?? 0,
                    zaloId,
                    threadType: type,
                  });
                }
              } finally {
                for (const lp of localPaths) await cleanTemp(lp);
              }
            }
          },
        );

        // Peek: if childnumber === 0 and no existing buffer, timer fires immediately
        // (actually always deferred 600ms — that's fine)
        return;
      }

      // ── 2b. Doodle (sketch/drawing) ────────────────────────────────────────
      if (msgType === ZALO_MSG_TYPES.DOODLE) {
        const { tgOpts, saveTgMapping } = await getBridgeContext();
        const url = media.href || media.thumb;
        if (!url) { console.warn('[ZaloHandler] Doodle: no URL'); return; }
        const localPath = await downloadToTemp(url, `doodle_${Date.now()}.jpg`);
        const stream = createReadStream(localPath);
        try {
          const sent = await tgBot.telegram.sendPhoto(config.telegram.groupId, { source: stream }, tgOpts);
          saveTgMapping(sent);
        } finally { await cleanTemp(localPath); }
        return;
      }


      if (msgType === ZALO_MSG_TYPES.GIF) {
        const { tgOpts, saveTgMapping } = await getBridgeContext();
        const url = media.href;
        if (!url) {
          console.warn('[ZaloHandler] GIF: no URL found in content:', media);
          return;
        }
        const ext = path.extname(url.split('?')[0] ?? '').toLowerCase() || '.mp4';
        const localPath = await downloadToTemp(url, `gif_${Date.now()}${ext}`);
        const stream = createReadStream(localPath);
        try {
          const sent = await tgBot.telegram.sendAnimation(
            config.telegram.groupId,
            { source: stream },
            tgOpts,
          );
          saveTgMapping(sent);
        } finally { await cleanTemp(localPath); }
        return;
      }

      // ── 4. File ────────────────────────────────────────────────────────────
      if (msgType === ZALO_MSG_TYPES.FILE) {
        const url = media.href;
        // title holds the original filename (e.g. "report.pdf")
        const fileName = media.title ?? `file_${Date.now()}`;
        if (!url) {
          console.warn('[ZaloHandler] File: no URL found in content:', media);
          return;
        }
        const localPath = await downloadToTemp(url, fileName);
        try {
          if (type === ThreadType.User) {
            const sourceFile = await buildHermesSourceFile(localPath, fileName);
            if (sourceFile) {
              saveRecentZaloFile(zaloId, sourceFile);
              const requestId = `zalo_${randomUUID().replace(/-/g, '').slice(0, 12)}`;
              const prompt = [
                `Anh Quốc vừa gửi file "${fileName}" qua Zalo.`,
                'Hãy đọc nội dung file và trả lời đúng yêu cầu nếu người dùng có kèm chỉ dẫn.',
                media.description ? `Ghi chú Zalo: ${media.description}` : '',
              ].filter(Boolean).join('\n');
              const decision = await decideWithHermes({
                requestId,
                channel: 'zalo',
                chat: { id: zaloId, type, name: displayName },
                sender: { id: msg.data.uidFrom, name: senderName },
                message: {
                  text: prompt,
                  msgId: msg.data.msgId,
                  timestamp: msg.data.ts,
                },
                routing: {
                  isDirectChat: true,
                  invokedByAlias: true,
                },
                sourceFiles: [sourceFile],
              });
              const handled = await sendHermesDecisionToZalo(api, decision, {
                requestId,
                zaloId,
                type,
                displayName,
                senderId: msg.data.uidFrom,
                senderName,
                originalText: `[File] ${fileName}`,
              });
              if (handled) return;
            } else {
              await api.sendMessage(
                { msg: `Em đã nhận file "${fileName}", nhưng file hơi lớn nên chưa đọc trực tiếp được. Anh gửi file nhỏ hơn hoặc copy phần cần xem vào đây giúp em nhé.` },
                zaloId,
                ThreadType.User,
              );
              return;
            }
          }

          const { tgOpts, saveTgMapping } = await getBridgeContext();
          const stream = createReadStream(localPath);
          const sent = await tgBot.telegram.sendDocument(
            config.telegram.groupId,
            { source: stream, filename: fileName },
            tgOpts,
          );
          saveTgMapping(sent);
        } finally { await cleanTemp(localPath); }
        return;
      }

      // ── 5. Video ───────────────────────────────────────────────────────────
      if (msgType === ZALO_MSG_TYPES.VIDEO) {
        const { tgOpts, saveTgMapping } = await getBridgeContext();
        const url = media.href;
        if (!url) { console.warn('[ZaloHandler] Video: no URL found in content:', media); return; }
        const localPath = await downloadToTemp(url, `video_${Date.now()}.mp4`);
        const stream = createReadStream(localPath);
        try {
          const sent = await tgBot.telegram.sendVideo(config.telegram.groupId, { source: stream }, tgOpts);
          saveTgMapping(sent);
        } finally { await cleanTemp(localPath); }
        return;
      }

      // ── 6. Voice ───────────────────────────────────────────────────────────
      if (msgType === ZALO_MSG_TYPES.VOICE) {
        const { tgOpts, saveTgMapping } = await getBridgeContext();
        const url = media.href;
        if (!url) { console.warn('[ZaloHandler] Voice: no URL found in content:', media); return; }
        const ext = path.extname(url.split('?')[0] ?? '').toLowerCase() || '.m4a';
        const localPath = await downloadToTemp(url, `voice_${Date.now()}${ext}`);
        const stream = createReadStream(localPath);
        try {
          const sent = await tgBot.telegram.sendVoice(config.telegram.groupId, { source: stream }, tgOpts);
          saveTgMapping(sent);
        } finally { await cleanTemp(localPath); }
        return;
      }

      // ── 7. Sticker – fetch real URL via getStickersDetail ──────────────────
      if (msgType === ZALO_MSG_TYPES.STICKER) {
        const { tgBase, tgOpts, saveTgMapping } = await getBridgeContext();
        const stickerId = media.id;
        if (!stickerId) {
          console.warn('[ZaloHandler] Sticker: no id in content:', media);
          return;
        }
        try {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const details: any[] = await api.getStickersDetail([stickerId]);
          const detail = details?.[0];
          const url: string | undefined =
            detail?.stickerWebpUrl ?? detail?.stickerUrl ?? detail?.stickerSpriteUrl;
          if (!url) {
            console.warn('[ZaloHandler] Sticker: no URL in detail:', detail);
            return;
          }
          const ext = path.extname(url.split('?')[0] ?? '').toLowerCase() || '.webp';
          const localPath = await downloadToTemp(url, `sticker_${Date.now()}${ext}`);
          try {
            let sent: { message_id: number };
            try {
              // Try native TG sticker (webp ≤512 KB displays as a proper sticker)
              const stream = createReadStream(localPath);
              sent = await tgBot.telegram.sendSticker(
                config.telegram.groupId,
                { source: stream },
                tgBase as Parameters<typeof tgBot.telegram.sendSticker>[2],
              );
            } catch {
              // Fall back to photo if file is too large or format unsupported
              const stream = createReadStream(localPath);
              sent = await tgBot.telegram.sendPhoto(config.telegram.groupId, { source: stream }, tgOpts);
            }
            saveTgMapping(sent);
          } finally { await cleanTemp(localPath); }
        } catch (stickerErr) {
          console.error('[ZaloHandler] Sticker fetch error:', stickerErr);
        }
        return;
      }

      // ── 8. Link ────────────────────────────────────────────────────────────
      if (msgType === ZALO_MSG_TYPES.LINK) {
        const href  = media.href;
        const title = media.title ?? href;
        if (!href) return;
        saveRecentZaloLink(zaloId, href, title);

        if (type === ThreadType.User) {
          const body = [
            'Anh Quốc vừa gửi một link Zalo:',
            `URL: ${href}`,
            title ? `Tiêu đề: ${title}` : '',
            media.description ? `Mô tả: ${media.description}` : '',
            'Hãy đọc nội dung công khai từ link này nếu truy cập được, rồi phản hồi ngắn gọn là em đọc được gì.',
          ].filter(Boolean).join('\n');
          const requestId = `zalo_${randomUUID().replace(/-/g, '').slice(0, 12)}`;
          try {
            const decision = await decideWithHermes({
              requestId,
              channel: 'zalo',
              chat: { id: zaloId, type, name: displayName },
              sender: { id: msg.data.uidFrom, name: senderName },
              message: {
                text: body,
                msgId: msg.data.msgId,
                timestamp: msg.data.ts,
              },
              routing: { isDirectChat: true, invokedByAlias: true },
            });
            if (decision.decision === 'auto_reply' && decision.replyText?.trim()) {
              await api.sendMessage({ msg: decision.replyText.trim() }, zaloId, ThreadType.User);
              console.log(`[Hermes] link auto_reply sent to Zalo requestId=${decision.requestId ?? requestId}`);
              return;
            }
            if (decision.decision === 'needs_approval' && decision.replyText?.trim()) {
              const approvalId = `ha_${randomUUID().replace(/-/g, '').slice(0, 10)}`;
              const approval = {
                approvalId,
                requestId: decision.requestId ?? requestId,
                zaloId,
                threadType: type,
                chatName: displayName,
                senderId: msg.data.uidFrom,
                senderName,
                originalText: body,
                replyText: decision.replyText.trim(),
                reason: decision.reason ?? decision.approvalPrompt,
                createdAt: new Date().toISOString(),
              };
              hermesApprovalStore.save(approval);
              const sent = await sendHermesApprovalRequest(approval);
              hermesApprovalStore.save({ ...approval, telegramMessageId: sent.messageId });
              return;
            }
          } catch (hermesErr) {
            console.error(`[Hermes] link decision failed requestId=${requestId}:`, hermesErr);
            await api.sendMessage(
              { msg: 'Em đã nhận link nhưng đang lỗi khi đọc nội dung. Anh thử gửi lại hoặc nói rõ anh muốn em xem phần nào nhé.' },
              zaloId,
              ThreadType.User,
            );
            return;
          }
        }

        const { tgBase, saveTgMapping } = await getBridgeContext();
        const linkText = type === ThreadType.Group
          ? `${groupCaption(senderName)}\n<a href="${href}">${title}</a>`
          : `<a href="${href}">${title}</a>`;
        const sent = await tgBot.telegram.sendMessage(config.telegram.groupId, linkText, {
          ...tgBase,
          parse_mode: 'HTML',
          link_preview_options: { is_disabled: false },
        });
        saveTgMapping(sent);
        return;
      }

      // ── 9. Web content (Zalo instant: bank card, mini app, etc.) ──────────
      if (msgType === ZALO_MSG_TYPES.WEBCONTENT) {
        const { tgBase, saveTgMapping } = await getBridgeContext();
        // For bank cards: fetch HTML, parse data, send QR image + caption
        if (media.action === 'zinstant.bankcard' && media.params) {
          try {
            const parsedParams = JSON.parse(media.params) as {
              pcItem?: { data_url?: string };
              item?:   { data_url?: string };
            };
            const dataUrl = parsedParams.pcItem?.data_url ?? parsedParams.item?.data_url;
            if (dataUrl) {
              const htmlResp = await fetch(`${dataUrl}?data=html`);
              const html = await htmlResp.text();
              const info = parseBankCardHtml(html);
              if (info) {
                const qrBuf = await QRCode.toBuffer(info.vietqr, {
                  width: 300, margin: 2,
                  color: { dark: '#000000ff', light: '#ffffffff' },
                });
                let caption = `🏦 <b>Tài khoản ngân hàng</b>`;
                if (info.bankName)      caption += `\nNgân hàng: <b>${info.bankName}</b>`;
                if (info.accountNumber) caption += `\nSTK: <code>${info.accountNumber}</code>`;
                if (info.holderName)    caption += `\nChủ TK: <b>${info.holderName}</b>`;
                const fullCaption = type === ThreadType.Group
                  ? `${groupCaption(senderName)}\n${caption}`
                  : caption;
                const sent = await tgBot.telegram.sendPhoto(
                  config.telegram.groupId,
                  { source: qrBuf },
                  { ...tgBase, caption: fullCaption, parse_mode: 'HTML' },
                );
                saveTgMapping(sent);
                return;
              }
            }
          } catch (err) {
            console.error('[ZaloHandler] bankcard parse error:', err);
          }
        }

        // Generic webcontent fallback
        let label = media.title || '';
        try {
          if (media.params) {
            const p = JSON.parse(media.params) as {
              customMsg?: { msg?: { vi?: string; en?: string } };
            };
            const vi = p.customMsg?.msg?.vi;
            const en = p.customMsg?.msg?.en;
            if (vi && vi.trim()) label = vi.trim();
            else if (en && en.trim()) label = en.trim();
          }
        } catch { /* use fallback */ }
        if (!label) label = '[Nội dung web]';

        const ACTION_ICONS: Record<string, string> = {
          'zinstant.bankcard': '🏦',
          'zinstant.transfer': '💸',
          'zinstant.invoice':  '🧾',
          'zinstant.qr':       '📷',
        };
        const icon = ACTION_ICONS[media.action ?? ''] ?? '📋';
        const body = `${icon} ${label}`;
        const text = type === ThreadType.Group ? `${groupCaption(senderName)}\n${body}` : body;
        const sent = await tgBot.telegram.sendMessage(config.telegram.groupId, text, {
          ...tgBase,
          parse_mode: 'HTML',
        });
        saveTgMapping(sent);
        return;
      }

      // ── 10. Location ───────────────────────────────────────────────────────
      if (msgType === ZALO_MSG_TYPES.LOCATION) {
        const { tgBase, saveTgMapping } = await getBridgeContext();
        let lat: number | undefined;
        let lng: number | undefined;
        try {
          const p = JSON.parse(media.params ?? '{}') as { latitude?: number; longitude?: number };
          lat = p.latitude;
          lng = p.longitude;
        } catch { /* ignore */ }

        if (lat !== undefined && lng !== undefined) {
          // Send as native TG location — shows map preview with Maps button
          const sent = await tgBot.telegram.sendLocation(
            config.telegram.groupId,
            lat,
            lng,
            { ...tgBase } as Parameters<typeof tgBot.telegram.sendLocation>[3],
          );
          if (type === ThreadType.Group) {
            // Send sender name as a follow-up caption since sendLocation has no HTML caption
            await tgBot.telegram.sendMessage(
              config.telegram.groupId,
              `${groupCaption(senderName)}📍 Vị trí`,
              { ...tgBase, parse_mode: 'HTML' },
            );
          }
          saveTgMapping(sent);
        } else {
          // Fallback: Google Maps link
          const mapsUrl = media.href || '#';
          const body    = `📍 <a href="${mapsUrl}">Vị trí</a>`;
          const text    = type === ThreadType.Group ? `${groupCaption(senderName)}\n${body}` : body;
          const sent    = await tgBot.telegram.sendMessage(config.telegram.groupId, text, { ...tgBase, parse_mode: 'HTML' });
          saveTgMapping(sent);
        }
        return;
      }

      // ── 11. Poll ────────────────────────────────────────────────────────────
      if (msgType === ZALO_MSG_TYPES.POLL) {
        const { topicId, tgBase, saveTgMapping } = await getBridgeContext();
        let pollId: number | undefined;
        let question = '';
        let isAnonymous = false;
        let action = '';
        try {
          const p = JSON.parse(media.params ?? '{}') as {
            pollId?: number;
            question?: string;
            isAnonymous?: boolean;
            action?: string;
          };
          pollId      = p.pollId;
          question    = p.question ?? '';
          isAnonymous = p.isAnonymous ?? false;
          action      = media.action ?? '';
        } catch { /* ignore */ }

        console.log(`[ZaloHandler] Poll event: action="${action}" pollId=${pollId}`);

        if (!pollId) return;

        // Fetch full poll details (options + vote counts)
        let pollDetail: Awaited<ReturnType<typeof api.getPollDetail>> | undefined;
        try {
          pollDetail = await api.getPollDetail(pollId);
          console.log(`[ZaloHandler] Poll detail: num_vote=${pollDetail?.num_vote} options=`, pollDetail?.options?.map((o: { content: string; votes: number }) => `${o.content}=${o.votes}`).join(','));
        } catch (e) {
          console.warn('[ZaloHandler] getPollDetail failed:', e);
        }

        const existingEntry = pollStore.getByPollId(pollId);
        console.log(`[ZaloHandler] Poll existingEntry=${existingEntry ? 'found' : 'NOT found'}`);
        type ZaloPollOption = { option_id: number; content: string; votes: number; voted: boolean; voters: string[] };

        if (action === 'create' && !existingEntry) {
          const options: ZaloPollOption[] = pollDetail?.options ?? [];
          if (options.length < 2) {
            // Can't create TG poll with < 2 options, send as text
            const text = type === ThreadType.Group
              ? `${groupCaption(senderName)}📊 <b>${escapeHtml(question)}</b>\n<i>Cuộc bình chọn mới (${options.length} lựa chọn)</i>`
              : `📊 <b>${escapeHtml(question)}</b>`;
            const sent = await tgBot.telegram.sendMessage(config.telegram.groupId, text, { ...tgBase, parse_mode: 'HTML' });
            saveTgMapping(sent);
            return;
          }

          const header = type === ThreadType.Group
            ? `${senderName} tạo bình chọn`
            : 'Bình chọn mới';

          const tgPollMsg = await tgBot.telegram.sendPoll(
            config.telegram.groupId,
            question,
            options.map(o => o.content),
            {
              ...tgBase,
              is_anonymous:        isAnonymous,
              allows_multiple_answers: pollDetail?.allow_multi_choices ?? false,
              question_parse_mode: undefined,
            } as Parameters<typeof tgBot.telegram.sendPoll>[3],
          );

          // Send editable score message below
          const scoreText = buildScoreText(header, pollDetail?.options ?? [], pollDetail?.closed ?? false);
          const tgScoreMsg = await tgBot.telegram.sendMessage(
            config.telegram.groupId,
            scoreText,
            { message_thread_id: topicId, parse_mode: 'HTML' },
          );

          pollStore.save({
            pollId,
            zaloGroupId:  zaloId,
            tgPollMsgId:  tgPollMsg.message_id,
            tgPollUUID:   (tgPollMsg as { poll?: { id?: string } }).poll?.id ?? '',
            tgScoreMsgId: tgScoreMsg.message_id,
            tgThreadId:   topicId,
            options: options.map(o => ({ option_id: o.option_id, content: o.content })),
          });
          saveTgMapping(tgPollMsg);
        } else {
          // ── Vote update (or unknown existing poll after restart) ──────────
          // Small delay so Zalo server has time to record the vote before we fetch
          await new Promise(r => setTimeout(r, 800));
          let updatedDetail = pollDetail;
          try { updatedDetail = await api.getPollDetail(pollId); } catch { /* use existing */ }
          const header = type === ThreadType.Group
            ? `${senderName} vừa bình chọn`
            : 'Cập nhật bình chọn';
          const detailOptions = updatedDetail?.options ?? [];
          const scoreText = buildScoreText(
            header,
            detailOptions.length > 0 ? detailOptions : (existingEntry?.options.map(o => ({ ...o, votes: 0, voted: false, voters: [] })) ?? []),
            updatedDetail?.closed ?? false,
          );
          console.log(`[ZaloHandler] Poll ${pollId} score:`, detailOptions.map((o: { content: string; votes: number }) => `${o.content}=${o.votes}`).join(', '));

          if (existingEntry) {
            try {
              await tgBot.telegram.editMessageText(
                config.telegram.groupId,
                existingEntry.tgScoreMsgId,
                undefined,
                scoreText,
                {
                  parse_mode: 'HTML',
                  reply_markup: updatedDetail?.closed
                    ? { inline_keyboard: [] }
                    : { inline_keyboard: [[{ text: '🔒 Khoá bình chọn', callback_data: `lock_poll:${pollId}` }]] },
                },
              );
              console.log(`[ZaloHandler] Poll ${pollId} score message edited OK`);
            } catch (editErr) {
              console.warn(`[ZaloHandler] Poll ${pollId} edit failed, sending new:`, editErr);
              const newScore = await tgBot.telegram.sendMessage(
                config.telegram.groupId,
                scoreText,
                { message_thread_id: existingEntry.tgThreadId, parse_mode: 'HTML',
                  reply_parameters: { message_id: existingEntry.tgPollMsgId, allow_sending_without_reply: true } },
              );
              pollStore.updateScoreMsg(pollId, newScore.message_id);
            }
          } else {
            // existingEntry lost (bot restarted) — just send score as standalone message
            const sent = await tgBot.telegram.sendMessage(
              config.telegram.groupId,
              scoreText,
              { ...tgBase, parse_mode: 'HTML' },
            );
            saveTgMapping(sent);
          }
        }
        return;
      }

      // ── Fallback ───────────────────────────────────────────────────────────
      // Before fallback: detect contact card by content shape (contactUid field)
      // Zalo sends contact cards as msgType 'chat.forward' with contactUid in content
      {
        const { tgBase, saveTgMapping } = await getBridgeContext();
        const rawContent = msg.data.content;
        const contactUid: string | undefined =
          (typeof rawContent === 'object' && rawContent !== null && 'contactUid' in rawContent)
            ? String((rawContent as Record<string, unknown>).contactUid)
            : (media.contactUid ? String(media.contactUid) : undefined);

        if (contactUid || msgType === ZALO_MSG_TYPES.CONTACT) {
          const uid = contactUid ?? '';
          // Fetch display name from userCache or API
          let contactName = userCache.getName(uid) ?? uid;
          if (uid && contactName === uid) {
            try {
              const resp = await api.getUserInfo(uid) as {
                changed_profiles?: Record<string, { displayName?: string }>;
              };
              contactName = resp?.changed_profiles?.[uid]?.displayName ?? uid;
              if (contactName !== uid) userCache.save(uid, contactName);
            } catch { /* non-fatal */ }
          }
          const qrUrl: string | undefined =
            (typeof rawContent === 'object' && rawContent !== null && 'qrCodeUrl' in rawContent)
              ? String((rawContent as Record<string, unknown>).qrCodeUrl)
              : media.qrCodeUrl;

          const body = `👤 <b>Danh thiếp</b>\nTên: <b>${escapeHtml(contactName)}</b>\nZalo ID: <code>${uid}</code>`;
          const fullText = type === ThreadType.Group ? `${groupCaption(senderName)}\n${body}` : body;

          if (qrUrl) {
            // Send QR code image + caption
            try {
              const localPath = await downloadToTemp(qrUrl, `qr_${Date.now()}.jpg`);
              const stream = createReadStream(localPath);
              const sent = await tgBot.telegram.sendPhoto(
                config.telegram.groupId,
                { source: stream },
                { ...tgBase, caption: fullText, parse_mode: 'HTML' },
              );
              saveTgMapping(sent);
              await cleanTemp(localPath);
            } catch {
              const sent = await tgBot.telegram.sendMessage(config.telegram.groupId, fullText, { ...tgBase, parse_mode: 'HTML' });
              saveTgMapping(sent);
            }
          } else {
            const sent = await tgBot.telegram.sendMessage(config.telegram.groupId, fullText, { ...tgBase, parse_mode: 'HTML' });
            saveTgMapping(sent);
          }
          return;
        }
      }

      console.log(`[ZaloHandler] Unhandled msgType="${msgType}" content:`, JSON.stringify(msg.data.content));
      const { tgBase, saveTgMapping } = await getBridgeContext();
      const fallback = type === ThreadType.Group
        ? `${groupCaption(senderName)}\n<i>[${msgType}]</i>`
        : `<i>[${msgType}]</i>`;
      const sentFallback = await tgBot.telegram.sendMessage(config.telegram.groupId, fallback, {
        ...tgBase,
        parse_mode: 'HTML',
      });
      saveTgMapping(sentFallback);
    } catch (err) {
      console.error('[ZaloHandler] Error:', err);
    }
  });

  // ── Undo (thu hồi tin nhắn) ────────────────────────────────────────────────
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  api.listener.on('undo', async (undo: any) => {
    try {
      const data = undo?.data;
      // The recalled Zalo message ID
      const zaloMsgId = String(data?.content?.globalMsgId ?? data?.msgId ?? '');
      if (!zaloMsgId) return;

      const tgMsgId = msgStore.getTgMsgId(zaloMsgId);
      if (tgMsgId === undefined) {
        console.log(`[ZaloHandler] Undo: no TG mapping for zaloMsgId=${zaloMsgId}`);
        return;
      }

      // Find which topic this message belongs to
      const zaloId = undo?.threadId ?? data?.idTo;
      const type   = (undo?.isGroup ? 1 : 0) as 0 | 1;
      const topicId = store.getTopicByZalo(String(zaloId), type);
      if (topicId === undefined) return;

      // Delete the forwarded TG message
      await tgBot.telegram.deleteMessage(config.telegram.groupId, tgMsgId);
      console.log(`[ZaloHandler] Undo: deleted TG msg ${tgMsgId} (zaloMsgId=${zaloMsgId})`);

      // Notify in topic
      await tgBot.telegram.sendMessage(
        config.telegram.groupId,
        `<i>🗑 Tin nhắn đã được thu hồi</i>`,
        { message_thread_id: topicId, parse_mode: 'HTML' },
      );
    } catch (err) {
      console.error('[ZaloHandler] Undo error:', err);
    }
  });

  // ── Reaction (cảm xúc) ─────────────────────────────────────────────────────
  const REACTION_EMOJI: Record<string, string> = {
    '/-heart':   '❤️',
    '/-strong':  '👍',
    ':>':        '😄',
    ':o':        '😮',
    ':-((':      '😢',
    ':-h':       '😡',
    ':-*':       '😘',
    ":')":       '😂',
    '/-shit':    '💩',
    '/-rose':    '🌹',
    '/-break':   '💔',
    '/-weak':    '👎',
    ';xx':       '🥰',
    ';-/':       '😕',
    ';-)':       '😉',
    '/-fade':    '✨',
    '/-ok':      '👌',
    '/-v':       '✌️',
    '/-thanks':  '🙏',
    '/-punch':   '👊',
    '/-no':      '🙅',
    '/-loveu':   '🤟',
    '--b':       '😞',
    ':((': '😭',
    'x-)':       '😎',
    '_()_':      '🙏',
    '/-bd':      '🎂',
    '/-bome':    '💣',
    '/-beer':    '🍺',
    '/-li':      '☀️',
    '/-share':   '🔁',
    '/-bad':     '😤',
    '':          '❌',  // remove reaction
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  api.listener.on('reaction', async (reaction: any) => {
    try {
      const data = reaction?.data;
      const rIcon: string = data?.content?.rIcon ?? '';
      const emoji = REACTION_EMOJI[rIcon] ?? rIcon;

      // If empty reaction icon → user removed reaction; skip notification
      if (!rIcon) return;

      const gMsgIds: Array<{ gMsgID?: string | number }> = data?.content?.rMsg ?? [];
      const zaloMsgId = String(gMsgIds[0]?.gMsgID ?? '');
      if (!zaloMsgId) return;

      const tgMsgId = msgStore.getTgMsgId(zaloMsgId);
      if (tgMsgId === undefined) return;

      const zaloId = reaction?.threadId ?? data?.idTo;
      const type   = (reaction?.isGroup ? 1 : 0) as 0 | 1;
      const topicId = store.getTopicByZalo(String(zaloId), type);
      if (topicId === undefined) return;

      const dName = data?.dName ?? data?.uidFrom ?? 'ai đó';

      // Send reaction emoji as a reply to the forwarded TG message
      await tgBot.telegram.sendMessage(
        config.telegram.groupId,
        `${emoji} <b>${escapeHtml(dName)}</b>`,
        {
          message_thread_id: topicId,
          parse_mode: 'HTML',
          reply_parameters: { message_id: tgMsgId, allow_sending_without_reply: true },
        },
      );
    } catch (err) {
      console.error('[ZaloHandler] Reaction error:', err);
    }
  });

  // ── Group events (vào/rời nhóm) ────────────────────────────────────────────
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  api.listener.on('group_event', async (event: any) => {
    try {
      const type    = event?.type as string | undefined;
      const data    = event?.data;
      const groupId = String(event?.threadId ?? data?.groupId ?? '');
      if (!groupId) return;

      // ── Poll vote: UPDATE_BOARD with BoardType.Poll ────────────────────────
      if (type === 'update_board' || type === 'remove_board') {
        // groupTopic.params is a JSON string containing poll info
        const rawParams = data?.groupTopic?.params ?? data?.topic?.params ?? '';
        let params: { boardType?: number; pollId?: number } = {};
        try { params = JSON.parse(rawParams); } catch { /* ignore */ }
        // BoardType.Poll = 3
        if (params.boardType === 3 && params.pollId) {
          const pollId = params.pollId;
          console.log(`[ZaloHandler] group_event update_board pollId=${pollId}`);
          const entry = pollStore.getByPollId(pollId);
          if (entry) {
            await new Promise(r => setTimeout(r, 600));
            let detail: Awaited<ReturnType<typeof api.getPollDetail>> | undefined;
            try { detail = await api.getPollDetail(pollId); } catch { /* ignore */ }
            if (detail?.options) {
              const actorName = data?.updateMembers?.[0]?.dName ?? data?.creatorId ?? '';
              const header = actorName ? `${actorName} vừa bình chọn` : 'Cập nhật bình chọn';
              const scoreText = buildScoreText(header, detail.options, detail.closed ?? false);
              console.log(`[ZaloHandler] Poll ${pollId} update:`, detail.options.map((o: { content: string; votes: number }) => `${o.content}=${o.votes}`).join(', '));
              try {
                await tgBot.telegram.editMessageText(
                  config.telegram.groupId,
                  entry.tgScoreMsgId,
                  undefined,
                  scoreText,
                  {
                    parse_mode: 'HTML',
                    reply_markup: detail.closed
                      ? { inline_keyboard: [] }
                      : { inline_keyboard: [[{ text: '🔒 Khoá bình chọn', callback_data: `lock_poll:${pollId}` }]] },
                  },
                );
              } catch {
                const newScore = await tgBot.telegram.sendMessage(
                  config.telegram.groupId,
                  scoreText,
                  { message_thread_id: entry.tgThreadId, parse_mode: 'HTML',
                    reply_parameters: { message_id: entry.tgPollMsgId, allow_sending_without_reply: true },
                    reply_markup: detail.closed
                      ? { inline_keyboard: [] }
                      : { inline_keyboard: [[{ text: '🔒 Khoá bình chọn', callback_data: `lock_poll:${pollId}` }]] } },
                );
                pollStore.updateScoreMsg(pollId, newScore.message_id);
              }
            }
          } else {
            console.log(`[ZaloHandler] update_board pollId=${pollId} not in pollStore (no TG mapping)`);
          }
        }
        return;
      }

      // Only notify for join/leave/remove — skip setting changes, pins, etc.
      const NOTIFY_TYPES = new Set(['join', 'leave', 'remove_member', 'block_member']);
      if (!type || !NOTIFY_TYPES.has(type)) return;

      const topicId = store.getTopicByZalo(groupId, 1 /* Group */);
      if (topicId === undefined) return;

      const members: Array<{ dName?: string }> = data?.updateMembers ?? [];
      const names = members.map(m => m.dName ?? '?').join(', ');
      const actor  = data?.creatorId === data?.sourceId ? '' : '';  // unused for now
      void actor;

      let notifText = '';
      if (type === 'join') {
        notifText = `➕ <b>${escapeHtml(names)}</b> đã tham gia nhóm`;
      } else if (type === 'leave') {
        notifText = `➖ <b>${escapeHtml(names)}</b> đã rời nhóm`;
      } else if (type === 'remove_member') {
        notifText = `🚫 <b>${escapeHtml(names)}</b> đã bị xóa khỏi nhóm`;
      } else if (type === 'block_member') {
        notifText = `🔒 <b>${escapeHtml(names)}</b> đã bị chặn khỏi nhóm`;
      }

      if (!notifText) return;

      await tgBot.telegram.sendMessage(
        config.telegram.groupId,
        `<i>${notifText}</i>`,
        { message_thread_id: topicId, parse_mode: 'HTML' },
      );
      console.log(`[ZaloHandler] GroupEvent type=${type} group=${groupId}`);
    } catch (err) {
      console.error('[ZaloHandler] GroupEvent error:', err);
    }
  });
}
