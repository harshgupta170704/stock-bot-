"""
Stock data service powered by Angel One SmartAPI.
Real-time NSE/BSE Indian stock data — completely free.

Symbol formats accepted:
  RELIANCE, TCS, INFY, HDFCBANK, SBIN, NIFTY, SENSEX
  (Just the plain NSE symbol — no suffix needed)
"""

import os
import time
import requests
import pyotp
import pandas as pd
from io import StringIO
from datetime import datetime, timedelta
from typing import Optional
from SmartApi import SmartConnect

# ── Credentials (set as Railway env variables) ─────────────────────────────────
ANGEL_API_KEY     = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_ID   = os.getenv("ANGEL_CLIENT_ID", "")
ANGEL_PASSWORD    = os.getenv("ANGEL_PASSWORD", "")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")

# ── Session cache (re-login once per day) ──────────────────────────────────────
_session = {
    "obj":          None,
    "refresh_token": None,
    "logged_in_at": None,
}

# ── Scrip master cache (symbol → token mapping) ────────────────────────────────
_scrip_df = None
_scrip_loaded_at = None
SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"


def _get_scrip_df() -> pd.DataFrame:
    """Load and cache the NSE scrip master (refreshed every 6 hours)."""
    global _scrip_df, _scrip_loaded_at
    now = time.time()
    if _scrip_df is not None and _scrip_loaded_at and (now - _scrip_loaded_at) < 21600:
        return _scrip_df

    try:
        data = requests.get(SCRIP_MASTER_URL, timeout=15).json()
        df = pd.DataFrame(data)
        df = df[df["exch_seg"] == "NSE"]       # NSE only
        df["symbol_clean"] = df["symbol"].str.replace("-EQ", "", regex=False).str.upper()
        _scrip_df = df
        _scrip_loaded_at = now
        return _scrip_df
    except Exception as e:
        print(f"[Angel] Scrip master load failed: {e}")
        return pd.DataFrame()


def _get_token(symbol: str) -> Optional[str]:
    """Get numeric token for a symbol (needed for all Angel One API calls)."""
    symbol = symbol.upper().replace("-EQ", "")
    df = _get_scrip_df()
    if df.empty:
        return None

    # Try exact match first
    match = df[df["symbol_clean"] == symbol]
    if match.empty:
        # Try partial match
        match = df[df["symbol_clean"].str.startswith(symbol)]
    if match.empty:
        return None

    return str(match.iloc[0]["token"])


def _get_session() -> Optional[SmartConnect]:
    """Return a valid SmartConnect session, logging in if needed."""
    global _session
    now = time.time()

    # Re-login every 12 hours
    if (
        _session["obj"] is not None
        and _session["logged_in_at"]
        and (now - _session["logged_in_at"]) < 43200
    ):
        return _session["obj"]

    try:
        obj = SmartConnect(api_key=ANGEL_API_KEY)
        totp = pyotp.TOTP(ANGEL_TOTP_SECRET).now()
        data = obj.generateSession(ANGEL_CLIENT_ID, ANGEL_PASSWORD, totp)

        if not data or data.get("status") is False:
            print(f"[Angel] Login failed: {data}")
            return None

        _session["obj"]           = obj
        _session["refresh_token"] = data["data"]["refreshToken"]
        _session["logged_in_at"]  = now
        print("[Angel] Login successful.")
        return obj

    except Exception as e:
        print(f"[Angel] Session error: {e}")
        return None


def get_stock_info(symbol: str) -> Optional[dict]:
    """
    Fetch a full price card for a symbol.
    Uses getLTP (1 call) for price + scrip master for metadata.
    """
    symbol = symbol.upper().replace("-EQ", "")
    obj = _get_session()
    if not obj:
        return None

    token = _get_token(symbol)
    if not token:
        return None

    try:
        resp = obj.ltpData("NSE", f"{symbol}-EQ", token)
        if not resp or resp.get("status") is False:
            return None

        d = resp["data"]
        price     = float(d.get("ltp", 0))
        close     = float(d.get("close", price))
        change    = price - close
        change_pct = (change / close * 100) if close else 0

        # Get OHLC from full quote
        quote_resp = obj.getQuote("NSE", f"{symbol}-EQ", token)
        ohlc = {}
        if quote_resp and quote_resp.get("status"):
            qd = quote_resp.get("data", {})
            ohlc = {
                "open":   float(qd.get("open", 0)) or None,
                "high":   float(qd.get("high", 0)) or None,
                "low":    float(qd.get("low", 0)) or None,
                "volume": float(qd.get("tradedVolume", 0)) or None,
            }

        # Get name from scrip master
        df = _get_scrip_df()
        name = symbol
        if not df.empty:
            row = df[df["symbol_clean"] == symbol]
            if not row.empty:
                name = row.iloc[0].get("name", symbol)

        return {
            "symbol":     symbol,
            "name":       name,
            "price":      price,
            "prev_close": close,
            "change":     change,
            "change_pct": change_pct,
            "open":       ohlc.get("open"),
            "high":       ohlc.get("high"),
            "low":        ohlc.get("low"),
            "volume":     ohlc.get("volume"),
            "avg_volume": None,
            "52w_high":   None,
            "52w_low":    None,
            "pe_ratio":   None,
            "market_cap": None,
            "market_cap_raw": None,
            "dividend_yield": None,
            "currency":   "INR",
            "exchange":   "NSE",
            "sector":     "",
        }
    except Exception as e:
        print(f"[Angel] get_stock_info error for {symbol}: {e}")
        return None


