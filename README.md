# effective-meme

A small Python bot that watches Indian Railways seat availability for a train and pings you on Telegram when seats start disappearing. It runs on a schedule through GitHub Actions, so there is no server to maintain.

## Features

- Checks seat availability for a chosen train, route, class, quota and journey date
- Solves the railway site's CAPTCHA automatically with OCR (`pytesseract`)
- Remembers the last result in `state.json` and compares each new check against it
- Sends a Telegram alert when availability drops by 10 or more seats since the last check
- Runs unattended every 30 minutes on GitHub Actions

## How it works

```
cron-job.org ──► GitHub Actions (workflow_dispatch) ──► bot.py
                                                          │
                                  ocr.py solves CAPTCHA ◄─┤
                                                          ▼
                                       fetch availability, compare with state.json
                                                          │
                                                          ▼
                                                  Telegram alert
```

1. The workflow starts (on a schedule, or triggered via the `workflow_dispatch` API).
2. `bot.py` requests the availability page and `ocr.py` reads the CAPTCHA image.
3. The seat count is compared with the value saved in `state.json`.
4. If the count dropped by the alert threshold, a Telegram message is sent.
5. `state.json` is updated for the next run.

## Project layout

| Path | Purpose |
| --- | --- |
| `bot.py` | Main script: fetches availability, compares with previous state, sends alerts |
| `ocr.py` | CAPTCHA solver built on `pytesseract` |
| `state.json` | Last known availability, persisted between runs |
| `test/` | Sample CAPTCHA images for testing the OCR |
| `.github/workflows/seat-check.yml` | GitHub Actions workflow that runs the bot |

## Setup

### 1. Create a Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram and create a bot to get a **bot token**.
2. Send any message to your new bot, then find your **chat ID** (for example via `https://api.telegram.org/bot<TOKEN>/getUpdates`).

### 2. Add repository secrets

In your repo go to **Settings → Secrets and variables → Actions** and add:

| Secret | Description |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token from BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID that should receive alerts |

> Adjust the secret names above to match what `bot.py` and the workflow actually read.

### 3. Configure the journey

Set the train, stations, class, quota and date in `bot.py`. Example:

| Setting | Example |
| --- | --- |
| Train | `07097` |
| From → To | `ED` (Erode Jn) → `KZE` (Kanhangad) |
| Class | `3A` |
| Quota | `GN` |
| Journey date | `18 Nov 2026` |

### 4. Enable the workflow

Push to `main`. The workflow in `.github/workflows/seat-check.yml` runs on Ubuntu 24.04 with Python 3.12 and installs Tesseract plus the Python dependencies.

## Running locally

```bash
# system dependency
sudo apt-get install tesseract-ocr

# python dependencies
pip install -r requirements.txt

# credentials
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_CHAT_ID="your-chat-id"

python bot.py
```

## Scheduling

GitHub's built-in `schedule` trigger can be delayed or skipped, so for reliable 30-minute runs this project can be triggered externally:

1. Create a GitHub personal access token with permission to run workflows.
2. In [cron-job.org](https://cron-job.org), add a job that sends a `POST` to
   `https://api.github.com/repos/<owner>/<repo>/actions/workflows/seat-check.yml/dispatches`
   with the body `{"ref": "main"}` and the token in the `Authorization` header.
3. Set it to run every 30 minutes.

## Notes

- Never commit your Telegram token or GitHub token. Keep them in Actions secrets.
- Since the repo is public, `state.json` and the workflow logs are visible to everyone.
- Public Actions minutes are free, but respect the railway site's terms and avoid checking more often than you need to.
- CAPTCHA solving is OCR-based and will occasionally fail; the bot should simply retry on the next run.

## Disclaimer

This is an unofficial personal project and is not affiliated with Indian Railways or IRCTC.



##Dev
-credit to kenz and rahul for maintaining. 
-developed by steve.
