import type { Proposal } from "../../api/client";

export type ProposalGroup = "facts" | "personas" | "requirements" | "assumptions" | "questions" | "other";

export interface ProposalView {
  id: string;
  group: ProposalGroup;
  label: string;
  text: string;
  detail?: string;
  badges: string[];
}

export const GROUP_LABELS: Record<ProposalGroup, string> = {
  facts: "Key facts",
  personas: "Personas",
  requirements: "Functional requirements",
  assumptions: "Assumptions",
  questions: "Open questions",
  other: "Other",
};

const FACT_LABELS: Record<string, string> = {
  "/objective": "Business objective",
  "/domain": "Application domain",
  "/security/classification": "Data classification",
  "/security/risk_level": "Risk level",
  "/accessibility/standard": "Accessibility standard",
};

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * Presentation-only view of a proposal. The backend owns the proposal contract;
 * this reads it defensively so an unexpected shape degrades to "Other" instead of crashing.
 */
export function viewProposal(proposal: Proposal): ProposalView {
  const p = proposal as unknown as Record<string, unknown>;
  const id = str(p.proposal_id);
  if (p.op === "set_fact") {
    const path = str(p.path);
    return { id, group: "facts", label: FACT_LABELS[path] ?? path, text: str(p.value), badges: [] };
  }
  if (p.op === "add_open_question") {
    return {
      id,
      group: "questions",
      label: "Question",
      text: str(p.question),
      badges: p.blocking === true ? ["Blocking"] : [],
    };
  }
  if (p.op === "add_item") {
    const item = (typeof p.item === "object" && p.item !== null ? p.item : {}) as Record<string, unknown>;
    switch (p.collection) {
      case "personas":
        return {
          id,
          group: "personas",
          label: "Persona",
          text: str(item.name),
          detail: str(item.description),
          badges: [],
        };
      case "functional_requirements":
        return {
          id,
          group: "requirements",
          label: "Requirement",
          text: str(item.title),
          detail: str(item.description),
          badges: item.priority ? [str(item.priority).toUpperCase()] : [],
        };
      case "assumptions":
        return { id, group: "assumptions", label: "Assumption", text: str(item.statement), badges: [] };
      default:
        return { id, group: "other", label: str(p.collection), text: JSON.stringify(item), badges: [] };
    }
  }
  return { id, group: "other", label: "Proposal", text: JSON.stringify(p), badges: [] };
}

export const OUTCOME_LABELS: Record<string, string> = {
  applied: "Applied",
  rejected_by_user: "Rejected",
  skipped_confirmed_fact: "Kept your confirmed value",
  skipped_duplicate: "Already present",
  skipped_id_conflict: "Identifier already used",
  invalid: "Not valid for the specification",
  would_break_references: "Skipped: depends on a rejected proposal",
};
