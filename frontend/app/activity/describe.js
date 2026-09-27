// Plain-language text for audit_log events. Unknown actions fall back to the raw name.
export function describe(e) {
  const d = e.data || {};
  const [type, verb] = e.action.split(".");
  if (type === "outbound_email") {
    if (verb === "created") return `Email draft to ${d.to_email} created`;
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
