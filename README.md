# AWM Chat

Internal Claude-powered chat application for Ascot Wealth Management.

## What this is

A private, sleek, company-internal chat interface to Claude with:

* Google Workspace SSO restricted to `@ascotwm.com`
* Per-user conversation history with pinned context.
* Server-side RAG (Phase 2) for effectively unlimited memory for user
* Token usage tracking and per-user monthly spend caps
* Admin dashboard with usage metrics and content review hooks
* Compliance audit trail: chats are company property and subject to spot checks too
* All data flows into a GCS-backed data lake for analytics and BigQuery reporting

## Architecture

```
┌─────────────────────────────────┐         ┌──────────────────────┐
│  Cloudflare Pages               │ ──────▶ │  Cloud Run (FastAPI) │
│  React + Vite                   │  HTTPS  │  awm-chat            │
│  chat.chimerasportstrading.com  │ ◀────── │  europe-west1        │
└─────────────────────────────────┘         └──────────┬───────────┘
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

1. GCP project: `chiops`
2. Enable Firestore, Cloud Run, Secret Manager, Cloud Build, GCS
3. Firebase project linked to `chiops`, Google auth restricted to `ascotwm.com`
4. Named Firestore database: `awm-chat` (set on backend via `FIRESTORE_DATABASE` env var)
5. Set secrets in Secret Manager: `ANTHROPIC_API_KEY`
6. Push to GitHub → Cloud Build deploys backend to Cloud Run service `awm-chat` (region `europe-west1`); Cloudflare Pages deploys frontend
7. Bootstrap first admin: see "Operations" below

## Operations

### Production environments

| Component | Where it lives |
|-----------|----------------|
| Frontend  | Cloudflare Pages project `awm-chat` → domains `awm-chat.pages.dev`, `chat.chimerasportstrading.com` |
| Backend   | Cloud Run service `awm-chat`, region `europe-west1`, project `chiops` |
| Firestore | Named database `awm-chat` in project `chiops` |
| Secrets   | Secret Manager in project `chiops` |
| Archive   | `gs://awm-chat-archive` |

### Frontend environment variables (Cloudflare Pages)

Set under **Pages project → Settings → Variables and Secrets → Production** (plain text, not secret). All five required:

| Name | Value |
|------|-------|
| `VITE_FIREBASE_API_KEY` | Web API key from Firebase console |
| `VITE_FIREBASE_AUTH_DOMAIN` | `chiops.firebaseapp.com` |
| `VITE_FIREBASE_PROJECT_ID` | `chiops` |
| `VITE_FIREBASE_APP_ID` | `1:991649774709:web:...` |
| `VITE_API_BASE` | `https://awm-chat-991649774709.europe-west1.run.app` |

Vite bakes env vars in at **build time**, so after changing them in Cloudflare you must **Retry deployment** for them to take effect. Variable names must be exact — paste artefacts like a leading `Name Value ` will silently break it (Vite reports `auth/invalid-api-key` in the browser console).

### Backend environment variables (Cloud Run)

Set on the `awm-chat` service. Critical one:

* `CORS_ORIGINS` — comma-separated list of allowed frontend origins. Must include every domain the frontend is served from, e.g. `https://chat.chimerasportstrading.com,https://awm-chat.pages.dev`. Missing origins surface as `No 'Access-Control-Allow-Origin' header` in the browser.

`cloudbuild.yaml` sets these on every deploy, so update there too if you change them.

### Required IAM grants for the Cloud Run service account

The deployed service runs as the **default compute SA**: `991649774709-compute@developer.gserviceaccount.com`. It needs:

| Role | Scope | Why |
|------|-------|-----|
| `roles/secretmanager.secretAccessor` | on secret `ANTHROPIC_API_KEY` | read the Claude API key |
| `roles/datastore.user` | project-wide | Firestore reads/writes |
| `roles/storage.objectAdmin` | on bucket `awm-chat-archive` | append-only conversation archive |

Missing `secretmanager.secretAccessor` shows up as a 500 on `POST /chat` with `Permission 'secretmanager.versions.access' denied` in Cloud Run logs.

### Bootstrap an admin user

There is no admin-bootstrap script. To grant admin to a user (including the first one):

1. Have them sign in once so their `users/{uid}` document gets created
2. Firestore Console → database `awm-chat` → `users` collection → find the doc by `email`
3. Add/edit field `role` (string) → set to `admin`

`require_admin` reads this on every request, so it takes effect on the next call. The user may need to sign out and back in for the frontend to unhide admin UI.

## Stack

* Frontend: React 18, Vite, Tailwind CSS, Firebase JS SDK
* Backend: Python 3.12, FastAPI, google-cloud-firestore, google-cloud-storage, anthropic
* Hosting: Cloudflare Pages (frontend), Cloud Run `europe-west1` (backend)
* Identity: Firebase Auth (Google SSO)
* Storage: Firestore + GCS, BigQuery sink for analytics
