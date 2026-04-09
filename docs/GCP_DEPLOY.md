# Deploying AI Pulse on Google Cloud Platform

Step-by-step guide for someone who has never used GCP before.
Every step is a console click or a Cloud Shell command — nothing on your local machine.

---

## What we're setting up (and why)

| GCP Service | What it does for us | Cost |
|-------------|-------------------|------|
| **Cloud Run** | Runs your app in a container, gives you a public URL, scales to zero when nobody visits | Free tier: 2M requests/month |
| **Container Registry** | Stores your Docker image (like a locker for the packaged app) | Free tier: 0.5 GB storage |
| **Cloud Scheduler** | Calls `POST /run` at 00:05 UTC every day to trigger the pipeline | Free tier: 3 jobs |
| **Secret Manager** | Stores your API keys encrypted — never visible in code or logs | Free tier: 6 active secrets |

**Estimated monthly cost: $0** on free tier for this workload.

---

## Prerequisites

- A Google account (Gmail works)
- A credit/debit card (GCP requires it but won't charge on free tier; new accounts get $300 free credit)
- Your two API keys ready:
  - `EXA_API_KEY` (from https://exa.ai)
  - `OPENROUTER_API_KEY` (from https://openrouter.ai/keys)

---

## Step 1: Create a GCP Project

1. Go to **https://console.cloud.google.com**
2. Click the project dropdown at the top-left (it may say "Select a project")
3. Click **"New Project"**
4. Name it: `ai-pulse`
5. Click **Create**
6. Make sure `ai-pulse` is selected in the project dropdown

---

## Step 2: Enable the required APIs

1. In the search bar at the top, type **"Cloud Run API"** → click the result → click **Enable**
2. Search **"Cloud Build API"** → click → **Enable**
3. Search **"Container Registry API"** → click → **Enable**
4. Search **"Cloud Scheduler API"** → click → **Enable**
5. Search **"Secret Manager API"** → click → **Enable**

This tells GCP "I want to use these services." They're all free-tier eligible.

---

## Step 3: Open Cloud Shell

1. In the top-right of the console, click the **terminal icon** `>_` (it says "Activate Cloud Shell")
2. A black terminal panel opens at the bottom of your browser
3. This is a free Linux VM with `gcloud`, `git`, `docker` pre-installed

Everything from here happens inside Cloud Shell.

---

## Step 4: Clone your repo

If your code is on GitHub:
```bash
git clone https://github.com/samarth910/ai-pulse-daily.git
cd ai-pulse-daily
```

---

## Step 5: Store your secrets

We use GCP Secret Manager so your API keys are **encrypted at rest** and
**never appear in environment variables, logs, or source code**.

```bash
# Set your project
gcloud config set project ai-pulse-492803

# Create secrets (paste your actual key values)
echo -n "YOUR_EXA_KEY_HERE" | gcloud secrets create exa-api-key --data-file=-
echo -n "YOUR_OPENROUTER_KEY_HERE" | gcloud secrets create openrouter-api-key --data-file=-

# Generate a random token to protect the /run endpoint
RUN_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo -n "$RUN_SECRET" | gcloud secrets create run-secret --data-file=-
echo "Save this RUN_SECRET value: $RUN_SECRET"
```

If secrets already exist from a prior deployment, add a new version instead:
```bash
echo -n "NEW_VALUE" | gcloud secrets versions add exa-api-key --data-file=-
echo -n "NEW_VALUE" | gcloud secrets versions add openrouter-api-key --data-file=-
```

---

## Step 6: Grant Cloud Run permission to read secrets

```bash
PROJECT_NUMBER=$(gcloud projects describe ai-pulse-492803 --format="value(projectNumber)")

for SECRET in exa-api-key openrouter-api-key run-secret; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
done
```

---

## Step 7: Build and deploy to Cloud Run

```bash
# Build the Docker image using Cloud Build
gcloud builds submit --tag gcr.io/ai-pulse-492803/ai-pulse

# Deploy to Cloud Run
gcloud run deploy ai-pulse \
  --image gcr.io/ai-pulse-492803/ai-pulse \
  --region asia-south1 \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --memory 512Mi \
  --timeout 300 \
  --set-secrets "EXA_API_KEY=exa-api-key:latest,OPENROUTER_API_KEY=openrouter-api-key:latest,RUN_SECRET=run-secret:latest" \
  --set-env-vars "DRY_RUN=0"
```

After ~2 minutes, Cloud Run gives you a URL like:
```
https://ai-pulse-xxxxx-el.a.run.app
```

**Open it in your browser.** You should see the AI Pulse homepage.

---

## Step 8: Set up daily scheduled runs

Cloud Scheduler will call your `/run` endpoint every day at 00:05 UTC.

```bash
# Get your Cloud Run URL
CLOUD_RUN_URL=$(gcloud run services describe ai-pulse --region asia-south1 --format="value(status.url)")

# Get your RUN_SECRET
RUN_SECRET=$(gcloud secrets versions access latest --secret=run-secret)

# Create the scheduled job
gcloud scheduler jobs create http ai-pulse-daily \
  --schedule="5 0 * * *" \
  --uri="${CLOUD_RUN_URL}/run" \
  --http-method=POST \
  --headers="X-Run-Token=${RUN_SECRET}" \
  --time-zone="UTC" \
  --location="asia-south1" \
  --attempt-deadline="300s"
```

---

## Step 9: Test it manually

```bash
RUN_SECRET=$(gcloud secrets versions access latest --secret=run-secret)
CLOUD_RUN_URL=$(gcloud run services describe ai-pulse --region asia-south1 --format="value(status.url)")

curl -X POST "$CLOUD_RUN_URL/run" -H "X-Run-Token: $RUN_SECRET"
```

You should see: `Pipeline triggered`

Wait ~30 seconds, then refresh your Cloud Run URL in the browser.

---

## Updating the app later

After you change code, just run these two commands in Cloud Shell:

```bash
cd ai-pulse-daily
git pull

gcloud builds submit --tag gcr.io/ai-pulse-492803/ai-pulse
gcloud run deploy ai-pulse \
  --image gcr.io/ai-pulse-492803/ai-pulse \
  --region asia-south1 \
  --set-secrets "EXA_API_KEY=exa-api-key:latest,OPENROUTER_API_KEY=openrouter-api-key:latest,RUN_SECRET=run-secret:latest" \
  --set-env-vars "DRY_RUN=0"
```

---

## Security walkthrough (what's protecting you)

### 1. API keys are NOT in your code

Your Exa and OpenRouter keys are stored in **GCP Secret Manager** — encrypted
with Google-managed keys (AES-256). They are injected into the container at
runtime as environment variables. Even if someone reads your GitHub repo,
your Dockerfile, or your Cloud Build logs, they will never see the keys.

### 2. The /run endpoint is protected

The `POST /run` endpoint requires an `X-Run-Token` header that matches your
`RUN_SECRET`. Without it, anyone who discovers your URL gets a `403 Forbidden`.
The comparison uses `hmac.compare_digest()` — a timing-safe comparison that
prevents attackers from guessing the secret one character at a time.

### 3. Cloud Run is sandwiched

- **HTTPS only** — Cloud Run enforces TLS. All traffic is encrypted in transit.
- **Stateless containers** — each request runs in an isolated container.
  There is no SSH, no filesystem access from outside.
- **IAM controls** — only your Google account and the Cloud Build service
  account can deploy new versions.

### 4. What could go wrong (and mitigations)

| Risk | Mitigation |
|------|-----------|
| Someone finds your URL and spams GET requests | Free tier absorbs this; Cloud Run auto-scales and bills per request, but the page is cached so cost is negligible |
| Someone finds your URL and spams POST /run | Protected by RUN_SECRET; returns 403 |
| Someone finds your URL and spams POST /run-now | Threading lock prevents concurrent runs; worst case is extra API costs (~$0.05/run) |
| Your API keys leak from GCP | Would require compromising your Google account; use 2FA |
| Cloud Build logs expose secrets | Secrets are injected via `--set-secrets`, not `--set-env-vars`, so they don't appear in build logs |

---

## Costs at a glance

| Service | Free tier | Your usage | Monthly cost |
|---------|-----------|------------|-------------|
| Cloud Run | 2M requests, 360k vCPU-seconds | ~100 requests + 1 pipeline run/day | $0 |
| Container Registry | 0.5 GB | ~150 MB image | $0 |
| Cloud Scheduler | 3 jobs | 1 job | $0 |
| Secret Manager | 6 secret versions, 10k accesses | 3 secrets, ~30 accesses/month | $0 |
| Cloud Build | 120 build-minutes/day | ~2 min/build | $0 |
| **Total** | | | **$0** |
