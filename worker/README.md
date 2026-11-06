# !seat Telegram → GitHub Actions Worker

Receives Telegram webhook messages, and on `!seat` triggers the
`seat-check.yml` workflow with `mode=reply`.

Deployed manually on Cloudflare Workers (paste `index.js` into the dashboard editor).

## Settings (Worker → Settings → Variables and Secrets)
Text: GH_REPO (hex-forge/effective_meme), GH_WORKFLOW (seat-check.yml), GH_REF (main)
Secrets: GH_TOKEN (fine-grained PAT, Actions: read/write, this repo only),
         TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, WEBHOOK_SECRET

## Webhook registration
curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -d "url=https://<worker>.workers.dev" -d "secret_token=<WEBHOOK_SECRET>"