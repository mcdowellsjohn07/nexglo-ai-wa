# NexgloTV WhatsApp Agent — Setup Guide

## Overview
This guide covers the complete setup of the NexgloTV WhatsApp AI Agent for production deployment on BotKeep.

## Prerequisites
- BotKeep Founder Free account (verified active)
- Meta Developer account with WhatsApp Business API access
- OpenRouter API key
- Google Cloud project with Sheets API enabled
- GitHub repository with this codebase

---

## 1. Meta WhatsApp Cloud API Setup

### 1.1 Create Meta App
1. Go to [Meta Developer Console](https://developers.facebook.com/)
2. Create a new **Business** app type
3. Add **WhatsApp** product
4. Note down:
   - **App ID** (for reference)
   - **App Secret** → `WHATSAPP_APP_SECRET`
   - **Phone Number ID** → `WHATSAPP_PHONE_NUMBER_ID`

### 1.2 Generate Access Token
1. In WhatsApp > API Setup, generate a **System User** token (permanent)
2. Or use temporary token for testing (expires 24h)
3. Copy token → `WHATSAPP_TOKEN`

### 1.3 Configure Webhook
1. In WhatsApp > Configuration, set:
   - **Callback URL**: `https://<your-botkeep-domain>/webhook`
   - **Verify Token**: Generate a random string → `WHATSAPP_VERIFY_TOKEN`
2. Subscribe to `messages` field
3. Verify and save

### 1.4 Phone Number
- Add/verify your business phone number in WhatsApp > Phone Numbers
- This is the number customers will message

---

## 2. OpenRouter Setup

1. Sign up at [OpenRouter](https://openrouter.ai/)
2. Create API key → `OPENROUTER_API_KEY`
3. Choose a model (e.g., `anthropic/claude-3.5-sonnet`, `openai/gpt-4o-mini`)
4. Set model slug → `OPENROUTER_MODEL`

---

## 3. Lark Base CRM Setup (RECOMMENDED)

The WhatsApp agent reads and writes the CRM directly in **Lark Base** — the same place your team manages leads, customers and payments.

### 3.1 What you get

A Base named **"NexgloTV CRM"** with 18 tables (from your import file):

| # | Table | Written by bot | Purpose |
|---|-------|----------------|---------|
| 01 | Leads | ✅ | Every enquiry, stage-tracked (NEW_LEAD → CONVERTED) |
| 02 | Free_Trials | ✅ | Trial requests/approvals (staff approves) |
| 03 | Customers | ✅ | Created ONLY after verified payment |
| 04 | Packages | ✅ seeded | 16 PKG rows with prices + 20% promo |
| 05 | Subscriptions | ✅ | Active subscription records |
| 06 | Payments | ✅ append | Payment refs, staff verify status |
| 07 | Installations | ✅ | Setup tracking, visit bookings |
| 08 | Devices | ✅ | Registered devices per customer |
| 09 | Resellers | read | Managed by team |
| 10 | Reseller_Sales | read | Managed by team |
| 11 | Commissions | read | Managed by team |
| 12 | Reseller_Payouts | read | Managed by team |
| 13 | Reseller_Wallet | read | Managed by team |
| 14 | Referrals | ✅ | Referral capture from chat |
| 15 | Staff | read | Staff directory for assignment |
| 16 | Support_Tickets | ✅ | Tickets created from complaints |
| 17 | Activities | ✅ | Audit trail of bot actions |
| 18 | Service_Zones | read | Visit fee quoting by area |

### 3.2 Connect the bot (local machine / BotKeep)

1. Install Lark CLI and create/bind the app once:
   ```bash
   lark-cli config init --new     # creates the Lark app in browser
   lark-cli auth login --domain base --no-wait --json   # authorize Base access
   ```
2. Set environment:
   ```bash
   CRM_PROVIDER=lark_base
   LARK_BASE_TOKEN=E8jObNOAeaZqUHsyxRHjR9VcpBg    # your existing Base
   ```
3. Start the app — tables and package rows are ensured automatically.

**On BotKeep:** run the same two `lark-cli` commands in the app's console once, then set the same env vars.

### 3.3 How the bot writes

- **New enquiry** → row in `01_Leads` (upsert keyed by WhatsApp number)
- **Quote given** → Lead updated with stage `PACKAGE_SELECTED` + quote notes
- **App installed → INSTALLED** → handoff recorded in `17_Activities`
- **Staff confirms setup** → Lead `SETUP_VERIFIED`
- **Staff verifies payment** → `06_Payments` row confirmed + exactly **one** `03_Customers` row created (idempotent — renewals update the same row)
- **Referral code given** → `14_Referrals` row
- **Complaint** → `16_Support_Tickets` row

Failed Lark API calls never break the customer chat — the agent continues and logs the sync failure for retry (spec §8.3).

### 3.4 Open your Base

https://gjpmrvdwvnro.jp.larksuite.com/base/E8jObNOAeaZqUHsyxRHjR9VcpBg

---

## 4. Google Sheets CRM Setup (alternative)

### 4.1 Create Spreadsheet
1. Create new Google Sheet named **"NexgloTV CRM"**
2. Copy spreadsheet ID from URL → `GOOGLE_SHEET_ID`

### 4.2 Create Service Account
1. In Google Cloud Console, create a Service Account
2. Grant **Editor** role on the spreadsheet (share with service account email)
3. Download JSON key file
4. Encode as base64: `cat key.json | base64 -w0` → `GOOGLE_SERVICE_ACCOUNT_JSON`
5. Or paste JSON directly (BotKeep encrypts env vars)

### 4.3 Enable Sheets API
- In Google Cloud Console, enable **Google Sheets API** for the project

---

## 4. BotKeep Deployment

### 4.1 Verify Founder Free
- Check BotKeep > Plans and Billing > **Founder Free active**

### 4.2 Create Application
1. New Python Application
2. Connect GitHub repository (or upload ZIP)
3. Set startup command: `python start.py`
4. Configure environment variables (see below)

### 4.3 Environment Variables
Set in BotKeep > Environment:

```bash
# Required - Meta WhatsApp
WHATSAPP_TOKEN=your_meta_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_APP_SECRET=your_app_secret
WHATSAPP_VERIFY_TOKEN=your_verify_token

# Required - OpenRouter
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_MODEL=your_model_slug

# Required - Google Sheets
GOOGLE_SHEET_ID=your_sheet_id
GOOGLE_SERVICE_ACCOUNT_JSON=your_base64_json

# Required - BotKeep
SERVER_PORT=8000
PUBLIC_BASE_URL=https://your-app.botkeep.cloud

# Business
BUSINESS_NAME=NexgloTV
BUSINESS_TIMEZONE=Africa/Freetown

# Optional - CRM (use mock for testing)
CRM_PROVIDER=google_sheets
# CRM_PROVIDER=mock

# Optional - Media
PRICE_CARD_MEDIA_URL=https://your-cdn.com/price-card.png

# Optional - Staff
ADMIN_TOKEN=generate_with_python_secrets_token_urlsafe_32
```

### 4.4 Deploy & Test
1. Deploy application
2. Check Console logs for `/health` endpoint
3. Test webhook: `curl https://your-app.botkeep.cloud/health`
4. In Meta Console, verify webhook callback works
5. Send test message from WhatsApp test number

---

## 5. Post-Deploy Configuration

### 5.1 Price Card Image
- Upload `NexgloTV_20_Percent_Discount_Price_Card.png` to CDN
- Set `PRICE_CARD_MEDIA_URL` to public HTTPS URL

### 5.2 Approved Apps
Edit `data/approved_apps.json` with verified app details:
```json
{
  "android_phone": {
    "app_name": "NexgloTV",
    "official_download_url": "https://play.google.com/store/apps/details?id=com.nexglotv",
    "app_icon_url": "https://your-cdn.com/android-icon.png",
    "enabled": true,
    "verified_by": "admin",
    "verified_at": "2026-10-11T00:00:00Z"
  }
}
```

### 5.3 Payment Details
Edit `data/payments.yaml` with verified accounts:
```yaml
payments:
  orange_money:
    number: "+232XXXXXXXXX"
    account_name: "NexgloTV Ltd"
    is_verified: true
```

### 5.3 Free Trial Policy
- Set trial duration in staff workflow (not in config)
- Staff approves per-request via `/admin/trials/{lead_id}/approve`

---

## 6. Staff Access

### 6.1 Admin Token
Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
Set as `ADMIN_TOKEN` in BotKeep environment.

### 6.2 Staff API Usage
```bash
# View handoff queue
curl -H "Authorization: Bearer $ADMIN_TOKEN" https://your-app.botkeep.cloud/admin/handoffs

# Reply as staff
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"Hello, I am helping you now."}' \
  https://your-app.botkeep.cloud/admin/conversations/232XXXXXXXXX/reply

# Verify payment & convert lead
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"verified_by":"staff_name"}' \
  https://your-app.botkeep.cloud/admin/payments/verify

# Confirm setup working
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"staff_name":"John"}' \
  https://your-app.botkeep.cloud/admin/leads/confirm-setup
```

---

## 7. Monitoring & Maintenance

### 7.1 Health Checks
- `/health` - basic status
- Check BotKeep Console for memory/CPU
- Monitor webhook response times

### 7.2 Database Backup
- SQLite at `data/nexglotv.sqlite`
- BotKeep persists disk; verify on restart
- Schedule periodic Google Sheets export

### 7.3 Logs
- BotKeep Console shows stdout/stderr
- Look for: webhook errors, CRM sync failures, payment verification issues

---

## 8. Troubleshooting

| Issue | Solution |
|-------|----------|
| Webhook verification fails | Check `WHATSAPP_VERIFY_TOKEN` matches Meta config |
| Signature verification fails | Ensure `WHATSAPP_APP_SECRET` is correct |
| Price card not sending | Verify `PRICE_CARD_MEDIA_URL` is public HTTPS |
| App link not sending | Check `data/approved_apps.json` has `enabled: true` |
| CRM not syncing | Verify service account has Editor access on Sheet |
| Payment details not showing | Check `data/payments.yaml` has `is_verified: true` |
| BotKeep deploy fails | Check Python version, `requirements.txt`, port binding |

---

## 9. Cutover to Production

1. Test with Meta **test number** first
2. Run full flow: price → package → device → install → handoff → payment
3. Verify CRM: Lead created, Customer created after payment
4. Switch `WHATSAPP_DRY_RUN=0` (remove or set to 0)
5. Point Meta webhook to production business number
6. Monitor first 24h closely