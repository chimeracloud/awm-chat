# Changelog — AWM Chat

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The frontend and backend share one version number, reported by the backend on
`GET /` as the FastAPI `version` and set in `frontend/package.json`.

## [0.6.0] - 2026-08-20

Cost and context control. A conversation with a report attached was re-sending
that report, in full, on every turn for the life of the thread.

### Added

- **Prompt caching across all three providers.** The system prompt is split into
  `SYSTEM_STABLE` (firm context and guidance, byte-identical for every user on
  every day) and a small volatile half holding the user's name, today's date and
  their pinned context, always placed after it. Anthropic marks the boundary
  explicitly with `cache_control`; OpenAI and Gemini cache the longest common
  prefix automatically, so for them the ordering *is* the entire mechanism. A
  second Anthropic breakpoint sits at the end of the settled history.
- `cache_read_tokens` / `cache_write_tokens` reported on the `done` event, so the
  saving can be checked rather than assumed.
- **PDF text extraction at upload** using pypdf. PDFs were previously left
  unextracted because they were always sent natively; the text layer is what
  makes the downgrade below possible.
- **`tools/backfill_pdf_text.py`** — extracts and stores the text layer for PDFs
  uploaded before extraction existed. Idempotent, dry-run by default.
- **Export CLI: `--email` and `--markdown-only`.** `--email` resolves the uid so
  nobody has to dig one out of Firestore; `--markdown-only` skips attachment
  binaries while still writing extracted text and transcripts.

### Changed

- **Full attachment fidelity is now sent for the newest message only.** A PDF
  sent natively is billed as its text *plus* a rendered image per page; earlier
  turns now get the stored text layer instead, which still lets the model quote
  and reason about the document at roughly a quarter of the size. Scanned PDFs
  have no text layer and stay native, since downgrading those would send nothing
  at all.
- **History is bounded by a token budget, not a message count.** Forty one-line
  messages and forty with a report attached are wildly different requests, and
  only a token budget bounds both. Messages are taken newest-first until the
  budget is spent, estimated from the message document alone — so trimming
  happens before any GCS download rather than after. The newest message is always
  kept even if it alone exceeds the budget: the provider's own error beats
  silently sending an empty request.
- `MAX_EXTRACTED_CHARS` reduced from 200,000 (~50k tokens for a single document)
  to 40,000, and truncation now says so in-band instead of cutting mid-sentence.

### ⚠️ Operator-visible behaviour

- **This changes what the model sees.** On turns before the newest, an attachment
  is represented by its extracted text rather than the original file. Answers
  that depended on page layout or on visual content in a non-scanned PDF may
  differ from before on older turns.
- Measured on a simulated 20-turn thread with a 1.2MB report attached: **42,142
  tokens before, 15,642 after**, with all 39 messages still in context. One real
  user had hit **78,602 tokens in a single request against a 30,000 TPM limit** —
  the document was nearly all of it.
- **Cached tokens are cheaper, not free.** They still count toward the user's
  allowance and do not relieve the per-minute rate limits that prompted this work.
- Backfill was run against production: 59 PDFs, 56 extracted, 3 scanned with no
  text layer (recorded so they are not retried, and correctly still sent
  natively).

### Notes

- The in-app export builds the whole zip in memory inside a Cloud Run request,
  including every attachment's raw bytes. For a heavy account that either
  exhausts the container or outruns the request timeout, and the browser reports
  it as "Load failed" — a dead connection rather than an HTTP error, which is why
  no message reaches the UI. **Use the CLI tool for large accounts**; it streams
  to disk instead of memory.

## [0.5.0] - 2026-08-07 → 2026-08-11

Multi-agent support. Users can switch agent inside the chat window, and all three
read the same conversation history.

### Added

- **Claude, OpenAI and Gemini as switchable agents.** A `providers/` package with
  one adapter per vendor behind a shared interface; a model catalog mapping model
  ID to vendor, which admins narrow via `available_models`; a switcher above the
  composer where agents with no key are greyed out rather than broken. Assistant
  messages record model and provider so mixed threads stay attributable.
