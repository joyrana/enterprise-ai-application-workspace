import {
  Badge,
  Body1,
  Button,
  Caption1,
  Field,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  MessageBarTitle,
  Radio,
  RadioGroup,
  Spinner,
  Subtitle2,
  Textarea,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  api,
  type AiStatus,
  type ApplyRunResult,
  type DecisionValue,
  type Run,
  type SpecRevision,
} from "../../api/client";
import { ProblemMessage } from "../../components/ProblemMessage";
import { formatDateTime } from "../../format";
import { GROUP_LABELS, OUTCOME_LABELS, viewProposal, type ProposalGroup, type ProposalView } from "./proposals";

const MAX_CHARS = 8000;
const GROUP_ORDER: ProposalGroup[] = ["facts", "personas", "requirements", "assumptions", "questions", "other"];

const useStyles = makeStyles({
  root: { display: "grid", gap: tokens.spacingVerticalL },
  row: { display: "flex", gap: tokens.spacingHorizontalS, alignItems: "center", flexWrap: "wrap" },
  group: { display: "grid", gap: tokens.spacingVerticalS },
  proposal: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: tokens.spacingHorizontalM,
    alignItems: "start",
    padding: tokens.spacingVerticalS,
    borderRadius: tokens.borderRadiusMedium,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    "@media (max-width: 720px)": { gridTemplateColumns: "1fr" },
  },
  label: { color: tokens.colorNeutralForeground3 },
  detail: { color: tokens.colorNeutralForeground2 },
  list: { margin: 0, paddingLeft: tokens.spacingHorizontalL },
});

interface Props {
  projectId: string;
  etag: string;
  onApplied: (next: { revision: SpecRevision; etag: string }) => void;
  /** Poll interval while a run is in progress. */
  pollMs?: number;
}

function newKey(): string {
  return `discovery-${crypto.randomUUID()}`;
}

function isActive(run: Run | null): boolean {
  return run !== null && (run.status === "queued" || run.status === "running");
}

export function DiscoveryTab({ projectId, etag, onApplied, pollMs = 1500 }: Props) {
  const styles = useStyles();
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [description, setDescription] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<unknown>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(newKey);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoadError(null);
      try {
        const [ai, runs] = await Promise.all([api.aiStatus(signal), api.listRuns(projectId, signal)]);
        setStatus(ai);
        setRun(runs.items[0] ?? null);
      } catch (error) {
        if (!signal?.aborted) setLoadError(error);
      }
    },
    [projectId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  // Poll while the latest run is in progress; resumes automatically after a page refresh.
  const activeRunId = isActive(run) ? run?.id : undefined;
  useEffect(() => {
    if (!activeRunId) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      api.getRun(projectId, activeRunId, controller.signal).then(
        (next) => setRun(next),
        () => undefined, // transient polling errors are retried on the next tick
      );
    }, pollMs);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [activeRunId, projectId, pollMs]);

  const start = async () => {
    setStarting(true);
    setStartError(null);
    try {
      const created = await api.startDiscovery(projectId, description.trim(), idempotencyKey);
      setRun(created);
      setIdempotencyKey(newKey());
    } catch (error) {
      setStartError(error);
    } finally {
      setStarting(false);
    }
  };

  if (loadError !== null) return <ProblemMessage error={loadError} onRetry={() => void load()} />;
  if (status === null) return <Spinner label="Loading discovery" />;

  if (!status.configured) {
    return (
      <MessageBar intent="info" layout="multiline">
        <MessageBarBody>
          <MessageBarTitle>No AI model is configured</MessageBarTitle>
          Discovery proposes requirements with an AI model. An administrator can configure Qwen through Hugging Face, a
          self-hosted model, or gpt-oss on Ollama by setting <code>MODEL_PROFILE</code> and <code>MODEL_ID</code> on the
          API server. You can still edit the specification directly.
        </MessageBarBody>
      </MessageBar>
    );
  }

  const trimmed = description.trim();
  const tooLong = description.length > MAX_CHARS;
  const busy = starting || isActive(run);

  return (
    <div className={styles.root}>
      <div className={styles.row}>
        <Caption1>
          Model: <strong>{status.model}</strong>
        </Caption1>
        {status.remote ? (
          <Badge appearance="tint" color="warning">
            Remote provider: descriptions leave your network
          </Badge>
        ) : (
          <Badge appearance="tint" color="success">
            Local model
          </Badge>
        )}
      </div>

      <Field
        label="Describe the application you need"
        hint="Who will use it, what they need to do, and anything that must or must not happen. Proposals are only added after you review them."
        validationState={tooLong ? "error" : "none"}
        validationMessage={tooLong ? `Use at most ${MAX_CHARS} characters.` : undefined}
      >
        <Textarea
          value={description}
          resize="vertical"
          rows={5}
          onChange={(_, data) => setDescription(data.value)}
          placeholder="For example: finance operations need to configure adjustments, validate source files, simulate calculations and send risky transactions for approval."
        />
      </Field>
      <div className={styles.row}>
        <Button appearance="primary" onClick={start} disabled={busy || !trimmed || tooLong}>
          {starting ? "Starting…" : "Propose requirements"}
        </Button>
      </div>
      {startError !== null && <ProblemMessage error={startError} />}

      {run !== null && (
        <RunView
          key={run.id}
          projectId={projectId}
          run={run}
          etag={etag}
          onApplied={(result, nextEtag) => {
            setRun(result.run);
            onApplied({ revision: result.revision, etag: nextEtag });
          }}
          onRetry={(text) => setDescription(text)}
          onReload={() => void load()}
        />
      )}
    </div>
  );
}

