# meme-coin-ai-bot

An hourly Telegram bot that tracks the top 5 Solana meme coins by 1-hour trading
volume (via DexScreener), compares them against the previous hour's rankings,
and uses Claude to write a short rank-shift report to a Telegram chat.

## How it works

1. `fetch_current_top_tokens()` queries the DexScreener search API for Solana
   pairs, filters out anything under $50k liquidity, and takes the top 5 by
   1-hour volume.
2. `generate_rank_shift_report()` compares the new ranking to the ranking
   saved from the previous run (`leaderboard_state.json`) to compute
   NEW ENTRY / RISING / DROPPING / HOLDING status per token, then asks Claude
   to format a Telegram-ready summary.
3. `send_telegram_alert()` posts that summary to a Telegram chat via the Bot
   API.
4. The new rankings are saved back to `leaderboard_state.json` so the next
   run can compute rank shifts again.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in the values below
```

Required environment variables:

| Variable             | Description                                      |
|----------------------|---------------------------------------------------|
| `TELEGRAM_BOT_TOKEN`  | Token for your Telegram bot (from @BotFather)     |
| `TELEGRAM_CHAT_ID`    | Chat/channel ID the bot should post updates to    |
| `ANTHROPIC_API_KEY`   | API key used to generate the report with Claude   |

## Running

```bash
python leaderboard_bot.py
```

Each run reads `leaderboard_state.json` (if present) for the previous
rankings and rewrites it with the current ones, so it's meant to be run
repeatedly (e.g. every hour) from the same working directory.

## Automation

A GitHub Actions workflow at `.github/workflows/hourly.yml` runs the bot
every hour. Set the three environment variables above as repository secrets
(`Settings > Secrets and variables > Actions`), and the workflow will cache
`leaderboard_state.json` between runs so rank-shift comparisons keep working
across scheduled invocations.
