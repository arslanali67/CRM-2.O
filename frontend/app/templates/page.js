"use client";
// F4: templates list; "New template" opens an editor dialog with the live preview.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { errorText } from "../companies/shared";
import { EmptyState, Loading, Modal, PageHeader, useToast } from "../ui";
import { LivePreview, TemplateFields } from "./editor";

const EMPTY = { name: "", subject: "", body: "" };

export default function Templates() {
  const router = useRouter();
  const toast = useToast();
  const [list, setList] = useState(null);
  const [archived, setArchived] = useState(false);
  const [form, setForm] = useState(null);

  async function load() {
    const res = await fetch(`/api/templates?archived=${archived}`);
    if (res.status === 401) return router.replace("/login");
    setList(await res.json());
  }
  useEffect(() => { load(); }, [archived]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create(e) {
    e.preventDefault();
    const res = await fetch("/api/templates", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
    const data = await res.json();
    if (!res.ok) return toast(errorText(data), "error");
    router.push(`/templates/${data.id}`);
  }

  if (!list) return <Loading what="templates" />;
  return (
    <main>
      <PageHeader title="Email templates" sub="Every edit is saved as a new version; old versions never change."
        actions={<>
          <label style={{ display: "flex", gap: 6, alignItems: "center" }}><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived</label>
          <button className="btn-primary" onClick={() => setForm(EMPTY)}>New template</button>
        </>} />
      {list.length === 0 ? (
        <EmptyState title={archived ? "No archived templates" : "Write your first template"}
                    action={!archived && <button className="btn-primary" onClick={() => setForm(EMPTY)}>New template</button>}>
          Use variables like {"{{company_name}}"} and {"{{contact_first_name | there}}"}; the preview shows the result for a real lead.
        </EmptyState>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Current subject</th><th>Version</th><th>Updated</th></tr></thead>
            <tbody>
              {list.map((t) => (
                <tr key={t.id}>
                  <td><Link href={`/templates/${t.id}`}><b>{t.name}</b></Link></td>
                  <td className="clip" style={{ maxWidth: 380 }} title={t.subject}>{t.subject}</td>
                  <td><span className="badge">v{t.version}</span></td>
                  <td><small>{new Date(t.version_created_at).toLocaleDateString()}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {form && (
        <Modal title="New template" wide onClose={() => setForm(null)}>
          <form onSubmit={create}>
            <label className="field"><span>Name</span>
              <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <TemplateFields value={form} onChange={setForm} />
            <div style={{ marginTop: 12 }}><LivePreview subject={form.subject} body={form.body} /></div>
            <div className="dialog-actions"><button type="button" onClick={() => setForm(null)}>Cancel</button>
              <button type="submit" className="btn-primary">Create template</button></div>
          </form>
        </Modal>
      )}
    </main>
  );
}
