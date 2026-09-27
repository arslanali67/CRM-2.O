// Plain-language text for audit_log events. Unknown actions fall back to the raw name.
export function describe(e) {
  const d = e.data || {};
  const [type, verb] = e.action.split(".");
  if (type === "outbound_email") {
    if (verb === "created") return `Email draft to ${d.to_email} created`;
    if (verb === "edited") return `Email draft to ${d.to_email} edited`;
    if (verb === "draft") return `Email to ${d.to_email} pulled back to draft`;
    if (verb === "checks_failed") {
      return `Safety checks failed at ${d.stage}: ${(d.failed || []).map((f) => `${f.name} (${f.detail})`).join("; ")}`;
    }
    if (d.reason === "safety_checks") return `Email to ${d.to_email} cancelled by safety checks`;
    if (verb === "sending") return `Sending email to ${d.to_email}…`;
    if (verb === "sent") return `Email to ${d.to_email} sent${d.via === "recovery" ? " (confirmed in Gmail Sent after an interruption)" : ""}`;
    if (verb === "failed") return `Email to ${d.to_email} failed: ${d.reason}`;
    if (verb === "queued" && d.reason) return `Email to ${d.to_email} back in the queue: ${d.reason}`;
    if (verb === "send_retry") return `Send attempt did not reach Gmail (${d.reason}); will retry`;
    if (verb === "send_interrupted") return `Send interrupted (${d.reason}); checking Gmail Sent before doing anything else`;
    if (verb === "recovered") return "Interrupted send confirmed in Gmail Sent";
    const why = d.reason === "do_not_contact" ? " (recipient blocked)" : "";
    return `Email to ${d.to_email} ${verb}${why}`;
  }
  const text = {
    "profile.updated": "Profile updated",
    "cv.uploaded": `CV uploaded: ${d.label}${d.is_default ? " (default)" : ""}`,
    "cv.default_set": "Default CV changed",
    "company.created": `Company added: ${d.name}`,
    "company.updated": "Company edited",
    "company.archived": "Company archived",
    "company.restored": "Company restored",
    "contact.created": `Contact added${d.email_class ? ` (${d.email_class})` : ""}`,
    "contact.updated": `Contact edited${d.email_class ? ` (${d.email_class}${d.manual ? ", manual" : ""})` : ""}`,
    "contact.archived": "Contact archived",
    "contact.restored": "Contact restored",
    "suppression.added": `Blocked ${d.email || d.domain || "company"}: ${d.reason}`,
    "suppression.lifted": `Block lifted: ${d.reason}`,
    "company.stage_changed": `Stage ${d.from} → ${d.to}${d.close_reason ? ` (${d.close_reason})` : ""}`,
    "compose_list.added": `${d.company_ids?.length} lead(s) added to the compose list`,
    "compose_list.removed": "Lead removed from the compose list",
    "template.created": `Template created: ${d.name}`,
    "template.version_created": `Template saved as version ${d.version}`,
    "template.renamed": `Template renamed to ${d.name}`,
    "template.archived": "Template archived",
    "template.restored": "Template restored",
    "note.created": "Note added",
    "note.edited": "Note edited",
    "note.deleted": "Note deleted",
    "task.created": `Task added: ${d.title}${d.due_date ? ` (due ${d.due_date})` : ""}`,
    "task.edited": `Task edited: ${d.title}`,
    "task.completed": `Task done: ${d.title}`,
    "task.reopened": `Task reopened: ${d.title}`,
    "task.deleted": `Task deleted: ${d.title}`,
    "compose.drafts_created": `${d.created} draft(s) created from template v${d.version}${d.skipped ? `, ${d.skipped} skipped` : ""}`,
    "email_account.saved": `Email account saved: ${d.email_address}`,
    "email_account.tested": `Email account test: ${d.ok ? "connected" : `failed (SMTP ${d.smtp_ok ? "ok" : "failed"}, IMAP ${d.imap_ok ? "ok" : "failed"})`}`,
    "email_account.disconnected": "Email account disconnected (app password deleted)",
    "sending.enabled": "Sending switched ON",
    "sending.disabled": "Sending switched OFF",
    "import.completed": `CSV imported: ${d.file} (${d.new} new companies, ${d.contacts} contacts, ${d.duplicate} duplicates skipped)`,
  }[e.action];
  return text || e.action;
}

export function EventList({ events }) {
  if (!events.length) return <p>No activity yet.</p>;
  return (
    <ul style={{ listStyle: "none", padding: 0 }}>
      {events.map((e) => (
        <li key={e.id} style={{ padding: "6px 0", borderBottom: "1px solid #eee" }}>
          <small style={{ color: "gray" }}>{new Date(e.at).toLocaleString()} · {e.actor}</small>
          <div>{describe(e)}</div>
        </li>
      ))}
    </ul>
  );
}
