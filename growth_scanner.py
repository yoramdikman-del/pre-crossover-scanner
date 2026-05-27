# ============================================================
# MACD Momentum Scanner v2.0
# אסטרטגיית הבן — ATR + EMA20 + Volume Direction
#
# שינויים v2:
# ① ATR > 3% — תנודתיות מינימלית
# ② EMA20 — ממוצע נע אקספוננציאלי
# ③ Volume Direction — קונים או מוכרים
# ④ עמודת ATR% בפלט
# ⑤ שעון שליחה: 08:00 ET = 15:00 ישראל (קיץ)
#
# פלט: מייל HTML + Google Sheets
# ============================================================

import yfinance as yf
import pandas as pd
import numpy as np
import smtplib
import os
import json
import time
import datetime as dt
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from concurrent.futures import ThreadPoolExecutor, as_completed

GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_PASSWORD = os.environ["GMAIL_PASSWORD"]
EMAIL_TO       = os.environ["EMAIL_TO"]
SHEET_ID       = "12606ZN0UVV1y2aGCAULbAWRs_aszOvd88M2FURiyv_k"

# ============================================================
# פרמטרים
# ============================================================
MIN_PRICE          = 10.0
MIN_MARKET_CAP     = 1_000_000_000
MIN_AVG_VOLUME     = 300_000
MIN_DAILY_TURNOVER = 3_000_000

# MACD
MACD_FAST          = 12
MACD_SLOW          = 26
MACD_SIGNAL        = 9
MACD_CROSS_LOOKBACK = 3

# SMA / EMA
SMA150_PERIOD      = 150
SMA50_PERIOD       = 50
EMA20_PERIOD       = 20
SMA150_SLOPE_DAYS  = 10

# RSI
RSI_PERIOD         = 14
RSI_MIN            = 45
RSI_TREND_DAYS     = 5

# RVOL
RVOL_MIN           = 1.0
RVOL_PERIOD        = 20

# ← חדש v2: ATR
ATR_PERIOD         = 14
ATR_MIN_PCT        = 3.0    # % תנודתיות מינימלית

MAX_WORKERS        = 10

# ============================================================
# יוניברס
# ============================================================
def get_universe():
    tickers = []
    ua = {"User-Agent": "Mozilla/5.0"}

    try:
        t = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            storage_options=ua)[0]["Symbol"]\
            .str.replace(".", "-", regex=False).tolist()
        tickers += t
        print(f"  ✓ S&P 500: {len(t)}")
    except Exception as e:
        print(f"  ⚠ S&P 500: {e}")

    try:
        df  = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
            storage_options=ua)[0]
        col = next((c for c in df.columns
                    if "tick" in c.lower() or "symbol" in c.lower()),
                   df.columns[0])
        t   = [x for x in df[col].str.replace(".", "-", regex=False)
               .dropna().tolist()
               if isinstance(x, str) and 1 <= len(x) <= 6]
        tickers += t
        print(f"  ✓ S&P 400: {len(t)}")
    except Exception as e:
        print(f"  ⚠ S&P 400: {e}")

    extras = [
        "CHKP","NICE","CYBR","MNDY","WIX","FVRR","GLBE",
        "IBKR","BNY","EXPD","DAL","BKR","AFL","ASTS","RKLB",
        "PLTR","OKTA","ZS","MDB","SNOW","DDOG","NET","CRWD",
        "AFRM","UPST","SOFI","HOOD","DAVE","GTLB","BRZE",
        "DUOL","HIMS","DOCS","TOST","FOUR",
    ]
    tickers += extras
    universe = list(dict.fromkeys(tickers))
    print(f"  ✓ סה\"כ: {len(universe)} מניות")
    return universe

# ============================================================
# אימות Google
# ============================================================
def get_google_token():
    try:
        import google.auth
        import google.auth.transport.requests
        import google.auth.external_account

        creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
        creds = google.auth.external_account.Credentials.from_info(
            creds_json,
            scopes=["https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"]
        )
        request = google.auth.transport.requests.Request()
        creds.refresh(request)
        return creds.token
    except Exception as e:
        print(f"⚠️ Google auth: {e}")
        return None

def sheets_request(method, endpoint, token, data=None):
    import urllib.request
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}{endpoint}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    if data:
        req.data = json.dumps(data).encode("utf-8")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"⚠️ Sheets: {e}")
        return None

