import {
  Body1,
  Button,
  Caption1,
  Field,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Spinner,
  Subtitle1,
  Textarea,
  Title2,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { type ReactNode, useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import { ProblemMessage } from "../components/ProblemMessage";
import { useAsync } from "../hooks/useAsync";

const useStyles = makeStyles({
  root: { display: "grid", gap: tokens.spacingVerticalXXL, maxWidth: "960px" },
  section: { display: "grid", gap: tokens.spacingVerticalM },
  editor: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200, minHeight: "260px" },
  actions: { display: "flex", gap: tokens.spacingHorizontalS, flexWrap: "wrap" },
  list: { margin: 0, paddingLeft: tokens.spacingHorizontalL },
});

const POLICY_EXAMPLE = {
  rules: [
    { id: "no-file-uploads", kind: "forbidden-components", constructs: ["field:file"] },
    { id: "small-forms", kind: "max-form-fields", max: 20, severity: "warning" },
    { id: "pii", kind: "sensitive-fields", name_patterns: ["email", "ssn"], minimum: "confidential" },
  ],
};

const THEME_EXAMPLE = {
  items: [
    { id: "acme", name: "Acme", base: "fluent2", brand_color: "#8a1538", font_family: "Segoe UI, sans-serif" },
  ],
};

const KINDS = [
  "allowed-frameworks (frameworks)",
  "allowed-design-systems (ids)",
  "forbidden-components (constructs, e.g. field:file, stat)",
  "max-form-fields (max)",
  "acceptance-criteria-required",
  "confirmed-requirements-only",
  "sensitive-fields (name_patterns, minimum classification)",
  "entity-naming (pattern)",
  "required-screen-states (states)",
];

interface Versioned<T> {
  version: number;
  value: T;
  note: string;
}

/** A JSON document saved with If-Match: "vN" (organization policies and brand themes). */
function VersionedJsonEditor<T>({
  id,
  title,
  description,
  label,
  example,
  load,
  save,
  children,
}: {
  id: string;
  title: string;
  description: string;
  label: string;
  example: unknown;
  load: (signal: AbortSignal) => Promise<Versioned<T>>;
  save: (value: unknown, version: number) => Promise<Versioned<T>>;
  children?: ReactNode;
}) {
  const styles = useStyles();
  const { state, setData } = useAsync<Versioned<T>>(load, id);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const loaded = state.status === "success" ? state.data : null;

  useEffect(() => {
    if (loaded) setText(JSON.stringify(loaded.value, null, 2));
  }, [loaded]);

  const submit = async () => {
    if (!loaded) return;
    setError(null);
    setSaved(false);
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      setError(new ApiError({ type: "urn:workspace:error:json", title: "The JSON is not valid", status: 0 }));
      return;
    }
    setBusy(true);
    try {
      setData(await save(parsed, loaded.version));
      setSaved(true);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.section} aria-labelledby={`${id}-heading`}>
      <Subtitle1 as="h2" id={`${id}-heading`}>
        {title}
      </Subtitle1>
      <Body1>{description}</Body1>
      {state.status === "loading" && <Spinner size="tiny" label={`Loading ${title.toLowerCase()}`} />}
      {state.status === "error" && <ProblemMessage error={state.error} />}
      {loaded && (
        <>
          <Caption1>{loaded.note}</Caption1>
          <Field label={label}>
            <Textarea
              className={styles.editor}
              value={text}
              resize="vertical"
              onChange={(_, data) => {
                setText(data.value);
                setSaved(false);
              }}
            />
          </Field>
          <div className={styles.actions}>
            <Button appearance="primary" disabled={busy} onClick={() => void submit()}>
              {busy ? "Saving…" : `Save ${title.toLowerCase()}`}
            </Button>
            <Button onClick={() => setText(JSON.stringify(example, null, 2))}>Insert example</Button>
          </div>
          {saved && (
            <MessageBar intent="success" role="status">
              <MessageBarBody>Saved as version {loaded.version}.</MessageBarBody>
            </MessageBar>
          )}
          {error !== null && <ProblemMessage error={error} />}
        </>
      )}
      {children}
    </section>
  );
}

function note(version: number, updatedBy?: string | null): string {
  if (version === 0) return "Nothing saved yet.";
  return updatedBy ? `Version ${version}, last changed by ${updatedBy}.` : `Version ${version}.`;
}

/** Organization policies (ADR-0018) and brand themes; only organization admins can change them. */
export function OrganizationPage() {
  const styles = useStyles();
  return (
    <div className={styles.root}>
      <Title2 as="h1">Organization</Title2>
      <VersionedJsonEditor
        id="policies"
        title="Policies"
        label="Policy (JSON)"
        description="Rules every project is checked against. Rules with severity “error” block code generation and builds until the specification complies; “warning” rules are reported."
        example={POLICY_EXAMPLE}
        load={async (signal) => {
          const p = await api.getOrgPolicies(signal);
          return { version: p.version, value: p.policy, note: note(p.version, p.updated_by) };
        }}
        save={async (value, version) => {
          const p = await api.saveOrgPolicies(value, version);
          return { version: p.version, value: p.policy, note: note(p.version, p.updated_by) };
        }}
      >
        <MessageBar intent="info" layout="multiline">
          <MessageBarBody>
            <MessageBarTitle>Rule kinds</MessageBarTitle>
            <ul className={styles.list} aria-label="Rule kinds">
              {KINDS.map((kind) => (
                <li key={kind}>{kind}</li>
              ))}
            </ul>
          </MessageBarBody>
        </MessageBar>
      </VersionedJsonEditor>
      <VersionedJsonEditor
        id="themes"
        title="Brand themes"
        label="Brand themes (JSON)"
        description="Your brand on top of Fluent 2 or Material 3. A project uses one by setting design_system.id to “org:<id>”. Brand colours must reach 4.5:1 contrast with white text."
        example={THEME_EXAMPLE}
        load={async (signal) => {
          const t = await api.getOrgThemes(signal);
          return { version: t.version, value: t.themes, note: note(t.version) };
        }}
        save={async (value, version) => {
          const t = await api.saveOrgThemes(value, version);
          return { version: t.version, value: t.themes, note: note(t.version) };
        }}
      />
    </div>
  );
}