interface RunViewProps {
  projectId: string;
  run: Run;
  etag: string;
  onApplied: (result: ApplyRunResult, etag: string) => void;
  onRetry: (description: string) => void;
  onReload: () => void;
}

function RunView({ projectId, run, etag, onApplied, onRetry, onReload }: RunViewProps) {
  const styles = useStyles();
  const views = useMemo(() => run.proposals.map(viewProposal), [run.proposals]);
  const [decisions, setDecisions] = useState<Record<string, DecisionValue>>(() =>
    Object.fromEntries(views.map((v) => [v.id, "accept" as DecisionValue])),
  );
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<unknown>(null);
  const [results, setResults] = useState<ApplyRunResult["results"] | null>(null);

  const meta = run.model
    ? `${run.model.model_id} · ${run.model.usage.total_tokens} tokens · ${(run.model.latency_ms / 1000).toFixed(1)} s${
        run.model.repaired ? " · output repaired once" : ""
      }`
    : null;

  if (run.status === "queued" || run.status === "running") {
    return <Spinner label={run.status === "queued" ? "Waiting to start…" : "The model is drafting proposals…"} />;
  }

  if (run.status === "failed") {
    return (
      <MessageBar intent="error" layout="multiline" role="alert">
        <MessageBarBody>
          <MessageBarTitle>Discovery did not complete</MessageBarTitle>
          {run.error?.message ?? "The run failed."}
        </MessageBarBody>
        <MessageBarActions>
          <Button onClick={() => onRetry(run.description)}>Use this description again</Button>
        </MessageBarActions>
      </MessageBar>
    );
  }

  if (run.not_applicable_reason) {
    return (
      <MessageBar intent="info" layout="multiline">
        <MessageBarBody>
          <MessageBarTitle>No proposals</MessageBarTitle>
          {run.not_applicable_reason}
        </MessageBarBody>
      </MessageBar>
    );
  }

  if (run.decisions || results) {
    const counts = new Map<string, number>();
    for (const r of results ?? []) counts.set(r.outcome, (counts.get(r.outcome) ?? 0) + 1);
    return (
      <MessageBar intent="success" layout="multiline" role="status">
        <MessageBarBody>
          <MessageBarTitle>
            {run.applied_revision ? `Applied to revision r${run.applied_revision}` : "Decisions recorded"}
          </MessageBarTitle>
          {results ? (
            <ul className={styles.list} aria-label="Outcome per proposal">
              {[...counts.entries()].map(([outcome, count]) => (
                <li key={outcome}>
                  {OUTCOME_LABELS[outcome] ?? outcome}: {count}
                </li>
              ))}
            </ul>
          ) : (
            "Start a new run to propose further changes."
          )}
        </MessageBarBody>
      </MessageBar>
    );
  }

  const setAll = (value: DecisionValue) => setDecisions(Object.fromEntries(views.map((v) => [v.id, value])));

  const apply = async () => {
    setApplying(true);
    setApplyError(null);
    try {
      const { result, etag: nextEtag } = await api.applyRun(
        projectId,
        run.id,
        { decisions: views.map((v) => ({ proposal_id: v.id, decision: decisions[v.id] ?? "reject" })) },
        etag,
      );
      setResults(result.results);
      onApplied(result, nextEtag);
    } catch (error) {
      setApplyError(error);
    } finally {
      setApplying(false);
    }
  };

  const grouped = GROUP_ORDER.map((group) => [group, views.filter((v) => v.group === group)] as const).filter(
    ([, items]) => items.length > 0,
  );
  const conflict = applyError instanceof ApiError && applyError.code === "revision-conflict";

  return (
    <section className={styles.root} aria-label="Proposals">
      <div>
        <Subtitle2 as="h2">{run.summary}</Subtitle2>
        <div>
          <Caption1>
            From “{run.description.slice(0, 120)}
            {run.description.length > 120 ? "…" : ""}” · {formatDateTime(run.created_at)}
          </Caption1>
        </div>
        {meta && <Caption1>{meta}</Caption1>}
      </div>
      <Body1>
        <strong>Accept</strong> adds a proposal as <em>proposed</em>. <strong>Confirm</strong> records it as confirmed
        by you. Confirmed facts are never overwritten by later AI runs.
      </Body1>
      <div className={styles.row}>
        <Button size="small" onClick={() => setAll("accept")}>
          Accept all
        </Button>
        <Button size="small" onClick={() => setAll("reject")}>
          Reject all
        </Button>
      </div>
      {grouped.map(([group, items]) => (
        <div key={group} className={styles.group}>
          <Subtitle2 as="h3">{GROUP_LABELS[group]}</Subtitle2>
          {items.map((v) => (
            <ProposalRow
              key={v.id}
              view={v}
              value={decisions[v.id] ?? "accept"}
              onChange={(value) => setDecisions((prev) => ({ ...prev, [v.id]: value }))}
            />
          ))}
        </div>
      ))}
      {conflict ? (
        <MessageBar intent="warning" role="alert">
          <MessageBarBody>
            <MessageBarTitle>The specification changed</MessageBarTitle>
            Someone saved a newer revision. Reload, then apply your decisions again.
          </MessageBarBody>
          <MessageBarActions>
            <Button onClick={onReload}>Reload</Button>
          </MessageBarActions>
        </MessageBar>
      ) : (
        applyError !== null && <ProblemMessage error={applyError} />
      )}
      <div className={styles.row}>
        <Button appearance="primary" onClick={apply} disabled={applying}>
          {applying ? "Applying…" : "Apply decisions"}
        </Button>
      </div>
    </section>
  );
}

function ProposalRow({
  view,
  value,
  onChange,
}: {
  view: ProposalView;
  value: DecisionValue;
  onChange: (value: DecisionValue) => void;
}) {
  const styles = useStyles();
  return (
    <div className={styles.proposal}>
      <div>
        <Caption1 className={styles.label}>{view.label}</Caption1>
        <Body1 as="p" style={{ margin: 0 }}>
          {view.text}{" "}
          {view.badges.map((b) => (
            <Badge key={b} appearance="outline" size="small">
              {b}
            </Badge>
          ))}
        </Body1>
        {view.detail && <Caption1 className={styles.detail}>{view.detail}</Caption1>}
      </div>
      <RadioGroup
        layout="horizontal"
        value={value}
        aria-label={`Decision for ${view.label.toLowerCase()}: ${view.text}`}
        onChange={(_, data) => onChange(data.value as DecisionValue)}
      >
        <Radio value="accept" label="Accept" />
        <Radio value="confirm" label="Confirm" />
        <Radio value="reject" label="Reject" />
      </RadioGroup>
    </div>
  );
}
