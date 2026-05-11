export type HermesDecisionKind = 'auto_reply' | 'needs_approval' | 'ignore' | 'passthrough';

export interface HermesZaloRequest {
  requestId: string;
  channel: 'zalo';
  chat: {
    id: string;
    type: 0 | 1;
    name: string;
  };
  sender: {
    id: string;
    name: string;
  };
  message: {
    text: string;
    msgId: string;
    timestamp?: string | number;
  };
  routing: {
    isDirectChat: boolean;
    invokedByAlias: boolean;
  };
  sourceFiles?: HermesZaloSourceFile[];
}

export interface HermesZaloSourceFile {
  name: string;
  mimeType?: string;
  contentBase64: string;
}

export interface HermesDecision {
  decision: HermesDecisionKind;
  requestId?: string;
  replyText?: string;
  approvalId?: string;
  approvalPrompt?: string;
  reason?: string;
}