def get_current_price(symbol: str) -> Optional[float]:
    """Quick price fetch using LTP endpoint."""
    symbol = symbol.upper().replace("-EQ", "")
    obj = _get_session()
    if not obj:
        return None

    token = _get_token(symbol)
    if not token:
        return None

    try:
        resp = obj.ltpData("NSE", f"{symbol}-EQ", token)
        if resp and resp.get("status"):
            return float(resp["data"]["ltp"])
        return None
    except Exception as e:
        print(f"[Angel] Price error for {symbol}: {e}")
        return None


def get_historical(symbol: str, period: str = "1mo") -> Optional[dict]:
    """Fetch historical OHLCV data using getCandleData."""
    symbol = symbol.upper().replace("-EQ", "")
    obj = _get_session()
    if not obj:
        return None

    token = _get_token(symbol)
    if not token:
        return None

    period_map = {
        "1d":  (timedelta(days=1),   "FIVE_MINUTE"),
        "5d":  (timedelta(days=5),   "ONE_HOUR"),
        "1mo": (timedelta(days=30),  "ONE_DAY"),
        "3mo": (timedelta(days=90),  "ONE_DAY"),
        "6mo": (timedelta(days=180), "ONE_DAY"),
        "1y":  (timedelta(days=365), "ONE_DAY"),
        "2y":  (timedelta(days=730), "ONE_DAY"),
    }
    delta, interval = period_map.get(period, (timedelta(days=30), "ONE_DAY"))

    now      = datetime.now()
    from_dt  = now - delta
    from_str = from_dt.strftime("%Y-%m-%d %H:%M")
    to_str   = now.strftime("%Y-%m-%d %H:%M")

    try:
        params = {
            "exchange":    "NSE",
            "symboltoken": token,
            "interval":    interval,
            "fromdate":    from_str,
            "todate":      to_str,
        }
        resp = obj.getCandleData(params)
        if not resp or resp.get("status") is False or not resp.get("data"):
            return None

        candles = resp["data"]
        closes  = [float(c[4]) for c in candles]
        dates   = [c[0][:10] for c in candles]

        if len(closes) < 2:
            return None

        start_price      = closes[0]
        end_price        = closes[-1]
        period_change    = end_price - start_price
        period_change_pct = (period_change / start_price * 100) if start_price else 0

        return {
            "symbol":            symbol,
            "dates":             dates,
            "closes":            closes,
            "period":            period,
            "period_change":     period_change,
            "period_change_pct": period_change_pct,
        }
    except Exception as e:
        print(f"[Angel] Historical error for {symbol}: {e}")
        return None


# ── Formatters ─────────────────────────────────────────────────────────────────

def format_large_number(n) -> str:
    if n is None:
        return "N/A"
    n = float(n)
    if n >= 1e12: return f"₹{n/1e12:.2f}T"
    if n >= 1e9:  return f"₹{n/1e9:.2f}B"
    if n >= 1e6:  return f"₹{n/1e6:.2f}M"
    return f"₹{n:,.0f}"

def format_market_cap(info: dict) -> str:
    return format_large_number(info.get("market_cap_raw"))

def format_volume(n) -> str:
    if n is None: return "N/A"
    n = int(n)
    if n >= 1_000_000_000: return f"{n/1e9:.2f}B"
    if n >= 1_000_000:     return f"{n/1e6:.2f}M"
    if n >= 1_000:         return f"{n/1e3:.1f}K"
    return str(n)

def trend_emoji(change: float) -> str:
    return "📈" if change > 0 else ("📉" if change < 0 else "➡️")

def arrow(change: float) -> str:
    return "▲" if change >= 0 else "▼"
