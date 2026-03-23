"""
📈 StockBot — A feature-rich Telegram bot for stock tracking.

Commands:
  /start        — Welcome & overview
  /help         — Full command list
  /price <sym>  — Live price of a stock
  /info <sym>   — Detailed stock info
  /history <sym> [period] — Historical performance
  /watch <sym>  — Add to watchlist
  /unwatch <sym>— Remove from watchlist
  /watchlist    — View your watchlist with prices
  /alert <sym> <above|below> <price> — Set a price alert
  /alerts       — View active alerts
  /delalert <id>— Delete an alert
  /buy <sym> <shares> <price> — Add to portfolio
  /sell <sym>   — Remove from portfolio
  /portfolio    — View portfolio with P&L
  /top          — Top gainers/losers (popular tickers)
  /compare <s1> <s2> — Compare two stocks
"""

import os
import asyncio
import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    JobQueue,
)
from telegram.constants import ParseMode

import database as db
import stock_service as svc

# ── Configuration ──────────────────────────────────────────────────────────────

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ALERT_CHECK_INTERVAL = 60  # seconds between alert checks

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────────

def fmt(price, currency="USD") -> str:
    symbol = "₹" if currency == "INR" else "$"
    return f"{symbol}{price:,.2f}"

def build_price_card(info: dict) -> str:
    """Build a nicely formatted price message."""
    c = info["currency"]
    sign = "+" if info["change"] >= 0 else ""
    emoji = svc.trend_emoji(info["change"])
    arr = svc.arrow(info["change"])

    lines = [
        f"{emoji} *{info['name']}* (`{info['symbol']}`)",
        f"",
        f"💰 *Price:* `{fmt(info['price'], c)}`",
        f"📊 *Change:* `{sign}{fmt(info['change'], c)} ({sign}{info['change_pct']:.2f}%)`",
        f"",
        f"🔓 Open:  `{fmt(info['open'] or 0, c)}`",
        f"🔺 High:  `{fmt(info['high'] or 0, c)}`",
        f"🔻 Low:   `{fmt(info['low'] or 0, c)}`",
        f"",
        f"📦 Volume:     `{svc.format_volume(info['volume'])}`",
        f"📦 Avg Volume: `{svc.format_volume(info['avg_volume'])}`",
    ]

    if info.get("market_cap_raw"):
        lines.append(f"🏢 Mkt Cap: `{svc.format_large_number(info['market_cap'])}`")
    if info.get("52w_high"):
        lines.append(f"📅 52W High: `{fmt(info['52w_high'], c)}`  Low: `{fmt(info['52w_low'], c)}`")
    if info.get("pe_ratio"):
        lines.append(f"📐 P/E: `{info['pe_ratio']:.2f}`")
    if info.get("dividend_yield"):
        lines.append(f"💵 Dividend Yield: `{info['dividend_yield']*100:.2f}%`")
    if info.get("sector"):
        lines.append(f"🏭 Sector: `{info['sector']}`")

    return "\n".join(lines)

async def fetch_and_reply(update: Update, symbol: str, mode: str = "price"):
    """Fetch stock info and send a formatted reply."""
    msg = await update.message.reply_text(f"⏳ Fetching data for `{symbol.upper()}`…", parse_mode=ParseMode.MARKDOWN)
    info = svc.get_stock_info(symbol)
    if not info:
        await msg.edit_text(
            f"❌ Could not find stock `{symbol.upper()}`. Please check the ticker symbol.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = build_price_card(info)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Watchlist", callback_data=f"watch:{symbol.upper()}"),
            InlineKeyboardButton("🔔 Set Alert", callback_data=f"alert_prompt:{symbol.upper()}"),
        ],
        [
            InlineKeyboardButton("📉 1M History", callback_data=f"hist:{symbol.upper()}:1mo"),
            InlineKeyboardButton("📉 6M History", callback_data=f"hist:{symbol.upper()}:6mo"),
        ]
    ])

    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

