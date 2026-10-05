import {
  Badge,
  Button,
  Caption1,
  Subtitle2,
  makeStyles,
  mergeClasses,
  tokens,
  type BadgeProps,
} from "@fluentui/react-components";
import { useState } from "react";
import { api, type Workflow } from "../../api/client";
import { ProblemMessage } from "../../components/ProblemMessage";

const STEP_LABELS: Record<string, { text: string; color: BadgeProps["color"] }> = {
  pending: { text: "Waiting", color: "informative" },
  running: { text: "Running", color: "brand" },
  awaiting_review: { text: "Needs your review", color: "warning" },
  completed: { text: "Done", color: "success" },
  skipped: { text: "Skipped", color: "subtle" },
  failed: { text: "Failed", color: "danger" },
};

const WORKFLOW_LABELS: Record<string, string> = {
  running: "Running",
  awaiting_review: "Waiting for your review",
  completed: "Completed",
  failed: "Stopped at a failed step",
  cancelled: "Cancelled",
};

const useStyles = makeStyles({
  root: {
    display: "grid",
    gap: tokens.spacingVerticalS,
    padding: tokens.spacingVerticalM,
    borderRadius: tokens.borderRadiusMedium,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  header: { display: "flex", gap: tokens.spacingHorizontalS, alignItems: "center", flexWrap: "wrap" },
  steps: { margin: 0, paddingLeft: tokens.spacingHorizontalL, display: "grid", gap: tokens.spacingVerticalXS },
  step: { display: "flex", gap: tokens.spacingHorizontalS, alignItems: "baseline", flexWrap: "wrap" },
  current: { fontWeight: tokens.fontWeightSemibold },
  muted: { color: tokens.colorNeutralForeground3 },
  actions: { display: "flex", gap: tokens.spacingHorizontalS },
});

interface Props {
  projectId: string;
  workflow: Workflow;
  onChanged: (workflow: Workflow) => void;
}

export function WorkflowProgress({ projectId, workflow, onChanged }: Props) {
  const styles = useStyles();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const finished = workflow.status === "completed" || workflow.status === "cancelled";

  const act = async (action: "resume" | "cancel") => {
    setBusy(true);
    setError(null);
    try {
      const next =
        action === "resume"
          ? await api.resumeWorkflow(projectId, workflow.id)
          : await api.cancelWorkflow(projectId, workflow.id);
      onChanged(next);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.root} aria-label={`Workflow: ${workflow.name}`}>
      <div className={styles.header}>
        <Subtitle2 as="h2">{workflow.name}</Subtitle2>
        <Caption1 role="status">{WORKFLOW_LABELS[workflow.status] ?? workflow.status}</Caption1>
      </div>
      <ol className={styles.steps} aria-label="Workflow steps">
        {workflow.steps.map((step, index) => {
          const label = STEP_LABELS[step.status] ?? { text: step.status, color: "informative" as const };
          const isCurrent = !finished && index === workflow.current_step;
          return (
            <li key={step.id} aria-current={isCurrent ? "step" : undefined}>
              <div className={styles.step}>
                <span className={mergeClasses(isCurrent && styles.current)}>{step.title}</span>
                <Badge appearance="tint" color={label.color} size="small">
                  {label.text}
                </Badge>
                {step.attempts > 1 && <Caption1 className={styles.muted}>attempt {step.attempts}</Caption1>}
              </div>
              {step.reason && <Caption1 className={styles.muted}>{step.reason}</Caption1>}
            </li>
          );
        })}
      </ol>
      {error !== null && <ProblemMessage error={error} />}
      {!finished && (
        <div className={styles.actions}>
          {workflow.can_resume && (
            <Button appearance="primary" size="small" disabled={busy} onClick={() => void act("resume")}>
              {workflow.status === "failed" ? "Retry step" : "Resume"}
            </Button>
          )}
          <Button size="small" disabled={busy} onClick={() => void act("cancel")}>
            Cancel workflow
          </Button>
        </div>
      )}
    </section>
  );
}
