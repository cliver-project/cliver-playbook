import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AlertCircleIcon, PlayIcon, UploadIcon } from "lucide-react";
import { toast } from "sonner";

import { apiErrorMessage } from "cliver-playbook-app-basic/api/client.ts";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "cliver-playbook-app-basic/components/ui/table.tsx";
import {
  activateRules,
  listEvalRuns,
  listRuleSets,
  previewRules,
  proposeRules,
  type IntentRule,
} from "cliver-playbook-app-rag-governance/api/governance.ts";
import { JsonTextArea, parseJsonText } from "cliver-playbook-app-rag-governance/components/gov/JsonTextArea.tsx";
import { ProjectPicker } from "cliver-playbook-app-rag-governance/components/gov/ProjectPicker.tsx";
import { StatusBadge } from "cliver-playbook-app-rag-governance/components/gov/StatusBadge.tsx";
import { useCurrentProject } from "cliver-playbook-app-rag-governance/components/gov/useProject.ts";

/**
 * Intent rules: the project's semantics, as a versioned rule set.
 *
 * A rule set is proposed, gated by a passing evaluation, then activated —
 * the page makes the gate visible instead of hiding it behind a button:
 * activation asks for the passing run and shows which one it used. The
 * preview box is the demo moment: type a customer question, watch the
 * matched intent, confidence and strategy — before anything is activated.
 *
 * Rules are edited as JSON. The server's IntentRule schema is the contract;
 * duplicating its fields as form controls would fork the contract on every
 * server release, so the page validates shape client-side (well-formed JSON
 * and an array) and lets the server's 422 name the offending rule.
 */
const PROP_PLACEHOLDER = `[
  {
    "intent": "policy_question",
    "priority": 100,
    "classifier": { "config": { "keywords": ["口径", "政策"] } },
    "strategy": "retrieval"
  }
]`;