- **Per-agent allowances and handover.** `usage/{uid}/months/{YYYY-MM}` gains
  `by_provider`. `cap_tokens` now applies per agent, so exhausting one leaves the
  others usable; optional `caps_by_provider` narrows a single agent. The cap is
  checked *before* anything is persisted, so a refused turn leaves no stray
  message and returns the agents that still have headroom. An out-of-tokens
  dialog offers a one-click switch that resends the message.
- **Battery indicators.** Fill is the user's own live allowance for that agent; a
  thin underbar is org month-to-date spend against a budget, from the vendor cost
  APIs, omitted when unconfigured.
- **Admin-managed keys.** An Agents & Keys tab writes keys through to Secret
  Manager, never Firestore. Keys are validated against the vendor before saving,
  never returned by any endpoint (masked last-4 only), restricted to allowlisted
  names, and every change is audited. Warns when a Cloud Run env var is shadowing
  a saved key.

### Fixed

- **Key validation failed with "client has been closed".** The validator
  constructed each vendor client inline and chained the call off it
  (`genai.Client(api_key=...).models.list()`), leaving no reference to the
  client. `google-genai`'s `models.list()` is lazily paginated, so the client was
  garbage collected — and its HTTP transport closed — before the request was
  issued. The request never reached Google, so **a perfectly good key looked
  broken**. Each client is now bound to a local, and Gemini takes only the first
  page rather than walking the whole catalog.
- **Cloud Run build failed with `ResolutionImpossible`.** `google-genai` 2.17.0
  requires `pydantic>=2.12.5` while `requirements.txt` still pinned 2.10.4. This
  was missed because the new SDKs were installed on top of an existing venv,
  where pip upgraded pydantic in place — so the local environment resolved fine
  while a from-scratch install could not.

### Changed

- **Secret reads are cached.** Previously every chat turn hit Secret Manager.
- The stored conversation format is unchanged — Firestore and the GCS archive
  keep the shape the app used when it was OpenAI-only, and each provider adapter
  translates it at send time without writing it back. **That is what lets a
  thread continue across agents, attachments included.**
- Documentation corrected where it still described an Anthropic-only backend
  after the July switch to OpenAI; the admin spend estimate no longer assumes a
  single model's pricing.

### Notes

- **No vendor publishes a remaining-credit balance** — checked for all three — so
  the battery deliberately shows allowance and spend rather than credits. The
  reasoning is recorded in `credits.py` and the README so it is not re-litigated.
- Usage documents written before multi-agent support are read as OpenAI usage
  rather than being backfilled.

## [0.4.0] - 2026-07-02

### Added

- **Per-user data export (admin).** `GET /admin/users/{uid}/export` packages one
  user's conversations, messages, pinned context, profile and uploaded
  attachments into a downloadable zip — readable Markdown plus JSON plus the
  original files plus a README on using them in Claude. Wired into the Admin →
  Users table via a new `apiDownload()` helper, with an equivalent standalone
  script for CLI use.
- **Self-service data export.** `GET /export/me` returns any signed-in user's own
  data as a zip, with a Download icon in the top bar. Reuses the shared zip
  builder.

### Changed

- **Chat provider switched from Anthropic Claude to OpenAI (Responses API)**,
  keeping web search, image/PDF/document uploads, streaming, usage metering and
  the graceful no-tools fallback.

### ⚠️ Risk posture

- Both export paths are read-only and every export is written to the audit log
  (`self_export` for the user-initiated route). The admin route is admin-only.

## [0.3.0] - 2026-06-25 → 2026-06-27

### Added

- `POST /admin/usage/reset` — zeroes this month's token counters for every user,
  audited, with a "Clear all usage" button on the Metrics tab. Caps are left
  unchanged.
- `POST /admin/users/{uid}/usage/reset` — the same per user, with a Reset action
  beside each user's monthly token total.

### Fixed

