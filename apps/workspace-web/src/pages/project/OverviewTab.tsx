import {
  Badge,
  Body1,
  Subtitle2,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import type { SpecRevision } from "../../api/client";
import { StatusBadge } from "../../components/StatusBadge";

const useStyles = makeStyles({
  grid: {
    display: "grid",
    gap: tokens.spacingVerticalXL,
    gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
  },
  section: { display: "grid", gap: tokens.spacingVerticalS, alignContent: "start", minWidth: 0 },
  muted: { color: tokens.colorNeutralForeground3 },
  list: { margin: 0, paddingLeft: tokens.spacingHorizontalL, display: "grid", gap: tokens.spacingVerticalXS },
});

/** Reads `value` at a JSON-pointer-like path such as "/framework/framework". */
function valueAt(root: unknown, path: string): unknown {
  let node: unknown = root;
  for (const part of path.split("/").filter(Boolean)) {
    if (typeof node !== "object" || node === null) return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === "object" && node !== null ? (node as { value?: unknown }).value : undefined;
}

export function OverviewTab({ revision }: { revision: SpecRevision }) {
  const styles = useStyles();
  const { summary, spec, issues } = revision;

  return (
    <div className={styles.grid}>
      <section className={styles.section} aria-labelledby="facts-heading">
        <Subtitle2 as="h2" id="facts-heading">
          Key facts ({summary.confirmed_facts} of {summary.total_facts} confirmed)
        </Subtitle2>
        <Table aria-labelledby="facts-heading" size="small">
          <TableHeader>
            <TableRow>
              <TableHeaderCell>Fact</TableHeaderCell>
              <TableHeaderCell>Value</TableHeaderCell>
              <TableHeaderCell>Status</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {summary.facts.map((fact) => {
              const value = valueAt(spec, fact.path);
              return (
                <TableRow key={fact.path}>
                  <TableCell>{fact.label}</TableCell>
                  <TableCell>
                    {value === undefined || value === null ? (
                      <span className={styles.muted}>Not yet known</span>
                    ) : (
                      String(value)
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={fact.status} />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </section>

      <section className={styles.section} aria-labelledby="collections-heading">
        <Subtitle2 as="h2" id="collections-heading">
          Requirements coverage
        </Subtitle2>
        <Table aria-labelledby="collections-heading" size="small">
          <TableHeader>
            <TableRow>
              <TableHeaderCell>Section</TableHeaderCell>
              <TableHeaderCell>Proposed</TableHeaderCell>
              <TableHeaderCell>Confirmed</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {summary.collections.map((c) => (
              <TableRow key={c.name}>
                <TableCell>{c.label}</TableCell>
                <TableCell>{c.proposed}</TableCell>
                <TableCell>{c.confirmed}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>

      <section className={styles.section} aria-labelledby="questions-heading">
        <Subtitle2 as="h2" id="questions-heading">
          Open questions ({summary.open_questions}, {summary.blocking_questions} blocking)
        </Subtitle2>
        {spec.open_questions.length === 0 ? (
          <Body1 className={styles.muted}>No open questions recorded.</Body1>
        ) : (
          <ul className={styles.list}>
            {spec.open_questions.map((q) => (
              <li key={q.id}>
                {q.question}{" "}
                {q.blocking && (
                  <Badge appearance="tint" color="danger" size="small">
                    Blocking
                  </Badge>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.section} aria-labelledby="warnings-heading">
        <Subtitle2 as="h2" id="warnings-heading">
          Warnings ({issues.length})
        </Subtitle2>
        {issues.length === 0 ? (
          <Body1 className={styles.muted}>No warnings for this revision.</Body1>
        ) : (
          <ul className={styles.list}>
            {issues.map((issue) => (
              <li key={`${issue.path}:${issue.code}`}>{issue.message}</li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
