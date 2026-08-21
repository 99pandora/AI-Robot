export type DocumentStatus = "pending" | "indexed" | "failed";

export interface DocumentRecord {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  status: DocumentStatus;
  version: number;
  is_seed: boolean;
  chunk_count: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  skipped?: boolean;
}

export interface HealthResponse {
  status: string;
  dependencies?: {
    mock_api?: "ok" | "unavailable" | string;
    feishu?: {
      status: FeishuConnectionStatus | string;
      configured: boolean;
      last_error: string | null;
    };
  };
}

export type FeishuConnectionStatus =
  | "disabled"
  | "stopped"
  | "starting"
  | "connected"
  | "reconnecting"
  | "failed"
  | "misconfigured";

export interface ChatStreamRequest {
  message: string;
  platform: string;
  user_id: string;
  conversation_id: string;
}

export interface ChatReference {
  filename: string;
  location: string;
  title: string;
  text: string;
}

export type ToolCallStatus = "started" | "completed" | "failed";

export interface ToolCallEvent {
  name: string;
  status: ToolCallStatus;
}

export interface ChatEvent {
  event: string;
  data: Record<string, unknown>;
}

export interface ChatMessage {
  /** 页面展示用的消息模型；工具调用和引用只挂在助手消息上。 */
  id: string;
  role: "user" | "assistant";
  content: string;
  references: ChatReference[];
  tools: ToolCallEvent[];
  error?: string;
}

export type ConversationStatus = "running" | "completed" | "failed";

export interface ConversationSummary {
  id: string;
  platform: string;
  user_id: string;
  conversation_id: string;
  turn_count: number;
  last_question: string;
  last_answer: string;
  status: ConversationStatus;
  tool_count: number;
  reference_count: number;
  total_duration_ms: number;
  created_at: string;
  updated_at: string;
}

export interface ConversationTurn {
  id: string;
  turn_index: number;
  user_message: string;
  assistant_message: string;
  status: ConversationStatus;
  tool_calls: ToolCallEvent[];
  references: ChatReference[];
  error: string | null;
  duration_ms: number;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  turns: ConversationTurn[];
}
