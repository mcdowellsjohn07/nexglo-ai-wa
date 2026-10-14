# NexgloTV — Deploy the WhatsApp AI Agent on Heroku

This guide provides step-by-step instructions to deploy the customized NexgloTV WhatsApp AI Agent to **Heroku**.

---

## 1. Architecture & Heroku Environment

- **Framework:** FastAPI running on Uvicorn.
- **Entrypoint:** Configured in `Procfile` (`web: uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`).
- **Python Version:** Python 3.12 (`runtime.txt: python-3.12.8`).
- **Cloud Architecture & Ephemeral Storage:**
  - Heroku dynos have an **ephemeral filesystem** (restarted at least once every 24 hours).
  - All critical commercial data (Leads, Subscriptions, Payments, Invoices/Receipts, Resellers, and Wallets) is stored in **Lark Base CRM** (cloud-backed, persistent).
  - Transient session memory (`runtime_data/nexglotv.sqlite`) is auto-initialized on dyno boot via `data/schema.sql`.

---

## 2. Prerequisites

1. A [Heroku account](https://signup.heroku.com/).
2. Heroku CLI installed on your machine (optional, but helpful: `npm install -g heroku` or standalone installer).
3. Meta Developer Account with WhatsApp Cloud API configured.
4. OpenRouter API Key (for LLM intelligence).

---

## 3. Deployment Method A: Deploy via Heroku Dashboard & GitHub (Recommended)

1. **Push your code to GitHub:**
   Ensure your repository has `Procfile`, `runtime.txt`, `requirements.txt`, and `app/`.

2. **Create New App on Heroku:**
   - Log into [dashboard.heroku.com](https://dashboard.heroku.com).
   - Click **New** -> **Create new app**.
   - Name your app (e.g. `nexglotv-wa-ai` or `nexglo-agent-sl`).
   - Choose region (**United States** or **Europe**).

3. **Connect GitHub:**
   - In the **Deploy** tab, select **GitHub**.
   - Search for your repository and click **Connect**.
   - Under **Manual deploy**, select `main` branch and click **Deploy Branch**.

---

## 4. Deployment Method B: Deploy via Heroku CLI

If using git directly with Heroku CLI:

```bash
# 1. Login to Heroku
heroku login

# 2. Create the Heroku app
heroku create nexglotv-wa-ai

# 3. Add Heroku remote if not added automatically
heroku git:remote -a nexglotv-wa-ai

# 4. Deploy your code
git push heroku main

# 5. Ensure 1 web dyno is running
heroku ps:scale web=1
```

---

## 5. Configure Heroku Environment Variables (Config Vars)

In the Heroku Dashboard, navigate to **Settings** -> **Config Vars** (click **Reveal Config Vars**) or run the `heroku config:set` commands below:

```bash
heroku config:set \
  BUSINESS_NAME="NexgloTV" \
  BUSINESS_DESCRIPTION="Internet-based television and entertainment service in Sierra Leone" \
  BUSINESS_TIMEZONE="Africa/Freetown" \
  CURRENCY_LABEL="Le" \
  WHATSAPP_TOKEN="<YOUR_META_ACCESS_TOKEN>" \
  WHATSAPP_PHONE_NUMBER_ID="<YOUR_PHONE_NUMBER_ID>" \
  WHATSAPP_APP_SECRET="<YOUR_APP_SECRET>" \
  WHATSAPP_VERIFY_TOKEN="<YOUR_RANDOM_VERIFY_TOKEN>" \
  GRAPH_API_VERSION="v21.0" \
  WHATSAPP_DRY_RUN="1" \
  ADMIN_TOKEN="<RANDOM_ADMIN_TOKEN>" \
  DB_PATH="runtime_data/nexglotv.sqlite" \
  LLM_PROVIDER="openrouter" \
  OPENROUTER_API_KEY="<YOUR_OPENROUTER_API_KEY>" \
  OPENROUTER_BASE_URL="https://openrouter.ai/api/v1" \
  OPENROUTER_MODEL="meta-llama/llama-3.3-70b-instruct" \
  OPENROUTER_TIMEOUT_SECONDS="25" \
  OPENROUTER_MAX_OUTPUT_TOKENS="500" \
  CRM_PROVIDER="lark_base" \
  LARK_BASE_TOKEN="E8jObNOAeaZqUHsyxRHjR9VcpBg" \
  DISCOUNT_PERCENT="20" \
  DISCOUNT_ACTIVE="true"
```

> **Note on Initial Setup:** Keep `WHATSAPP_DRY_RUN=1` initially while confirming health and webhook validation. Once verified, set `WHATSAPP_DRY_RUN=0` to enable outbound WhatsApp messaging.

---

## 6. Verify Health Endpoint

Open your app's public URL in your browser or run:

```bash
curl -i https://YOUR-APP-NAME.herokuapp.com/health
```

**Expected Response (`HTTP 200 OK`):**
```json
{
  "status": "ok",
  "business": "NexgloTV",
  "signature_verification": true,
  "dry_run": true,
  "llm": "configured"
}
```

---

## 7. Connect Meta WhatsApp Cloud API Webhook

1. Go to your [Meta Developer Dashboard](https://developers.facebook.com/apps).
2. Select your App -> **WhatsApp** -> **Configuration**.
3. Under **Webhook**, click **Edit**:
   - **Callback URL:** `https://YOUR-APP-NAME.herokuapp.com/webhook`
   - **Verify Token:** The exact value configured in `WHATSAPP_VERIFY_TOKEN`.
4. Click **Verify and Save**. Meta will send a GET challenge which your app will answer automatically.
5. Under **Webhook Fields**, click **Manage** and subscribe to **`messages`**.

---

## 8. Go-Live Smoke Test

1. Switch to live mode on Heroku:
   ```bash
   heroku config:set WHATSAPP_DRY_RUN=0
   ```
2. Send a test message to your NexgloTV WhatsApp number:
   - Message: `hi` or `hola`
   - The bot responds with the NexgloTV welcome menu.
   - Reply `1` or `packages`: Verify package pricing displays **1 Month / 1 Device: Le180** (regular Le225).
   - Test free trial request: Verify 24-hour non-repeatable trial logic.
3. Stream Heroku logs in real time to monitor requests:
   ```bash
   heroku logs --tail
   ```

---

## 9. Troubleshooting & FAQ

| Issue | Cause & Fix |
|---|---|
| **Application Error (H10 / H14)** | Check `heroku logs --tail`. Make sure web dyno is scaled (`heroku ps:scale web=1`). |
| **Meta Webhook Verification Failed** | Verify callback ends with `/webhook` and verify token matches `WHATSAPP_VERIFY_TOKEN`. |
| **Incoming Webhook 403 Forbidden** | Meta `WHATSAPP_APP_SECRET` mismatch for signature validation. |
| **No Reply Received on WhatsApp** | Check `WHATSAPP_DRY_RUN=0`, verify phone number ID and Meta token permissions. |
| **Dyno Sleeping (Eco dynos)** | Eco dynos sleep after 30 mins of inactivity. Use **Basic** ($7/mo) or standard dyno for 24/7 responsiveness. |
