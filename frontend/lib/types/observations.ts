export type ObservationStatus = 'open' | 'answered' | 'resolved';
export type ObservationFilter = ObservationStatus | 'active' | 'all';

export interface ObservationTextSummary {
  body_preview: string;
  body_length: number;
  body_content_url: string;
}

export interface ObservationReplyRow extends ObservationTextSummary {
  public_id: string;
  author_email: string;
  status_change: string;
  created_at: string;
}

export interface ObservationAnchorRow {
  version_public_id: string;
  version_is_trashed: boolean;
  version_number: number;
  page: number;
  method: 'exact' | 'reanchored_section' | 'orphaned';
  text_snippet: string;
  quads_length: number;
  quads_content_url: string;
}

export interface ObservationRow extends ObservationTextSummary {
  public_id: string;
  status: ObservationStatus;
  author_email: string;
  section_key: string | null;
  section_heading: string | null;
  created_on: number;
  resolved_in: number | null;
  reply_count: number;
  current_anchor: ObservationAnchorRow | null;
  created_at: string;
}

export interface ObservationPage<T> {
  results: T[];
  next_cursor: string | null;
}

export interface ObservationContentChunk {
  content: string;
  offset: number;
  next_offset: number | null;
  eof: boolean;
}

export interface LoadedObservationPage<T> {
  items: T[];
  nextCursor: string | null;
  isLoaded: boolean;
  isLoading: boolean;
  error: string | null;
}

export interface LoadedObservationContent {
  content: string;
  nextOffset: number | null;
  eof: boolean;
  isLoaded: boolean;
  isLoading: boolean;
  error: string | null;
}
