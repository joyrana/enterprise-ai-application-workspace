import { Badge, Body1, Caption1, Spinner, Tab, TabList, Title2, makeStyles, tokens } from "@fluentui/react-components";
import { useCallback, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type SpecRevision } from "../../api/client";
import { ProblemMessage } from "../../components/ProblemMessage";
import { RouterLink } from "../../components/RouterLink";
import { useAsync } from "../../hooks/useAsync";
import { AuditTab } from "./AuditTab";
import { DiscoveryTab } from "./DiscoveryTab";
import { HistoryTab } from "./HistoryTab";
import { OverviewTab } from "./OverviewTab";
import { ScreensTab } from "./ScreensTab";
import { SpecEditorTab } from "./SpecEditorTab";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "discovery", label: "Discovery" },
  { id: "specification", label: "Specification" },
  { id: "screens", label: "Screens" },
  { id: "history", label: "History" },
  { id: "audit", label: "Audit" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const useStyles = makeStyles({
  header: { display: "grid", gap: tokens.spacingVerticalXS, marginBottom: tokens.spacingVerticalM },
  titleRow: { display: "flex", alignItems: "center", gap: tokens.spacingHorizontalM, flexWrap: "wrap" },
  panel: {
    marginTop: tokens.spacingVerticalM,
    backgroundColor: tokens.colorNeutralBackground1,
    borderRadius: tokens.borderRadiusLarge,
    padding: tokens.spacingHorizontalL,
    boxShadow: tokens.shadow4,
    minWidth: 0,
  },
});

interface Current {
  revision: SpecRevision;
  etag: string;
}

export function ProjectPage() {
  const styles = useStyles();
  const navigate = useNavigate();
  const { projectId = "", tab } = useParams();
  const selected: TabId = TABS.some((t) => t.id === tab) ? (tab as TabId) : "overview";
  const { state, reload, setData } = useAsync<Current>((signal) => api.getSpec(projectId, signal), projectId);
  const [historyKey, setHistoryKey] = useState(0);

  const onSaved = useCallback(
    (next: Current) => {
      setData(next);
      setHistoryKey((k) => k + 1);
    },
    [setData],
  );

  if (state.status === "loading") return <Spinner label="Loading project" />;
  if (state.status === "error") {
    return (
      <>
        <ProblemMessage error={state.error} onRetry={reload} />
        <p>
          <RouterLink to="/projects">Back to projects</RouterLink>
        </p>
      </>
    );
  }

  const { revision, etag } = state.data;
  const spec = revision.spec;

  return (
    <>
      <div className={styles.header}>
        <RouterLink to="/projects">Projects</RouterLink>
        <div className={styles.titleRow}>
          <Title2 as="h1">{spec.metadata.name}</Title2>
          <Badge appearance="outline" aria-label={`Revision ${revision.revision}`}>
            r{revision.revision}
          </Badge>
        </div>
        {spec.metadata.description && <Body1>{spec.metadata.description}</Body1>}
        <Caption1>Specification schema {revision.schema_version}</Caption1>
      </div>
      <TabList
        selectedValue={selected}
        onTabSelect={(_, data) => navigate(`/projects/${projectId}/${String(data.value)}`)}
        aria-label="Project sections"
      >
        {TABS.map((t) => (
          <Tab key={t.id} value={t.id}>
            {t.label}
          </Tab>
        ))}
      </TabList>
      <section className={styles.panel} aria-label={TABS.find((t) => t.id === selected)?.label}>
        {selected === "overview" && <OverviewTab revision={revision} />}
        {selected === "discovery" && <DiscoveryTab projectId={projectId} etag={etag} onApplied={onSaved} />}
        {selected === "specification" && (
          <SpecEditorTab
            key={etag}
            projectId={projectId}
            revision={revision}
            etag={etag}
            onSaved={onSaved}
            onReload={reload}
          />
        )}
        {selected === "screens" && <ScreensTab projectId={projectId} revision={revision.revision} />}
        {selected === "history" && <HistoryTab key={historyKey} projectId={projectId} />}
        {selected === "audit" && <AuditTab key={historyKey} projectId={projectId} />}
      </section>
    </>
  );
}
