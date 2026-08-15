import type { DocumentRecord, HealthResponse } from "./types";

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
