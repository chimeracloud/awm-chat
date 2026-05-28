# AWM Chat

Internal Claude-powered chat application for Ascot Wealth Management.

> **AWM Chat is a living tool — it grows with the team.**
> It ships deliberately lean. New capability — document and image upload, integration with internal company apps, and so on — is added as the team asks for it. See [Roadmap](#roadmap).

## What this is

A private, company-internal chat interface to Claude with:

* Google Workspace SSO restricted to `@ascotwm.com`
* Per-user conversation history with pinned context
* Admin-controlled AI model selection (per user) and monthly token caps
* Admin dashboard with usage metrics, content review hooks, and editable settings
* Compliance audit trail — chats are company property and subject to spot checks
* GCS-backed append-only conversation archive (BigQuery sink planned for Phase 2)

End-user guide: [`docs/user-manual.md`](docs/user-manual.md).

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
       ┌────────────────┐                    ┌──────────────────┐                    ┌────────────────┐
       │   Firestore    │                    │       GCS        │                    │  Anthropic API │
       │  database      │                    │ (chat archives)  │                    │  (Claude)      │
       │  `awm-chat`    │                    └─────────┬────────┘                    └────────────────┘
       └────────────────┘                              │
                                                       ▼
                                             ┌──────────────────┐
                                             │  BigQuery        │
                                             │  (Phase 2)       │
                                             └──────────────────┘
```

### Identity

* Firebase Auth with Google provider, restricted to `ascotwm.com` Workspace domain
* Backend verifies the Firebase ID token on every request
* Admin role flag stored in Firestore `users/{uid}.role`

### Data model

All collections live in the named Firestore database **`awm-chat`** (not the project `(default)`):

* `users/{uid}` — profile, role, monthly token cap, AI model override, acknowledgement flag
* `conversations/{conv_id}` — owner_uid, title, created_at, updated_at, archived
* `conversations/{conv_id}/messages/{msg_id}` — role, content, token counts, timestamp
* `pins/{uid}/items/{pin_id}` — pinned context snippets always included in the prompt
* `usage/{uid}/months/{YYYY-MM}` — token counts, request counts
* `audit/{event_id}` — compliance events (admin actions, flag matches, settings changes)
* `settings/global` — admin-editable defaults: `default_model`, `available_models`, `default_cap_tokens`, `flag_keywords`. Auto-seeded on first read.

### GCS layout

```
gs://awm-chat-archive/
  conversations/{uid}/{conv_id}.ndjson    # append-only per message
  exports/{YYYY-MM-DD}/...                # nightly BigQuery exports (Phase 2)
```

### Anthropic proxy

The backend is the only thing that holds the Anthropic API key (Google Secret Manager). The frontend never sees it. Per request, the proxy:

1. Verifies the user's Firebase JWT
2. Checks their monthly cap
3. Loads conversation history + pinned context
4. Picks the model — per-user `users/{uid}.model` → `settings/global.default_model` → env `CLAUDE_MODEL`
5. Calls Claude with streaming
6. Streams the response back to the client
7. Persists the exchange to Firestore + GCS
8. Increments usage counters and runs the keyword-flag check

## Deployment

Live deployment summary:

1. GCP project: **`chiops`** (project number `991649774709`)
2. Backend: Cloud Run service `awm-chat` in **`europe-west1`**, deployed by **Cloud Run's GitHub continuous deployment** (builds from `backend/Dockerfile`). The `cloudbuild.yaml` in this repo is reference material only and is not wired into the active pipeline.
3. Frontend: Cloudflare Pages, deployed by the Cloudflare Pages GitHub integration (`npm run build` from `frontend/`, output `dist/`)
4. Firestore: named database `awm-chat` in `chiops` (set via backend env `FIRESTORE_DATABASE=awm-chat`)
5. Archive: `gs://awm-chat-archive` (region `europe-west2`)
6. Secrets: `ANTHROPIC_API_KEY` in Secret Manager (`chiops`)
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
| `roles/secretmanager.secretAccessor` | on secret `ANTHROPIC_API_KEY` | read the Claude API key |

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

AWM Chat is built to grow on demand. Currently on the list:

* **Document upload** — attach a document to a message; Claude reads it as input
* **Image upload** — attach an image; Claude's multimodal blocks
* **Integration with internal company apps** — pull data or perform actions in other internal systems (RAG-style context injection, or Claude tool/function calling — scoped per integration)
* **In-app Help page** — surface [`docs/user-manual.md`](docs/user-manual.md) inside the app, linked from the top bar
* **SPA routing fallback** — `frontend/public/_redirects` with `/*  /index.html  200` so hard refreshes on deep routes always serve the SPA

Phase 2 items (see [`docs/phase-2.md`](docs/phase-2.md)):

* **BigQuery sink** for the conversation archive
* **RAG / vector retrieval** for conversations that exceed the context window

If you need something that isn't here yet, that's a feature request, not a limitation — see [`docs/user-manual.md`](docs/user-manual.md) §10.

## Stack

* Frontend: React 18, Vite, Tailwind CSS, Firebase JS SDK
* Backend: Python 3.12, FastAPI, google-cloud-firestore, google-cloud-storage, anthropic, firebase-admin
* Hosting: Cloudflare Pages (frontend), Cloud Run `europe-west1` (backend)
* Identity: Firebase Auth (Google SSO)
* Storage: Firestore (named DB `awm-chat`) + GCS

## Repo layout

```
backend/      FastAPI app + Dockerfile
frontend/     React 18 + Vite SPA + Tailwind
docs/         deployment notes, phase-2 plan, user manual
```
