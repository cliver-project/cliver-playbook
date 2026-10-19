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

/** Retrieval legs a request may ask for. */
export type RetrievalMode = "dense" | "sparse" | "hybrid";

/** One flat, browser-configurable option of a stage implementation.
 *
 * The server derives this descriptor from the implementation's Pydantic
 * options model; the upload page renders one form control per `type` and
 * never hardcodes chunker-specific fields. */
export interface StageOptionField {
  name: string;
  label: string;
  type: "boolean" | "integer" | "string" | "enum";
  default: boolean | number | string | null;
  enum: string[] | null;
  minimum: number | null;
  maximum: number | null;
  description: string;
}

export interface StageOption {
  name: string;
  model_id: string | null;
  version: string | null;
  dim: number | null;
  /** Modes the implementation can honour (retrievers only). The chat page
   * hides the modes the selected retriever does not declare instead of
   * offering a combination the server would reject with 422. */
  modes: RetrievalMode[] | null;
  /** Output-shaping options (chunkers only). An empty array means the
   * stage is configurable but has no options; `null` means it does not
   * accept options at all. */
  config_schema: StageOptionField[] | null;
}

export interface StageDefaults {
  chunker: string;
  embedder: string;
  retriever: string;
  reranker: string;
  llm: string;
}

/** What the indexed corpus was actually produced with.
 *
 * `embedders` is the set recorded on `indexed` documents. The query
 * embedder must match the one that produced the stored vectors, so the
 * chat page limits its choice to these names rather than to every
 * registered embedder — picking a model that never indexed anything
 * guarantees an empty dense leg. */
export interface CorpusStats {
  embedders: string[];
}

export interface StageCatalog {
  chunkers: StageOption[];
  embedders: StageOption[];
  retrievers: StageOption[];
  rerankers: StageOption[];
  llms: StageOption[];
  defaults: StageDefaults;
  corpus: CorpusStats;
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

/** The effective chunker configuration that produced a document's chunks.
 *
 * `version` is the chunker implementation version, not the document
 * version. Older rows may carry an empty object; the server fills the
 * defaults on the next upload. */
export interface ChunkerConfig {
  version: string | null;
  chunk_size: number | null;
  chunk_overlap: number | null;
  options: Record<string, unknown>;
}

export interface DocumentRow {
  id: string;
  title: string;
  source_uri: string | null;
  mime_type: string;
  chunker_id: string;
  chunker_config: ChunkerConfig;
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
  chunker_config: ChunkerConfig;
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
  /** The embedder recorded on the document after indexing. */
  embedder: string;
  /** The implementation version of that embedder (`stub@1.0`), which is
   * also the identity retrieval filters embedding rows by. */
  embedder_version: string;
}

export interface IndexOptions {
  /** Override the embedder recorded at upload time. Omit to use it. */
  embedder?: string;
  /** Re-embed even when the document is already indexed with this model. */
  force?: boolean;
}

export interface UploadOptions {
  file: File;
  chunker?: string;
  embedder?: string;
  chunkSize?: number;
  chunkOverlap?: number;
  /** Validated chunker-specific options, sent as JSON in the
   * `chunker_options` form field. Omit for chunkers with no options. */
  chunkerOptions?: Record<string, unknown>;
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
  if (options.chunkerOptions !== undefined) {
    form.append("chunker_options", JSON.stringify(options.chunkerOptions));
  }
  if (options.title) form.append("title", options.title);
  const { data } = await api.post<UploadResponse>("/rag/documents/upload", form);
  return data;
}

/**
 * Embed a document's chunks and make it searchable.
 *
 * Idempotent when the document is already indexed with the same embedder;
 * an `embedder` override (or `force`) re-embeds and replaces the stored
 * vectors. The backend takes both as query parameters.
 */
export async function indexDocument(
  documentId: string,
  options: IndexOptions = {},
): Promise<IndexResponse> {
  const { data } = await api.post<IndexResponse>(
    `/rag/documents/${encodeURIComponent(documentId)}/index`,
    undefined,
    { params: { embedder: options.embedder, force: options.force || undefined } },
  );
  return data;
}

export interface DeleteResponse {
  document_id: string;
  deleted: boolean;
}

/** Remove a document together with its chunks and embeddings (permanent). */
export async function deleteDocument(documentId: string): Promise<DeleteResponse> {
  const { data } = await api.delete<DeleteResponse>(
    `/rag/documents/${encodeURIComponent(documentId)}`,
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
  /** The mode the request asked for. */
  requested_mode: string;
  /** The mode that actually ran. A retriever that cannot honour the
   * requested combination reports its effective mode here rather than
   * echoing the request. */
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
  requested_mode: string;
  mode: string;
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
