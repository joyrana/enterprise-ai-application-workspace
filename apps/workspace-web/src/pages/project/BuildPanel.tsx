import { Badge, Body1, Button, Caption1, Spinner, Subtitle2, makeStyles, tokens } from "@fluentui/react-components";
import { useEffect, useState } from "react";
import { api, type Build, type BuildPage } from "../../api/client";
import { ProblemMessage } from "../../components/ProblemMessage";
import { useAsync } from "../../hooks/useAsync";

const useStyles = makeStyles({
  root: { display: "grid", gap: tokens.spacingVerticalS },
  row: { display: "flex", gap: tokens.spacingHorizontalS, alignItems: "center", flexWrap: "wrap" },
  steps: { margin: 0, paddingLeft: tokens.spacingHorizontalL },
  log: {
    margin: 0,
    padding: tokens.spacingHorizontalM,
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusMedium,
    overflow: "auto",
    maxHeight: "30vh",
    whiteSpace: "pre",
  },
});

const ACTIVE = new Set(["queued", "running"]);
const POLL_MS = 3000;

const LABELS: Record<Build["status"], { text: string; color: "informative" | "success" | "danger" | "warning" }> = {
  queued: { text: "Queued", color: "informative" },
  running: { text: "Building", color: "informative" },
  succeeded: { text: "Built", color: "success" },
  failed: { text: "Build failed", color: "danger" },
  timed_out: { text: "Timed out", color: "warning" },
  output_too_large: { text: "Output too large", color: "warning" },
  rejected: { text: "Rejected before building", color: "danger" },
  runner_error: { text: "Runner error", color: "warning" },
};

/** Builds of the generated project in the isolated runner (ADR-0015). */
export function BuildPanel({ projectId, revision }: { projectId: string; revision: number }) {
  const styles = useStyles();
  const { state, reload, setData } = useAsync<BuildPage>(
    (signal) => api.listBuilds(projectId, signal),
    `${projectId}:builds`,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const latest = state.status === "success" ? state.data.items[0] : undefined;
  const active = latest !== undefined && ACTIVE.has(latest.status);

  // Poll quietly (no spinner) while the latest build is queued or running.
  useEffect(() => {
    if (!active) return undefined;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      api.listBuilds(projectId, controller.signal).then(setData, () => undefined);
    }, POLL_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [active, latest, projectId, setData]);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.requestBuild(projectId, revision);
      reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.root} aria-labelledby="builds-heading">
      <Subtitle2 as="h3" id="builds-heading">
        Isolated build
      </Subtitle2>
      <Caption1>
        Builds r{revision} in a container with no network and no credentials. A separate build worker runs queued
        builds; nothing generated runs inside the workspace.
      </Caption1>
      <div className={styles.row}>
        <Button disabled={busy || active} onClick={() => void start()}>
          {active ? "Build in progress" : "Build in isolated runner"}
        </Button>
      </div>
      {error !== null && <ProblemMessage error={error} />}
      {state.status === "loading" && <Spinner size="tiny" label="Loading builds" />}
      {state.status === "error" && <ProblemMessage error={state.error} onRetry={reload} />}
      {state.status === "success" && latest === undefined && <Body1>No builds yet.</Body1>}
      {latest !== undefined && <BuildDetails build={latest} />}
    </section>
  );
}

function BuildDetails({ build }: { build: Build }) {
  const styles = useStyles();
  const label = LABELS[build.status];
  const report = build.report;
  return (
    <div className={styles.root}>
      <div className={styles.row}>
        <Badge appearance="tint" color={label.color}>
          {label.text}
        </Badge>
        <Caption1>
          r{build.spec_revision} · {build.generator}
          {report ? ` · ${(report.duration_ms / 1000).toFixed(1)} s` : ""}
          {report && build.status === "succeeded" ? ` · ${Object.keys(report.artifacts).length} files built` : ""}
        </Caption1>
      </div>
      {build.status === "queued" && <Body1>Waiting for a build worker.</Body1>}
      {report?.reason && <Body1>{report.reason}</Body1>}
      {report && report.steps.length > 0 && (
        <ul className={styles.steps} aria-label="Build steps">
          {report.steps.map((step) => (
            <li key={step.name}>
              {step.name}: {step.exit_code === 0 ? "passed" : `failed (exit ${step.exit_code})`} in{" "}
              {(step.duration_ms / 1000).toFixed(1)} s
            </li>
          ))}
        </ul>
      )}
      {report && report.log_tail.length > 0 && (
        <pre className={styles.log} role="region" aria-label="Build log" tabIndex={0}>
          {report.log_tail.join("\n")}
        </pre>
      )}
      {report && report.isolation.length > 0 && <Caption1>Isolation: {report.isolation.join(" · ")}</Caption1>}
    </div>
  );
}
