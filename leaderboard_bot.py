import os
import sys
import json
import html
from datetime import datetime, timezone

import requests
import anthropic

DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/search?q=solana"
STATE_FILE = "leaderboard_state.json"
SITE_OUTPUT_PATH = os.path.join("docs", "index.html")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CALLMEBOT_PHONE = os.getenv("CALLMEBOT_PHONE")    # e.g. "+255700000000", the WhatsApp number that ran the CallMeBot signup
CALLMEBOT_APIKEY = os.getenv("CALLMEBOT_APIKEY")  # returned by CallMeBot after you message it "I allow callmebot to send me messages"
SITE_URL = os.getenv("LEADERBOARD_SITE_URL", "")

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
            # The search endpoint returns pairs from other chains too (Base, BSC, ...)
            # that merely match "solana" as a search term; only keep actual Solana pairs.
            if p.get("chainId") != "solana":
                continue

            symbol = p.get("baseToken", {}).get("symbol") or "UNKNOWN"
            if symbol.upper() in ("SOL", "WSOL"):
                continue  # native/wrapped SOL isn't a meme coin

            liq = p.get("liquidity", {}).get("usd") or 0
            vol_h1 = p.get("volume", {}).get("h1") or 0

            # Filter: Minimum $50k liquidity baseline
            if liq >= 50000:
                candidates.append({
                    "symbol": symbol,
                    "name": p.get("baseToken", {}).get("name") or "Unknown",
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


def compute_rank_shifts(current_tokens, previous_state):
    """Annotates tokens with rank + rank-shift status, and builds the new state map."""
    current_state_map = {}
    ranked_payload = []

    for rank, token in enumerate(current_tokens, 1):
        sym = token["symbol"]
        prev_rank = previous_state.get(sym, None)

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

    return ranked_payload, current_state_map


def render_plain_report(ranked_payload):
    """Builds the WhatsApp report directly from the ranked data, no AI involved."""
    lines = ["\U0001F4CA *HOURLY MEME COIN RANK SHIFT REPORT* \U0001F4CA"]
    for token in ranked_payload:
        lines.append(
            f"\n#{token['current_rank']} *${token['symbol']}* | {token['rank_shift']}\n"
            f"Price: ${token['price_usd']} | 1h Vol: ${token['volume_1h']:,.0f} | "
            f"Liquidity: ${token['liquidity_usd']:,.0f}\n"
            f"Chart: {token['url']}"
        )
    return "\n".join(lines)


def generate_rank_shift_report(ranked_payload):
    """Asks Claude to turn the ranked payload into a short WhatsApp-ready summary.

    Falls back to a plain, non-AI formatted report when no Anthropic API key
    is configured, so the bot still runs without that dependency.
    """
    if not ANTHROPIC_API_KEY:
        return render_plain_report(ranked_payload)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""
    You are an automated crypto market-tracker bot updating live leaderboard rank shifts:

    CURRENT RANKING DATA:
    {json.dumps(ranked_payload, indent=2)}

    TASK:
    Write a short WhatsApp message summarizing the hourly leaderboard changes.
    Use only WhatsApp-supported formatting: *bold* and _italic_. No headers,
    no tables, no unsupported markdown. Keep the entire message under 600
    characters total, since it is sent as a URL query parameter.

    FORMAT:
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
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


def send_whatsapp_alert(text):
    """Sends the report as a WhatsApp message via the CallMeBot API."""
    url = "https://api.callmebot.com/whatsapp.php"
    body = text if not SITE_URL else f"{text}\n\nFull dashboard: {SITE_URL}"
    params = {
        "phone": CALLMEBOT_PHONE,
        "text": body,
        "apikey": CALLMEBOT_APIKEY,
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Error sending WhatsApp alert: {e}", file=sys.stderr)


def render_site(ranked_payload):
    """Renders the standalone leaderboard dashboard as a static HTML file."""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rows = []
    for token in ranked_payload:
        change = token["price_change_h1"] or 0
        change_class = "positive" if change >= 0 else "negative"
        rows.append(f"""
        <li class="token-card">
          <div class="rank">#{token['current_rank']}</div>
          <div class="details">
            <div class="symbol-row">
              <span class="symbol">${html.escape(str(token['symbol']))}</span>
              <span class="name">{html.escape(str(token['name']))}</span>
            </div>
            <div class="shift">{html.escape(str(token['rank_shift']))}</div>
            <div class="stats">
              <span>Price: ${html.escape(str(token['price_usd']))}</span>
              <span>1h Vol: ${token['volume_1h']:,.0f}</span>
              <span>Liquidity: ${token['liquidity_usd']:,.0f}</span>
              <span class="{change_class}">1h Change: {change:+.2f}%</span>
            </div>
          </div>
          <a class="chart-link" href="{html.escape(token['url'] or '#')}" target="_blank" rel="noopener">Chart &rarr;</a>
        </li>""")

    rows_html = "\n".join(rows) if rows else "<li class=\"empty\">No qualifying tokens this run.</li>"

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Solana Meme Coin Leaderboard</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #f7f7fb;
    --card: #ffffff;
    --text: #14141a;
    --muted: #6b6b76;
    --accent: #7c5cff;
    --positive: #1a9e63;
    --negative: #d3384a;
    --border: #e5e5ec;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0f0f14;
      --card: #191922;
      --text: #f2f2f7;
      --muted: #9a9aa8;
      --accent: #9c85ff;
      --border: #2a2a35;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 24px 16px calc(24px + env(safe-area-inset-bottom, 0px));
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  header {{
    max-width: 720px;
    margin: 0 auto 24px;
  }}
  h1 {{
    font-size: 1.5rem;
    margin: 0 0 4px;
  }}
  .updated {{
    color: var(--muted);
    font-size: 0.85rem;
  }}
  ul {{
    list-style: none;
    margin: 0 auto;
    padding: 0;
    max-width: 720px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }}
  .token-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    display: flex;
    align-items: flex-start;
    gap: 14px;
  }}
  .rank {{
    font-weight: 700;
    color: var(--accent);
    font-size: 1.1rem;
    min-width: 2.2em;
  }}
  .details {{ flex: 1; min-width: 0; }}
  .symbol-row {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; }}
  .symbol {{ font-weight: 700; font-size: 1.05rem; }}
  .name {{ color: var(--muted); font-size: 0.85rem; }}
  .shift {{ margin: 4px 0; font-size: 0.85rem; }}
  .stats {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    font-size: 0.8rem;
    color: var(--muted);
  }}
  .positive {{ color: var(--positive); }}
  .negative {{ color: var(--negative); }}
  .chart-link {{
    color: var(--accent);
    text-decoration: none;
    font-size: 0.85rem;
    white-space: nowrap;
  }}
  .empty {{ text-align: center; color: var(--muted); padding: 24px; }}
