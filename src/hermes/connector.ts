import { config } from '../config.js';
import type { HermesDecision, HermesZaloRequest } from './types.js';

function normalizeDecision(payload: unknown, requestId: string): HermesDecision {
  if (!payload || typeof payload !== 'object') {
    return { decision: 'passthrough', requestId, reason: 'invalid_response' };
  }

  const raw = payload as Record<string, unknown>;
  const decisionRaw = String(raw.decision ?? raw.action ?? 'passthrough');
  const decision = decisionRaw === 'need_approval' ? 'needs_approval' : decisionRaw;

  if (!['auto_reply', 'needs_approval', 'ignore', 'passthrough'].includes(decision)) {
    return { decision: 'passthrough', requestId, reason: `unsupported_decision:${decisionRaw}` };
  }

  return {
    decision: decision as HermesDecision['decision'],
    requestId: typeof raw.requestId === 'string' ? raw.requestId : requestId,
    replyText: typeof raw.replyText === 'string'
      ? raw.replyText
      : typeof raw.reply_text === 'string'
        ? raw.reply_text
        : undefined,
    approvalId: typeof raw.approvalId === 'string'
      ? raw.approvalId
      : typeof raw.approval_id === 'string'
        ? raw.approval_id
        : undefined,
    approvalPrompt: typeof raw.approvalPrompt === 'string'
      ? raw.approvalPrompt
      : typeof raw.approval_prompt === 'string'
        ? raw.approval_prompt
        : undefined,
    reason: typeof raw.reason === 'string' ? raw.reason : undefined,
  };
}

export async function decideWithHermes(request: HermesZaloRequest): Promise<HermesDecision> {
  if (!config.hermes.coreUrl) {
    return { decision: 'passthrough', requestId: request.requestId, reason: 'hermes_core_disabled' };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), config.hermes.timeoutMs);
  try {
    const response = await fetch(`${config.hermes.coreUrl}/api/zalo/decide`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal: controller.signal,
    });

    if (!response.ok) {
      return {
        decision: 'passthrough',
        requestId: request.requestId,
        reason: `hermes_http_${response.status}`,
      };
    }

    return normalizeDecision(await response.json(), request.requestId);
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    console.warn(`[Hermes] Decision request failed: ${reason}`);
    return { decision: 'passthrough', requestId: request.requestId, reason: 'hermes_request_failed' };
  } finally {
    clearTimeout(timeout);
  }
}

