import {
  Body1,
  Button,
  Field,
  Input,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  MessageBarTitle,
  Textarea,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useState } from "react";
import {
  ApiError,
  api,
  type ImpactReport,
  type SpecRevision,
  type SpecUpdate,
  type ValidationResult,
} from "../../api/client";
import { ProblemMessage } from "../../components/ProblemMessage";

const useStyles = makeStyles({
  root: { display: "grid", gap: tokens.spacingVerticalM },
  editor: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200, minHeight: "420px" },
  actions: { display: "flex", gap: tokens.spacingHorizontalS, flexWrap: "wrap", alignItems: "end" },
  summary: { flexGrow: 1, minWidth: "240px" },
  list: { margin: `${tokens.spacingVerticalXS} 0 0`, paddingLeft: tokens.spacingHorizontalL },
});

interface Props {
  projectId: string;
  revision: SpecRevision;
  etag: string;
  onSaved: (next: { revision: SpecRevision; etag: string }) => void;
  onReload: () => void;
}

type Feedback =
  | { kind: "parse"; message: string }
  | { kind: "conflict"; error: ApiError }
  | { kind: "error"; error: unknown }
  | { kind: "validated"; result: ValidationResult }
  | { kind: "impact"; report: ImpactReport }
  | { kind: "unchanged" };

function parse(text: string): { ok: true; value: unknown } | { ok: false; message: string } {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch (error) {
    return { ok: false, message: error instanceof Error ? error.message : "Invalid JSON" };
  }
}

/**
 * Milestone 1 editor: the canonical spec as JSON, validated and saved by the
 * backend with optimistic concurrency. Structured, section-by-section editors
 * replace this in Milestone 2; the save contract stays the same.
 */
