# Skill: WhatsApp Delivery

## Purpose
Delivers SmartDigest SOD and EOD briefings to WhatsApp via the Twilio API.

---

## Setup (One-Time)
1. Sign up at https://www.twilio.com (free tier available)
2. Navigate to Messaging → Try it out → Send a WhatsApp message
3. On your phone WhatsApp, send the join code to +1 415 523 8886
4. Set env vars:
```bash
export TWILIO_ACCOUNT_SID=ACxxxxxxx
export TWILIO_AUTH_TOKEN=your_token
export SMARTDIGEST_WHATSAPP_FROM=whatsapp:+14155238886
export SMARTDIGEST_WHATSAPP_TO=whatsapp:+91XXXXXXXXXX  # your number
```

---

## Usage

**Deliver SOD to WhatsApp:**
```bash
python scripts/deliver_whatsapp.py --type sod
```

**Deliver EOD to WhatsApp:**
```bash
python scripts/deliver_whatsapp.py --type eod
```

**Preview without sending:**
```bash
python scripts/deliver_whatsapp.py --type sod --preview
```

---

## When User Says
- "Send my morning brief to WhatsApp" → `deliver_whatsapp.py --type sod`
- "WhatsApp me the evening recap"     → `deliver_whatsapp.py --type eod`
- "Enable WhatsApp delivery"          → Set `"enabled": true` in `config/delivery.json` whatsapp block

---

## Production (Beyond Sandbox)
For production WhatsApp (no sandbox limit):
- Apply for WhatsApp Business API via Meta
- Or use Twilio production WhatsApp number ($0.005/message)
- Update `SMARTDIGEST_WHATSAPP_FROM` with your registered number
