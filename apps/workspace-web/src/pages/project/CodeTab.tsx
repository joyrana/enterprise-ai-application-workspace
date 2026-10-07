import {
  Badge,
  Body1,
  Button,
  Caption1,
  Field,
  Select,
  Spinner,
  Subtitle2,
  makeStyles,
  mergeClasses,
  tokens,
} from "@fluentui/react-components";
import { useEffect, useState } from "react";
import { api, type CodeDiff, type CodeFile, type CodeManifest } from "../../api/client";
import { ProblemMessage } from "../../components/ProblemMessage";
import { useAsync } from "../../hooks/useAsync";

const useStyles = makeStyles({
  root: { display: "grid", gap: tokens.spacingVerticalL },
  row: { display: "flex", gap: tokens.spacingHorizontalS, alignItems: "center", flexWrap: "wrap" },
  browser: {
    display: "grid",
    gridTemplateColumns: "minmax(200px, 280px) minmax(0, 1fr)",
    gap: tokens.spacingHorizontalM,
    "@media (max-width: 720px)": { gridTemplateColumns: "1fr" },
  },
  files: { listStyleType: "none", margin: 0, padding: 0, display: "grid", gap: tokens.spacingVerticalXXS },
  fileButton: { justifyContent: "flex-start", width: "100%", fontFamily: tokens.fontFamilyMonospace },
  code: {
    margin: 0,
    padding: tokens.spacingHorizontalM,
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusMedium,
    overflow: "auto",
    maxHeight: "60vh",
    whiteSpace: "pre",
  },
  added: { color: tokens.colorPaletteGreenForeground2 },
  removed: { color: tokens.colorPaletteRedForeground2 },
  muted: { color: tokens.colorNeutralForeground3 },
});

export function CodeTab({ projectId, revision }: { projectId: string; revision: number }) {
  const styles = useStyles();
  const { state, reload } = useAsync<CodeManifest>((signal) => api.getCode(projectId, signal), `${projectId}:${revision}`);

  if (state.status === "loading") return <Spinner label="Generating code" />;
  if (state.status === "error") return <ProblemMessage error={state.error} onRetry={reload} />;
  const manifest = state.data;

  return (
    <div className={styles.root}>
      <div className={styles.row}>
        <Caption1>
          {manifest.generator} · {manifest.design_system} · spec r{manifest.spec_revision} · {manifest.files.length}{" "}
          files
        </Caption1>
        <Badge appearance="tint" color="informative">
          Static app: no data access or behaviour yet
        </Badge>
        <DownloadButton projectId={projectId} revision={manifest.spec_revision} />
      </div>
      {manifest.warnings.length > 0 && (
        <Body1>
          {manifest.warnings.length} warning(s) carried into the code (shown as &quot;not supported yet&quot; markers);
          see the Screens tab.
        </Body1>
      )}
      <FileBrowser projectId={projectId} manifest={manifest} />
      <DiffView projectId={projectId} revision={manifest.spec_revision} />
    </div>
  );
}

function DownloadButton({ projectId, revision }: { projectId: string; revision: number }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const download = async () => {
    setBusy(true);
    setError(null);
    try {
      const { blob, filename } = await api.downloadCode(projectId, revision);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button appearance="primary" disabled={busy} onClick={() => void download()}>
        {busy ? "Preparing…" : "Download zip"}
      </Button>
      {error !== null && <ProblemMessage error={error} />}
    </>
  );
}

function FileBrowser({ projectId, manifest }: { projectId: string; manifest: CodeManifest }) {
  const styles = useStyles();
  const firstScreen = manifest.files.find((f) => f.path.startsWith("src/screens/"))?.path ?? manifest.files[0]?.path;
  const [path, setPath] = useState<string | undefined>(firstScreen);
  const [file, setFile] = useState<CodeFile | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    setFile(null);
    setError(null);
    api.getCodeFile(projectId, path, manifest.spec_revision, controller.signal).then(
      (next) => setFile(next),
      (e: unknown) => {
        if (!controller.signal.aborted) setError(e);
      },
    );
    return () => controller.abort();
  }, [projectId, path, manifest.spec_revision]);

  return (
    <section aria-label="Generated files" className={styles.browser}>
      <ul className={styles.files} aria-label="Files">
        {manifest.files.map((f) => (
          <li key={f.path}>
            <Button
              appearance={f.path === path ? "secondary" : "transparent"}
              size="small"
              className={styles.fileButton}
              aria-pressed={f.path === path}
              onClick={() => setPath(f.path)}
            >
              {f.path}
            </Button>
          </li>
        ))}
      </ul>
      <div>
        {error !== null ? (
          <ProblemMessage error={error} />
        ) : file ? (
          <>
            <Caption1 className={styles.muted}>
              {file.path} · sha256 {file.sha256.slice(0, 12)}…
            </Caption1>
            <pre className={styles.code} role="region" aria-label={`Contents of ${file.path}`} tabIndex={0}>
              {file.content}
            </pre>
          </>
        ) : (
          <Spinner size="tiny" label="Loading file" />
        )}
      </div>
    </section>
  );
}

function DiffView({ projectId, revision }: { projectId: string; revision: number }) {
  const styles = useStyles();
  const [base, setBase] = useState(revision > 1 ? revision - 1 : 0);
  const [diff, setDiff] = useState<CodeDiff | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (base < 1) return;
    const controller = new AbortController();
    setDiff(null);
    setError(null);
    api.getCodeDiff(projectId, base, revision, controller.signal).then(
      (next) => setDiff(next),
      (e: unknown) => {
        if (!controller.signal.aborted) setError(e);
      },
    );
    return () => controller.abort();
  }, [projectId, base, revision]);

  if (revision < 2) return null;
  const options = Array.from({ length: revision - 1 }, (_, i) => revision - 1 - i);

  return (
    <section aria-label="Changes between revisions">
      <Subtitle2 as="h2">Changes since an earlier revision</Subtitle2>
      <Field label={`Compare r${revision} with`} style={{ maxWidth: 240 }}>
        <Select value={String(base)} onChange={(_, data) => setBase(Number(data.value))}>
          {options.map((r) => (
            <option key={r} value={r}>
              r{r}
            </option>
          ))}
        </Select>
      </Field>
      {error !== null && <ProblemMessage error={error} />}
      {diff && diff.files.length === 0 && <Body1>The generated code is identical.</Body1>}
      {diff &&
        diff.files.map((f) => (
          <div key={f.path}>
            <Caption1>
              <strong>{f.path}</strong> · {f.status} · +{f.additions} −{f.deletions}
            </Caption1>
            <pre className={styles.code} role="region" aria-label={`Diff of ${f.path}`} tabIndex={0}>
              {f.unified.split("\n").map((line, i) => (
                <span
                  key={i}
                  className={mergeClasses(
                    line.startsWith("+") && !line.startsWith("+++") && styles.added,
                    line.startsWith("-") && !line.startsWith("---") && styles.removed,
                  )}
                >
                  {line}
                  {"\n"}
                </span>
              ))}
            </pre>
          </div>
        ))}
    </section>
  );
}
