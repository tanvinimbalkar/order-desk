# Order Desk

Order Desk is a small Streamlit demo for Linden Supply, a fictional reusable-bag company that sells custom bag programs to retailers. It catches breaks between a purchase order, the shipment notice, and the invoice before a retailer files a chargeback.

Tagline: **An AI ops agent for a fictional bag supplier. Click Run morning check and watch it work.**

All retailers, styles, and dollar amounts are fictional.

## What it does

The desk holds six purchase orders across three retailers (Northfield Grocers, BrightMart, and Coastal Pharmacy). Each order has three simplified EDI records:

- **850** purchase order: PO number, retailer, dates, and line items (style, description, quantity, price)
- **856** shipment notice: PO number, ship date, and quantity shipped by style
- **810** invoice: invoice number, PO number, and quantity billed and price by style

Four orders have one planted problem: a short shipment, an invoice price that does not match the PO, a missing line, or a shipment after the cancel date. Two orders are clean.

A sample-day control switches between Monday and Tuesday. Each day keeps its own approvals for the session. The app has three tabs:

- **Agent** — Run morning check. The agent reads each order out loud, then shows the summary, a morning brief, and a proposed fix for every problem. Approve, Edit, Skip, or View order. Ask the agent about the day.
- **Orders** — each PO with Ordered / Shipped / Invoiced by line. Mismatches are amber. High chargeback risk is red. The badge is Clean, Needs attention, or Resolved.
- **Exceptions** — the same proposed fixes, plus Resolved today.

## How matching works

Matching is plain Python in `core/match.py`. There is no model in the loop.

1. Pair the 856 and the 810 to the 850 by `po_number`.
2. Pair line items by `style_code`.
3. Flag a line or the whole order:

| Rule | What it means | Dollars | Chargeback risk |
| --- | --- | --- | --- |
| Short shipment | The style is on the shipment, but quantity shipped is less than quantity ordered | Unshipped units × PO price | Medium |
| Quantity billed | Quantity billed is not the quantity shipped | Absolute unit gap × invoice price | Medium |
| Price | Invoice unit price is not the PO unit price | Absolute price gap × quantity billed | Low |
| Missing line | A style is on the PO but missing from the shipment or the invoice, or it appears on the shipment or invoice without a PO line | Extended price of the missing units | High |
| Late shipment | Ship date is after the cancel date | Full PO merchandise value | High |

A style that is absent from both the shipment and the invoice is one missing line, not also a short shipment. A ship date on the cancel date is still on time. Several rules can apply to one order; each keeps its own dollar figure, so the total at risk can overlap when that happens.

`data/sample.py` builds two books. Monday uses `random.Random(42)` and PO-850-1001 through PO-850-1006. Tuesday uses `random.Random(99)` and PO-850-2001 through PO-850-2006, with the planted problems on different orders.

Lists are sorted by chargeback risk (High, then Medium, then Low), and by dollars within a risk level.

## The morning brief and the agent

Gemini writes a 4 to 6 line brief from the flagged exceptions and the totals only. The prompt tells it to use the counts, PO numbers, and dollar amounts verbatim. After each draft, the app checks that every number, PO number, and retailer name in the reply is in that day's data. If the check fails, it tries once more, then uses a rule-based brief. The caption stays "Written by AI from this run."

`scripts/precompute.py` calls Gemini once per sample day and saves the brief plus answers for the three suggested questions to `data/cache/monday.json` and `data/cache/tuesday.json`. Those files are the fallback when the key is missing or the API fails. The app does not show that fallback.

The chat can call four tools: `list_exceptions`, `get_order`, `draft_email`, and `mark_resolved`. Drafted messages are templates filled with the real figures.

The key and model come from Streamlit secrets:

- `GEMINI_API_KEY`
- `MODEL` — a free-tier Gemini Flash model, for example `gemini-3.8-flash`

If the saved brief is missing or fails those checks, the run uses the rule-based brief.

## Run it locally

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
streamlit run app.py
```

To generate the Gemini brief, copy the secrets example, add a key, and precompute from the project root:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
python scripts/precompute.py
```

Edit `.streamlit/secrets.toml` so `GEMINI_API_KEY` is your key and `MODEL` is a free-tier Flash model. Precompute reads those values with `st.secrets`. Commit `data/cache/` if you want the deployed app to have the fallback brief and answers. Do not commit `secrets.toml`.

## Tests

`pytest` covers every match rule (short ship, billed quantity, price, missing line, late ship), the seeded sample, the rule-based brief, cache fallback, and the email drafts.