def save_to_sheets(results, token, scan_time):
    if not token:
        print("⚠️ אין token")
        return

    timestamp  = scan_time.strftime("%d/%m/%Y %H:%M")
    sheet_name = f"Momentum {scan_time.strftime('%d.%m %H:%M')}"

    sheets_request("POST", ":batchUpdate", token, {
        "requests": [{"addSheet": {"properties": {"title": sheet_name}}}]
    })

    headers = [
        "Ticker","מצב MACD","ציון","תנאים",
        "Cross Days","ATR%","Vol Direction",
        "MACD Line","Histogram","Hist Growing",
        "RSI","RSI Change 5d","RSI Rising",
        "SMA150↑","SMA150 Slope","SMA50>SMA150",
        "מחיר מעל EMA20","מחיר מעל SMA50","מחיר מעל SMA150","מחיר מעל SMA200",
        "RVOL","מחיר","סקטור","Mkt Cap $B","סיגנל"
    ]

    rows = [[f"MACD Momentum Scanner v2 — {timestamp} — {len(results)} מניות"]]
    rows.append([
        f"ATR>{ATR_MIN_PCT}% · MACD Histogram חצה אפס · "
        f"SMA150↑ · RSI>{RSI_MIN}↑ · RVOL>{RVOL_MIN}"
    ])
    rows.append([])

    # מיון לפי מצב: FRESH, VALID, WATCH
    for mode_label in ["🔥 FRESH", "✅ VALID", "👀 WATCH"]:
        mode_results = [r for r in results if r["mode"] == mode_label]
        if not mode_results:
            continue
        rows.append([mode_label] + [""]*(len(headers)-1))
        rows.append(headers)
        for r in mode_results:
            rows.append([
                r["ticker"], r["mode"], r["score"], r["conditions"],
                str(r["cross_days"]),
                f"{r['atr_pct']:.1f}%",
                r["vol_direction"],
                round(r["macd_line"], 3),
                round(r["histogram"], 3),
                "✅" if r["hist_growing"] else "—",
                r["rsi"],
                f"{r['rsi_change']:+.1f}",
                "✅" if r["rsi_rising"] else "—",
                "✅" if r["sma150_rising"] else "❌",
                f"{r['sma150_slope']:+.3f}%",
                "✅" if r["sma50_above_sma150"] else "—",
                "✅" if r["above_ema20"] else "—",
                "✅" if r["above_sma50"] else "—",
                "✅" if r["above_sma150"] else "—",
                "✅" if r["above_sma200"] else "—",
                round(r["rvol"], 2),
                r["price"],
                r["sector"],
                r["mkt_cap_b"],
                r["signal"],
            ])
        rows.append([])

    sheets_request("PUT",
        f"/values/{sheet_name}!A1?valueInputOption=RAW",
        token, {"values": rows})

    print(f"✅ נשמר — {sheet_name}")
    print(f"🔗 https://docs.google.com/spreadsheets/d/{SHEET_ID}")

