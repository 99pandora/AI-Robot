import type {
  ChatEvent,
  ChatStreamRequest,
  ConversationDetail,
  ConversationStatus,
  ConversationSummary,
  DocumentRecord,
  HealthResponse,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

interface ErrorPayload {
  detail?: string;
  message?: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try {
      const payload = (await response.json()) as ErrorPayload;
      detail = payload.detail ?? payload.message ?? detail;
    } catch {
      // 非 JSON 错误响应使用状态码兜底，避免覆盖原始错误。
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function listDocuments(): Promise<DocumentRecord[]> {
  return request<DocumentRecord[]>("/documents");
}

export function uploadDocument(file: File): Promise<DocumentRecord> {
  const formData = new FormData();
  formData.append("file", file);
  return request<DocumentRecord>("/documents", {
    method: "POST",
    body: formData,
  });
}

export function reindexDocument(documentId: string): Promise<DocumentRecord> {
  return request<DocumentRecord>(`/documents/${encodeURIComponent(documentId)}/reindex`, {
    method: "POST",
  });
}

export function deleteDocument(documentId: string): Promise<void> {
  return request<void>(`/documents/${encodeURIComponent(documentId)}`, {
    method: "DELETE",
  });
}

export function downloadUrl(documentId: string): string {
  return `${API_BASE}/documents/${encodeURIComponent(documentId)}/download`;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export interface ConversationQuery {
  limit?: number;
  status?: ConversationStatus;
  keyword?: string;
}

export function listConversations(query: ConversationQuery = {}): Promise<ConversationSummary[]> {
  // 仅传递有值的筛选条件，保持接口默认分页和状态行为。
  const params = new URLSearchParams();
  if (query.limit) params.set("limit", String(query.limit));
  if (query.status) params.set("status", query.status);
  if (query.keyword?.trim()) params.set("keyword", query.keyword.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<ConversationSummary[]>(`/conversations${suffix}`);
}

export function getConversation(conversationPk: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/conversations/${encodeURIComponent(conversationPk)}`);
}

export async function streamChat(
  payload: ChatStreamRequest,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  // 直接读取 fetch 的 ReadableStream，保证 token 到达后立即交给页面渲染。
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) {
    throw new Error(await responseError(response, `聊天请求失败（${response.status}）`));
  }
  if (!response.body) {
    throw new Error("浏览器不支持流式响应");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      // 一个网络分片可能包含多个 SSE 帧，也可能只包含半个帧，因此保留尾部残片。
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      frames.forEach((frame) => {
        const event = parseSseFrame(frame);
        if (event) {
          onEvent(event);
        }
      });
      if (done) {
        const event = parseSseFrame(buffer);
        if (event) {
          onEvent(event);
        }
        break;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

async function responseError(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as ErrorPayload;
    return payload.detail ?? payload.message ?? fallback;
  } catch {
    return fallback;
  }
}

function parseSseFrame(frame: string): ChatEvent | null {
  // 后端每个事件都由 event 和一行或多行 data 组成，data 统一按 JSON 解码。
  let eventName = "message";
  const dataLines: string[] = [];
  frame.split(/\r?\n/).forEach((line) => {
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  });
  if (!dataLines.length) {
    return null;
  }
  try {
    const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
    return { event: eventName, data };
  } catch {
    return { event: eventName, data: { raw: dataLines.join("\n") } };
  }
}
