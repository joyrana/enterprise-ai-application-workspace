import {
  Body1,
  Button,
  Caption1,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Title2,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { AddRegular } from "@fluentui/react-icons";
import { useState } from "react";
import { api, type Project } from "../api/client";
import { ProblemMessage } from "../components/ProblemMessage";
import { RouterLink } from "../components/RouterLink";
import { useAsync } from "../hooks/useAsync";
import { useCreateProject } from "./CreateProjectProvider";
import { formatDateTime } from "../format";

const useStyles = makeStyles({
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: tokens.spacingHorizontalM,
    marginBottom: tokens.spacingVerticalL,
  },
  panel: {
    backgroundColor: tokens.colorNeutralBackground1,
    borderRadius: tokens.borderRadiusLarge,
    padding: tokens.spacingHorizontalL,
    boxShadow: tokens.shadow4,
    overflowX: "auto",
  },
  empty: {
    display: "grid",
    justifyItems: "start",
    gap: tokens.spacingVerticalM,
    padding: tokens.spacingVerticalXXL,
  },
  more: { marginTop: tokens.spacingVerticalM },
});

export function ProjectsPage() {
  const styles = useStyles();
  const { openCreateProject } = useCreateProject();
  const [extra, setExtra] = useState<{ items: Project[]; cursor: string | null } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<unknown>(null);
  const { state, reload } = useAsync((signal) => api.listProjects(null, signal), "projects");

  const loadMore = async (cursor: string) => {
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await api.listProjects(cursor);
      setExtra((prev) => ({ items: [...(prev?.items ?? []), ...page.items], cursor: page.next_cursor ?? null }));
    } catch (err) {
      setMoreError(err);
    } finally {
      setLoadingMore(false);
    }
  };

  let content;
  if (state.status === "loading") {
    content = <Spinner label="Loading projects" />;
  } else if (state.status === "error") {
    content = <ProblemMessage error={state.error} onRetry={reload} />;
  } else {
    const items = [...state.data.items, ...(extra?.items ?? [])];
    const cursor = extra ? extra.cursor : (state.data.next_cursor ?? null);
    content =
      items.length === 0 ? (
        <div className={styles.empty}>
          <Body1>No projects yet. A project holds one application's requirements, design decisions and history.</Body1>
          <Button appearance="primary" icon={<AddRegular />} onClick={openCreateProject}>
            Create your first project
          </Button>
        </div>
      ) : (
        <>
          <Table aria-label="Projects">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Name</TableHeaderCell>
                <TableHeaderCell>Revision</TableHeaderCell>
                <TableHeaderCell>Last updated</TableHeaderCell>
                <TableHeaderCell>Created by</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((p) => (
                <TableRow key={p.id}>
                  <TableCell>
                    <RouterLink to={`/projects/${p.id}`}>{p.name}</RouterLink>
                    {p.description && (
                      <div>
                        <Caption1>{p.description}</Caption1>
                      </div>
                    )}
                  </TableCell>
                  <TableCell>r{p.current_revision}</TableCell>
                  <TableCell>{formatDateTime(p.updated_at)}</TableCell>
                  <TableCell>{p.created_by}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {moreError !== null && <ProblemMessage error={moreError} />}
          {cursor && (
            <Button className={styles.more} onClick={() => loadMore(cursor)} disabled={loadingMore}>
              {loadingMore ? "Loading…" : "Load more"}
            </Button>
          )}
        </>
      );
  }

  return (
    <>
      <div className={styles.header}>
        <Title2 as="h1">Projects</Title2>
        <Button appearance="primary" icon={<AddRegular />} onClick={openCreateProject}>
          New project
        </Button>
      </div>
      <section className={styles.panel} aria-busy={state.status === "loading"}>
        {content}
      </section>
    </>
  );
}
