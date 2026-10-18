import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AlertCircleIcon, MessageSquareIcon, SearchIcon } from "lucide-react";
import { toast } from "sonner";

import { apiErrorMessage } from "cliver-playbook-app-basic/api/client.ts";
import { Badge } from "cliver-playbook-app-basic/components/ui/badge.tsx";
import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "cliver-playbook-app-basic/components/ui/card.tsx";
import { Input } from "cliver-playbook-app-basic/components/ui/input.tsx";
import { Label } from "cliver-playbook-app-basic/components/ui/label.tsx";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "cliver-playbook-app-basic/components/ui/select.tsx";
import { Textarea } from "cliver-playbook-app-basic/components/ui/textarea.tsx";
import {
  chatRag,
  fetchStageCatalog,
  searchRag,
  type ChatResponse,
  type RetrievalMode,
  type SearchResponse,
  type StageOption,
} from "cliver-playbook-app-rag/api/rag.ts";
import { CitationBadge } from "cliver-playbook-app-rag/components/rag/CitationBadge.tsx";
import { StageSelector } from "cliver-playbook-app-rag/components/rag/StageSelector.tsx";
import { useAuth } from "cliver-playbook-app-user/components/auth/AuthContext.tsx";

/**
 * Grounded chat over the knowledge base, with every stage selectable.
 *
 * The retriever, embedder, reranker and LLM come from the server's stage
 * catalog; the mode decides which retrieval leg(s) run. An override is sent
 * only when the user actually changes a stage — omitting a field lets the
 * server apply its configured default, which keeps the page on the same
 * defaults a scripted client gets. The exceptions are deliberate:
 *
 * - The query embedder list shows every registered embedder, matching the
 *   ingestion page, but only models recorded on indexed documents are
 *   selectable. Vectors from different models are not comparable, so a
 *   model that indexed nothing would guarantee an empty dense leg; it stays
 *   visible with a "no vectors" marker instead of disappearing from the
 *   dropdown. The catalog's `corpus.embedders` is the set recorded on
 *   indexed documents; when the server default is among them it wins,
 *   otherwise the first one does.
 * - The mode list is limited to what the selected retriever declares. The
 *   server rejects unsupported combinations with 422 rather than silently
 *   downgrading; hiding them here avoids offering a request that cannot run.
 *   A retriever may still *degrade* a supported mode (lexical-only reports
 *   `sparse` for a `hybrid` request), so results render the server's
 *   effective mode, with the requested one shown when they differ.
 *
 * Two actions share the form. "Ask" retrieves, reranks and generates, and
 * renders the answer with citations. "Search only" stops after retrieval,
 * which is how a user inspects which chunks a stage combination finds — and
 * how the dense/sparse/hybrid selector becomes observable rather than a black
 * box. "Search only" is hidden without `rag:search:read`; the page itself is
 * gated by `rag:chat:read`.
 *
 * The question is snapshotted with each result: editing the textarea after an
 * answer arrives must not make the answer look like it belongs to the new
 * text. A `no_hits` answer is a successful refusal from the server (the
 * generator was skipped); the page renders it as an empty state, never as an
 * error, and never invents text of its own.
 *
 * The answer is rendered as plain text with preserved whitespace, not through
 * an HTML/Markdown injector: model output is untrusted input, and there is no
 * formatting feature here worth letting it reach the DOM as markup.
 */

const MODES: RetrievalMode[] = ["hybrid", "dense", "sparse"];

const MODE_LABEL: Record<RetrievalMode, string> = {
  hybrid: "rag.chat.modeHybrid",
  dense: "rag.chat.modeDense",
  sparse: "rag.chat.modeSparse",
};

/** Whole, positive integers only; anything else is treated as invalid input
 * rather than silently replaced by the server default. */
function parsePositiveInteger(raw: string): number | undefined {
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  const value = Number(trimmed);
  return Number.isInteger(value) && value > 0 ? value : undefined;
}

interface AskInput {
  question: string;
  mode: RetrievalMode;
  topK?: number;
  rerankTopK?: number;
  retriever?: string;
  embedder?: string;
  reranker?: string;
  llm?: string;
}

interface SearchInput {
  question: string;
  mode: RetrievalMode;
  topK?: number;
  retriever?: string;
  embedder?: string;
}

