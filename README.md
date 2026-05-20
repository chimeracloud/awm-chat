# AWM Chat

Internal Claude-powered chat application for Ascot Wealth Management.

## What this is

A private, sleek, company-internal chat interface to Claude with:

* Google Workspace SSO restricted to `@ascotwm.com`
* Per-user conversation history with pinned context
* Server-side RAG (Phase 2) for effectively unlimited memory
* Token usage tracking and per-user monthly spend caps
* Admin dashboard with usage metrics and content review hooks
* Compliance audit trail: chats are company property and subject to spot checks too
* All data flows into a GCS-backed data lake for analytics and BigQuery reporting

## Architecture

```
┌──────────────────────┐         ┌──────────────────────┐
│  Cloudflare Pages    │ ──────▶ │  Cloud Run (FastAPI) │
│  React + Vite        │  HTTPS  │  awm-chat-api        │
│  chat.ascotwm.com    │ ◀────── │                      │
└──────────────────────┘         └──────────┬───────────┘
                                            │
                ┌───────────────────────────┼───────────────────────────┐
                ▼                           ▼                           ▼
       ┌────────────────┐         ┌──────────────────┐         ┌────────────────┐
       │   Firestore    │         │       GCS        │         │  Anthropic API │
       │  (metadata)    │         │ (chat archives)  │         │  (Claude)      │
       └────────────────┘         └──────────────────┘         └────────────────┘
                                            │
                                            ▼
                                  ┌──────────────────┐
                                  │  BigQuery        │
                                  │  (data lake)     │
                                  └──────────────────┘
```

### Identity

* Firebase Auth with Google provider, restricted to `ascotwm.com` workspace domain
* Backend verifies the Firebase ID token on every request
* Admin role flag stored in Firestore `users/{uid}.role`

### Data model

* `users/{uid}` ... profile, role, monthly token cap, acknowledgement flag
* `conversations/{conv_id}` ... owner_uid, title, created_at, updated_at, archived
* `conversations/{conv_id}/messages/{msg_id}` ... role, content, token counts, timestamp
* `pins/{uid}/items/{pin_id}` ... pinned context snippets always included in prompt
* `usage/{uid}/months/{YYYY-MM}` ... token counts, request counts, spend estimate
* `audit/{event_id}` ... compliance events (admin reads, flag matches)

### GCS layout

```
gs://awm-chat-archive/
  conversations/{uid}/{conv_id}.ndjson    # append-only per message
  exports/{YYYY-MM-DD}/...                # nightly bigquery exports
```

### Anthropic proxy

The backend is the only thing that holds the Anthropic API key (Google Secret Manager). The frontend never sees it. The proxy:

1. Verifies the user's Firebase JWT
2. Checks their monthly cap
3. Loads conversation history + pinned context
4. Calls Claude with streaming
5. Streams the response back to the client
6. Writes the exchange to Firestore + GCS
7. Increments usage counters

## Deployment

See `docs/deployment.md` for the full setup. Short version:

1. Create GCP project `awm-chat-prod`
2. Enable Firestore, Cloud Run, Secret Manager, Cloud Build, GCS
3. Create Firebase project, link to the GCP project, enable Google auth restricted to ascotwm.com
4. Set secrets in Secret Manager: `ANTHROPIC_API_KEY`
5. Push to GitHub ... Cloud Build deploys backend, Cloudflare Pages deploys frontend
6. Bootstrap first admin user via the `scripts/bootstrap_admin.py` script

## Stack

* Frontend: React 18, Vite, Tailwind CSS, Firebase JS SDK
* Backend: Python 3.12, FastAPI, google-cloud-firestore, google-cloud-storage, anthropic
* Hosting: Cloudflare Pages (frontend), Cloud Run europe-west2 (backend)
* Identity: Firebase Auth (Google SSO)
* Storage: Firestore + GCS, BigQuery sink for analytics
