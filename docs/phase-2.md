# Phase 2 Roadmap

Everything intentionally omitted from the MVP, in priority order.

## Tier 1: data lake and unlimited memory

### BigQuery sink

A scheduled Cloud Run job (`scripts/sink_to_bq.py`) that:

1. Reads new NDJSON archives from `gs://awm-chat-archive/conversations/`
2. Loads into `awm_chat.messages` table partitioned by date, clustered by uid
3. Joins to `awm_chat.users` for reporting
4. Frequency: hourly initially, eventually streaming via Pub/Sub

Schema:

```
awm_chat.messages
  message_id STRING
  conversation_id STRING
  uid STRING
  email STRING
  role STRING        # user | assistant
  content STRING
  input_tokens INT64
  output_tokens INT64
  ts TIMESTAMP
  flags ARRAY<STRING>
```

Looker Studio dashboards on top: usage trends, top topics by embedding cluster, productivity proxies (chat-to-action ratios).

### RAG memory

Once a conversation's history exceeds the context window, fall back to retrieval:

1. On every message persistence, generate embeddings via Voyage AI or Vertex AI (text-embedding-005)
2. Store in Vertex AI Vector Search or pgvector on Cloud SQL
3. On chat turn: embed the user's latest message, retrieve top-k similar past messages from this user's history (any conversation), inject as additional context
4. Use Haiku, not Sonnet, for embedding generation to keep costs sane

## Tier 2: compliance hardening

### Semantic flagging

In addition to keyword flags:

* Embedding similarity to known sensitive categories (client PII, financial data, regulatory references)
* Daily batch run, not per-message, to keep latency low

### Audit log viewer

Admin view to query the audit collection:

* All admin reads of user data are logged
* All keyword/semantic flags are logged
* Acknowledgements are logged
* Exportable to BigQuery

### Encryption upgrade

* Customer-managed encryption keys (CMEK) on Firestore and GCS
* Key rotation policy
* DLP API scan on archive ingestion (optional)

## Tier 3: experience improvements

* File and image attachments (PDF, docx, xlsx, images) ... use Claude's native multimodal
* Voice input via Web Speech API
* Slash commands for common workflows (`/summarise`, `/translate`, `/draft-email`)
* Shared conversations (opt-in, by link, audit logged)
* Conversation templates per role (adviser, paraplanner, ops)

## Tier 4: model routing

Single model is wasteful. Route based on intent:

* Haiku: summarisation, classification, simple Q&A
* Sonnet: drafting, analysis (default)
* Opus: complex reasoning when user explicitly requests "deep think"

Implementation: a tiny classifier (Haiku itself) on the first message decides the tier.

## Tier 5: extend to other companies

* Cape Berkshire workspace
* Ascot White Co. (if applicable)
* Per-tenant Firestore prefix, per-tenant GCS bucket
* Shared backend, tenant resolved from email domain
