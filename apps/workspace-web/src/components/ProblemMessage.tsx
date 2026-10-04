import {
  Button,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  MessageBarTitle,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import type { ReactNode } from "react";
import { ApiError } from "../api/client";

const useStyles = makeStyles({
  list: { margin: `${tokens.spacingVerticalXS} 0 0`, paddingLeft: tokens.spacingHorizontalL },
  path: { fontFamily: tokens.fontFamilyMonospace },
  meta: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
});

interface Props {
  error: unknown;
  onRetry?: () => void;
  action?: ReactNode;
}

/** Renders an API problem (or unexpected error) without leaking internals. */
export function ProblemMessage({ error, onRetry, action }: Props) {
  const styles = useStyles();
  const problem = error instanceof ApiError ? error.problem : null;
  const title = problem?.title ?? "Something went wrong";
  const detail = problem ? problem.detail : "An unexpected error occurred in the workspace.";

  return (
    <MessageBar intent="error" layout="multiline" role="alert">
      <MessageBarBody>
        <MessageBarTitle>{title}</MessageBarTitle>
        {detail}
        {problem?.errors && problem.errors.length > 0 && (
          <ul className={styles.list} aria-label="Problems">
            {problem.errors.map((e) => (
              <li key={`${e.path}:${e.message}`}>
                <span className={styles.path}>{e.path}</span>: {e.message}
              </li>
            ))}
          </ul>
        )}
        {problem?.request_id && <div className={styles.meta}>Request id: {problem.request_id}</div>}
      </MessageBarBody>
      {(onRetry || action) && (
        <MessageBarActions>
          {action}
          {onRetry && <Button onClick={onRetry}>Retry</Button>}
        </MessageBarActions>
      )}
    </MessageBar>
  );
}
