import os
import sys
import json
import requests
import anthropic

DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/search?q=solana"
STATE_FILE = "leaderboard_state.json"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-sonnet-5"


def load_previous_state():
    """Loads previous hour's rank rankings from local JSON file."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_current_state(current_ranks):
    """Saves current rankings for the next hour's comparison."""
    with open(STATE_FILE, "w") as f:
        json.dump(current_ranks, f, indent=2)


def fetch_current_top_tokens():
    """Fetches Solana tokens filtered by $50k+ liquidity baseline sorted by 1h volume."""
    try:
        response = requests.get(DEXSCREENER_URL, timeout=10)
        response.raise_for_status()
        pairs = response.json().get("pairs") or []

        candidates = []
        for p in pairs:
            liq = p.get("liquidity", {}).get("usd") or 0
            vol_h1 = p.get("volume", {}).get("h1") or 0

            # Filter: Minimum $50k liquidity baseline
            if liq >= 50000:
                candidates.append({
                    "symbol": p.get("baseToken", {}).get("symbol", "UNKNOWN"),
                    "name": p.get("baseToken", {}).get("name", "Unknown"),
                    "price_usd": p.get("priceUsd", "0"),
                    "liquidity_usd": liq,
                    "volume_1h": vol_h1,
                    "price_change_h1": p.get("priceChange", {}).get("h1", 0),
                    "url": p.get("url", "")
                })

        # Sort candidates by 1h volume to construct live ranking
        candidates = sorted(candidates, key=lambda x: x["volume_1h"], reverse=True)
        return candidates[:5]
    except Exception as e:
        print(f"Error fetching DexScreener data: {e}", file=sys.stderr)
        return []


def generate_rank_shift_report(current_tokens, previous_state):
    """Calculates position changes and formats Claude prompt for state updates."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    current_state_map = {}
    ranked_payload = []

    for rank, token in enumerate(current_tokens, 1):
        sym = token["symbol"]
        prev_rank = previous_state.get(sym, None)

        # Calculate rank shift text
        if prev_rank is None:
            shift = "NEW ENTRY \U0001F7E2"
        elif prev_rank > rank:
            shift = f"RISING (Was #{prev_rank}) ⬆️"
        elif prev_rank < rank:
            shift = f"DROPPING (Was #{prev_rank}) \U0001F53B"
        else:
            shift = "HOLDING POSITION ⚖️"

        token["rank_shift"] = shift
        token["current_rank"] = rank
        current_state_map[sym] = rank
        ranked_payload.append(token)

    prompt = f"""
    You are an automated crypto market-tracker bot updating live leaderboard rank shifts:

    CURRENT RANKING DATA:
    {json.dumps(ranked_payload, indent=2)}

    TASK:
    Format an immediate Telegram notification summarizing the hourly leaderboard changes.

    FORMAT (Telegram Markdown):
    \U0001F4CA *HOURLY MEME COIN RANK SHIFT REPORT* \U0001F4CA

    For each token (Rank 1 to 5):
    - Rank #[X]: $[SYMBOL] | Status: [Rank Shift Status]
    - Price: $X.XX | 1h Vol: $XX,XXX | Liquidity: $XX,XXX
    - Trend Assessment: [1-sentence analysis on whether it's holding strength or fading]
    - Chart: [URL]

    Keep total output clean, brief, and actionable. Avoid conversational fluff.
    """

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text, current_state_map


def send_telegram_alert(text):
    """Sends notification payload to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"Error sending Telegram alert: {e}", file=sys.stderr)


def main():
    missing = [name for name, value in (
        ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
        ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
        ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
    ) if not value]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    prev_ranks = load_previous_state()
    current_tokens = fetch_current_top_tokens()

    if current_tokens:
        report, new_state = generate_rank_shift_report(current_tokens, prev_ranks)
        send_telegram_alert(report)
        save_current_state(new_state)
        print("Hourly leaderboard update successfully processed.")
    else:
        print("No qualifying tokens found this run; skipping alert.")


if __name__ == "__main__":
    main()
