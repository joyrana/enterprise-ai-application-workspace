import {
  Badge,
  Body1,
  Button,
  Caption1,
  Field,
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
import { useState } from "react";
import { api, type UpgradeResult } from "../../api/client";
import { ProblemMessage } from "../../components/ProblemMessage";

const useStyles = makeStyles({
  root: { display: "grid", gap: tokens.spacingVerticalS },
  row: { display: "flex", gap: tokens.spacingHorizontalS, alignItems: "center", flexWrap: "wrap" },
  path: { fontFamily: tokens.fontFamilyMonospace },
});

type Status = UpgradeResult["files"][number]["status"];

const LABELS: Record<Status, string> = {
  unchanged: "Unchanged",
  regenerated: "Regenerated",
  kept: "Your version kept",
  merged: "Merged",
  conflict: "Conflict",
  added: "New file",
  "user-file": "Your file",
  removed: "Removed",
  orphaned: "No longer generated (kept)",
  deleted: "Stays deleted",
  restored: "Restored",
  "side-by-side": "Kept, new version beside it",
};

/** Hidden in the table: files nobody needs to look at. */
const QUIET = new Set<Status>(["unchanged", "regenerated", "added", "removed"]);

function download(result: UpgradeResult) {
  const bytes = Uint8Array.from(atob(result.archive_base64), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: "application/zip" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = result.filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** Upgrade a hand-edited copy of the generated project to the current revision (Milestone 5). */
export function UpgradePanel({ projectId, revision }: { projectId: string; revision: number }) {
  const styles = useStyles();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<UpgradeResult | null>(null);

  const upgrade = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.upgradeCode(projectId, file));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const shown = result?.files.filter((f) => !QUIET.has(f.status)) ?? [];
  return (
    <section className={styles.root} aria-labelledby="upgrade-heading">
      <Subtitle2 as="h3" id="upgrade-heading">
        Upgrade your edited copy
      </Subtitle2>
      <Caption1>
        Edited the downloaded project? Upload it to bring it to r{revision}: your edits are merged with the regenerated
        code, and overlapping changes are marked as conflicts. Nothing is stored or run.
      </Caption1>
      <div className={styles.row}>
        <Field label="Project zip">
          {(fieldProps) => (
            <input
              {...fieldProps}
              type="file"
              accept=".zip,application/zip"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setResult(null);
              }}
            />
          )}
        </Field>
        <Button disabled={!file || busy} onClick={() => void upgrade()}>
          {busy ? "Merging…" : "Upgrade"}
        </Button>
      </div>
      {error !== null && <ProblemMessage error={error} />}
      {result && (
        <div className={styles.root}>
          <div className={styles.row}>
            <Badge appearance="tint" color={result.conflicts > 0 ? "warning" : "success"}>
              {result.conflicts > 0 ? `${result.conflicts} conflict(s) to resolve` : "Merged without conflicts"}
            </Badge>
            <Caption1>
              r{result.from_revision} → r{result.to_revision}
              {result.base_reproduced ? "" : ` · made by ${result.from_generator}: edited files kept side by side`}
            </Caption1>
            <Button appearance="primary" onClick={() => download(result)}>
              Download upgraded project
            </Button>
          </div>
          {shown.length === 0 ? (
            <Body1>No files need your attention.</Body1>
          ) : (
            <Table aria-label="Files that need your attention" size="small">
              <TableHeader>
                <TableRow>
                  <TableHeaderCell>File</TableHeaderCell>
                  <TableHeaderCell>Outcome</TableHeaderCell>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.map((f) => (
                  <TableRow key={f.path}>
                    <TableCell className={styles.path}>{f.path}</TableCell>
                    <TableCell>
                      {LABELS[f.status]}
                      {f.conflicts > 0 ? ` (${f.conflicts})` : ""}
                      {f.note ? ` — ${f.note}` : ""}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      )}
    </section>
  );
}
