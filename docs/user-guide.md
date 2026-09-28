# User guide

Every page is linked from the **Dashboard** (http://localhost:3000). The top bar has a **search** box and the **notifications bell**.

The daily loop:

**Import → pick leads → compose drafts → review & approve each email → (sending ON) → replies arrive → opportunities & tasks**

## 1. Profile & CV (once)

**Profile & CV** holds your details, which templates can use as variables:
- name, email, phone, headline
- skills, experience
- links, target roles, availability

Upload your CV as a **PDF** (max 5 MB). Each upload is a new, unchangeable version, and one version is the default.

## 2. Getting companies in

- **Import CSV:** upload an `ai_companies` CSV.
  - Required columns: `company`, `website` and `all_emails`.
  - Optional columns, among others: `field` (industry), `linkedin` and `contact_name`.
  - You can set the city and country for the whole batch.
  - **Preview** first; nothing is saved until you click **Import N new companies**.
  - Duplicates (same domain or email) and unusable rows are skipped. You can download them as a "rejected rows" CSV.
- **Leads → Add company:** add one by hand.
- Contacts' emails are classified automatically as careers, personal, generic or unsuitable. You can override the class on the contact.

## 3. Leads

**Leads** lists your companies.
- **Stages:** new, qualified, contacted, replied, closed (needs a reason), on hold. "Contacted" and "replied" are set automatically from real events.
- **Filters:** stage, source, text, reply status, AI label, template used, and dates.
- **Bulk actions:** set the stage, or **Add to compose list**.
- Click a company for its page. The tabs there are overview, contacts, emails, replies, opportunities, notes, tasks and timeline.
- **Duplicates** (link on Leads) suggests companies that are probably the same. You pick which one to keep; the merge moves everything and can be undone. Nothing merges automatically.

## 4. Templates

**Templates** have a name, a subject and a plain-text body. Every edit saves a new version.

Variables use `{{name}}`, or `{{name | fallback}}` for a value used when the variable is empty:

| Group | Variables |
|---|---|
| Company | `company_name`, `company_domain`, `company_website`, `company_city`, `company_country`, `company_industry` |
| Contact | `contact_name`, `contact_first_name`, `contact_role`, `contact_email` |
| You | `my_full_name`, `my_first_name`, `my_email`, `my_phone`, `my_location`, `my_headline`, `my_summary`, `my_skills`, `my_top_skills`, `my_current_title`, `my_current_company`, `my_linkedin`, `my_github`, `my_portfolio`, `my_target_role`, `my_availability` |

Example: `Hi {{contact_first_name | there}},`.

## 5. Compose → review → approve

1. **Compose list:** choose a template, choose whether to attach your CV, and click **Create N draft(s)**.
   - The best contact of each company is picked automatically.
   - Companies with unresolved variables are skipped, and the reason is shown.
2. **Outbox → Drafts:** open each email and read exactly what will be sent. You can edit the subject and body, **Discard** the draft, or click **Approve & queue this email**.
   - Approval runs **12 safety checks**:
     - do-not-contact
     - valid address
     - known, suitable contact
     - active lead
     - no duplicate in flight
     - recipient cooldown
     - company cooldown
     - variables resolved
     - content complete
     - approval valid
     - rate limits
     - kill switch

     A failed check refuses the approval and tells you why.
   - Approval is bound to the exact content. Any later change needs a new approval; **Pull back to draft** clears it.
3. **Sending switch** (top of the Outbox): nothing is sent while it is OFF. See [email.md](email.md#4-sending-is-off-until-you-switch-it-on).

**History** shows everything sent, with delivery and bounce status. Threads show your email and the replies together.

## 6. Replies

- **Inbox:** stored messages with their label (reply, auto-reply, bounce, unrelated) and, if enabled, the AI analysis ([ai.md](ai.md)).
- A reply **cancels pending emails to that company** and sets the lead to *replied*. The app never answers; follow-ups are **tasks** for you.
- The **notifications bell** shows new replies, bounces, sending problems and system problems. Choose which kinds appear in **Settings**.

## 7. Opportunities

From a reply, click **Create opportunity** (one click, never automatic).
- **Stages:** new → applied → screening → interviewing → offer → hired, plus rejected and withdrawn.
- Every stage change is recorded with who, when and why.
- AI labels only *suggest* a stage.

## 8. Notes and tasks

Notes and tasks can be attached to companies, contacts, templates and opportunities. **Tasks** shows what is due and overdue.

## 9. Do-not-contact

**Do-not-contact** blocks an email, a whole domain or a company.
- A block immediately cancels pending emails, and the database refuses any email to a blocked recipient.
- Blocks are never deleted, only lifted with a reason.
- Hard bounces add blocks automatically.

## 10. Settings

Settings covers:
- sending limits: daily cap, gap, how long an approval stays valid
- cooldowns: per recipient and per company
- AI on/off and the model
- notification kinds

Changes apply immediately and are recorded in **Activity**.

## 11. Backup, export, activity

- **Backup & export:** see [backup.md](backup.md).
- **Activity:** every change, who made it (you or the system) and when.