# ── Command Handlers ───────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username or "", user.first_name or "")

    text = (
        f"👋 Welcome, *{user.first_name}*!\n\n"
        "I'm *StockBot* — your personal market tracker right inside Telegram.\n\n"
        "🔹 *What I can do:*\n"
        "• Real-time stock prices & details\n"
        "• Personal watchlist with live prices\n"
        "• Price alerts (above / below a target)\n"
        "• Portfolio tracker with P&L\n"
        "• Historical performance charts\n"
        "• Compare two stocks side-by-side\n\n"
        "Type /help to see all commands.\n"
        "Start by trying: `/price AAPL`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *StockBot — Command Reference*\n\n"
        "*📊 Price & Info*\n"
        "`/price AAPL` — Live price card\n"
        "`/info TSLA` — Detailed fundamentals\n"
        "`/history MSFT 3mo` — Historical perf (1d/5d/1mo/3mo/6mo/1y)\n"
        "`/compare AAPL GOOGL` — Side-by-side comparison\n\n"
        "*👁 Watchlist*\n"
        "`/watch NVDA` — Add to watchlist\n"
        "`/unwatch NVDA` — Remove from watchlist\n"
        "`/watchlist` — View watchlist with live prices\n\n"
        "*🔔 Alerts*\n"
        "`/alert AAPL above 200` — Alert when price goes above $200\n"
        "`/alert TSLA below 150` — Alert when price drops below $150\n"
        "`/alerts` — View your active alerts\n"
        "`/delalert 3` — Delete alert #3\n\n"
        "*💼 Portfolio*\n"
        "`/buy AAPL 10 178.50` — Add 10 shares bought at $178.50\n"
        "`/sell AAPL` — Remove stock from portfolio\n"
        "`/portfolio` — View portfolio with P&L\n\n"
        "*📈 Market*\n"
        "`/top` — Popular stocks overview\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/price SYMBOL`\nExample: `/price AAPL`", parse_mode=ParseMode.MARKDOWN)
        return
    await fetch_and_reply(update, context.args[0])


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/info SYMBOL`\nExample: `/info TSLA`", parse_mode=ParseMode.MARKDOWN)
        return
    await fetch_and_reply(update, context.args[0], mode="info")


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: `/history SYMBOL [period]`\nPeriods: `1d 5d 1mo 3mo 6mo 1y`\nExample: `/history AAPL 3mo`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    symbol = context.args[0].upper()
    period = context.args[1] if len(context.args) > 1 else "1mo"
    valid_periods = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y"]
    if period not in valid_periods:
        await update.message.reply_text(f"❌ Invalid period. Choose from: `{' '.join(valid_periods)}`", parse_mode=ParseMode.MARKDOWN)
        return

    msg = await update.message.reply_text(f"⏳ Loading {period} history for `{symbol}`…", parse_mode=ParseMode.MARKDOWN)
    hist = svc.get_historical(symbol, period)
    if not hist:
        await msg.edit_text(f"❌ Could not load history for `{symbol}`.", parse_mode=ParseMode.MARKDOWN)
        return

    closes = hist["closes"]
    hi = max(closes)
    lo = min(closes)
    sign = "+" if hist["period_change"] >= 0 else ""
    emoji = svc.trend_emoji(hist["period_change"])

    text = (
        f"{emoji} *{symbol}* — {period} Performance\n\n"
        f"📅 From: `{hist['dates'][0]}`  →  `{hist['dates'][-1]}`\n\n"
        f"🟢 Start: `${closes[0]:,.2f}`\n"
        f"🔵 End:   `${closes[-1]:,.2f}`\n"
        f"🔺 High:  `${hi:,.2f}`\n"
        f"🔻 Low:   `${lo:,.2f}`\n\n"
        f"📊 Period Change: `{sign}${hist['period_change']:,.2f} ({sign}{hist['period_change_pct']:.2f}%)`\n\n"
    )

    # Mini ASCII sparkline (20 chars)
    if len(closes) >= 2:
        mn, mx = min(closes), max(closes)
        rng = mx - mn or 1
        bars = "▁▂▃▄▅▆▇█"
        spark = "".join(bars[min(int((c - mn) / rng * 7), 7)] for c in closes[::max(1, len(closes)//20)])
        text += f"📉 Sparkline:\n`{spark}`"

    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/watch SYMBOL`", parse_mode=ParseMode.MARKDOWN)
        return
    symbol = context.args[0].upper()
    user_id = update.effective_user.id

    # Validate symbol
    price = svc.get_current_price(symbol)
    if price is None:
        await update.message.reply_text(f"❌ `{symbol}` not found. Please check the ticker.", parse_mode=ParseMode.MARKDOWN)
        return

    added = db.add_to_watchlist(user_id, symbol)
    if added:
        await update.message.reply_text(f"✅ *{symbol}* added to your watchlist!\nCurrent price: `${price:,.2f}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"ℹ️ *{symbol}* is already in your watchlist.", parse_mode=ParseMode.MARKDOWN)


async def cmd_unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/unwatch SYMBOL`", parse_mode=ParseMode.MARKDOWN)
        return
    symbol = context.args[0].upper()
    removed = db.remove_from_watchlist(update.effective_user.id, symbol)
    if removed:
        await update.message.reply_text(f"🗑 *{symbol}* removed from your watchlist.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"❌ *{symbol}* was not in your watchlist.", parse_mode=ParseMode.MARKDOWN)


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    symbols = db.get_watchlist(user_id)
    if not symbols:
        await update.message.reply_text(
            "📋 Your watchlist is empty.\nUse `/watch SYMBOL` to add stocks.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    msg = await update.message.reply_text("⏳ Loading watchlist prices…")
    lines = ["👁 *Your Watchlist*\n"]

    for sym in symbols:
        info = svc.get_stock_info(sym)
        if info:
            sign = "+" if info["change"] >= 0 else ""
            emoji = svc.trend_emoji(info["change"])
            lines.append(
                f"{emoji} *{sym}* — `${info['price']:,.2f}`  "
                f"`{sign}{info['change_pct']:.2f}%`"
            )
        else:
            lines.append(f"⚠️ *{sym}* — data unavailable")

    lines.append("\n_Tap a symbol to get details: /price SYMBOL_")
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: `/alert SYMBOL above|below PRICE`\n"
            "Examples:\n"
            "`/alert AAPL above 200`\n"
            "`/alert TSLA below 150`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    symbol = context.args[0].upper()
    direction = context.args[1].lower()
    if direction not in ("above", "below"):
        await update.message.reply_text("❌ Direction must be `above` or `below`.", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        target = float(context.args[2])
    except ValueError:
        await update.message.reply_text("❌ Price must be a number.", parse_mode=ParseMode.MARKDOWN)
        return

    # Validate ticker
    price = svc.get_current_price(symbol)
    if price is None:
        await update.message.reply_text(f"❌ `{symbol}` not found.", parse_mode=ParseMode.MARKDOWN)
        return

    alert_id = db.add_alert(update.effective_user.id, symbol, target, direction)
    dir_word = "rises above" if direction == "above" else "drops below"
    await update.message.reply_text(
        f"🔔 Alert #{alert_id} set!\n\n"
        f"I'll notify you when *{symbol}* {dir_word} `${target:,.2f}`\n"
        f"Current price: `${price:,.2f}`",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    alerts = db.get_user_alerts(update.effective_user.id)
    if not alerts:
        await update.message.reply_text(
            "🔔 No active alerts.\nUse `/alert SYMBOL above|below PRICE` to set one.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    lines = ["🔔 *Your Active Alerts*\n"]
    for a in alerts:
        dir_emoji = "⬆️" if a["direction"] == "above" else "⬇️"
        lines.append(
            f"`#{a['id']}` {dir_emoji} *{a['symbol']}* {a['direction']} `${a['target_price']:,.2f}`"
        )
    lines.append("\nUse `/delalert ID` to remove an alert.")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_delalert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/delalert ID`\nGet IDs from `/alerts`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        alert_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID must be a number.", parse_mode=ParseMode.MARKDOWN)
        return

    deleted = db.delete_alert(alert_id, update.effective_user.id)
    if deleted:
        await update.message.reply_text(f"🗑 Alert #{alert_id} deleted.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"❌ Alert #{alert_id} not found.", parse_mode=ParseMode.MARKDOWN)


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: `/buy SYMBOL SHARES BUY_PRICE`\n"
            "Example: `/buy AAPL 10 178.50`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    symbol = context.args[0].upper()
    try:
        shares = float(context.args[1])
        buy_price = float(context.args[2])
    except ValueError:
        await update.message.reply_text("❌ Shares and price must be numbers.", parse_mode=ParseMode.MARKDOWN)
        return

    price = svc.get_current_price(symbol)
    if price is None:
        await update.message.reply_text(f"❌ `{symbol}` not found.", parse_mode=ParseMode.MARKDOWN)
        return

    db.add_to_portfolio(update.effective_user.id, symbol, shares, buy_price)
    invested = shares * buy_price
    current_val = shares * price
    pl = current_val - invested
    sign = "+" if pl >= 0 else ""
    await update.message.reply_text(
        f"💼 Added to portfolio!\n\n"
        f"📌 *{symbol}* × {shares} shares @ `${buy_price:,.2f}`\n"
        f"💰 Invested: `${invested:,.2f}`\n"
        f"📊 Current:  `${current_val:,.2f}`\n"
        f"{'📈' if pl>=0 else '📉'} P&L: `{sign}${pl:,.2f}`",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/sell SYMBOL`", parse_mode=ParseMode.MARKDOWN)
        return
    symbol = context.args[0].upper()
    removed = db.remove_from_portfolio(update.effective_user.id, symbol)
    if removed:
        await update.message.reply_text(f"💼 *{symbol}* removed from your portfolio.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"❌ *{symbol}* not found in your portfolio.", parse_mode=ParseMode.MARKDOWN)


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    holdings = db.get_portfolio(user_id)
    if not holdings:
        await update.message.reply_text(
            "💼 Your portfolio is empty.\nUse `/buy SYMBOL SHARES PRICE` to add stocks.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    msg = await update.message.reply_text("⏳ Loading portfolio…")
    total_invested = 0
    total_current = 0
    lines = ["💼 *Your Portfolio*\n"]

    for h in holdings:
        price = svc.get_current_price(h["symbol"])
        if price is None:
            lines.append(f"⚠️ *{h['symbol']}* — data unavailable")
            continue

        invested = h["shares"] * h["buy_price"]
        current = h["shares"] * price
        pl = current - invested
        pl_pct = (pl / invested * 100) if invested else 0
        sign = "+" if pl >= 0 else ""
        emoji = "📈" if pl >= 0 else "📉"

        total_invested += invested
        total_current += current

        lines.append(
            f"{emoji} *{h['symbol']}* × {h['shares']} shares\n"
            f"   Buy: `${h['buy_price']:,.2f}` → Now: `${price:,.2f}`\n"
            f"   P&L: `{sign}${pl:,.2f} ({sign}{pl_pct:.1f}%)`"
        )

    total_pl = total_current - total_invested
    total_pct = (total_pl / total_invested * 100) if total_invested else 0
    sign = "+" if total_pl >= 0 else ""
    emoji = "📈" if total_pl >= 0 else "📉"

    lines.append(f"\n{'─'*30}")
    lines.append(f"💰 Total Invested: `${total_invested:,.2f}`")
    lines.append(f"💹 Current Value:  `${total_current:,.2f}`")
    lines.append(f"{emoji} Total P&L:      `{sign}${total_pl:,.2f} ({sign}{total_pct:.1f}%)`")

    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    POPULAR = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "NFLX"]
    msg = await update.message.reply_text("⏳ Loading popular stocks…")
    lines = ["📊 *Popular Stocks Overview*\n"]

    for sym in POPULAR:
        info = svc.get_stock_info(sym)
        if info:
            sign = "+" if info["change"] >= 0 else ""
            emoji = svc.trend_emoji(info["change"])
            lines.append(
                f"{emoji} *{sym}* `${info['price']:,.2f}`  "
                f"`{sign}{info['change_pct']:.2f}%`"
            )

    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_compare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/compare SYMBOL1 SYMBOL2`\nExample: `/compare AAPL MSFT`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    s1, s2 = context.args[0].upper(), context.args[1].upper()
    msg = await update.message.reply_text(f"⏳ Comparing *{s1}* vs *{s2}*…", parse_mode=ParseMode.MARKDOWN)

    i1 = svc.get_stock_info(s1)
    i2 = svc.get_stock_info(s2)

    if not i1 or not i2:
        missing = s1 if not i1 else s2
        await msg.edit_text(f"❌ Could not find `{missing}`.", parse_mode=ParseMode.MARKDOWN)
        return

    def row(label, v1, v2):
        return f"*{label}*\n  {s1}: `{v1}`\n  {s2}: `{v2}`"

    lines = [
        f"⚖️ *{s1}* vs *{s2}*\n",
        row("Price", f"${i1['price']:,.2f}", f"${i2['price']:,.2f}"),
        row("Day Change", f"{'+' if i1['change']>=0 else ''}{i1['change_pct']:.2f}%",
                          f"{'+' if i2['change']>=0 else ''}{i2['change_pct']:.2f}%"),
        row("Mkt Cap", svc.format_large_number(i1["market_cap"]), svc.format_large_number(i2["market_cap"])),
        row("P/E Ratio", f"{i1['pe_ratio']:.2f}" if i1["pe_ratio"] else "N/A",
                         f"{i2['pe_ratio']:.2f}" if i2["pe_ratio"] else "N/A"),
        row("52W High", f"${i1['52w_high']:,.2f}" if i1["52w_high"] else "N/A",
                        f"${i2['52w_high']:,.2f}" if i2["52w_high"] else "N/A"),
        row("52W Low",  f"${i1['52w_low']:,.2f}" if i1["52w_low"] else "N/A",
                        f"${i2['52w_low']:,.2f}" if i2["52w_low"] else "N/A"),
        row("Sector", i1["sector"] or "N/A", i2["sector"] or "N/A"),
    ]

    await msg.edit_text("\n\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── Callback Query Handler (Inline Buttons) ────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data.startswith("watch:"):
        symbol = data.split(":")[1]
        price = svc.get_current_price(symbol)
        added = db.add_to_watchlist(user_id, symbol)
        if added:
            await query.message.reply_text(
                f"✅ *{symbol}* added to watchlist!  `${price:,.2f}`",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.message.reply_text(f"ℹ️ *{symbol}* already in watchlist.", parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("hist:"):
        _, symbol, period = data.split(":")
        hist = svc.get_historical(symbol, period)
        if not hist:
            await query.message.reply_text(f"❌ Could not load history for `{symbol}`.", parse_mode=ParseMode.MARKDOWN)
            return

        closes = hist["closes"]
        mn, mx = min(closes), max(closes)
        rng = mx - mn or 1
        bars = "▁▂▃▄▅▆▇█"
        spark = "".join(bars[min(int((c - mn) / rng * 7), 7)] for c in closes[::max(1, len(closes)//20)])
        sign = "+" if hist["period_change"] >= 0 else ""
        emoji = svc.trend_emoji(hist["period_change"])

        text = (
            f"{emoji} *{symbol}* — {period} History\n\n"
            f"Start: `${closes[0]:,.2f}` → End: `${closes[-1]:,.2f}`\n"
            f"Change: `{sign}${hist['period_change']:,.2f} ({sign}{hist['period_change_pct']:.2f}%)`\n\n"
            f"`{spark}`"
        )
        await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("alert_prompt:"):
        symbol = data.split(":")[1]
        price = svc.get_current_price(symbol)
        await query.message.reply_text(
            f"🔔 *Set an alert for {symbol}* (current: `${price:,.2f}`)\n\n"
            f"Use:\n`/alert {symbol} above 200`\n`/alert {symbol} below 150`",
            parse_mode=ParseMode.MARKDOWN
        )


# ── Alert Checker Job ──────────────────────────────────────────────────────────

async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    """Background job to check price alerts and notify users."""
    alerts = db.get_all_active_alerts()
    if not alerts:
        return

    # Group by symbol to minimize API calls
    by_symbol = {}
    for a in alerts:
        by_symbol.setdefault(a["symbol"], []).append(a)

    for symbol, sym_alerts in by_symbol.items():
        price = svc.get_current_price(symbol)
        if price is None:
            continue

        for alert in sym_alerts:
            triggered = (
                alert["direction"] == "above" and price >= alert["target_price"]
            ) or (
                alert["direction"] == "below" and price <= alert["target_price"]
            )

            if triggered:
                dir_word = "risen above" if alert["direction"] == "above" else "dropped below"
                emoji = "🚀" if alert["direction"] == "above" else "⚠️"
                text = (
                    f"{emoji} *Price Alert Triggered!*\n\n"
                    f"*{symbol}* has {dir_word} your target of `${alert['target_price']:,.2f}`\n"
                    f"Current price: `${price:,.2f}`"
                )
                try:
                    await context.bot.send_message(
                        chat_id=alert["user_id"],
                        text=text,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    db.deactivate_alert(alert["id"])
                except Exception as e:
                    logger.error(f"Failed to send alert {alert['id']}: {e}")


# ── Error Handler ──────────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("⚠️ Something went wrong. Please try again.")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    db.init_db()
    logger.info("Database initialized.")

    app = Application.builder().token(BOT_TOKEN).build()

    # Register commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("info", cmd_info))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("alert", cmd_alert))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("delalert", cmd_delalert))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("sell", cmd_sell))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("compare", cmd_compare))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Error handler
    app.add_error_handler(error_handler)

    # Background alert checker job (every 60 seconds)
    app.job_queue.run_repeating(check_alerts, interval=ALERT_CHECK_INTERVAL, first=10)

    logger.info("🚀 StockBot is running...")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
