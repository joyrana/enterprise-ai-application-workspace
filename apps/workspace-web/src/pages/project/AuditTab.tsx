import {
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
} from "@fluentui/react-components";
import { api } from "../../api/client";
import { ProblemMessage } from "../../components/ProblemMessage";
import { formatDateTime } from "../../format";
import { useAsync } from "../../hooks/useAsync";

const useStyles = makeStyles({ scroll: { overflowX: "auto" } });

const ACTION_LABELS: Record<string, string> = {
  "project.created": "Project created",
  "spec.revised": "Specification revised",
  "ai.run.started": "AI run started",
  "ai.run.succeeded": "AI run completed",
  "ai.run.failed": "AI run failed",
  "ai.proposals.applied": "AI proposals applied",
  "ai.flagged_proposals.accepted": "Flagged AI proposals accepted",
};

function describe(details: Record<string, unknown>): string {
  const parts: string[] = [];
  if (typeof details.revision === "number") parts.push(`revision r${details.revision}`);
  if (typeof details.change_summary === "string") parts.push(`“${details.change_summary}”`);
  if (typeof details.name === "string") parts.push(details.name);
  if (typeof details.skill === "string") parts.push(details.skill);
  if (typeof details.applied === "number") parts.push(`${details.applied} applied`);
  if (typeof details.error_kind === "string") parts.push(details.error_kind);
  return parts.join(" · ");
}

export function AuditTab({ projectId }: { projectId: string }) {
  const styles = useStyles();
  const { state, reload } = useAsync((signal) => api.listAudit(projectId, null, signal), projectId);

  if (state.status === "loading") return <Spinner label="Loading audit trail" />;
  if (state.status === "error") return <ProblemMessage error={state.error} onRetry={reload} />;

  return (
    <div className={styles.scroll}>
      <Table aria-label="Audit trail">
        <TableHeader>
          <TableRow>
            <TableHeaderCell>When</TableHeaderCell>
            <TableHeaderCell>Who</TableHeaderCell>
            <TableHeaderCell>What</TableHeaderCell>
            <TableHeaderCell>Details</TableHeaderCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {state.data.items.map((e) => (
            <TableRow key={e.id}>
              <TableCell>{formatDateTime(e.occurred_at)}</TableCell>
              <TableCell>{e.actor}</TableCell>
              <TableCell>{ACTION_LABELS[e.action] ?? e.action}</TableCell>
              <TableCell>{describe(e.details)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
