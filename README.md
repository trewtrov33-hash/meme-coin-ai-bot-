# meme-coin-ai-bot

An hourly bot that tracks the top 5 Solana meme coins by 1-hour trading
volume (via DexScreener), compares them against the previous hour's
rankings, sends a WhatsApp alert with Claude-written rank-shift commentary,
and publishes a dedicated live dashboard website.

## How it works

1. `fetch_current_top_tokens()` queries the DexScreener search API for Solana
   pairs, filters out anything under $50k liquidity, and takes the top 5 by
   1-hour volume.
2. `compute_rank_shifts()` compares the new ranking to the ranking saved from
   the previous run (`leaderboard_state.json`) to compute NEW ENTRY / RISING
   / DROPPING / HOLDING status per token.
3. `generate_rank_shift_report()` asks Claude to turn that data into a short
   WhatsApp-ready summary.
4. `send_whatsapp_alert()` sends it to your phone via the Twilio WhatsApp API.
5. `render_site()` writes a standalone dashboard (`docs/index.html`) showing
   the full leaderboard, styled and theme-aware.
6. The new rankings are saved back to `leaderboard_state.json` so the next
   run can compute rank shifts again.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in the values below
```

Required environment variables:

| Variable               | Description                                                        |
|-------------------------|--------------------------------------------------------------------|
| `ANTHROPIC_API_KEY`     | API key used to generate the report with Claude                    |
| `TWILIO_ACCOUNT_SID`    | Twilio account SID                                                  |
| `TWILIO_AUTH_TOKEN`     | Twilio auth token                                                    |
| `TWILIO_WHATSAPP_FROM`  | Your Twilio WhatsApp sender number, e.g. `+14155238886`              |
| `TWILIO_WHATSAPP_TO`    | Your WhatsApp number (with country code), e.g. `+255700000000`       |
| `LEADERBOARD_SITE_URL`  | Optional: dashboard URL, appended to WhatsApp alerts if set          |

To get Twilio WhatsApp credentials: create a free Twilio account, open
**Messaging > Try it out > Send a WhatsApp message** to join the sandbox (or
apply for a production WhatsApp sender), and copy your Account SID and Auth
Token from the console dashboard.

## Running

```bash
python leaderboard_bot.py
```

Each run reads `leaderboard_state.json` (if present) for the previous
rankings and rewrites it with the current ones, and regenerates
`docs/index.html`, so it's meant to be run repeatedly (e.g. every hour) from
the same working directory.

## Automation & dashboard hosting

A GitHub Actions workflow at `.github/workflows/hourly.yml` runs the bot
every hour, sends the WhatsApp alert, and publishes `docs/index.html` to
GitHub Pages.

To enable it:

1. Set the five required env vars above as repository secrets
   (`Settings > Secrets and variables > Actions > Secrets`). If you set
   `LEADERBOARD_SITE_URL`, add it as a repository **variable** instead of a
   secret (`Settings > Secrets and variables > Actions > Variables`).
2. Go to `Settings > Pages` and set **Source** to **GitHub Actions**.
3. Run the workflow once manually from the **Actions** tab
   (`Hourly Leaderboard Update > Run workflow`) to publish the first version
   of the dashboard; after that it updates automatically every hour.

The workflow caches `leaderboard_state.json` between runs so rank-shift
comparisons keep working across scheduled invocations.