# ============================================================
# פונקציות חישוב
# ============================================================
def calc_macd(closes, fast=12, slow=26, signal=9):
    ema_fast    = closes.ewm(span=fast,   adjust=False).mean()
    ema_slow    = closes.ewm(span=slow,   adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram

def calc_rsi(series, period=14):
    d = series.diff()
    g = d.clip(lower=0).ewm(com=period-1, min_periods=period).mean()
    l = (-d.clip(upper=0)).ewm(com=period-1, min_periods=period).mean()
    return 100 - (100 / (1 + g / l.replace(0, np.nan)))

def calc_atr(highs, lows, closes, period=14):
    """ATR כ-% מהמחיר הנוכחי"""
    h = highs.copy()
    l = lows.copy()
    c = closes.copy()
    tr = pd.concat([
        h - l,
        (h - c.shift()).abs(),
        (l - c.shift()).abs()
    ], axis=1).max(axis=1)
    atr     = tr.ewm(span=period, adjust=False).mean()
    atr_pct = (atr / c * 100).iloc[-1]
    return round(float(atr_pct), 2)

def calc_volume_direction(closes, volumes, period=5):
    """
    בודק האם הנפח האחרון מגיע עם עליית מחיר (קונים) או ירידה (מוכרים).
    מחזיר: '📈 קונים', '📉 מוכרים', '➡️ ניטרלי'
    """
    price_change = float(closes.iloc[-1]) - float(closes.iloc[-period])
    vol_recent   = float(volumes.iloc[-period:].mean())
    vol_avg      = float(volumes.iloc[-period*3:-period].mean()) if len(volumes) > period*4 else vol_recent

    rvol_recent = vol_recent / vol_avg if vol_avg > 0 else 1

    if price_change > 0 and rvol_recent >= 1.1:
        return "📈 קונים"
    elif price_change < 0 and rvol_recent >= 1.1:
        return "📉 מוכרים"
    else:
        return "➡️ ניטרלי"

def find_histogram_cross(histogram, lookback=3):
    for i in range(1, lookback + 1):
        prev = float(histogram.iloc[-i-1])
        curr = float(histogram.iloc[-i])
        if prev <= 0 and curr > 0:
            return i, round(prev, 4), round(curr, 4)
    return None

def score_momentum(cross_days, rsi_val, rsi_rising, rvol,
                   sma150_rising, macd_now, above_sma50,
                   above_sma150, above_sma200, hist_growing,
                   atr_pct, above_ema20, sma50_above_sma150):
    s = 0
    conditions = 0

    # ① SMA150 עולה
    if sma150_rising:
        s += 18; conditions += 1

    # ② MACD Histogram חצה אפס
    if cross_days is not None:
        s += max(8, 22 - cross_days * 5); conditions += 1

    # ③ RSI עולה ומעל MIN
    if rsi_val >= RSI_MIN and rsi_rising:
        s += 18; conditions += 1
    elif rsi_val >= RSI_MIN:
        s += 10; conditions += 1

    # ④ RVOL
    if rvol >= 1.5:   s += 12; conditions += 1
    elif rvol >= 1.0: s +=  6

    # ⑤ ATR — בונוס על תנודתיות
    if atr_pct >= 5:  s += 10
    elif atr_pct >= 3: s += 6

    # ⑥ מיקום מאמות
    if above_sma150:        s += 5
    if above_sma200:        s += 5
    if above_ema20:         s += 5
    if sma50_above_sma150:  s += 5
    if macd_now > 0:        s += 4
    if hist_growing:        s += 3

    return min(s, 100), conditions

# ============================================================
# ניתוח מניה בודדת
# ============================================================
def analyze(ticker, sector_cache={}):
    try:
        tk   = yf.Ticker(ticker)
        hist = tk.history(period="1y", interval="1d", auto_adjust=True)

        if hist.empty or len(hist) < 60:
            return None, "insufficient_history"

        hist    = hist.dropna(subset=["Close","Open","High","Low"])
        closes  = hist["Close"]
        opens   = hist["Open"]
        highs   = hist["High"]
        lows    = hist["Low"]
        volumes = hist["Volume"]

        price    = float(closes.iloc[-1])
        avg_vol  = float(volumes.iloc[-RVOL_PERIOD-1:-1].mean())
        last_vol = float(volumes.iloc[-1])

        if price   < MIN_PRICE:      return None, "price_low"
        if avg_vol < MIN_AVG_VOLUME: return None, "volume_low"
        if price * avg_vol < MIN_DAILY_TURNOVER:
            return None, "turnover_low"

        # ← חדש v2: ATR
        atr_pct = calc_atr(highs, lows, closes, ATR_PERIOD)
        if atr_pct < ATR_MIN_PCT:
            return None, f"atr_low({atr_pct:.1f}%)"

        # Market Cap
        try:
            mktcap = getattr(yf.Ticker(ticker).fast_info, "market_cap", 0) or 0
        except:
            mktcap = 0
        if mktcap > 0 and mktcap < MIN_MARKET_CAP:
            return None, "mktcap_small"

        # SMA / EMA
        sma150 = closes.rolling(SMA150_PERIOD).mean()
        sma50  = closes.rolling(SMA50_PERIOD).mean()
        ema20  = closes.ewm(span=EMA20_PERIOD, adjust=False).mean()
        sma200 = closes.rolling(200).mean()

        sma150_now = float(sma150.iloc[-1]) if not pd.isna(sma150.iloc[-1]) else None
        sma50_now  = float(sma50.iloc[-1])  if not pd.isna(sma50.iloc[-1])  else None
        ema20_now  = float(ema20.iloc[-1])
        sma200_now = float(sma200.iloc[-1]) if not pd.isna(sma200.iloc[-1]) else 0

        if not sma150_now: return None, "sma150_na"

        # SMA150 slope
        sma150_Nd = float(sma150.iloc[-SMA150_SLOPE_DAYS-1]) \
                    if not pd.isna(sma150.iloc[-SMA150_SLOPE_DAYS-1]) else None
        if not sma150_Nd: return None, "sma150_slope_na"

        sma150_slope = (sma150_now - sma150_Nd) / sma150_Nd * 100
        sma150_rising = sma150_slope > 0

        # מיקומים
        above_sma150      = price > sma150_now
        above_sma50       = price > sma50_now  if sma50_now  else False
        above_ema20       = price > ema20_now
        above_sma200      = price > sma200_now and sma200_now > 0
        sma50_above_sma150= (sma50_now > sma150_now) if sma50_now else False

        # RVOL
        rvol = last_vol / avg_vol if avg_vol > 0 else 0
        if rvol < RVOL_MIN: return None, f"rvol_low({rvol:.1f})"

        # RSI
        rsi_series = calc_rsi(closes, RSI_PERIOD)
        rsi_now    = float(rsi_series.iloc[-1])
        rsi_Nd     = float(rsi_series.iloc[-RSI_TREND_DAYS-1]) \
                     if not pd.isna(rsi_series.iloc[-RSI_TREND_DAYS-1]) else rsi_now
        rsi_rising = rsi_now > rsi_Nd
        rsi_change = round(rsi_now - rsi_Nd, 1)

        # MACD
        macd_line, signal_line, histogram = calc_macd(
            closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)

        cross_result  = find_histogram_cross(histogram, MACD_CROSS_LOOKBACK)
        hist_now      = float(histogram.iloc[-1])
        hist_prev     = float(histogram.iloc[-2])
        hist_positive = hist_now > 0
        hist_growing  = hist_now > hist_prev
        macd_now_val  = float(macd_line.iloc[-1])
        signal_now    = float(signal_line.iloc[-1])
        cross_days    = cross_result[0] if cross_result else None

        # ← חדש v2: Volume Direction
        vol_direction = calc_volume_direction(closes, volumes)

        # סקטור
        if ticker in sector_cache:
            sector = sector_cache[ticker]
        else:
            try:
                sector = tk.info.get("sector", "—") or "—"
                sector_cache[ticker] = sector
            except:
                sector = "—"

        # ציון ומצב
        score, conditions = score_momentum(
            cross_days, rsi_now, rsi_rising, rvol,
            sma150_rising, macd_now_val, above_sma50,
            above_sma150, above_sma200, hist_growing,
            atr_pct, above_ema20, sma50_above_sma150
        )

        # מצב
        if cross_days is not None and cross_days <= 2 and conditions >= 3:
            mode = "🔥 FRESH"
        elif cross_days is not None and cross_days <= 3 and conditions >= 3:
            mode = "✅ VALID"
        elif hist_positive and conditions >= 3:
            mode = "👀 WATCH"
        else:
            return None, f"insufficient({conditions}/4,cross={cross_days})"

        last_candle = "🟢 ירוק" if price > float(opens.iloc[-1]) else "🔴 אדום"

        signal = ("🚀 חזק מאוד" if score >= 80 else
                  "✅ חזק"      if score >= 60 else
                  "📊 בינוני"   if score >= 40 else "🟡 חלש")

        return {
            "ticker":            ticker,
            "mode":              mode,
            "signal":            signal,
            "score":             score,
            "conditions":        f"{conditions}/4",
            "cross_days":        cross_days if cross_days else "—",
            # ← חדש v2
            "atr_pct":           atr_pct,
            "vol_direction":     vol_direction,
            "above_ema20":       above_ema20,
            "sma50_above_sma150":sma50_above_sma150,
            # MACD
            "macd_line":         float(macd_now_val),
            "signal_line":       float(signal_now),
            "histogram":         float(hist_now),
            "hist_growing":      hist_growing,
            # RSI
            "rsi":               round(rsi_now, 1),
            "rsi_rising":        rsi_rising,
            "rsi_change":        rsi_change,
            # SMA
            "sma150_rising":     sma150_rising,
            "sma150_slope":      round(sma150_slope, 3),
            "above_sma50":       above_sma50,
            "above_sma150":      above_sma150,
            "above_sma200":      above_sma200,
            # נפח
            "rvol":              round(rvol, 2),
            # כללי
            "price":             round(price, 2),
            "sector":            sector,
            "mkt_cap_b":         round(mktcap/1e9, 1) if mktcap else "—",
            "last_candle":       last_candle,
        }, None

    except Exception as e:
        return None, f"error:{str(e)[:50]}"

# ============================================================
# HTML למייל
# ============================================================
def build_stock_row(r):
    score = r["score"]
    if "FRESH" in r["mode"]:
        if score >= 75: bg = "#C8E6C9"
        elif score >= 55: bg = "#DCEDC8"
        else: bg = "#F1F8E9"
    elif "VALID" in r["mode"]:
        if score >= 75: bg = "#BBDEFB"
        elif score >= 55: bg = "#DDEEFF"
        else: bg = "#E3F2FD"
    else:
        bg = "#FFF9C4"

    atr_color  = "#1D9E75" if r["atr_pct"] >= 5 else "#BA7517"
    rsi_color  = "#D63B3B" if r["rsi"] > 70 else "#1D9E75" if r["rsi"] >= RSI_MIN else "#888"
    vol_dir    = r["vol_direction"]

    return f"""
    <tr style="border-bottom:1px solid #eee;background:{bg}">
      <td style="padding:8px 10px;font-weight:700;font-size:13px;">{r['ticker']}</td>
      <td style="padding:8px 10px;font-size:12px;">{r['mode']}</td>
      <td style="padding:8px 10px;font-size:13px;font-weight:700;
                 color:{atr_color};">{r['atr_pct']:.1f}%</td>
      <td style="padding:8px 10px;font-size:12px;">{vol_dir}</td>
      <td style="padding:8px 10px;font-size:12px;">
        {'✅' if r['sma150_rising'] else '❌'}</td>
      <td style="padding:8px 10px;font-size:12px;">
        {'✅' if r['sma50_above_sma150'] else '—'}</td>
      <td style="padding:8px 10px;font-size:12px;">
        {'✅' if r['above_ema20'] else '—'}</td>
      <td style="padding:8px 10px;font-size:12px;">
        {'✅' if r['above_sma50'] else '—'}</td>
      <td style="padding:8px 10px;font-size:12px;color:{rsi_color};
                 font-weight:600;">{r['rsi']}</td>
      <td style="padding:8px 10px;font-size:12px;">
        {r['rsi_change']:+.1f}</td>
      <td style="padding:8px 10px;font-size:12px;">{r['rvol']:.1f}x</td>
      <td style="padding:8px 10px;font-size:13px;">${r['price']}</td>
      <td style="padding:8px 10px;font-size:11px;color:#777;">
        {r['sector'][:14]}</td>
      <td style="padding:8px 10px;font-size:12px;font-weight:700;">
        {r['score']}</td>
      <td style="padding:8px 10px;font-size:12px;">{r['signal']}</td>
    </tr>"""

def build_section(title, emoji, section_results):
    if not section_results:
        return ""
    rows_html = "".join(build_stock_row(r) for r in section_results)
    return f"""
    <div style="margin-bottom:24px;">
      <div style="font-size:16px;font-weight:700;color:#1F3864;
                  margin-bottom:10px;padding-bottom:6px;
                  border-bottom:2px solid #2E75B6;">
        {emoji} {title} ({len(section_results)})
      </div>
      <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;">
        <thead>
          <tr style="background:#1F3864;color:white;">
            <th style="padding:7px 10px;text-align:right;font-size:10px;">Ticker</th>
            <th style="padding:7px 10px;text-align:right;font-size:10px;">מצב</th>
            <th style="padding:7px 10px;text-align:right;font-size:10px;">ATR%</th>
            <th style="padding:7px 10px;text-align:right;font-size:10px;">נפח</th>
            <th style="padding:7px 10px;text-align:center;font-size:10px;">SMA150↑</th>
            <th style="padding:7px 10px;text-align:center;font-size:10px;">SMA50&gt;SMA150</th>
            <th style="padding:7px 10px;text-align:center;font-size:10px;">מעל EMA20</th>
            <th style="padding:7px 10px;text-align:center;font-size:10px;">מעל SMA50</th>
            <th style="padding:7px 10px;text-align:right;font-size:10px;">RSI</th>
            <th style="padding:7px 10px;text-align:right;font-size:10px;">ΔRSI</th>
            <th style="padding:7px 10px;text-align:right;font-size:10px;">RVOL</th>
            <th style="padding:7px 10px;text-align:right;font-size:10px;">מחיר</th>
            <th style="padding:7px 10px;text-align:right;font-size:10px;">סקטור</th>
            <th style="padding:7px 10px;text-align:right;font-size:10px;">ציון</th>
            <th style="padding:7px 10px;text-align:right;font-size:10px;">סיגנל</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      </div>
    </div>"""

def build_email_html(results, scan_time, total_scanned):
    today = scan_time.strftime("%d/%m/%Y")
    hour  = scan_time.strftime("%H:%M")
    sheets_link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"

    fresh   = [r for r in results if "FRESH" in r["mode"]]
    valid   = [r for r in results if "VALID" in r["mode"]]
    watch   = [r for r in results if "WATCH" in r["mode"]]

    # תמצית קונים
    buyers  = [r for r in results if "קונים" in r["vol_direction"]]
    high_atr = [r for r in results if r["atr_pct"] >= 5]

    summary_items = []
    if buyers:
        t = ", ".join(r["ticker"] for r in buyers[:5])
        summary_items.append(
            f"<li>📈 <strong>{len(buyers)} מניות</strong> עם נפח קונים: {t}</li>")
    if high_atr:
        t = ", ".join(r["ticker"] for r in high_atr[:5])
        summary_items.append(
            f"<li>⚡ <strong>{len(high_atr)} מניות</strong> ATR &gt;5%: {t}</li>")

    summary_html = ""
    if summary_items:
        summary_html = f"""
        <div style="margin-bottom:20px;padding:14px 16px;background:#E8F4FD;
                    border-radius:8px;font-size:13px;color:#1F3864;direction:rtl;">
          <strong>📋 תמצית:</strong>
          <ul style="margin:8px 0 0 0;padding-right:18px;">
            {"".join(summary_items)}
          </ul>
        </div>"""

    body = ""
    if not results:
        body = """
        <div style="text-align:center;padding:40px;color:#888;">
          <div style="font-size:48px;">🔍</div>
          <div style="font-size:18px;margin-top:12px;">אין מניות במומנטום כרגע</div>
        </div>"""
    else:
        body = (summary_html +
                build_section("FRESH — חציה טרייה", "🔥", fresh) +
                build_section("VALID — אושר", "✅", valid) +
                build_section("WATCH — ממתין", "👀", watch))

        body += f"""
        <div style="margin-top:16px;padding:12px;background:#f8f9fa;
                    border-radius:8px;font-size:12px;color:#666;">
          <strong>מקרא:</strong>
          ATR% = תנודתיות יומית ממוצעת ·
          📈 קונים = נפח עולה עם מחיר עולה ·
          📉 מוכרים = נפח עולה עם מחיר יורד ·
          ΔRSI = שינוי RSI ב-5 ימים<br>
          <strong>פילטרים v2:</strong>
          ATR &gt;{ATR_MIN_PCT}% ·
          MACD Histogram חצה אפס (1-3 ימים) ·
          SMA150↑ · RSI &gt;{RSI_MIN}↑ · RVOL &gt;{RVOL_MIN}
        </div>"""

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:20px;">
<div style="max-width:1100px;margin:0 auto;background:white;border-radius:12px;
            overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">

  <div style="background:linear-gradient(135deg,#1F3864,#2E75B6);
              padding:24px 28px;color:white;direction:rtl;text-align:right;">
    <div style="font-size:24px;font-weight:bold;">
      📊 MACD Momentum Scanner
      <span style="font-size:14px;opacity:0.8;">v2</span>
    </div>
    <div style="font-size:14px;margin-top:6px;opacity:0.85;">
      {today} · {hour} ET · נסרקו <strong>{total_scanned}</strong> ·
      🔥{len(fresh)} FRESH · ✅{len(valid)} VALID · 👀{len(watch)} WATCH
    </div>
    <div style="font-size:12px;margin-top:4px;opacity:0.7;">
      ATR &gt;{ATR_MIN_PCT}% · MACD חצה אפס · SMA150↑ · EMA20 · נפח קונים/מוכרים
    </div>
  </div>

  <div style="padding:24px 20px;direction:rtl;text-align:right;">
    <div style="margin-bottom:16px;padding:10px 14px;background:#E1F5EE;
                border-radius:8px;font-size:13px;color:#085041;">
      📊 <strong>Google Sheets:</strong>
      <a href="{sheets_link}" style="color:#085041;font-weight:600;">{sheets_link}</a>
    </div>
    {body}
  </div>

  <div style="background:#f8f9fa;padding:14px 20px;font-size:11px;color:#999;
              direction:rtl;text-align:right;border-top:1px solid #eee;">
    נשלח אוטומטית ע"י GitHub Actions · זה אינו ייעוץ השקעות
  </div>
</div>
</body>
</html>"""

# ============================================================
# MAIN
# ============================================================
scan_time = datetime.now()
print(f"\n{'='*60}")
print(f"  MACD MOMENTUM SCANNER v2.0")
print(f"  ATR>{ATR_MIN_PCT}% · MACD חצה אפס · SMA150↑ · EMA20")
print(f"  {scan_time.strftime('%d/%m/%Y %H:%M')}")
print(f"{'='*60}")

print("\n[1/3] טוען יוניברס...")
TICKERS = get_universe()

print(f"\n[2/3] סורק {len(TICKERS)} מניות...")
results  = []
rejected = {}
total    = len(TICKERS)

sector_cache = {}
batches = [TICKERS[i:i+50] for i in range(0, total, 50)]

for batch_num, batch in enumerate(batches, 1):
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(analyze, t, sector_cache): t for t in batch}
        for future in as_completed(futures):
            result, reason = future.result()
            if result:
                results.append(result)
                print(f"  ✅ {result['ticker']:<7} "
                      f"{result['mode']:<12} "
                      f"ATR:{result['atr_pct']:.1f}% "
                      f"{result['vol_direction']} "
                      f"RSI:{result['rsi']:.0f} "
                      f"Score:{result['score']}")
            else:
                rejected[reason] = rejected.get(reason, 0) + 1
    if batch_num < len(batches):
        time.sleep(1.5)

# מיון: FRESH ראשון, אחר כך score
mode_order = {"🔥 FRESH": 0, "✅ VALID": 1, "👀 WATCH": 2}
results.sort(key=lambda x: (mode_order.get(x["mode"], 3), -x["score"]))

fresh = [r for r in results if "FRESH" in r["mode"]]
valid = [r for r in results if "VALID" in r["mode"]]
watch = [r for r in results if "WATCH" in r["mode"]]

print(f"\n{'='*60}")
print(f"  🔥 FRESH: {len(fresh)}  ✅ VALID: {len(valid)}  👀 WATCH: {len(watch)}")
print(f"  סיבות פסילה (Top 8):")
for r, n in sorted(rejected.items(), key=lambda x: -x[1])[:8]:
    print(f"    {r:<50} {n:>5} ({n/total*100:.1f}%)")

print("\n[3/3] שומר ושולח...")
token = get_google_token()
save_to_sheets(results, token, scan_time)

html_body = build_email_html(results, scan_time, total)
total_active = len(results)
subject = (
    f"📊 MACD Momentum v2 — {scan_time.strftime('%d/%m/%Y')} — "
    f"🔥{len(fresh)} 📈{len(valid)} 👀{len(watch)}"
    if total_active else
    f"📊 MACD Momentum v2 — {scan_time.strftime('%d/%m/%Y')} — אין מומנטום"
)

msg = MIMEMultipart("alternative")
msg["Subject"] = subject
msg["From"]    = GMAIL_USER
msg["To"]      = EMAIL_TO
msg.attach(MIMEText(html_body, "html", "utf-8"))

try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, EMAIL_TO, msg.as_string())
    print(f"\n✅ מייל נשלח ל-{EMAIL_TO}")
except Exception as e:
    print(f"❌ שגיאה: {e}")
    raise

print(f"\n{'='*60}")
print(f"  הסתיים | {len(results)} מניות במומנטום")
print(f"{'='*60}")
