import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { SendIcon, WrenchIcon } from "lucide-react";
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
import { askGoverned, type QueryResponse } from "cliver-playbook-app-rag-governance/api/governance.ts";
import { ProjectPicker } from "cliver-playbook-app-rag-governance/components/gov/ProjectPicker.tsx";
import { StatusBadge } from "cliver-playbook-app-rag-governance/components/gov/StatusBadge.tsx";
import { useCurrentProject } from "cliver-playbook-app-rag-governance/components/gov/useProject.ts";

/**
 * The governed query facade — the loop's exit, in public.
 *
 * One question in, one answer out — but unlike the ungoverned chat page, the
 * observations panel is half the product: which intent matched, which
 * strategy it picked, which rule version decided, which documents are
 * cited, which tools ran at which as-of period with what latency. A
 * presenter lets the audience pick the question, then reads the panel left
 * to right: every behaviour above it produced this trace.
 *
 * `as_of` is optional and defaults to the server's now. The finance demo
 * pins 2026-10-31 because its ERP fixture is that period — asking a live
 * tool question without the pin would answer from a period the mock does
 * not have.
 */
export default function GovQueryPage() {
  const { t } = useTranslation();
  const { project, projectId } = useCurrentProject();

  const [question, setQuestion] = useState("");
  const [asOf, setAsOf] = useState("2026-10-31T23:59:59+08:00");
  // A reasoning model spends most of the budget on hidden reasoning; the
  // plain-answer default (1024) would routinely come back empty.
  const [maxTokens, setMaxTokens] = useState("4096");
  const [answer, setAnswer] = useState<QueryResponse | null>(null);

  const ask = useMutation({
    mutationFn: () =>
      askGoverned(projectId!, question, asOf || undefined, Number(maxTokens) || undefined),
    onSuccess: setAnswer,
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  const suggestions = [
    "本月经营情况一屏分析：营收、毛利、净利、应收、应付、流动资金、资产负债率",
    "应收 90 天以上占比多少？有没有预警？",
    "收入确认的口径是什么？坏账怎么计提？",
  ];

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">{t("gov.query.title")}</h1>
          <p className="text-muted-foreground max-w-2xl">{t("gov.query.description")}</p>
        </div>
        <ProjectPicker />
      </section>

      {project && project.status !== "active" ? (
        <p className="text-muted-foreground text-sm">{t("gov.query.notActive", { status: project.status })}</p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{t("gov.query.askTitle")}</CardTitle>
          <CardDescription>{t("gov.query.askDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-72 flex-1 space-y-1.5">
              <Label htmlFor="gov-question">{t("gov.query.questionLabel")}</Label>
              <Input
                id="gov-question"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder={t("gov.query.questionPlaceholder")}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && question.trim()) ask.mutate();
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="gov-as-of">{t("gov.query.asOf")}</Label>
              <Input
                id="gov-as-of"
                value={asOf}
                onChange={(event) => setAsOf(event.target.value)}
                placeholder={t("gov.query.asOfPlaceholder")}
                className="w-64 font-mono text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="gov-max-tokens">{t("gov.query.maxTokens")}</Label>
              <Input
                id="gov-max-tokens"
                type="number"
                min={1}
                max={8192}
                step={256}
                value={maxTokens}
                onChange={(event) => setMaxTokens(event.target.value)}
                className="w-28"
              />
            </div>
            <Button onClick={() => ask.mutate()} disabled={!projectId || !question.trim() || ask.isPending}>
              <SendIcon className="size-4" />
              {ask.isPending ? t("gov.query.asking") : t("gov.query.ask")}
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            {suggestions.map((suggestion) => (
              <Button
                key={suggestion}
                size="sm"
                variant="outline"
                onClick={() => setQuestion(suggestion)}
              >
                {suggestion}
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>

      {answer ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle>{t("gov.query.answerTitle")}</CardTitle>
              <CardDescription>
                {t("gov.query.asOfAnswer", { asOf: answer.as_of.slice(0, 19).replace("T", " ") })}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="whitespace-pre-wrap leading-relaxed">{answer.text}</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("gov.query.observationsTitle")}</CardTitle>
              <CardDescription>{t("gov.query.observationsDescription")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                {answer.refused ? (
                  <Badge variant="destructive">{t("gov.query.refused")}</Badge>
                ) : (
                  <StatusBadge status={answer.strategy} />
                )}
                {answer.intent ? (
                  <span className="font-mono text-xs">{answer.intent}</span>
                ) : null}
                <span className="text-muted-foreground text-xs">
                  {t("gov.query.ruleVersion", { version: answer.rule_version ?? "—" })}
                </span>
              </div>

              {answer.tool_calls.length > 0 ? (
                <div className="space-y-2">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <WrenchIcon className="size-4" />
                    {t("gov.query.toolCalls")}
                  </p>
                  <ul className="space-y-1 text-sm">
                    {answer.tool_calls.map((call, index) => (
                      <li key={index} className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs">{call.name}</span>
                        <Badge variant="outline">
                          {call.row_count} {t("gov.query.rows")}
                        </Badge>
                        <span className="text-muted-foreground text-xs">
                          {call.latency_ms}ms · {call.period ?? "—"}
                          {call.is_snapshot ? ` · ${t("gov.query.snapshot")}` : ""}
                        </span>
                        {call.error ? (
                          <Badge variant="destructive">{call.error}</Badge>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {answer.citations.length > 0 ? (
                <div className="space-y-2">
                  <p className="text-sm font-medium">{t("gov.query.citations")}</p>
                  <ul className="space-y-1 text-sm">
                    {answer.citations.map((citation, index) => (
                      <li key={index} className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{citation.kind}</Badge>
                        <span className="font-mono text-xs">{citation.ref}</span>
                        {citation.locator ? (
                          <span className="text-muted-foreground text-xs">
                            {citation.locator}
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