</style>
</head>
<body>
<header>
  <h1>Solana Meme Coin Leaderboard</h1>
  <div class="updated">Last updated: {generated_at} &middot; refreshes hourly</div>
</header>
<ul>
{rows_html}
</ul>
</body>
</html>
"""

    os.makedirs(os.path.dirname(SITE_OUTPUT_PATH), exist_ok=True)
    with open(SITE_OUTPUT_PATH, "w") as f:
        f.write(page)


def main():
    missing = [name for name, value in (
        ("CALLMEBOT_PHONE", CALLMEBOT_PHONE),
        ("CALLMEBOT_APIKEY", CALLMEBOT_APIKEY),
    ) if not value]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    if not ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY not set; using plain-text report instead of Claude-generated commentary.")

    prev_ranks = load_previous_state()
    current_tokens = fetch_current_top_tokens()

    if current_tokens:
        ranked_payload, new_state = compute_rank_shifts(current_tokens, prev_ranks)
        report = generate_rank_shift_report(ranked_payload)
        send_whatsapp_alert(report)
        save_current_state(new_state)
        print("Hourly leaderboard update successfully processed.")
    else:
        ranked_payload = []
        print("No qualifying tokens found this run; skipping alert.")

    # Always regenerate the dashboard, even with an empty ranking, so the
    # GitHub Pages publish step always has a docs/index.html to upload.
    render_site(ranked_payload)


if __name__ == "__main__":
    main()