- **Chat appeared stuck in a loop: no reply, no error.** Two causes. In
  `frontend/src/lib/api.js` the `streamChat` SSE parser wrapped event dispatch in
  a `try`/`catch` meant only for malformed JSON lines, so a real `error` event
  was thrown and immediately swallowed — the UI showed endless typing dots and
  the message silently vanished on reload, prompting the user to re-send. The
  `try`/`catch` is now scoped to `JSON.parse` only. In `backend/app/chat.py`, web
  tools were added to every request, so a user whose admin-assigned model cannot
  use the server-side web tools failed on **every** turn; the call is now retried
  once without web tools when the tool-enabled call fails before producing output.
- **An invalid per-user model ID broke that user's chat entirely.** A shorthand
  like `4.6` typed into the admin panel caused every request for that user to 404
  at the Anthropic API. Model resolution now goes through a guard that only
  accepts strings starting with `claude-`, falling back to the global default and
  then the built-in default.

## [0.2.0] - 2026-05-28

Phase 2.

### Added

- **Attachments** — direct-to-GCS upload via V4 signed URLs. PDFs and images
  reach the model as native document/image content blocks; DOCX, TXT, MD and CSV
  are text-extracted server-side. Up to 5 attachments per message, with originals
  archived in GCS for compliance. New `/attachments` routes (init / complete /
  get / download) with per-file size and type allowlists.
- **Video transcription** via Google Video Intelligence. The model receives only
  the transcript.
- `/chat` accepts `attachment_ids`; user messages persist a lightweight
  attachment summary, and `_load_history` rebuilds content blocks for prior turns
  so the model can refer back to earlier attachments.
- Composer paperclip button with per-file upload progress and an explicit
  "transcribing" state; MessageList gains inline image thumbnails, an inline
  video player, and a file card with download link for documents.
- **In-app Help** at `/help`, rendering `docs/user-manual.md`, linked from the top
  bar for every signed-in user.
- **SPA fallback** so hard refreshes on `/admin`, `/help` and `/c/:id` always
  serve the SPA shell.
- **Firm context and live web access** — `backend/app/awm_context.py` carries a
  curated firm reference (services, philosophy, team, fees, FAQ, URLs) distilled
  from ascotwm.com, injected into the system prompt so the model answers
  AWM-specific questions accurately without fetching the site each turn.
  `web_search` and `web_fetch` tool specs enable live search and URL fetching
  during a turn.

### ⚠️ Risk posture

- **Video is transcribed, not analysed.** The model receives the transcript only
  — no emotion or biometric inference is performed or forwarded.
- The flag-keyword scan was extended to cover extracted document text and video
  transcripts, not just typed messages.

## [0.1.0] - 2026-05-20

### Added

- Initial AWM Chat prototype: React 18 + Vite SPA on Cloudflare Pages, FastAPI
  backend on Cloud Run `europe-west1`, Firebase Auth (Google SSO), Firestore and
  GCS.
- `FIRESTORE_DATABASE` env var for named-database support, letting the backend
  target a dedicated `awm-chat` database instead of `(default)` and keeping
  collections isolated from other data in the project.
- **Admin settings** — a `settings/global` Firestore doc for admin-configurable
  defaults (default model, available models, default token cap, flag keywords),
  `GET`/`PUT /admin/settings` (admin only), and a per-user model field. Chat
  resolves the model per-user first, then the global default, then the env
  fallback. AdminPage gains a functional Settings tab and a per-user model
  dropdown; TopBar shows an admin shortcut to admin users.

### Fixed

- `CORS_ORIGINS` default and the Cloud Build env var corrected to the real
  frontend domains, and the Cloud Run deploy region corrected to `europe-west1`.

### Notes

- CI/CD is Cloud Run's GitHub integration, not the (unused) `cloudbuild.yaml`.

[0.6.0]: https://github.com/chimeracloud/awm-chat/releases/tag/v0.6.0
[0.5.0]: https://github.com/chimeracloud/awm-chat/releases/tag/v0.5.0
[0.4.0]: https://github.com/chimeracloud/awm-chat/releases/tag/v0.4.0
[0.3.0]: https://github.com/chimeracloud/awm-chat/releases/tag/v0.3.0
[0.2.0]: https://github.com/chimeracloud/awm-chat/releases/tag/v0.2.0
[0.1.0]: https://github.com/chimeracloud/awm-chat/releases/tag/v0.1.0