export default function GovRulesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { projectId } = useCurrentProject();

  const ruleSets = useQuery({
    queryKey: ["gov-rules", projectId],
    queryFn: () => listRuleSets(projectId!),
    enabled: projectId !== null,
  });
  const evalRuns = useQuery({
    queryKey: ["gov-evals", projectId],
    queryFn: () => listEvalRuns(projectId!),
    enabled: projectId !== null,
  });

  const sets = ruleSets.data?.items ?? [];
  const activeSet = sets.find((set) => set.status === "active");
  const proposedSet = sets.find((set) => set.status === "proposed");
  const passedRuns = (evalRuns.data?.items ?? []).filter((run) => run.status === "passed");

  const [proposeText, setProposeText] = useState("");
  const proposeParsed = useMemo(() => parseJsonText(proposeText), [proposeText]);
  // Narrowed once, here, so the mutation below closes over a plain array
  // instead of re-deriving the guard.
  const proposedRules: IntentRule[] | null =
    "value" in proposeParsed && Array.isArray(proposeParsed.value) && proposeParsed.value.length > 0
      ? (proposeParsed.value as IntentRule[])
      : null;

  const [question, setQuestion] = useState("");
  const [matches, setMatches] = useState<Awaited<ReturnType<typeof previewRules>>["matches"] | null>(null);

  const [activateRunId, setActivateRunId] = useState<string | null>(null);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["gov-rules", projectId] });
    void queryClient.invalidateQueries({ queryKey: ["gov-projects"] });
  };

  const propose = useMutation({
    mutationFn: () => proposeRules(projectId!, proposedRules!),
    onSuccess: () => {
      toast.success(t("gov.rules.proposedToast"));
      setProposeText("");
      invalidate();
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  const preview = useMutation({
    mutationFn: () => previewRules(projectId!, question),
    onSuccess: (data) => setMatches(data.matches),
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  const activate = useMutation({
    mutationFn: () => {
      const source = proposedSet ?? activeSet;
      if (!source || !activateRunId) throw new Error(t("gov.rules.activateMissing"));
      return activateRules(projectId!, source.rules, activateRunId);
    },
    onSuccess: () => {
      toast.success(t("gov.rules.activatedToast"));
      setActivateRunId(null);
      invalidate();
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">{t("gov.rules.title")}</h1>
          <p className="text-muted-foreground max-w-2xl">{t("gov.rules.description")}</p>
        </div>
        <ProjectPicker />
      </section>

      {ruleSets.isError ? (
        <p className="text-destructive flex items-center gap-2 text-sm">
          <AlertCircleIcon className="size-4" />
          {t("gov.rules.loadFailed")} ({apiErrorMessage(ruleSets.error)})
        </p>
      ) : sets.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("gov.rules.empty")}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("gov.rules.setsTitle")}</CardTitle>
            <CardDescription>{t("gov.rules.setsDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("gov.rules.version")}</TableHead>
                  <TableHead>{t("gov.common.status")}</TableHead>
                  <TableHead>{t("gov.rules.evalGate")}</TableHead>
                  <TableHead className="text-right">{t("gov.rules.rulesCount")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sets.map((set) => (
                  <TableRow key={set.version ?? "none"}>
                    <TableCell className="font-mono">{set.version ?? "—"}</TableCell>
                    <TableCell>{set.status ? <StatusBadge status={set.status} /> : "—"}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {set.eval_run_id ?? t("gov.rules.noGate")}
                    </TableCell>
                    <TableCell className="text-right">{set.rules?.length ?? 0}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {activeSet && activeSet.rules.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>
              {t("gov.rules.activeTitle")} · {t("gov.rules.version")} {activeSet.version}
            </CardTitle>
            <CardDescription>{t("gov.rules.activeDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("gov.rules.intent")}</TableHead>
                  <TableHead>{t("gov.rules.priority")}</TableHead>
                  <TableHead>{t("gov.rules.strategy")}</TableHead>
                  <TableHead>{t("gov.rules.keywords")}</TableHead>
                  <TableHead>{t("gov.rules.tools")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activeSet.rules.map((rule) => (
                  <TableRow key={rule.intent}>
                    <TableCell className="font-mono text-xs">{rule.intent}</TableCell>
                    <TableCell>{rule.priority ?? 100}</TableCell>
                    <TableCell>
                      <StatusBadge status={rule.strategy ?? "retrieval"} />
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {(rule.classifier?.config?.keywords ?? []).join(", ") || "—"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {(rule.tools ?? []).join(", ") || "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{t("gov.rules.previewTitle")}</CardTitle>
          <CardDescription>{t("gov.rules.previewDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-64 flex-1 space-y-1.5">
              <Label htmlFor="gov-preview-question">{t("gov.rules.questionLabel")}</Label>
              <Input
                id="gov-preview-question"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder={t("gov.rules.questionPlaceholder")}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && question.trim()) preview.mutate();
                }}
              />
            </div>
            <Button onClick={() => preview.mutate()} disabled={!projectId || !question.trim() || preview.isPending}>
              <PlayIcon className="size-4" />
              {preview.isPending ? t("gov.rules.previewing") : t("gov.rules.preview")}
            </Button>
          </div>
          {matches ? (
            matches.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("gov.rules.previewNoMatch")}</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {matches.map((match, index) => (
                  <li key={index} className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={match.strategy} />
                    <span className="font-mono text-xs">{match.intent}</span>
                    <span className="text-muted-foreground text-xs">
                      {t("gov.rules.confidence", { value: match.confidence })} ·{" "}
                      {t("gov.rules.priority")} {match.priority}
                    </span>
                  </li>
                ))}
              </ul>
            )
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("gov.rules.proposeTitle")}</CardTitle>
          <CardDescription>{t("gov.rules.proposeDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <JsonTextArea
            value={proposeText}
            onChange={setProposeText}
            placeholder={PROP_PLACEHOLDER}
            rows={10}
            disabled={propose.isPending}
          />
          <Button
            onClick={() => propose.mutate()}
            disabled={!projectId || proposedRules === null || propose.isPending}
          >
            <UploadIcon className="size-4" />
            {propose.isPending ? t("gov.rules.proposing") : t("gov.rules.propose")}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("gov.rules.activateTitle")}</CardTitle>
          <CardDescription>{t("gov.rules.activateDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1.5">
              <Label>{t("gov.rules.evalGate")}</Label>
              <Select
                value={activateRunId ?? undefined}
                onValueChange={setActivateRunId}
                disabled={passedRuns.length === 0}
              >
                <SelectTrigger className="w-80">
                  <SelectValue
                    placeholder={
                      passedRuns.length === 0
                        ? t("gov.rules.noPassedRuns")
                        : t("gov.rules.pickRun")
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {passedRuns.map((run) => (
                    <SelectItem key={run.id} value={run.id}>
                      {run.created_at.slice(0, 19).replace("T", " ")} · {run.stage} ·{" "}
                      {run.summary}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              onClick={() => activate.mutate()}
              disabled={!projectId || !activateRunId || !proposedSet || activate.isPending}
            >
              {activate.isPending ? t("gov.rules.activating") : t("gov.rules.activate")}
            </Button>
          </div>
          {!proposedSet ? (
            <p className="text-muted-foreground text-sm">{t("gov.rules.nothingToActivate")}</p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
