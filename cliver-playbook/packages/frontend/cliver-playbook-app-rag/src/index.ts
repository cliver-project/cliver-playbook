/**
 * Public surface of the rag frontend package.
 *
 * The barrel carries what an app wires up once — routes, nav entries,
 * translations — plus the API wrappers, because a project that vendors or
 * re-skins the pages still needs the typed client. Components and pages are
 * reachable through deep paths
 * (`cliver-playbook-app-rag/pages/RagDocumentsPage.tsx`); deep paths carry the
 * source extension, which is the package's `exports` contract and what makes
 * cross-package imports work with no aliases configured.
 */

export {
  chatRag,
  fetchStageCatalog,
  getDocument,
  indexDocument,
  listDocumentChunks,
  listDocuments,
  searchRag,
  uploadDocument,
  type ChatRequest,
  type ChatResponse,
  type ChunkList,
  type ChunkRow,
  type Citation,
  type DocumentList,
  type DocumentRow,
  type IndexResponse,
  type PreviewChunk,
  type RetrievalMode,
  type SearchHit,
  type SearchRequest,
  type SearchResponse,
  type StageCatalog,
  type StageDefaults,
  type StageOption,
  type UploadOptions,
  type UploadResponse,
} from "cliver-playbook-app-rag/api/rag.ts";
export { ragTranslations } from "cliver-playbook-app-rag/locales/index.ts";
export { ragNavItems } from "cliver-playbook-app-rag/nav.ts";
export { ragRoutes, ragStandaloneRoutes } from "cliver-playbook-app-rag/routes.tsx";
