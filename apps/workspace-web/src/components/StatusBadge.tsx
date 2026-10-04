import { Badge } from "@fluentui/react-components";

const LABELS = {
  unknown: { label: "Unknown", color: "informative" },
  proposed: { label: "Proposed", color: "warning" },
  confirmed: { label: "Confirmed", color: "success" },
} as const;

export type FactStatus = keyof typeof LABELS;

/** Status is always conveyed by text, never by colour alone. */
export function StatusBadge({ status }: { status: FactStatus }) {
  const { label, color } = LABELS[status];
  return (
    <Badge appearance="tint" color={color} shape="rounded">
      {label}
    </Badge>
  );
}
