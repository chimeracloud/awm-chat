# Deployment guide

End-to-end setup for first deploy. Allow ~60-90 minutes.

## 1. Google Cloud project

```bash
gcloud projects create awm-chat-prod --name="AWM Chat"
gcloud config set project awm-chat-prod

# Enable APIs
gcloud services enable \
  firestore.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  identitytoolkit.googleapis.com \
  firebase.googleapis.com
```

## 2. Firestore (native mode, europe-west2)

```bash
gcloud firestore databases create --location=europe-west2 --type=firestore-native
```

## 3. GCS archive bucket

```bash
gcloud storage buckets create gs://awm-chat-archive \
  --location=europe-west2 \
  --uniform-bucket-level-access \
  --public-access-prevention
```

Lock down with KMS encryption later if compliance demands it.

## 4. Artifact Registry for Docker

```bash
gcloud artifacts repositories create awm-chat \
  --repository-format=docker \
  --location=europe-west2
```

## 5. Service account for the Cloud Run service

```bash
gcloud iam service-accounts create awm-chat-api \
  --display-name="AWM Chat API"

PROJECT=awm-chat-prod
SA=awm-chat-api@$PROJECT.iam.gserviceaccount.com

for ROLE in \
  roles/datastore.user \
  roles/storage.objectAdmin \
  roles/secretmanager.secretAccessor \
  roles/firebase.sdkAdminServiceAgent; do
  gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=$ROLE
done
```

## 6. Secrets

```bash
echo -n "sk-ant-..." | gcloud secrets create ANTHROPIC_API_KEY --data-file=-
```

If you rotate, add a new version: `gcloud secrets versions add ANTHROPIC_API_KEY --data-file=-`.

## 7. Firebase

In the [Firebase Console](https://console.firebase.google.com):

1. Add project ... select the existing `awm-chat-prod` GCP project
2. Authentication > Sign-in method > Google > Enable
3. Authentication > Settings > Authorized domains: add `chat.ascotwm.com` and `localhost`
4. Project settings > Your apps > Add web app, copy the config values into `frontend/.env`
5. In Google Workspace admin (admin.google.com): no extra setup needed if you only allow `hd=ascotwm.com`, but the backend also verifies the email domain server-side

## 8. Backend deploy

Connect Cloud Build to your GitHub repo (Cloud Build > Triggers > Connect repository), then create a trigger:

* Source: your `awm-chat` repo, branch `main`
* Config: `backend/cloudbuild.yaml`
* Path filter: `backend/**`

Push to main and the API will deploy to Cloud Run.

Verify: `curl https://awm-chat-api-XXXXX.a.run.app/healthz`

## 9. Map custom domain

```bash
gcloud beta run domain-mappings create \
  --service=awm-chat-api \
  --domain=awm-chat-api.ascotwm.com \
  --region=europe-west2
```

Add the returned DNS records in Cloudflare (CNAME, proxy off so cert can issue).

## 10. Frontend deploy (Cloudflare Pages)

In Cloudflare dashboard > Pages > Create > Connect to Git > `awm-chat` repo:

* Framework preset: Vite
* Build command: `npm run build`
* Build output directory: `dist`
* Root directory: `frontend`
* Environment variables: paste contents of `frontend/.env.example` with real values

Custom domain: `chat.ascotwm.com`.

## 11. Bootstrap first admin

Sign in once with your `@ascotwm.com` account to create your user document, then promote yourself:

```bash
gcloud firestore documents update users/YOUR_UID \
  --field role=admin
```

(or via the Firestore console UI)

## 12. Smoke test

1. Sign in at `chat.ascotwm.com`
2. Accept privacy
3. Send a message
4. Confirm: usage shows non-zero, conversation appears in sidebar, GCS bucket has an NDJSON file under `conversations/{uid}/`
5. Navigate to `/admin`, confirm your user appears with non-zero tokens

## Ongoing

* Per-user caps: set in Admin > Users
* Spend cap on the Anthropic console as a hard backstop
* BigQuery sink (Phase 2): scheduled Cloud Run job that reads GCS NDJSON and loads into BigQuery for the data lake
* RAG (Phase 2): embeddings written on each turn into Vertex AI Vector Search, retrieved when conversation history exceeds the context window
