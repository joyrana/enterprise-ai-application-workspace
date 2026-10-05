import {
  Badge,
  Body1,
  Caption1,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Spinner,
  Subtitle2,
  Tab,
  TabList,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useState } from "react";
import { api, type UiPreview } from "../../api/client";
import { ProblemMessage } from "../../components/ProblemMessage";
import { RenderTree } from "../../design/RenderTree";
import { useAsync } from "../../hooks/useAsync";

const SOURCE_LABELS: Record<string, string> = {
  "spec-screen": "From a specified screen",
  "entity-list": "Derived from a data entity (list)",
  "entity-form": "Derived from a data entity (form)",
};

const useStyles = makeStyles({
  root: { display: "grid", gap: tokens.spacingVerticalL },
  row: { display: "flex", gap: tokens.spacingHorizontalS, alignItems: "center", flexWrap: "wrap" },
  preview: {
    display: "grid",
    gap: tokens.spacingVerticalM,
    padding: tokens.spacingHorizontalL,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorNeutralBackground2,
    minWidth: 0,
    overflowX: "auto",
  },
  issues: { margin: 0, paddingLeft: tokens.spacingHorizontalL, display: "grid", gap: tokens.spacingVerticalXS },
  path: { fontFamily: tokens.fontFamilyMonospace, color: tokens.colorNeutralForeground3 },
});

export function ScreensTab({ projectId, revision }: { projectId: string; revision: number }) {
  const styles = useStyles();
  const { state, reload } = useAsync<UiPreview>(
    (signal) => api.getUiPreview(projectId, signal),
    `${projectId}:${revision}`,
  );
  const [selected, setSelected] = useState<string | null>(null);

  if (state.status === "loading") return <Spinner label="Building the screen preview" />;
  if (state.status === "error") return <ProblemMessage error={state.error} onRetry={reload} />;

  const preview = state.data;
  const screens = preview.rendered;
  const current = screens.find((s) => s.screen_id === selected) ?? screens[0];
  const irScreen = preview.document.screens.find((s) => s.id === current?.screen_id);
  const errors = preview.issues.filter((i) => i.severity === "error").length;

  return (
    <div className={styles.root}>
      <div className={styles.row}>
        <Caption1>
          Design system: <strong>{preview.design_system.id}</strong> {preview.design_system.version} · spec r
          {preview.spec_revision} · UI IR v{preview.document.ir_version}
        </Caption1>
        <Badge appearance="tint" color={preview.design_system.selected_by === "spec" ? "success" : "informative"}>
          {preview.design_system.selected_by === "spec" ? "Selected in the spec" : "Default"}
        </Badge>
      </div>
      {preview.design_system.note && <Caption1>{preview.design_system.note}</Caption1>}

      {screens.length === 0 ? (
        <MessageBar intent="info" layout="multiline">
          <MessageBarBody>
            <MessageBarTitle>No screens yet</MessageBarTitle>
            Screens are derived from the specification&apos;s screens, or from its data entities when no screens are
            specified. Add either in the Specification tab or through Discovery.
          </MessageBarBody>
        </MessageBar>
      ) : (
        <>
          <TabList
            selectedValue={current?.screen_id}
            onTabSelect={(_, data) => setSelected(String(data.value))}
            aria-label="Screens"
            size="small"
          >
            {screens.map((s) => (
              <Tab key={s.screen_id} value={s.screen_id}>
                {s.title}
              </Tab>
            ))}
          </TabList>
          {current && (
            <>
              <div className={styles.row}>
                <Caption1>
                  Route <code>{current.route}</code>
                  {irScreen ? ` · ${SOURCE_LABELS[irScreen.source.kind] ?? irScreen.source.kind}` : ""}
                </Caption1>
              </div>
              <section className={styles.preview} aria-label={`Preview of ${current.title}`}>
                <RenderTree nodes={current.root} />
              </section>
            </>
          )}
        </>
      )}

      <section aria-label="Design checks">
        <Subtitle2 as="h2">Design checks</Subtitle2>
        {preview.issues.length === 0 ? (
          <Body1>No issues: labels, heading order, table captions, actions and references all check out.</Body1>
        ) : (
          <>
            <Body1>
              {errors > 0
                ? `${errors} error(s) must be fixed before code can be generated.`
                : "Only warnings: review them before generating code."}
            </Body1>
            <ul className={styles.issues} aria-label="Issues">
              {preview.issues.map((issue, i) => (
                <li key={`${issue.path}-${issue.code}-${i}`}>
                  <Badge appearance="tint" color={issue.severity === "error" ? "danger" : "warning"} size="small">
                    {issue.severity}
                  </Badge>{" "}
                  {issue.message} <span className={styles.path}>{issue.path}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
