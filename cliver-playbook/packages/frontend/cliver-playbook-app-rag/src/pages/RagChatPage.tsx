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
} from "cliver-playbook-app-rag/api/rag.ts";
import { CitationBadge } from "cliver-playbook-app-rag/components/rag/CitationBadge.tsx";
import { StageSelector } from "cliver-playbook-app-rag/components/rag/StageSelector.tsx";

/**
 * Grounded chat over the knowledge base, with every stage selectable.
 *
 * The retriever, embedder, reranker and LLM come from the server's stage
 * catalog; the mode decides which retrieval leg(s) run. An override is sent
 * only when the user actually changes a stage — omitting a field lets the
 * server apply its configured default, which keeps the page on the same
 * defaults a scripted client gets.
 *
 * The query embedder matters for the dense leg: vectors from different
 * embedders are not comparable, so a user who indexed documents with a
 * non-default embedder must select the same one here, or dense retrieval
 * silently finds nothing. The documents page shows each row's embedder for
 * exactly that reason.
 *
 * Two actions share the form. "Ask" retrieves, reranks and generates, and
 * renders the answer with citations. "Search only" stops after retrieval,
 * which is how a user inspects which chunks a stage combination finds — and
 * how the dense/sparse/hybrid selector becomes observable rather than a black
 * box. A `no_hits` answer is a successful refusal from the server (the
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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : apiErrorMessage(error);
}

function parsePositive(raw: string): number | undefined {
  const value = Number(raw);
  return raw.trim() && Number.isFinite(value) && value > 0 ? value : undefined;
}

export default function RagChatPage() {
  const { t } = useTranslation();

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
  const [hits, setHits] = useState<SearchResponse | null>(null);

  const effectiveRetriever = retriever ?? catalog.data?.defaults.retriever ?? "";
  const effectiveEmbedder = embedder ?? catalog.data?.defaults.embedder ?? "";
  const effectiveReranker = reranker ?? catalog.data?.defaults.reranker ?? "";
  const effectiveLlm = llm ?? catalog.data?.defaults.llm ?? "";

  const ask = useMutation({
    mutationFn: () =>
      chatRag({
        question,
        mode,
        top_k: parsePositive(topK),
        rerank_top_k: parsePositive(rerankTopK),
        // Only explicit overrides travel; absent fields keep server defaults.
        retriever: retriever ?? undefined,
        embedder: embedder ?? undefined,
        reranker: reranker ?? undefined,
        llm: llm ?? undefined,
      }),
    onSuccess: (data) => {
      setAnswer(data);
      setHits(null);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const search = useMutation({
    mutationFn: () =>
      searchRag({
        query: question,
        mode,
        top_k: parsePositive(topK),
        retriever: retriever ?? undefined,
        embedder: embedder ?? undefined,
      }),
    onSuccess: (data) => {
      setHits(data);
      setAnswer(null);
    },
    onError: (error) => toast.error(errorMessage(error)),
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
              options={catalog.data?.embedders ?? []}
              onChange={setEmbedder}
              disabled={busy}
              description={t("rag.chat.embedderHint")}
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
                value={mode}
                onValueChange={(value) => setMode(value as RetrievalMode)}
                disabled={busy}
              >
                <SelectTrigger id="rag-mode" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MODES.map((value) => (
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
                value={topK}
                onChange={(event) => setTopK(event.target.value)}
                placeholder={t("rag.chat.optional")}
                disabled={busy}
              />
              <p className="text-muted-foreground text-xs">{t("rag.chat.topKHint")}</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rag-rerank-top-k">{t("rag.chat.rerankTopKLabel")}</Label>
              <Input
                id="rag-rerank-top-k"
                type="number"
                min={1}
                value={rerankTopK}
                onChange={(event) => setRerankTopK(event.target.value)}
                placeholder={t("rag.chat.optional")}
                disabled={busy}
              />
              <p className="text-muted-foreground text-xs">{t("rag.chat.rerankTopKHint")}</p>
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            <Button onClick={() => ask.mutate()} disabled={!question.trim() || busy}>
              {ask.isPending ? t("rag.chat.asking") : t("rag.chat.ask")}
            </Button>
            <Button
              variant="outline"
              onClick={() => search.mutate()}
              disabled={!question.trim() || busy}
            >
              <SearchIcon className="size-4" />
              {search.isPending ? t("rag.chat.searching") : t("rag.chat.searchOnly")}
            </Button>
          </div>
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
                mode,
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
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
          <CardContent>
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
