# AI reply analysis (optional)

When a company replies, the app can ask Google's Gemini to read the reply and suggest:
- a **label**: interview request, interested, needs info, scheduling, application redirect, referral, keep on file, not hiring, rejection, offer, unsubscribe request, or other
- a short summary
- any dates, links, requested documents and people mentioned

Everything is optional. Without a key the app works fully; replies are simply not analysed.

## What the AI can and cannot do

- Every item it returns must **quote the email word for word**. Anything it cannot prove from the email is dropped and shown as "unproven".
- Links must be `http(s)` and actually appear in the email.
- The email is treated as untrusted data. Instructions hidden in an email ("ignore your rules…") are ignored, and even if the model followed them, nothing would happen.
- AI results **never** send, approve or cancel an email, and never change a lead or opportunity stage. They only:
  - set the notification priority
  - show a one-click suggestion that you may accept

## 1. Get a Gemini API key

1. Go to https://aistudio.google.com/apikey and sign in with a Google account.
2. Click **Create API key** and copy it.

**Free tier limits and privacy** (Google's terms at the time of writing):
- About **20 requests per day per model**. The app analyses at most 5 replies every 2 minutes, 4.5 s apart. When the daily quota is used up, analyses fail with "rate limited" and are retried automatically (up to 3 attempts, 10 minutes apart).
- On the free tier, **Google may use your inputs to improve its products.** The reply text is sent to Google, with the quoted history of your own email removed.
- A paid key removes both limits.

## 2. Add the key to `.env`

Open `.env` in a text editor (e.g. Notepad) and set:
```
GEMINI_API_KEY=your-key-here
```
Then restart: `docker compose up -d`.

**Never paste the key into chats, issues or commits.** If it ever leaks, delete it in AI Studio and create a new one.

## 3. Check it works

- **Settings → AI analysis** should show *API key: present in .env*.
- **Inbox:** new replies get an AI label within a few minutes. You can also press **Analyse now** on a reply.

## Choosing the model, or switching AI off

In **Settings → AI analysis**:
- **Analyse replies with AI:** switch analysis off without removing the key.
- **Model:** empty means the default from `.env` (`GEMINI_MODEL`, default `gemini-3.8-flash`). **Show available models** lists what your key can use, and a new model is checked against that list before it is saved.

Changes apply to the next analysis; nothing needs a restart.

Google retires models from time to time. If analyses fail with an HTTP 404 error saying the model is not found, pick another model in Settings.
