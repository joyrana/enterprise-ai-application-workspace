import {
  Body1,
  Button,
  Caption1,
  Field,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Spinner,
  Textarea,
  Title2,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useEffect, useState } from "react";
import { ApiError, api, type OrgPolicy } from "../api/client";
import { ProblemMessage } from "../components/ProblemMessage";
import { useAsync } from "../hooks/useAsync";

const useStyles = makeStyles({
  root: { display: "grid", gap: tokens.spacingVerticalM, maxWidth: "960px" },
  editor: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200, minHeight: "320px" },
  actions: { display: "flex", gap: tokens.spacingHorizontalS, flexWrap: "wrap" },
  list: { margin: 0, paddingLeft: tokens.spacingHorizontalL },
});

const EXAMPLE = {
  rules: [
    { id: "no-file-uploads", kind: "forbidden-components", constructs: ["field:file"] },
    { id: "small-forms", kind: "max-form-fields", max: 20, severity: "warning" },
    { id: "pii", kind: "sensitive-fields", name_patterns: ["email", "ssn"], minimum: "confidential" },
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

/** Organization policies (ADR-0018): typed rules checked deterministically; errors block code generation. */
export function OrganizationPage() {
  const styles = useStyles();
  const { state, setData } = useAsync<OrgPolicy>((signal) => api.getOrgPolicies(signal), "org-policies");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  const loaded = state.status === "success" ? state.data : null;
  useEffect(() => {
    if (loaded) setText(JSON.stringify(loaded.policy, null, 2));
  }, [loaded]);

  if (state.status === "loading") return <Spinner label="Loading organization policies" />;
  if (state.status === "error") return <ProblemMessage error={state.error} />;
  const current = state.data;

  const save = async () => {
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
      setData(await api.saveOrgPolicies(parsed, current.version));
      setSaved(true);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.root}>
      <Title2 as="h1">Organization policies</Title2>
      <Body1>
        Rules every project in your organization is checked against. Rules with severity &quot;error&quot; block code
        generation and builds until the specification complies; &quot;warning&quot; rules are reported. Only
        organization admins can change them.
      </Body1>
      <Caption1>
        {current.version === 0
          ? "No policies saved yet."
          : `Version ${current.version}, last changed by ${current.updated_by ?? "unknown"}.`}
      </Caption1>
      <Field label="Policy (JSON)" hint="Each rule has an id, a kind and optional severity (error or warning).">
        <Textarea
          className={styles.editor}
          value={text}
          onChange={(_, data) => {
            setText(data.value);
            setSaved(false);
          }}
          resize="vertical"
        />
      </Field>
      <div className={styles.actions}>
        <Button appearance="primary" disabled={busy} onClick={() => void save()}>
          {busy ? "Saving…" : "Save policies"}
        </Button>
        <Button onClick={() => setText(JSON.stringify(EXAMPLE, null, 2))}>Insert example</Button>
      </div>
      {saved && (
        <MessageBar intent="success" role="status">
          <MessageBarBody>Saved as version {current.version}.</MessageBarBody>
        </MessageBar>
      )}
      {error !== null && <ProblemMessage error={error} />}
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
    </div>
  );
}
