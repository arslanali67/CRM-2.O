"use client";
import { useRouter } from "next/navigation";
import { useDialog } from "../ui";

export const STAGES = ["new", "applied", "screening", "interviewing", "offer", "hired", "rejected", "withdrawn"];
const STAGE_TONE = { new: "", applied: "accent", screening: "accent", interviewing: "warning", offer: "success",
  hired: "success", rejected: "danger", withdrawn: "" };

export const StageBadge = ({ stage }) => <span className={`badge${STAGE_TONE[stage] ? ` badge-${STAGE_TONE[stage]}` : ""}`}>{stage}</span>;

// M19: one click from a reply (never automatic). Prefills a title; the owner can change it.
export function CreateOpportunity({ messageId, companyId, suggestedTitle, label = "Create opportunity" }) {
  const dialog = useDialog();
  const router = useRouter();
  async function create() {
    const title = await dialog.prompt("Create opportunity", { label: "Role / opportunity title", defaultValue: suggestedTitle || "", required: true, confirmLabel: "Create" });
    if (!title?.trim()) return;
    const body = messageId ? { inbound_message_id: messageId, title } : { company_id: companyId, title };
    const res = await fetch("/api/opportunities", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await res.json();
    if (res.ok) router.push(`/opportunities/${data.id}`);
    else await dialog.alert("Couldn't create the opportunity", { body: data.detail || "" });
  }
  return <button onClick={create}>{label}</button>;
}
