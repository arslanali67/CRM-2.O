"use client";
import { useRouter } from "next/navigation";

export const STAGES = ["new", "applied", "screening", "interviewing", "offer", "hired", "rejected", "withdrawn"];
export const STAGE_COLOR = { new: "#888", applied: "steelblue", screening: "teal", interviewing: "darkorange",
  offer: "seagreen", hired: "green", rejected: "crimson", withdrawn: "#aaa" };

export const StageBadge = ({ stage }) => (
  <mark style={{ background: STAGE_COLOR[stage], color: "white", padding: "0 6px", borderRadius: 4 }}>{stage}</mark>
);

// M19: one click from a reply (never automatic). Prefills a title; the owner can change it.
export function CreateOpportunity({ messageId, companyId, suggestedTitle, label = "Create opportunity" }) {
  const router = useRouter();
  async function create() {
    const title = window.prompt("Role / opportunity title:", suggestedTitle || "");
    if (!title?.trim()) return;
    const body = messageId ? { inbound_message_id: messageId, title } : { company_id: companyId, title };
    const res = await fetch("/api/opportunities", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await res.json();
    if (res.ok) router.push(`/opportunities/${data.id}`);
    else window.alert(data.detail || "Could not create the opportunity");
  }
  return <button onClick={create}>{label}</button>;
}
