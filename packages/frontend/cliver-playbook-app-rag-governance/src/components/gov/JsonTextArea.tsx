import { useTranslation } from "react-i18next";

import { Textarea } from "cliver-playbook-app-basic/components/ui/textarea.tsx";

/**
 * Parse JSON text, or report why it failed — the helper the structured
 * editors below pair with the textarea so their submit buttons can gate on
 * well-formedness without duplicating try/catch blocks.
 */
export function parseJsonText(text: string): { value: unknown } | { error: string } {
  try {
    return { value: JSON.parse(text) as unknown };
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

/**
 * Parse JSON Lines (one JSON value per line), the golden-set wire format.
 *
 * Parsing the whole document as JSON is wrong by construction here: two
 * cases on two lines are not one JSON value. Empty lines (the exporter's
 * trailing newline, human spacing) are skipped; the first bad line names
 * itself in the error.
 */
export function parseJsonLinesText(
  text: string,
): { value: unknown[]; lineCount: number } | { error: string; line: number } {
  const lines = text.split("\n");
  const parsed: unknown[] = [];
  let lineCount = 0;
  for (const [index, raw] of lines.entries()) {
    const line = raw.trim();
    if (!line) continue;
    lineCount += 1;
    try {
      parsed.push(JSON.parse(line) as unknown);
    } catch (error) {
      return {
        error: error instanceof Error ? error.message : String(error),
        line: index + 1,
      };
    }
  }
  return { value: parsed, lineCount };
}

/**
 * A textarea for a structured document — either one JSON value
 * (`format="json"`) or JSON Lines (`format="jsonl"`).
 *
 * Empty input is not an error: the hint explains the expected shape and the
 * owning form disables its submit until there is content.
 */
export function JsonTextArea({
  value,
  onChange,
  rows = 12,
  placeholder,
  id,
  disabled,
  format = "json",
}: {
  value: string;
  onChange: (text: string) => void;
  rows?: number;
  placeholder?: string;
  id?: string;
  disabled?: boolean;
  format?: "json" | "jsonl";
}) {
  const { t } = useTranslation();
  const empty = value.trim() === "";
  const jsonParsed = parseJsonText(value);
  const linesParsed = parseJsonLinesText(value);

  let message: { tone: "error" | "muted"; text: string };
  if (format === "jsonl") {
    if (empty) {
      message = { tone: "muted", text: t("gov.common.jsonlHint") };
    } else if ("error" in linesParsed) {
      message = {
        tone: "error",
        text: t("gov.common.invalidJsonLine", {
          line: linesParsed.line,
          error: linesParsed.error,
        }),
      };
    } else {
      message = {
        tone: "muted",
        text: t("gov.common.jsonlValid", { count: linesParsed.lineCount }),
      };
    }
  } else if (empty) {
    message = { tone: "muted", text: t("gov.common.emptyDocument") };
  } else if ("error" in jsonParsed) {
    message = { tone: "error", text: `${t("gov.common.invalidJson")}: ${jsonParsed.error}` };
  } else {
    message = { tone: "muted", text: t("gov.common.validJson") };
  }

  return (
    <div className="space-y-1.5">
      <Textarea
        id={id}
        rows={rows}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        className="font-mono text-xs"
        spellCheck={false}
      />
      <p className={message.tone === "error" ? "text-destructive text-xs" : "text-muted-foreground text-xs"}>
        {message.text}
      </p>
    </div>
  );
}
