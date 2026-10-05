import { describe, expect, it } from "vitest";
import type { Proposal } from "../../api/client";
import { viewProposal } from "./proposals";

describe("viewProposal", () => {
  it("describes a proposed screen with its components and the requirements it serves", () => {
    const view = viewProposal({
      op: "add_item",
      proposal_id: "p-approvals-queue",
      collection: "screens",
      item: {
        id: "approvals-queue",
        name: "Approvals queue",
        purpose: "Review risky transactions.",
        requirement_ids: ["route-risky-transactions"],
        components: [
          { id: "risky", kind: "table", label: "Risky transactions", entity_id: "transaction" },
          { id: "note", kind: "text" },
        ],
      },
      rationale: null,
    } as unknown as Proposal);
    expect(view.group).toBe("screens");
    expect(view.label).toBe("Screen");
    expect(view.text).toBe("Approvals queue");
    expect(view.detail).toBe(
      'Review risky transactions. · Components: table "Risky transactions" of transaction, text · Serves: route-risky-transactions',
    );
  });
});
