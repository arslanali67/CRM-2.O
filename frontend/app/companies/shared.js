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

export function errorText(body) {
  if (Array.isArray(body?.detail)) {
    return body.detail.map((d) => `${d.loc.slice(1).join(".") || "input"}: ${d.msg}`).join("; ");
  }
  return body?.detail || "Something went wrong";
}
