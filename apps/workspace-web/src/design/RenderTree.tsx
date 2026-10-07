import {
  Body1,
  Body1Strong,
  Button,
  Caption1,
  Card,
  Checkbox,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Select,
  Subtitle1,
  Subtitle2,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Textarea,
  Title1,
  Title2,
  Title3,
  Toolbar,
  ToolbarButton,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import type { ElementType, FormEvent, ReactNode } from "react";
import type { RenderNode } from "../api/client";

/**
 * Renders an adapter's render tree (data from the API) with real Fluent components.
 *
 * The tree is untrusted data: only allowlisted components are rendered, only allowlisted
 * props with validated values are passed, text is rendered as text, and nothing is
 * evaluated. Anything else is shown as an explicit "unsupported" marker. No event handlers
 * are ever taken from the data; forms do not submit.
 */

type Check = (value: unknown) => boolean;

const str: Check = (v) => typeof v === "string" && v.length <= 300;
const bool: Check = (v) => typeof v === "boolean";
const smallInt: Check = (v) => typeof v === "number" && Number.isInteger(v) && v > 0 && v < 100;
const length: Check = (v) => typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 100_000;
const short: Check = (v) => typeof v === "string" && v.length > 0 && v.length <= 200;
const route: Check = (v) => typeof v === "string" && /^\/[a-z0-9/-]{0,199}$/.test(v);
const oneOf =
  (...values: string[]): Check =>
  (v) =>
    typeof v === "string" && values.includes(v);

const TYPOGRAPHY = { as: oneOf("h1", "h2", "h3", "h4", "p", "span") };

interface Entry {
  render: ElementType;
  props: Record<string, Check>;
}

export const REGISTRY: Record<string, Entry> = {
  Title1: { render: Title1, props: TYPOGRAPHY },
  Title2: { render: Title2, props: TYPOGRAPHY },
  Title3: { render: Title3, props: TYPOGRAPHY },
  Subtitle1: { render: Subtitle1, props: TYPOGRAPHY },
  Subtitle2: { render: Subtitle2, props: TYPOGRAPHY },
  Body1: { render: Body1, props: TYPOGRAPHY },
  Body1Strong: { render: Body1Strong, props: TYPOGRAPHY },
  Caption1: { render: Caption1, props: TYPOGRAPHY },
  Field: { render: Field, props: { label: str, required: bool, hint: str } },
  Input: { render: Input, props: { name: str, type: oneOf("text", "number", "date", "datetime-local"), required: bool, min: short, max: short, minLength: length, maxLength: length, pattern: short, step: oneOf("any") } },
  Textarea: { render: Textarea, props: { name: str, required: bool, minLength: length, maxLength: length } },
  Select: { render: Select, props: { name: str, required: bool } },
  Checkbox: { render: Checkbox, props: { label: str, name: str, required: bool } },
  Button: { render: Button, props: { appearance: oneOf("primary", "secondary"), type: oneOf("button", "submit"), navigateTo: route } },
  Table: { render: Table, props: { "aria-label": str } },
  TableHeader: { render: TableHeader, props: {} },
  TableRow: { render: TableRow, props: {} },
  TableHeaderCell: { render: TableHeaderCell, props: {} },
  TableBody: { render: TableBody, props: {} },
  TableCell: { render: TableCell, props: { colSpan: smallInt } },
  Card: { render: Card, props: { "aria-label": str } },
  MessageBar: { render: MessageBar, props: { intent: oneOf("info", "warning", "error", "success") } },
  MessageBarBody: { render: MessageBarBody, props: {} },
  MessageBarTitle: { render: MessageBarTitle, props: {} },
  Toolbar: { render: Toolbar, props: { "aria-label": str } },
  ToolbarButton: { render: ToolbarButton, props: { appearance: oneOf("primary", "subtle"), navigateTo: route } },
  form: { render: "form", props: { "aria-label": str } },
  section: { render: "section", props: { "aria-label": str } },
  div: { render: "div", props: { "data-unsupported": str, "data-role": oneOf("actions") } },
  span: { render: "span", props: {} },
  option: { render: "option", props: { value: str, disabled: bool } },
  input: { render: "input", props: { type: oneOf("file"), name: str } },
};

const MAX_DEPTH = 24;

const useStyles = makeStyles({
  form: { display: "grid", gap: tokens.spacingVerticalM, maxWidth: "560px" },
  actions: { display: "flex", gap: tokens.spacingHorizontalS, flexWrap: "wrap" },
  unsupported: {
    padding: tokens.spacingVerticalS,
    border: `${tokens.strokeWidthThin} dashed ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusMedium,
    color: tokens.colorNeutralForeground2,
  },
  section: { display: "grid", gap: tokens.spacingVerticalS },
});

function safeProps(entry: Entry, props: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props)) {
    const check = entry.props[key];
    if (check?.(value)) out[key] = value;
  }
  return out;
}

const preventSubmit = (event: FormEvent) => event.preventDefault();

function RenderOne({ node, depth }: { node: RenderNode; depth: number }) {
  const styles = useStyles();
  const entry = Object.prototype.hasOwnProperty.call(REGISTRY, node.component) ? REGISTRY[node.component] : undefined;
  if (!entry || depth > MAX_DEPTH) {
    return (
      <div className={styles.unsupported} data-unknown-component={node.component}>
        Unsupported component: {node.component}
      </div>
    );
  }
  const props = safeProps(entry, node.props as Record<string, unknown>);
  // The preview shows the design only: navigation targets are for generated code, not DOM attributes.
  delete props.navigateTo;
  const childNodes = node.children ?? [];

  // A native control inside Field needs the render-function form to receive the label wiring.
  const onlyChild = childNodes.length === 1 ? childNodes[0] : undefined;
  if (node.component === "Field" && onlyChild?.component === "input") {
    const inputProps = safeProps(REGISTRY.input as Entry, onlyChild.props as Record<string, unknown>);
    return <Field {...props}>{(fieldProps) => <input {...fieldProps} {...inputProps} />}</Field>;
  }

  const children: ReactNode[] = [];
  if (node.text) children.push(node.text);
  childNodes.forEach((child, i) => children.push(<RenderOne key={i} node={child} depth={depth + 1} />));

  const extra: Record<string, unknown> = {};
  if (node.component === "form") {
    extra.onSubmit = preventSubmit;
    extra.className = styles.form;
    extra.noValidate = true;
  } else if (node.component === "div" && props["data-role"] === "actions") {
    extra.className = styles.actions;
  } else if (node.component === "div" && props["data-unsupported"]) {
    extra.className = styles.unsupported;
  } else if (node.component === "section") {
    extra.className = styles.section;
  }
  const Component = entry.render;
  // Field and Select expect exactly one child element; pass it directly rather than in an array.
  const content = children.length === 1 ? children[0] : children.length === 0 ? undefined : children;
  return (
    <Component {...props} {...extra}>
      {content}
    </Component>
  );
}

export function RenderTree({ nodes }: { nodes: RenderNode[] }) {
  return (
    <>
      {nodes.map((node, i) => (
        <RenderOne key={i} node={node} depth={0} />
      ))}
    </>
  );
}
