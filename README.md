# AWM Chat

Internal multi-agent AI chat application for Ascot Wealth Management.

> **AWM Chat is a living tool — it grows with the team.**
> It ships deliberately lean. New capability — document and image upload, integration with internal company apps, and so on — is added as the team asks for it. See [Roadmap](#roadmap).

## What this is

A private, company-internal chat interface to **three AI agents — Claude, OpenAI and Gemini** — with:

* Google Workspace SSO restricted to `@ascotwm.com`
* **In-chat agent switching**, with all three agents reading the same conversation history
* **Per-agent monthly token allowances**, with battery-style level indicators
* **Out-of-tokens handover** — when one agent is spent, the user is offered an agent that isn't, and their message is resent automatically
* Per-user conversation history with pinned context
* Admin dashboard with usage metrics, content review hooks, and editable settings
* Compliance audit trail — chats are company property and subject to spot checks
* GCS-backed append-only conversation archive (BigQuery sink planned for Phase 2)

End-user guide: [`docs/user-manual.md`](docs/user-manual.md).

## Agents

| Agent | Vendor | Models | Key |
|-------|--------|--------|-----|
| Claude | Anthropic | Opus 5, Sonnet 5, Haiku 4.5 | `ANTHROPIC_API_KEY` |
| OpenAI | OpenAI | GPT-4o, GPT-4o mini, GPT-4.1 | `OPENAI_API_KEY` |
| Gemini | Google | Gemini 2.5 Pro, 2.5 Flash | `GEMINI_API_KEY` |

Which models staff can actually pick is controlled by admins via
`settings/global.available_models`. An agent whose key is missing is shown
greyed out in the switcher rather than failing at send time.

### One storage format, three agents

**The stored conversation format never changes.** Firestore and the GCS archive
hold exactly the shape the app used when it was OpenAI-only; each provider
adapter in [`backend/app/providers/`](backend/app/providers/) translates that
shape into its vendor's wire format at send time and never writes it back. That
is what lets a user switch agent mid-thread and have the new agent read
everything that came before, including attachments.

The canonical shape is documented in
[`backend/app/providers/__init__.py`](backend/app/providers/__init__.py).

## Architecture

```
┌─────────────────────────────────┐         ┌──────────────────────┐
│  Cloudflare Pages               │ ──────▶ │  Cloud Run (FastAPI) │
│  React + Vite                   │  HTTPS  │  awm-chat            │
│  chat.chimerasportstrading.com  │ ◀────── │  europe-west1        │
└─────────────────────────────────┘         └──────────┬───────────┘
                                                       │
                ┌──────────────────────────────────────┼──────────────────────────────────────┐
                ▼                                      ▼                                      ▼
       ┌────────────────┐                    ┌──────────────────┐        ┌───────────────────────┐
       │   Firestore    │                    │       GCS        │        │  Anthropic  (Claude)  │
       │  database      │                    │ (chat archives)  │        │  OpenAI     (GPT)     │
       │  `awm-chat`    │                    └─────────┬────────┘        │  Google     (Gemini)  │
       └────────────────┘                              │                 └───────────────────────┘
                                                       ▼                    one adapter each,
                                             ┌──────────────────┐          translating the same
                                             │  BigQuery        │          stored format
                                             │  (Phase 2)       │
                                             └──────────────────┘
```

### Identity

* Firebase Auth with Google provider, restricted to `ascotwm.com` Workspace domain
* Backend verifies the Firebase ID token on every request
* Admin role flag stored in Firestore `users/{uid}.role`

### Data model

All collections live in the named Firestore database **`awm-chat`** (not the project `(default)`):

* `users/{uid}` — profile, role, monthly token cap, selected model, acknowledgement flag. Optional `caps_by_provider` sets a narrower allowance for one agent; anything omitted falls back to `cap_tokens`.
* `conversations/{conv_id}` — owner_uid, title, created_at, updated_at, archived
* `conversations/{conv_id}/messages/{msg_id}` — role, content, token counts, timestamp, plus `model` and `provider` on assistant messages so a mixed-agent thread stays attributable
* `pins/{uid}/items/{pin_id}` — pinned context snippets always included in the prompt
* `usage/{uid}/months/{YYYY-MM}` — token counts, request counts. The top-level `tokens_used` / `input_tokens` / `output_tokens` / `requests` are unchanged all-agent totals; per-agent figures live under `by_provider.{anthropic,openai,google}`. Documents written before multi-agent support are read as OpenAI usage rather than being backfilled.
* `audit/{event_id}` — compliance events (admin actions, flag matches, settings changes)
* `settings/global` — admin-editable defaults: `default_model`, `available_models`, `default_cap_tokens`, `flag_keywords`. Auto-seeded on first read.

**Per-agent allowances.** `cap_tokens` now applies *per agent*, not across all
of them — each agent gets its own pool of that size. That is deliberate: a
shared pool would mean running out on one agent means running out on all three,
which defeats the handover. If you want the old total, divide `cap_tokens` by
the number of enabled agents or set `caps_by_provider` explicitly.

### GCS layout

```
gs://awm-chat-archive/
  conversations/{uid}/{conv_id}.ndjson    # append-only per message
  exports/{YYYY-MM-DD}/...                # nightly BigQuery exports (Phase 2)
```

### AI proxy

The backend is the only thing that holds the vendor API keys (Google Secret Manager). The frontend never sees them. Per request, the proxy:

1. Verifies the user's Firebase JWT
2. Resolves the agent — the model picked in the chat window → per-user `users/{uid}.model` → `settings/global.default_model` → env `DEFAULT_MODEL`, skipping any model that is off the admin allowlist or whose vendor key is missing
3. Checks the user's monthly cap **for that agent**; if it is spent, returns `429` with the list of agents that still have tokens
4. Loads conversation history + pinned context (in the canonical format)
5. Hands it to that vendor's adapter, which translates and streams
6. Streams the response back to the client
7. Persists the exchange to Firestore + GCS in the canonical format
8. Increments per-agent usage counters and runs the keyword-flag check

The cap is checked **before** anything is persisted, so a refused turn leaves no
stray message behind and the client can safely retry on another agent.

### Context and cost control

A long thread with a document attached is dominated by that document, not by the
conversation. Two mechanisms keep a turn's request size bounded — both are
described in full in [`CHANGELOG.md`](CHANGELOG.md) 0.6.0.

**Attachment fidelity is newest-message-only.** A PDF sent natively is billed as
its text *plus* a rendered image per page. Only the newest message sends
attachments natively; earlier turns send the stored text layer, which still lets
the model quote and reason about the document at roughly a quarter of the size.
Scanned PDFs have no text layer and stay native — downgrading those would send
nothing at all. PDF text is extracted at upload with pypdf;
`MAX_EXTRACTED_CHARS` (40,000) bounds it and truncation is marked in-band.

**History is bounded by a token budget, not a message count.** Messages are taken
newest-first until the budget is spent, estimated from the message document alone
so trimming happens before any GCS download. The newest message is always kept
even if it alone exceeds the budget — the provider's own error is better than
silently sending an empty request.

**Prompt caching.** The system prompt is split into `SYSTEM_STABLE` — firm
context and guidance, byte-identical for every user on every day — and a small
volatile half holding the user's name, today's date and their pins, always placed
after it. Anthropic marks the boundary with `cache_control`; OpenAI and Gemini
cache the longest common prefix automatically, so for them the ordering is the
whole mechanism. `cache_read_tokens` / `cache_write_tokens` come back on the
`done` event. **Cached tokens are cheaper, not free** — they still count toward
the user's allowance and do not relieve per-minute rate limits.

### Maintenance tools

Both live in `backend/tools/` and run from a workstation against production.

| Tool | What |
|---|---|
| `export_user_data.py` | Exports one user's data to a zip. `--email` resolves the uid; `--markdown-only` skips attachment binaries while still writing extracted text and transcripts. **Use this rather than the in-app export for large accounts** — the in-app route builds the zip in memory inside a Cloud Run request, and for a heavy user it exhausts the container or outruns the timeout, which the browser reports as "Load failed" with no HTTP error. |
| `backfill_pdf_text.py` | Extracts and stores the text layer for PDFs uploaded before extraction existed. Without it those keep being sent natively on every turn. Idempotent, dry-run by default. |

## Deployment

Live deployment summary:

1. GCP project: **`chiops`** (project number `991649774709`)
2. Backend: Cloud Run service `awm-chat` in **`europe-west1`**, deployed by **Cloud Run's GitHub continuous deployment** (builds from `backend/Dockerfile`). The `cloudbuild.yaml` in this repo is reference material only and is not wired into the active pipeline.
3. Frontend: Cloudflare Pages, deployed by the Cloudflare Pages GitHub integration (`npm run build` from `frontend/`, output `dist/`)
4. Firestore: named database `awm-chat` in `chiops` (set via backend env `FIRESTORE_DATABASE=awm-chat`)
5. Archive: `gs://awm-chat-archive` (region `europe-west2`)
6. Secrets in Secret Manager (`chiops`): `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`.
   Optional, for the org-spend marker only: `ANTHROPIC_ADMIN_KEY`, `OPENAI_ADMIN_KEY`
7. Bootstrap the first admin: see [Operations](#operations) below

Pushing to `main` triggers both rebuilds independently.

## Operations

### Production environments

| Component | Where it lives |
|-----------|----------------|
| Frontend  | Cloudflare Pages project `awm-chat` → domains `awm-chat.pages.dev`, `chat.chimerasportstrading.com` |
| Backend   | Cloud Run service `awm-chat`, region `europe-west1`, project `chiops` |
| Firestore | Named database `awm-chat` in project `chiops` (location `europe-west2`) |
| Secrets   | Secret Manager in project `chiops` |
| Archive   | `gs://awm-chat-archive` (location `europe-west2`) |

### Battery indicators — what they can and cannot show

Each agent in the switcher has a battery. It has two layers, and the reason for
that split is worth recording so it doesn't get re-litigated:

**No AI vendor exposes a remaining-credit-balance API.** Checked for all three:

| Vendor | What is available | Balance endpoint |
|--------|-------------------|------------------|
| Anthropic | Usage & Cost Admin API — `/v1/organizations/usage_report/messages`, `/v1/organizations/cost_report`. Needs an Admin key (`sk-ant-admin01-…`), lands ~5 min after a request | **None.** An open feature request asks for `GET /v1/organizations/me/balance` |
| OpenAI | `/v1/organization/costs` (admin key) — daily spend | **None.** `/v1/dashboard/billing/credit_grants` is an undocumented console endpoint requiring a browser session token, not an API key |
| Google | Cloud Billing Budget API, Project Spend Caps, BigQuery billing export | **None.** The AI Studio prepay balance is console-only |

So the battery shows:

1. **The fill — the user's own monthly token allowance for that agent.** Exact,
   live, needs no admin keys, and is the number that actually gates them. This
   is what drains as they chat.
2. **The thin underbar — organisation-wide month-to-date spend against a
   budget**, read from the vendor's cost API. Best-effort: absent when no admin
   key or budget is configured, and the UI omits it silently rather than
   showing a broken gauge.

For a true remaining balance, use each vendor's console. Set hard spend caps
there as the real backstop.

### Frontend environment variables (Cloudflare Pages)

Set under **Pages project → Settings → Variables and Secrets → Production** (plain text, not secret). All five required:

| Name | Value |
|------|-------|
| `VITE_FIREBASE_API_KEY` | Web API key from the chiops Firebase console |
| `VITE_FIREBASE_AUTH_DOMAIN` | `chiops.firebaseapp.com` |
| `VITE_FIREBASE_PROJECT_ID` | `chiops` |
| `VITE_FIREBASE_APP_ID` | `1:991649774709:web:...` |
| `VITE_API_BASE` | `https://awm-chat-991649774709.europe-west1.run.app` |

Vite bakes env vars in at **build time**, so after changing them in Cloudflare you must **Retry deployment** for them to take effect. Variable names must be exact — paste artefacts like a leading `Name Value ` will silently break it (Vite reports `auth/invalid-api-key` in the browser console).

### Backend environment variables (Cloud Run)

Currently set on the `awm-chat` service:

| Name | Value |
|------|-------|
| `GCP_PROJECT` | `chiops` |
| `FIRESTORE_DATABASE` | `awm-chat` |
| `GCS_ARCHIVE_BUCKET` | `awm-chat-archive` |
| `ALLOWED_EMAIL_DOMAIN` | `ascotwm.com` |
| `CORS_ORIGINS` | `https://chat.chimerasportstrading.com,https://awm-chat.pages.dev,http://localhost:5173` |

Multi-agent additions (all optional — sensible defaults apply):

| Name | Purpose |
|------|---------|
| `DEFAULT_MODEL` | Fallback agent when a user has no preference. Defaults to `claude-sonnet-5` |
| `DEFAULT_CAP_TOKENS` | Monthly allowance **per agent** per user. Defaults to `500000` |
| `ANTHROPIC_BUDGET_USD` / `OPENAI_BUDGET_USD` / `GOOGLE_BUDGET_USD` | Monthly budget each agent's spend marker is measured against. `0` hides the marker |
| `GCP_BILLING_EXPORT_TABLE` | BigQuery table of the GCP billing export, e.g. `chiops.billing.gcp_billing_export_v1_XXXX`. Required for the Gemini spend marker — Google has no cost endpoint |
| `PROVIDER_SPEND_CACHE_SECONDS` | How long vendor spend is cached. Defaults to `300` |

Update with:

```bash
gcloud run services update awm-chat \
  --region=europe-west1 --project=chiops \
  --update-env-vars="^@^KEY=val@OTHER=val,with,commas"
```

The `^@^` prefix switches the per-variable separator to `@`, so a value can contain commas (needed for `CORS_ORIGINS`). Env vars persist across CI/CD redeploys — set once, they stick.

`CORS_ORIGINS` must include every domain the frontend is served from. Missing origins surface as `No 'Access-Control-Allow-Origin' header` in the browser.

### IAM for the Cloud Run service account

The service runs as the default compute SA: `991649774709-compute@developer.gserviceaccount.com`. In this project it has the inherited `roles/editor`, which is sufficient for everything below. If you ever switch to least privilege, the minimum it needs is:

| Role | Scope | Why |
|------|-------|-----|
| `roles/datastore.user` | project-wide | Firestore reads/writes |
| `roles/storage.objectAdmin` | on bucket `awm-chat-archive` | append-only conversation archive |
| `roles/secretmanager.secretAccessor` | on secrets `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` | read the vendor API keys |

Symptom of a missing `secretAccessor` (or equivalent): a 500 on `POST /chat` with `Permission 'secretmanager.versions.access' denied` in Cloud Run logs.

### Required Firestore indexes

Two composite indexes are needed in the `awm-chat` database (already created):

| Collection | Fields | Used by |
|---|---|---|
| `conversations` | `owner_uid` ASC, `archived` ASC, `updated_at` DESC | a user's conversation list |
| `audit` | `type` ASC, `created_at` DESC | the admin Flagged Content view |

Add more with:

```bash
gcloud firestore indexes composite create \
  --project=chiops --database=awm-chat \
  --collection-group=<collection> \
  --field-config=field-path=<f1>,order=ascending \
  --field-config=field-path=<f2>,order=descending
```

### Bootstrap an admin user

There is no admin-bootstrap script. To grant admin to a user (including the first one):

1. Have them sign in once so their `users/{uid}` document gets created
2. Firestore Console → database `awm-chat` → `users` collection → find the doc by `email`
3. Set field `role` (string) → `admin`

`require_admin` reads this on every request, so it takes effect on the next call. The user may need to sign out and back in (or hard-refresh) for the frontend to unhide the admin UI.

## Roadmap

AWM Chat is built to grow on demand.

Delivered in 0.2.0 (see [`CHANGELOG.md`](CHANGELOG.md)): document upload, image
upload, video transcription, the in-app Help page, and the SPA routing fallback.

Still on the list:

* **Integration with internal company apps** — pull data or perform actions in other internal systems (RAG-style context injection, or provider tool/function calling — scoped per integration)

Phase 2 items (see [`docs/phase-2.md`](docs/phase-2.md)):

* **BigQuery sink** for the conversation archive
* **RAG / vector retrieval** for conversations that exceed the context window

If you need something that isn't here yet, that's a feature request, not a limitation — see [`docs/user-manual.md`](docs/user-manual.md) §10.

## Stack

* Frontend: React 18, Vite, Tailwind CSS, Firebase JS SDK
* Backend: Python 3.12, FastAPI, google-cloud-firestore, google-cloud-storage, anthropic + openai + google-genai, firebase-admin
* Hosting: Cloudflare Pages (frontend), Cloud Run `europe-west1` (backend)
* Identity: Firebase Auth (Google SSO)
* Storage: Firestore (named DB `awm-chat`) + GCS

## Repo layout

```
backend/      FastAPI app + Dockerfile
frontend/     React 18 + Vite SPA + Tailwind
docs/         deployment notes, phase-2 plan, user manual
```
