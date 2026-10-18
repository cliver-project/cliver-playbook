import { api } from "cliver-playbook-app-basic/api/client.ts";

/**
 * RAG-domain API calls.
 *
 * Every endpoint lives under `/api/v1/rag`, so all of them go through the
 * shared axios instance — base URL, bearer injection and the 401 redirect are
 * the same as the rest of the Web API. Stage names are plain strings: the
 * catalog endpoint is the source of truth for which ones exist, and the
 * browser must be able to render a newly registered stage without a rebuild.
 *
 * The ingestion flow is two calls on purpose. `uploadDocument` chunks the file
 * and returns a preview with `status="pending"`; `indexDocument` then embeds
 * those chunks and flips the document to `indexed`. A user inspects the
 * chunking result before committing to an embedding stage.
 */

// ---------------------------------------------------------------------------
// Stage discovery
// ---------------------------------------------------------------------------

export interface StageOption {
  name: string;
  model_id: string | null;
  version: string | null;
  dim: number | null;
}

export interface StageDefaults {
  chunker: string;
  embedder: string;
  retriever: string;
  reranker: string;
  llm: string;
}

export interface StageCatalog {
  chunkers: StageOption[];
  embedders: StageOption[];
  retrievers: StageOption[];
  rerankers: StageOption[];
  llms: StageOption[];
  defaults: StageDefaults;
}

/** Every registered implementation per stage plus the configured defaults.
 *
 * The UI builds its selectors from this response, so registering a new
 * embedder or reranker on the server makes it selectable with no frontend
 * change. Reading it needs `rag:documents:read`, which every role that can
 * reach the RAG pages holds. */
export async function fetchStageCatalog(): Promise<StageCatalog> {
  const { data } = await api.get<StageCatalog>("/rag/stages");
  return data;
}

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

export interface DocumentRow {
  id: string;
  title: string;
  source_uri: string | null;
  mime_type: string;
  chunker_id: string;
  embedder_id: string;
  dim: number;
  version: number;
  status: string;
  failure_reason: string | null;
  chunk_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface DocumentList {
  items: DocumentRow[];
}

export interface ChunkRow {
  id: string;
  ordinal: number;
  text: string;
  token_count: number;
  metadata: Record<string, unknown>;
  parent_id: string | null;
}

export interface ChunkList {
  items: ChunkRow[];
}

export interface PreviewChunk {
  ordinal: number;
  text: string;
  token_count: number;
  chunk_id_prefix: string;
}

export interface UploadResponse {
  document_id: string;
  title: string;
  status: string;
  chunker: string;
  embedder: string;
  dim: number;
  version: number;
  chunk_count: number;
  preview_truncated: boolean;
  preview_chunks: PreviewChunk[];
}

export interface IndexResponse {
  document_id: string;
  status: string;
  chunk_count: number;
  dim: number;
  embedder_version?: string;
}

export interface UploadOptions {
  file: File;
  chunker?: string;
  embedder?: string;
  chunkSize?: number;
  chunkOverlap?: number;
  title?: string;
}

/** Chunk a file and persist the result for preview (no embeddings yet). */
export async function uploadDocument(options: UploadOptions): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", options.file);
  // Omit unset fields instead of sending empty strings: the server applies
  // its layered settings defaults only when a field is absent.
  if (options.chunker) form.append("chunker", options.chunker);
  if (options.embedder) form.append("embedder", options.embedder);
  if (options.chunkSize !== undefined) form.append("chunk_size", String(options.chunkSize));
  if (options.chunkOverlap !== undefined) {
    form.append("chunk_overlap", String(options.chunkOverlap));
  }
  if (options.title) form.append("title", options.title);
  const { data } = await api.post<UploadResponse>("/rag/documents/upload", form);
  return data;
}

/** Embed a pending document's chunks and make it searchable. Idempotent. */
export async function indexDocument(documentId: string): Promise<IndexResponse> {
  const { data } = await api.post<IndexResponse>(
    `/rag/documents/${encodeURIComponent(documentId)}/index`,
  );
  return data;
}

export async function listDocuments(): Promise<DocumentList> {
  const { data } = await api.get<DocumentList>("/rag/documents");
  return data;
}

export async function getDocument(documentId: string): Promise<DocumentRow> {
  const { data } = await api.get<DocumentRow>(
    `/rag/documents/${encodeURIComponent(documentId)}`,
  );
  return data;
}

export async function listDocumentChunks(documentId: string): Promise<ChunkList> {
  const { data } = await api.get<ChunkList>(
    `/rag/documents/${encodeURIComponent(documentId)}/chunks`,
  );
  return data;
}

// ---------------------------------------------------------------------------
// Search and chat
// ---------------------------------------------------------------------------

export type RetrievalMode = "dense" | "sparse" | "hybrid";

export interface SearchRequest {
  query: string;
  top_k?: number;
  mode?: RetrievalMode;
  retriever?: string;
  /** Query embedder for the dense leg. Must match the embedder that
   * indexed the target documents; vectors from different models are not
   * comparable. */
  embedder?: string;
}

export interface SearchHit {
  chunk_id: string;
  document_id: string;
  ordinal: number;
  text: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface SearchResponse {
  retriever: string;
  mode: string;
  hits: SearchHit[];
}

export interface ChatRequest {
  question: string;
  mode?: RetrievalMode;
  top_k?: number;
  rerank_top_k?: number;
  retriever?: string;
  /** Query embedder for the dense leg; defaults to the server value. */
  embedder?: string;
  reranker?: string;
  llm?: string;
}

export interface Citation {
  chunk_id: string;
  document_id: string;
  ordinal: number;
  score: number;
  text_preview: string;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  model_id: string;
  hits_used: number;
  no_hits: boolean;
  retriever: string;
  reranker: string;
  llm: string;
}

/** Retrieval only — useful for inspecting which chunks a stage combination
 * finds before asking the generator to answer from them. */
export async function searchRag(request: SearchRequest): Promise<SearchResponse> {
  const { data } = await api.post<SearchResponse>("/rag/search", request);
  return data;
}

/** Retrieve, rerank and generate a grounded answer with citations.
 *
 * A `no_hits: true` response is a successful exchange: the server skips the
 * generator and returns an explicit refusal when nothing survives the
 * relevance floor. The UI renders it as an empty state, not an error. */
export async function chatRag(request: ChatRequest): Promise<ChatResponse> {
  const { data } = await api.post<ChatResponse>("/rag/chat", request);
  return data;
}
