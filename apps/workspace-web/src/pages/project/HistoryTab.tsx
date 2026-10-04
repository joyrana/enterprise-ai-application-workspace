import {
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Spinner,
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
import { api, type SpecRevision } from "../../api/client";
import { ProblemMessage } from "../../components/ProblemMessage";
import { formatDateTime } from "../../format";
import { useAsync } from "../../hooks/useAsync";

const useStyles = makeStyles({
  hash: { fontFamily: tokens.fontFamilyMonospace },
  code: {
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
    maxHeight: "60vh",
    overflow: "auto",
    margin: 0,
    whiteSpace: "pre",
  },
  scroll: { overflowX: "auto" },
});

export function HistoryTab({ projectId }: { projectId: string }) {
  const styles = useStyles();
  const { state, reload } = useAsync((signal) => api.listRevisions(projectId, null, signal), projectId);
  const [viewing, setViewing] = useState<number | null>(null);
  const [detail, setDetail] = useState<
    { status: "loading" } | { status: "error"; error: unknown } | { status: "done"; data: SpecRevision } | null
  >(null);

  const open = async (revision: number) => {
    setViewing(revision);
    setDetail({ status: "loading" });
    try {
      setDetail({ status: "done", data: await api.getRevision(projectId, revision) });
    } catch (error) {
      setDetail({ status: "error", error });
    }
  };

  if (state.status === "loading") return <Spinner label="Loading revision history" />;
  if (state.status === "error") return <ProblemMessage error={state.error} onRetry={reload} />;

  return (
    <div className={styles.scroll}>
      <Table aria-label="Specification revisions">
        <TableHeader>
          <TableRow>
            <TableHeaderCell>Revision</TableHeaderCell>
            <TableHeaderCell>Change</TableHeaderCell>
            <TableHeaderCell>Author</TableHeaderCell>
            <TableHeaderCell>Saved</TableHeaderCell>
            <TableHeaderCell>Content hash</TableHeaderCell>
            <TableHeaderCell>Actions</TableHeaderCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {state.data.items.map((r) => (
            <TableRow key={r.revision}>
              <TableCell>r{r.revision}</TableCell>
              <TableCell>{r.change_summary ?? <Caption1>No summary</Caption1>}</TableCell>
              <TableCell>{r.created_by}</TableCell>
              <TableCell>{formatDateTime(r.created_at)}</TableCell>
              <TableCell className={styles.hash} title={r.content_hash}>
                {r.content_hash.slice(7, 19)}
              </TableCell>
              <TableCell>
                <Button size="small" onClick={() => open(r.revision)} aria-label={`View revision ${r.revision}`}>
                  View
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {state.data.next_cursor && <Caption1>Showing the 20 most recent revisions.</Caption1>}

      <Dialog open={viewing !== null} onOpenChange={(_, data) => !data.open && setViewing(null)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Revision r{viewing}</DialogTitle>
            <DialogContent>
              {detail?.status === "loading" && <Spinner label="Loading revision" />}
              {detail?.status === "error" && <ProblemMessage error={detail.error} />}
              {detail?.status === "done" && (
                <pre className={styles.code} tabIndex={0} aria-label={`Revision ${viewing} JSON`}>
                  {JSON.stringify(detail.data.spec, null, 2)}
                </pre>
              )}
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setViewing(null)}>Close</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