export default function RagChatPage() {
  const { t } = useTranslation();
  const { hasPerm } = useAuth();
  const canSearch = hasPerm("rag:search:read");

  const catalog = useQuery({ queryKey: ["rag-stages"], queryFn: fetchStageCatalog });

  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<RetrievalMode>("hybrid");
  const [retriever, setRetriever] = useState<string | null>(null);
  const [embedder, setEmbedder] = useState<string | null>(null);
  const [reranker, setReranker] = useState<string | null>(null);
  const [llm, setLlm] = useState<string | null>(null);
  const [topK, setTopK] = useState("");
  const [rerankTopK, setRerankTopK] = useState("");
  const [answer, setAnswer] = useState<ChatResponse | null>(null);
  const [answerQuestion, setAnswerQuestion] = useState<string | null>(null);
  const [hits, setHits] = useState<SearchResponse | null>(null);
  const [hitsQuestion, setHitsQuestion] = useState<string | null>(null);

  const effectiveRetriever = retriever ?? catalog.data?.defaults.retriever ?? "";
  const effectiveReranker = reranker ?? catalog.data?.defaults.reranker ?? "";
  const effectiveLlm = llm ?? catalog.data?.defaults.llm ?? "";

  // Mode capability: the selected retriever's declared modes define the
  // options. An absent/empty declaration is treated as "unknown" and offers
  // the full set rather than locking the control.
  const selectedRetriever = (catalog.data?.retrievers ?? []).find(
    (option: StageOption) => option.name === effectiveRetriever,
  );
  const supportedModes =
    selectedRetriever?.modes && selectedRetriever.modes.length > 0
      ? selectedRetriever.modes
      : MODES;
  const availableModes = MODES.filter((candidate) => supportedModes.includes(candidate));
  const activeMode: RetrievalMode = availableModes.includes(mode)
    ? mode
    : (availableModes[0] ?? "hybrid");

  // Query embedder: list the full registry so the dropdown mirrors the
  // ingestion page, but make only corpus-backed models selectable. A model
  // that indexed nothing cannot contribute a dense leg, so it is marked
  // unavailable rather than hidden. The server default wins when it indexed
  // the corpus; otherwise the first corpus embedder becomes the effective
  // choice so the dense leg can match.
  const allEmbedderOptions = catalog.data?.embedders ?? [];
  const corpusEmbedderNames = catalog.data?.corpus.embedders ?? [];
  const selectableEmbedders = allEmbedderOptions.filter((option: StageOption) =>
    corpusEmbedderNames.includes(option.name),
  );
  const unavailableEmbedderNames = allEmbedderOptions
    .map((option: StageOption) => option.name)
    .filter((name) => !corpusEmbedderNames.includes(name));
  const serverDefaultEmbedder = catalog.data?.defaults.embedder ?? "";
  const autoEmbedder =
    selectableEmbedders.length === 0
      ? undefined
      : selectableEmbedders.some((option) => option.name === serverDefaultEmbedder)
        ? serverDefaultEmbedder
        : selectableEmbedders[0].name;
  const effectiveEmbedder = embedder ?? autoEmbedder ?? serverDefaultEmbedder;

  // The explicit selection wins; otherwise send the corpus-derived choice.
  // With no indexed corpus there is nothing to match, so the field is
  // omitted and the server's default applies.
  const requestEmbedder = embedder ?? autoEmbedder;

  const topKValue = parsePositiveInteger(topK);
  const rerankTopKValue = parsePositiveInteger(rerankTopK);
  const topKInvalid = topK.trim() !== "" && topKValue === undefined;
  const rerankTopKInvalid = rerankTopK.trim() !== "" && rerankTopKValue === undefined;
  const inputsInvalid = topKInvalid || rerankTopKInvalid;

  const buildAskInput = (): AskInput => ({
    question,
    mode: activeMode,
    topK: topKValue,
    rerankTopK: rerankTopKValue,
    retriever: retriever ?? undefined,
    embedder: requestEmbedder,
    reranker: reranker ?? undefined,
    llm: llm ?? undefined,
  });

  const buildSearchInput = (): SearchInput => ({
    question,
    mode: activeMode,
    topK: topKValue,
    retriever: retriever ?? undefined,
    embedder: requestEmbedder,
  });

  const ask = useMutation({
    mutationFn: (input: AskInput) =>
      chatRag({
        question: input.question,
        mode: input.mode,
        top_k: input.topK,
        rerank_top_k: input.rerankTopK,
        retriever: input.retriever,
        embedder: input.embedder,
        reranker: input.reranker,
        llm: input.llm,
      }),
    // Clear the previous exchange before running: a result must never sit
    // under a question it was not produced from (and a failed run leaves no
    // stale card behind).
    onMutate: () => {
      setAnswer(null);
      setAnswerQuestion(null);
      setHits(null);
      setHitsQuestion(null);
    },
    onSuccess: (data, input) => {
      setAnswer(data);
      setAnswerQuestion(input.question);
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  const search = useMutation({
    mutationFn: (input: SearchInput) =>
      searchRag({
        query: input.question,
        mode: input.mode,
        top_k: input.topK,
        retriever: input.retriever,
        embedder: input.embedder,
      }),
    onMutate: () => {
      setAnswer(null);
      setAnswerQuestion(null);
      setHits(null);
      setHitsQuestion(null);
    },
    onSuccess: (data, input) => {
      setHits(data);
      setHitsQuestion(input.question);
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  const busy = ask.isPending || search.isPending;

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{t("rag.chat.title")}</h1>
        <p className="text-muted-foreground max-w-2xl">{t("rag.chat.description")}</p>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MessageSquareIcon className="size-5" />
            {t("rag.chat.questionTitle")}
          </CardTitle>
          <CardDescription>{t("rag.chat.questionDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {catalog.isError ? (
            <p className="text-destructive flex items-center gap-2 text-sm">
              <AlertCircleIcon className="size-4" />
              {t("rag.chat.catalogFailed")} ({apiErrorMessage(catalog.error)})
            </p>
          ) : null}

          <div className="space-y-1.5">
            <Label htmlFor="rag-question">{t("rag.chat.questionLabel")}</Label>
            <Textarea
              id="rag-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder={t("rag.chat.questionPlaceholder")}
              rows={4}
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <StageSelector
              id="rag-retriever"
              label={t("rag.chat.retrieverLabel")}
              value={effectiveRetriever}
              options={catalog.data?.retrievers ?? []}
              onChange={setRetriever}
              disabled={busy}
            />
            <StageSelector
              id="rag-embedder"
              label={t("rag.chat.embedderLabel")}
              value={effectiveEmbedder}
              options={allEmbedderOptions}
              onChange={setEmbedder}
              disabled={busy}
              unavailable={unavailableEmbedderNames}
              unavailableLabel={t("rag.chat.embedderUnavailable")}
              description={
                corpusEmbedderNames.length === 0
                  ? t("rag.chat.corpusEmpty")
                  : t("rag.chat.embedderHint")
              }
            />
            <StageSelector
              id="rag-reranker"
              label={t("rag.chat.rerankerLabel")}
              value={effectiveReranker}
              options={catalog.data?.rerankers ?? []}
              onChange={setReranker}
              disabled={busy}
            />
            <StageSelector
              id="rag-llm"
              label={t("rag.chat.llmLabel")}
              value={effectiveLlm}
              options={catalog.data?.llms ?? []}
              onChange={setLlm}
              disabled={busy}
            />
            <div className="space-y-1.5">
              <Label htmlFor="rag-mode">{t("rag.chat.modeLabel")}</Label>
              <Select
                value={activeMode}
                onValueChange={(value) => setMode(value as RetrievalMode)}
                disabled={busy}
              >
                <SelectTrigger id="rag-mode" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {availableModes.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t(MODE_LABEL[value])}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">{t("rag.chat.modeHint")}</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rag-top-k">{t("rag.chat.topKLabel")}</Label>
              <Input
                id="rag-top-k"
                type="number"
                min={1}
                step={1}
                value={topK}
                onChange={(event) => setTopK(event.target.value)}
                placeholder={t("rag.chat.optional")}
                disabled={busy}
              />
              {topKInvalid ? (
                <p className="text-destructive text-xs">{t("rag.chat.invalidInteger")}</p>
              ) : (
                <p className="text-muted-foreground text-xs">{t("rag.chat.topKHint")}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rag-rerank-top-k">{t("rag.chat.rerankTopKLabel")}</Label>
              <Input
                id="rag-rerank-top-k"
                type="number"
                min={1}
                step={1}
                value={rerankTopK}
                onChange={(event) => setRerankTopK(event.target.value)}
                placeholder={t("rag.chat.optional")}
                disabled={busy}
              />
              {rerankTopKInvalid ? (
                <p className="text-destructive text-xs">{t("rag.chat.invalidInteger")}</p>
              ) : (
                <p className="text-muted-foreground text-xs">{t("rag.chat.rerankTopKHint")}</p>
              )}
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            <Button
              onClick={() => ask.mutate(buildAskInput())}
              disabled={!question.trim() || busy || inputsInvalid}
            >
              {ask.isPending ? t("rag.chat.asking") : t("rag.chat.ask")}
            </Button>
            {canSearch ? (
              <Button
                variant="outline"
                onClick={() => search.mutate(buildSearchInput())}
                disabled={!question.trim() || busy || inputsInvalid}
              >
                <SearchIcon className="size-4" />
                {search.isPending ? t("rag.chat.searching") : t("rag.chat.searchOnly")}
              </Button>
            ) : null}
          </div>

          {ask.isError ? (
            <p className="text-destructive flex items-center gap-2 text-sm">
              <AlertCircleIcon className="size-4" />
              {apiErrorMessage(ask.error)}
            </p>
          ) : null}
          {canSearch && search.isError ? (
            <p className="text-destructive flex items-center gap-2 text-sm">
              <AlertCircleIcon className="size-4" />
              {apiErrorMessage(search.error)}
            </p>
          ) : null}
        </CardContent>
      </Card>

      {answer ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("rag.chat.answerTitle")}</CardTitle>
            <CardDescription>
              {t("rag.chat.answerDescription", {
                model: answer.model_id,
                hits: answer.hits_used,
                retriever: answer.retriever,
                reranker: answer.reranker,
                // The mode that actually ran, not the local selector state:
                // a retriever may degrade a supported mode.
                mode: answer.mode,
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {answerQuestion ? (
              <p className="text-muted-foreground text-sm">
                {t("rag.chat.asked", { question: answerQuestion })}
              </p>
            ) : null}
            {answer.requested_mode !== answer.mode ? (
              <Badge variant="outline">
                {t("rag.chat.modeFellBack", {
                  requested: answer.requested_mode,
                  mode: answer.mode,
                })}
              </Badge>
            ) : null}
            {answer.no_hits ? (
              <div className="space-y-1">
                <p className="font-medium">{t("rag.chat.noHitsTitle")}</p>
                <p className="text-muted-foreground text-sm">{t("rag.chat.noHitsHint")}</p>
              </div>
            ) : (
              <p className="text-sm whitespace-pre-wrap">{answer.answer}</p>
            )}

            <div className="space-y-2">
              <p className="text-sm font-medium">{t("rag.chat.citationsTitle")}</p>
              {answer.citations.length === 0 ? (
                <p className="text-muted-foreground text-sm">{t("rag.chat.citationsEmpty")}</p>
              ) : (
                <ul className="space-y-2">
                  {answer.citations.map((citation) => (
                    <li key={citation.chunk_id} className="rounded-md border p-3">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <CitationBadge citation={citation} />
                        <Badge variant="outline" className="font-mono">
                          {citation.document_id.slice(0, 8)}
                        </Badge>
                        <span className="text-muted-foreground text-xs">
                          {t("rag.common.score")}: {citation.score.toFixed(4)}
                        </span>
                      </div>
                      <p className="text-muted-foreground text-sm whitespace-pre-wrap">
                        {citation.text_preview}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {hits ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("rag.chat.searchResultsTitle")}</CardTitle>
            <CardDescription>
              {t("rag.chat.searchResultsDescription", {
                retriever: hits.retriever,
                mode: hits.mode,
                count: hits.hits.length,
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {hitsQuestion ? (
              <p className="text-muted-foreground text-sm">
                {t("rag.chat.asked", { question: hitsQuestion })}
              </p>
            ) : null}
            {hits.requested_mode !== hits.mode ? (
              <Badge variant="outline">
                {t("rag.chat.modeFellBack", {
                  requested: hits.requested_mode,
                  mode: hits.mode,
                })}
              </Badge>
            ) : null}
            {hits.hits.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("rag.chat.searchEmpty")}</p>
            ) : (
              <ul className="space-y-2">
                {hits.hits.map((hit) => (
                  <li key={hit.chunk_id} className="rounded-md border p-3">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <Badge variant="secondary" className="font-mono">
                        #{hit.ordinal} · {hit.chunk_id.slice(0, 8)}
                      </Badge>
                      <Badge variant="outline" className="font-mono">
                        {hit.document_id.slice(0, 8)}
                      </Badge>
                      <span className="text-muted-foreground text-xs">
                        {t("rag.common.score")}: {hit.score.toFixed(4)}
                      </span>
                    </div>
                    <p className="text-sm whitespace-pre-wrap">{hit.text}</p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
