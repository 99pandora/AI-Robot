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
}
