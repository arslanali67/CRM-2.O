export const COMPANY_FIELDS = [
  ["name", "Name *"],
  ["website", "Website", "url"],
  ["domain", "Domain (filled from website if empty)"],
  ["industry", "Industry"],
  ["city", "City"],
  ["country", "Country"],
  ["linkedin_url", "LinkedIn URL", "url"],
  ["description", "Description", "textarea"],
];

export const CONTACT_FIELDS = [
  ["name", "Name"],
  ["email", "Email", "email"],
  ["role", "Role"],
  ["phone", "Phone"],
  ["linkedin_url", "LinkedIn URL", "url"],
];

export const EMAIL_CLASSES = ["careers", "personal", "generic", "unsuitable"];

export const STAGES = ["new", "qualified", "contacted", "replied", "closed", "on_hold"];

export function errorText(body) {
  if (Array.isArray(body?.detail)) {
    return body.detail.map((d) => `${d.loc.slice(1).join(".") || "input"}: ${d.msg}`).join("; ");
  }
  return body?.detail || "Something went wrong";
}

const STAGE_TONE = { new: "", qualified: "accent", contacted: "accent", replied: "success", closed: "danger", on_hold: "warning" };
export const LeadStage = ({ stage }) => (
  <span className={`badge${STAGE_TONE[stage] ? ` badge-${STAGE_TONE[stage]}` : ""}`}>{stage.replace("_", " ")}</span>
);

// Company form fields (Add company dialog, Overview edit).
export function CompanyFields({ form, setForm }) {
  return COMPANY_FIELDS.map(([k, label, type]) => (
    <label key={k} className="field">
      <span>{label}</span>
      {type === "textarea"
        ? <textarea rows={3} value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
        : <input type={type || "text"} required={k === "name"} value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />}
    </label>
  ));
}
