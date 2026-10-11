# Configuration Checklist

Track every required configuration value before going live.

## Critical (Production Blocking)

| Item | Variable | Status | Notes |
|------|----------|--------|-------|
| Meta WhatsApp Token | `WHATSAPP_TOKEN` | ☐ | System User permanent token |
| Phone Number ID | `WHATSAPP_PHONE_NUMBER_ID` | ☐ | From Meta WhatsApp > API Setup |
| App Secret | `WHATSAPP_APP_SECRET` | ☐ | Meta App Settings > Basic |
| Verify Token | `WHATSAPP_VERIFY_TOKEN` | ☐ | Random string, match Meta config |
| OpenRouter API Key | `OPENROUTER_API_KEY` | ☐ | From openrouter.ai |
| OpenRouter Model | `OPENROUTER_MODEL` | ☐ | Valid model slug (e.g., `anthropic/claude-3.5-sonnet`) |
| Google Sheet ID | `GOOGLE_SHEET_ID` | ☐ | From spreadsheet URL |
| Google Service Account | `GOOGLE_SERVICE_ACCOUNT_JSON` | ☐ | Base64-encoded JSON key |
| BotKeep Domain | `PUBLIC_BASE_URL` | ☐ | `https://<app>.botkeep.cloud` |
| Admin Token | `ADMIN_TOKEN` | ☐ | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

## High Priority (Feature Complete)

| Item | Variable/File | Status | Notes |
|------|---------------|--------|-------|
| Price Card Image URL | `PRICE_CARD_MEDIA_URL` | ☐ | Public HTTPS, Meta-fetchable |
| Price Card Media ID | `PRICE_CARD_MEDIA_ID` | ☐ | Optional: upload to Meta first |
| Orange Money Number | `data/payments.yaml` | ☐ | Verified account |
| Orange Money Account Name | `data/payments.yaml` | ☐ | Exact registered name |
| AfriMoney Details | `data/payments.yaml` | ☐ | If offering |
| QMoney Details | `data/payments.yaml` | ☐ | If offering |
| Bank Transfer Details | `data/payments.yaml` | ☐ | If offering |
| Approved Apps Config | `data/approved_apps.json` | ☐ | All platforms with `enabled: true` |
| Free Trial Duration | Staff workflow | ☐ | Set per-request via admin |

## Medium Priority (Operational)

| Item | Variable/File | Status | Notes |
|------|---------------|--------|-------|
| Business Phone | `BUSINESS_PHONE` | ☐ | WhatsApp Business number |
| CRM Provider | `CRM_PROVIDER` | ☐ | `google_sheets` or `mock` |
| Discount Percent | `DISCOUNT_PERCENT` | ☐ | Default 20 |
| Discount Active | `DISCOUNT_ACTIVE` | ☐ | `true`/`false` |
| Visit Fee Auto-quote | `VISIT_FEE_AUTOQUOTE_ENABLED` | ☐ | `false` until staff process ready |
| Follow-up Enabled | `FOLLOWUP_SEND_ENABLED` | ☐ | `false` until templates approved |

## Verification Commands

```bash
# Test all configs load
python -c "
from app.config import Settings
s = Settings.from_env({})
print('Business:', s.business_name)
print('Timezone:', s.timezone)
print('DB:', s.db_path)
print('LLM:', s.llm_provider, 'configured:', s.llm_configured)
print('WhatsApp:', 'configured' if s.whatsapp_configured else 'dry-run')
print('Admin:', 'enabled' if s.admin_enabled else 'disabled')
print('CRM:', s.crm_provider)
"

# Test price calculation
python -c "
from app.nexglo_pricing import calculate_price, format_price_card
q = calculate_price(3, 2)
print('3mo x 2dev:', q.formatted_total())
print('Breakdown:', q.formatted_breakdown())
print()
quotes = [calculate_price(m, d) for m in (1,3,6,12) for d in (1,2,3,4)]
print(format_price_card(quotes))
"

# Test CRM mock
python -c "
from app.crm_sheets import CRMService, create_crm_provider
crm = CRMService(create_crm_provider('mock'))
lead = crm.ensure_lead('50760001234', '50760001234', 'Test User')
print('Lead created:', lead.lead_id)
"
```

## Sign-off

- [ ] All Critical items configured
- [ ] All High Priority items configured
- [ ] Medium Priority items reviewed
- [ ] Dry-run flow tested end-to-end
- [ ] Staff trained on admin API
- [ ] Meta webhook verified with test number
- [ ] BotKeep deployment successful
- [ ] `/health` returns 200
- [ ] Ready for production cutover