# UK Pool Pump Availability Tracker

Watches UK retailers for the **Intex SX925** sand filter pump (and compatible pumps for a
**10ft Bestway Steel Pro Max**) and sends a **Telegram push** (with an **email fallback**) the
moment a watched pump comes into stock — with the price and a direct buy link. It does **not**
buy anything; you click through and purchase yourself.

It runs free on **GitHub Actions** every ~5 hours, so nothing needs to be installed or kept
running on your PC.

## Why a browser, not a simple fetch?

UK retailer pages (Amazon, OnBuy, Bestway, pool specialists) block plain HTTP requests with a
`403`, and search-engine "in stock" flags lag reality (a listing can show in stock in search but
**SOLD OUT** on the live page). So each check renders the **real product page in a headless
browser** and reads the actual buy-state — "Add to basket" vs "Sold out"/"Currently unavailable".

## How it works

1. `pumptracker/config.yaml` lists **targets** — one product page per vendor.
2. Each run renders every page, decides in/out of stock, and extracts the price.
3. It compares against `pumptracker/state.json` and alerts **only on an out-of-stock → in-stock
   transition**, so you're not pinged repeatedly while something stays in stock.
4. The updated `state.json` is committed back to the repo (dedupe + a free price/stock history).

Each vendor is checked independently — one site failing never aborts the run.

## One-time setup

Everything below is clicking and copy-pasting — no software on your machine.

### 1. Keep this repo private
It will hold your notification settings as GitHub **secrets** (encrypted), but private is safest.

### 2. Create a Telegram bot (primary alerts)
1. In Telegram, open a chat with **@BotFather** → send `/newbot` → follow the prompts.
2. Copy the **bot token** it gives you (looks like `123456:ABC-DEF...`).
3. Open a chat with your new bot and send it any message (e.g. `hi`) — this is required before it
   can find your chat id.

### 3. Get your Telegram chat id
Run the helper locally (needs Python + `pip install httpx`):
```bash
TELEGRAM_BOT_TOKEN=your-token python -m pumptracker.scripts.get_telegram_chat_id
```
It prints your **chat id** (a number). Copy it.

### 4. Gmail app password (email fallback)
Already generated? Good. If not: enable 2-Step Verification on your Google account, then create an
app password at <https://myaccount.google.com/apppasswords>. It's the 16-character code.
> Hotmail/Outlook is fine as a **recipient** but a poor **sender** (SMTP auth is restricted), which
> is why the sending account is Gmail.

### 5. Add repository secrets
Repo **Settings → Secrets and variables → Actions → New repository secret**. Add:

| Secret name          | Value                                                        | Required |
|----------------------|-------------------------------------------------------------|----------|
| `TELEGRAM_BOT_TOKEN` | The BotFather token                                         | for Telegram |
| `TELEGRAM_CHAT_ID`   | The chat id from step 3                                      | for Telegram |
| `GMAIL_ADDRESS`      | Your Gmail address (the sender)                             | for email |
| `GMAIL_APP_PASSWORD` | The 16-character app password                               | for email |
| `ALERT_EMAIL_TO`     | Where alerts should land (e.g. your Hotmail). Defaults to `GMAIL_ADDRESS` if unset | optional |

Telegram and email are independent — set up either, both, or (for testing) neither.

### 6. Turn it on and test
1. **Actions** tab → enable workflows if prompted.
2. Open **Pool pump tracker** → **Run workflow** (manual `workflow_dispatch`) to check it runs and
   commits `state.json`.
3. After that, it runs automatically every ~5 hours.

## Local usage (optional)

```bash
pip install -r requirements.txt
python -m playwright install chromium

python -m pumptracker.main --dry-run     # check + print, never send or save
python -m pumptracker.main --test-notify # send a test alert on configured channels
pytest pumptracker/tests                  # offline parser + logic tests
```

If you already have a Chromium/Chrome installed and don't want Playwright to download its own,
point at it with `PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome`. Not needed on GitHub Actions (the
workflow installs a matching browser) or for a normal `playwright install`.

## Editing what's watched

Open `pumptracker/config.yaml` and edit the `targets` list — add a URL, remove one, or fix a link
if a vendor renumbers the product. Each target is:

```yaml
  - id: onbuy-bestway-800gal        # unique id (used in state.json)
    vendor: OnBuy                    # label shown in alerts
    product: Bestway 800gal Flowclear filter pump
    url: https://www.onbuy.com/...   # the exact product page to watch
    method: playwright               # default; use "httpx" only for clean static pages
    # price_selector: ".price"       # optional CSS override if auto-price is wrong
```

The `settings` block at the top controls check pacing, the plausible price band, and the text
markers used to decide stock — tweak if a vendor uses unusual wording.

## Notes & limits

- **Delivery to Chislehurst (BR7):** the tracker shows the vendor's generic dispatch line
  ("dispatched in 1–2 days"); the exact doorstep date only appears at checkout.
- **Amazon** is best-effort — it sometimes blocks even a real browser from cloud IPs and may report
  "unknown" rather than a stock state. Other vendors are more reliable.
- **Cost:** £0. Well within the GitHub Actions free tier at a few runs a day.
- **First run** may alert for anything already in stock — that's intended (you want to know now).