export function SpecEditorTab({ projectId, revision, etag, onSaved, onReload }: Props) {
  const styles = useStyles();
  const original = JSON.stringify(revision.spec, null, 2);
  const [text, setText] = useState(original);
  const [changeSummary, setChangeSummary] = useState("");
  const [busy, setBusy] = useState<"validate" | "impact" | "save" | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const dirty = text !== original;

  const validate = async () => {
    const parsed = parse(text);
    if (!parsed.ok) return setFeedback({ kind: "parse", message: parsed.message });
    setBusy("validate");
    try {
      setFeedback({ kind: "validated", result: await api.validateSpec(projectId, parsed.value) });
    } catch (error) {
      setFeedback({ kind: "error", error });
    } finally {
      setBusy(null);
    }
  };

  const previewImpact = async () => {
    const parsed = parse(text);
    if (!parsed.ok) return setFeedback({ kind: "parse", message: parsed.message });
    setBusy("impact");
    try {
      setFeedback({ kind: "impact", report: await api.previewImpact(projectId, parsed.value) });
    } catch (error) {
      setFeedback({ kind: "error", error });
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    const parsed = parse(text);
    if (!parsed.ok) return setFeedback({ kind: "parse", message: parsed.message });
    setBusy("save");
    setFeedback(null);
    try {
      const result = await api.saveSpec(
        projectId,
        { spec: parsed.value as SpecUpdate["spec"], change_summary: changeSummary.trim() || null },
        etag,
      );
      if (result.created) {
        onSaved({ revision: result.revision, etag: result.etag });
      } else {
        setFeedback({ kind: "unchanged" });
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "revision-conflict") {
        setFeedback({ kind: "conflict", error });
      } else {
        setFeedback({ kind: "error", error });
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={styles.root}>
      <Body1>
        Editing revision r{revision.revision}. The backend validates structure and references on every save and records
        a new immutable revision.
      </Body1>
      <Field label="Specification (JSON)">
        <Textarea
          className={styles.editor}
          textarea={{ className: styles.editor, spellCheck: false }}
          value={text}
          resize="vertical"
          onChange={(_, data) => setText(data.value)}
        />
      </Field>
      <div className={styles.actions}>
        <Field label="Change summary" className={styles.summary} hint="Shown in the revision history. Optional.">
          <Input value={changeSummary} maxLength={500} onChange={(_, data) => setChangeSummary(data.value)} />
        </Field>
        <Button onClick={validate} disabled={busy !== null}>
          {busy === "validate" ? "Validating…" : "Validate"}
        </Button>
        <Button onClick={previewImpact} disabled={busy !== null || !dirty}>
          {busy === "impact" ? "Comparing…" : "Preview impact"}
        </Button>
        <Button appearance="primary" onClick={save} disabled={busy !== null || !dirty}>
          {busy === "save" ? "Saving…" : "Save revision"}
        </Button>
        <Button appearance="subtle" onClick={() => setText(original)} disabled={busy !== null || !dirty}>
          Discard changes
        </Button>
      </div>

      {feedback?.kind === "parse" && (
        <MessageBar intent="error" role="alert">
          <MessageBarBody>
            <MessageBarTitle>The JSON is not valid</MessageBarTitle>
            {feedback.message}
          </MessageBarBody>
        </MessageBar>
      )}
      {feedback?.kind === "conflict" && (
        <MessageBar intent="warning" role="alert" layout="multiline">
          <MessageBarBody>
            <MessageBarTitle>Someone saved a newer revision</MessageBarTitle>
            {feedback.error.problem.detail} Copy your edits before reloading; reloading replaces the editor contents.
          </MessageBarBody>
          <MessageBarActions>
            <Button onClick={onReload}>Reload latest</Button>
          </MessageBarActions>
        </MessageBar>
      )}
      {feedback?.kind === "error" && <ProblemMessage error={feedback.error} />}
      {feedback?.kind === "unchanged" && (
        <MessageBar intent="info">
          <MessageBarBody>No changes to save: the content matches revision r{revision.revision}.</MessageBarBody>
        </MessageBar>
      )}
      {feedback?.kind === "validated" && (
        <MessageBar intent={feedback.result.valid ? "success" : "error"} role="status" layout="multiline">
          <MessageBarBody>
            <MessageBarTitle>
              {feedback.result.valid ? "Valid specification" : "The specification has errors"}
            </MessageBarTitle>
            {feedback.result.issues.length === 0 ? (
              "No issues found."
            ) : (
              <ul className={styles.list} aria-label="Validation issues">
                {feedback.result.issues.map((issue) => (
                  <li key={`${issue.path}:${issue.code}`}>
                    {issue.severity === "error" ? "Error" : "Warning"} at {issue.path}: {issue.message}
                  </li>
                ))}
              </ul>
            )}
          </MessageBarBody>
        </MessageBar>
      )}
      {feedback?.kind === "impact" && <ImpactSummary report={feedback.report} />}
    </div>
  );
}

function describe(label: string, changes: ImpactReport["entities"]): string | null {
  const parts = [
    changes.added.length ? `added ${changes.added.join(", ")}` : "",
    changes.removed.length ? `removed ${changes.removed.join(", ")}` : "",
    changes.changed.length ? `changed ${changes.changed.join(", ")}` : "",
  ].filter(Boolean);
  return parts.length ? `${label}: ${parts.join("; ")}` : null;
}

function ImpactSummary({ report }: { report: ImpactReport }) {
  const styles = useStyles();
  const lines = [describe("Entities", report.entities), describe("Screens", report.screens)].filter(
    (line): line is string => line !== null,
  );
  const intent = !report.spec_valid || report.generation_blocked ? "warning" : "info";
  return (
    <MessageBar intent={intent} role="status" layout="multiline">
      <MessageBarBody>
        <MessageBarTitle>Impact compared with r{report.base_revision} (nothing saved)</MessageBarTitle>
        {report.note && <Body1>{report.note}</Body1>}
        {lines.length > 0 && (
          <ul className={styles.list} aria-label="Changes to entities and screens">
            {lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
        {report.ui_issues.length > 0 && (
          <ul className={styles.list} aria-label="Screen errors">
            {report.ui_issues.map((issue) => (
              <li key={`${issue.path}:${issue.code}`}>{issue.message}</li>
            ))}
          </ul>
        )}
        {report.files.length > 0 && (
          <ul className={styles.list} aria-label="Generated files that would change">
            {report.files.map((f) => (
              <li key={f.path}>
                {f.path} · {f.status} · +{f.additions} −{f.deletions}
              </li>
            ))}
          </ul>
        )}
        {report.spec_valid && !report.generation_blocked && report.files.length === 0 && lines.length === 0 && (
          <Body1>No effect on the screens or the generated code.</Body1>
        )}
      </MessageBarBody>
    </MessageBar>
  );
}