## Deploy on Streamlit Community Cloud

1. Push this project to GitHub. Include `data/cache/` if you ran precompute and want those fallbacks in production.
2. Open [share.streamlit.io](https://share.streamlit.io), choose **Create app**, and point it at the repo.
3. Set the main file to `app.py`. The Python version should be 3.11 or newer.
4. Under **Advanced settings → Secrets**, paste:

```toml
GEMINI_API_KEY = "your-key-here"
MODEL = "gemini-3.8-flash"
```

Secrets let the deployed app write a live brief and answer questions. If the key is missing, or the API fails, the app uses `data/cache/` and does not show an error. If those files are missing too, the brief is built from the exception list.

5. Deploy. The app should open on the Agent tab for Monday, with Run morning check and the empty-state card.

## Artwork & Approvals

The same app has a second workspace, Artwork & Approvals. The public link stays in **demo mode**: fictional Linden Supply projects, no Gmail, Drive, or other live connections, and no model calls. A **trial** is a separate private deployment for one company, pointed at that company's own tools.

`?workspace=artwork` opens the artwork workspace. `?workspace=orders`, or no parameter, opens Orders & Shipments exactly as before.

Demo and trial use the same tables. Demo stores them in SQLite. A trial stores them in Postgres (Supabase). Files stay in the company's Google Drive; the app stores the Drive file id and a small preview, not a second copy of the print file.

### Onboard a trial company in under 30 minutes

1. Create a Supabase project and copy the Postgres connection string.
2. Copy `tenant.example.yaml` to `tenant.yaml`. Set `mode: trial`, `llm_paid: true`, and the paid model name. Turn on Gmail, Drive, and WhatsApp. Add ClickUp or HubSpot only if the company uses them.
3. Set environment variables: `DATABASE_URL`, `TOKEN_KEY` (a long random string), `LLM_API_KEY`, `LLM_PAID=true`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
4. In Google Cloud, create an OAuth client, enable the Gmail API and the Drive API, and add the redirect you will use. Scopes are `gmail.readonly`, `gmail.compose` (drafts only), and `drive.readonly`.
5. ClickUp: a personal token with read access to one list. HubSpot: a private app token that can read deals and contacts. Paste each token on the Settings tab. It is encrypted with `TOKEN_KEY` before it is stored.
6. Deploy on Render as a private web service: `pip install -r requirements.txt`, then `streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`. Put the same environment variables on the service. Require the Render login or your host's login in front of the app. The app also asks each teammate for the email and password stored for them.
7. Add a Render cron, or set the GitHub Actions variable `ARTWORK_TRIAL` to `true`, so `python worker.py` runs each morning. Streamlit does not run that job itself.
8. Sign in, open Settings, confirm each connector says connected, and upload one WhatsApp export (`.txt` or `.zip`) to prove the pipeline. Re-uploading the same export does not duplicate messages.
9. Send one proof from the Proofing tab and open the token link in a private window. The customer does not need an account. Factory links work the same way, in English and Simplified Chinese.

When the trial ends, run `python delete_tenant_data.py --yes`. That removes the company's stored rows.

Customer proof links look like `?proof=...` and factory links look like `?factory=...`. They expire after 30 days and can be revoked. An old or revoked link says: "This link has expired, please contact [company]."

### What data this app accesses and how it is protected

This app reads the mail, files, and chats you choose so your team can see which packaging job is stuck. It does not send email to your customers. When someone presses Approve, the note is saved as a draft for a person to send.

Here is what a trial can read, and only if you switch that connection on:

- **Gmail.** Messages from a label you pick, or from the inbox after a start date. The app can create drafts. It cannot send mail.
- **Google Drive.** Files inside one folder you pick. Each subfolder is a project. The app does not change those files.
- **WhatsApp.** Only a chat export you upload. There is no connection to WhatsApp itself.
- **ClickUp and HubSpot.** Optional. Read-only, and only if you turn them on.
- **Proof and factory links.** A customer or factory opens one project from a private link. They do not see your other projects.

Passwords are stored as hashes. Connector tokens are encrypted before they are saved. Pages should be served over HTTPS, which Render and Streamlit Cloud do. Customer text is sent to an AI model only in a trial, and only to a paid model you name in the config. It is not sent to a free model, and it is not used to train a model. The public demo never calls a model; it uses the saved fictional examples.

You choose how long the trial data is kept. At the end, `delete_tenant_data.py` deletes what this app stored. Files in Google Drive are not deleted, because this app never took a copy of them.

