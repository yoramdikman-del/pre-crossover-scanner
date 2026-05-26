# ============================================================
# Pre-Market Scanner v2.0 — ~900 מניות
# S&P500 + S&P400 אוטומטי מ-Wikipedia
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
PM_MIN_CHANGE  = 1.5
PM_MIN_VOLUME  = 50_000
PM_TOP_GAINERS = 25
PM_TOP_LOSERS  = 10
MAX_WORKERS    = 12     # threads מקבילים
BATCH_SIZE     = 50     # מניות לכל batch
BATCH_SLEEP    = 2.0    # שניות בין batches

# ============================================================
# הורדת רשימת מניות אוטומטית מ-Wikipedia
# ============================================================
def get_universe():
    tickers = []
    ua = {"User-Agent": "Mozilla/5.0"}

    # S&P 500
    try:
        t = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            storage_options=ua)[0]["Symbol"]\
            .str.replace(".", "-", regex=False).tolist()
        tickers += t
        print(f"  ✓ S&P 500: {len(t)} מניות")
    except Exception as e:
        print(f"  ⚠ S&P 500: {e}")

    # S&P 400
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
        print(f"  ✓ S&P 400: {len(t)} מניות")
    except Exception as e:
        print(f"  ⚠ S&P 400: {e}")

    # extras — ADR ישראליות + נוספות
    extras = [
        "CHKP","NICE","CYBR","MNDY","WIX","FVRR","GLBE",
        "IBKR","BNY","EXPD","DAL","BKR","KEYS","AFL",
        "PLTR","OKTA","ZS","MDB","SNOW","DDOG","NET",
        "CRWD","PANW","FTNT","HUBS","WDAY","VEEV","TEAM",
    ]
    tickers += extras

    # הסרת כפילויות
    universe = list(dict.fromkeys(tickers))
    print(f"  ✓ סה\"כ: {len(universe)} מניות ייחודיות")
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
        print(f"⚠️ שגיאת אימות Google: {e}")
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
        print(f"⚠️ שגיאת Sheets: {e}")
        return None

def save_to_sheets(gainers, losers, token, scan_time, total_scanned):
    if not token:
        print("⚠️ אין token — מדלג")
        return

    timestamp  = scan_time.strftime("%d/%m/%Y %H:%M")
    sheet_name = f"PreMkt {scan_time.strftime('%d.%m %H:%M')}"

    sheets_request("POST", ":batchUpdate", token, {
        "requests": [{"addSheet": {"properties": {"title": sheet_name}}}]
    })

    headers = [
        "Ticker","שינוי%","מחיר PM","סגירה אמש","נפח PM",
        "מעל MA150","MA150 עולה","RSI","מעל MA50","סקטור","סיגנל"
    ]

    rows = [[f"Pre-Market Scanner v2 — {timestamp} — "
             f"נסרקו {total_scanned} | {len(gainers)} עולות / {len(losers)} יורדות"]]
    rows.append([f"S&P500 + S&P400 | שינוי>{PM_MIN_CHANGE}% | נפח>{PM_MIN_VOLUME:,}"])
    rows.append([])
    rows.append(["📈 TOP GAINERS"] + [""]*(len(headers)-1))
    rows.append(headers)

    for r in gainers:
        rows.append([
            r["ticker"], f"{r['pm_change']:+.2f}%",
            f"${r['pm_price']}", f"${r['prev_close']}",
            f"{r['pm_volume']:,}",
            "✅" if r["above_ma150"] else "❌",
            "✅" if r["ma_rising"]   else "❌",
            r["rsi"],
            "✅" if r["above_ma50"]  else "❌",
            r["sector"], r["signal"],
        ])

    rows.append([])
    rows.append(["📉 TOP LOSERS"] + [""]*(len(headers)-1))
    rows.append(headers)

    for r in losers:
        rows.append([
            r["ticker"], f"{r['pm_change']:+.2f}%",
            f"${r['pm_price']}", f"${r['prev_close']}",
            f"{r['pm_volume']:,}",
            "✅" if r["above_ma150"] else "❌",
            "✅" if r["ma_rising"]   else "❌",
            r["rsi"],
            "✅" if r["above_ma50"]  else "❌",
            r["sector"], r["signal"],
        ])

    sheets_request("PUT",
        f"/values/{sheet_name}!A1?valueInputOption=RAW",
        token, {"values": rows})

    print(f"✅ נשמר — טאב: {sheet_name}")
    print(f"🔗 https://docs.google.com/spreadsheets/d/{SHEET_ID}")

# ============================================================
# פונקציות עזר
# ============================================================
def calc_rsi(closes, period=14):
    delta = closes.diff()
    gain  = delta.clip(lower=0).ewm(com=period-1, min_periods=period).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period-1, min_periods=period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return round(float((100 - (100 / (1 + rs))).iloc[-1]), 1)

def build_signal(r):
    parts = []
    if r["above_ma150"] and r["ma_rising"]: parts.append("MA150✅")
    elif r["above_ma150"]:                   parts.append("MA150⚠️")
    else:                                    parts.append("MA150❌")
    if 45 <= r["rsi"] <= 65:                 parts.append("RSI✅")
    elif r["rsi"] > 65:                      parts.append("RSI🔥")
    else:                                    parts.append("RSI⚠️")
    if r["above_ma50"]:                      parts.append("SMA50✅")
    score = sum([
        r["above_ma150"] and r["ma_rising"],
        45 <= r["rsi"] <= 70,
        r["above_ma50"],
    ])
    quality = ("🔥 חזק" if score == 3 else
               "✅ בינוני" if score == 2 else "⚠️ חלש")
    return f"{quality} | {' '.join(parts)}"

# ============================================================
# ניתוח מניה בודדת
# ============================================================
def analyze_premarket(ticker):
    try:
        tk = yf.Ticker(ticker)

        # Pre-Market
        hist_pm = tk.history(
            period="1d", interval="1m",
            prepost=True, auto_adjust=True
        )
        if hist_pm.empty: return None

        hist_pm.index = hist_pm.index.tz_convert("America/New_York")
        premarket = hist_pm[
            (hist_pm.index.time >= dt.time(4, 0)) &
            (hist_pm.index.time <  dt.time(9, 30))
        ]
        if premarket.empty or len(premarket) < 3: return None

        pm_price  = round(float(premarket["Close"].iloc[-1]), 2)
        pm_volume = int(premarket["Volume"].sum())
        if pm_volume < PM_MIN_VOLUME: return None

        # נתונים יומיים
        hist_daily = tk.history(period="1y", interval="1d", auto_adjust=True)
        if hist_daily.empty or len(hist_daily) < 155: return None

        closes     = hist_daily["Close"]
        prev_close = round(float(closes.iloc[-1]), 2)
        ma150      = closes.rolling(150).mean()
        ma50       = closes.rolling(50).mean()

        ma150_now = float(ma150.iloc[-1])
        ma150_5d  = float(ma150.iloc[-6]) if not pd.isna(ma150.iloc[-6]) else ma150_now
        ma50_now  = float(ma50.iloc[-1])

        slope_5d  = (ma150_now - ma150_5d) / ma150_5d * 100
        ma_rising = slope_5d > 0

        pm_change = round((pm_price - prev_close) / prev_close * 100, 2)
        if abs(pm_change) < PM_MIN_CHANGE: return None

        rsi = calc_rsi(closes)

        try:
            sector = tk.info.get("sector", "—") or "—"
        except:
            sector = "—"

        result = {
            "ticker":      ticker,
            "pm_price":    pm_price,
            "pm_change":   pm_change,
            "pm_volume":   pm_volume,
            "prev_close":  prev_close,
            "ma150":       round(ma150_now, 2),
            "ma50":        round(ma50_now,  2),
            "above_ma150": pm_price > ma150_now,
            "above_ma50":  pm_price > ma50_now,
            "ma_rising":   ma_rising,
            "rsi":         rsi,
            "sector":      sector,
        }
        result["signal"] = build_signal(result)
        return result
    except:
        return None

# ============================================================
# סריקה חכמה עם batches
# ============================================================
def scan_with_batches(tickers):
    gainers = []
    losers  = []
    total   = len(tickers)
    done    = 0
    errors  = 0

    batches = [tickers[i:i+BATCH_SIZE]
               for i in range(0, total, BATCH_SIZE)]

    print(f"\n  סורק {total} מניות ב-{len(batches)} batches "
          f"({BATCH_SIZE} מניות / batch)...")

    for batch_num, batch in enumerate(batches, 1):
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(analyze_premarket, t): t
                       for t in batch}
            for future in as_completed(futures):
                done += 1
                result = future.result()
                if result:
                    if result["pm_change"] > 0:
                        gainers.append(result)
                        print(f"  📈 {result['ticker']:6s} "
                              f"{result['pm_change']:+.2f}% "
                              f"Vol:{result['pm_volume']//1000}K "
                              f"{result['signal']}")
                    else:
                        losers.append(result)
                        print(f"  📉 {result['ticker']:6s} "
                              f"{result['pm_change']:+.2f}% "
                              f"Vol:{result['pm_volume']//1000}K")

        print(f"  [{done}/{total}] Batch {batch_num}/{len(batches)} "
              f"— נמצאו: 📈{len(gainers)} 📉{len(losers)}")

        # sleep בין batches למניעת חסימה
        if batch_num < len(batches):
            time.sleep(BATCH_SLEEP)

    return gainers, losers

# ============================================================
# HTML למייל
# ============================================================
def build_stock_row(r, is_gainer=True):
    change_color = "#1D9E75" if is_gainer else "#D63B3B"
    ma_icon      = ("✅" if r["above_ma150"] and r["ma_rising"] else
                    "⚠️" if r["above_ma150"] else "❌")
    rsi_color    = ("#D63B3B" if r["rsi"] > 70 else
                    "#1D9E75" if 45 <= r["rsi"] <= 65 else "#888")
    vol_k        = f"{r['pm_volume']//1000:,}K"
    sector_short = r["sector"][:14] if r["sector"] != "—" else "—"

    return f"""
    <tr style="border-bottom:1px solid #f0f0f0;">
      <td style="padding:9px 12px;font-weight:700;font-size:14px;">{r['ticker']}</td>
      <td style="padding:9px 12px;font-size:14px;font-weight:700;
                 color:{change_color};">{r['pm_change']:+.2f}%</td>
      <td style="padding:9px 12px;font-size:13px;">${r['pm_price']}</td>
      <td style="padding:9px 12px;font-size:13px;color:#888;">${r['prev_close']}</td>
      <td style="padding:9px 12px;font-size:12px;">{vol_k}</td>
      <td style="padding:9px 12px;font-size:13px;text-align:center;">{ma_icon}</td>
      <td style="padding:9px 12px;font-size:13px;color:{rsi_color};
                 font-weight:600;">{r['rsi']}</td>
      <td style="padding:9px 12px;font-size:11px;color:#777;">{sector_short}</td>
      <td style="padding:9px 12px;font-size:11px;">{r['signal']}</td>
    </tr>"""

def build_table(title, emoji, rows_html, count):
    return f"""
    <div style="margin-bottom:28px;">
      <div style="font-size:16px;font-weight:700;color:#1F3864;
                  margin-bottom:10px;padding-bottom:6px;
                  border-bottom:2px solid #2E75B6;">
        {emoji} {title} ({count})
      </div>
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;
                      font-family:Arial,sans-serif;">
          <thead>
            <tr style="background:#1F3864;color:white;">
              <th style="padding:8px 12px;text-align:right;font-size:11px;">Ticker</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;">שינוי%</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;">מחיר PM</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;">סגירה</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;">נפח</th>
              <th style="padding:8px 12px;text-align:center;font-size:11px;">MA150</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;">RSI</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;">סקטור</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;">סיגנל</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
      </div>
    </div>"""

def build_email_html(gainers, losers, scan_time, total_scanned):
    today       = scan_time.strftime("%d/%m/%Y")
    hour        = scan_time.strftime("%H:%M")
    sheets_link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"

    gainers_table = (
        build_table("TOP GAINERS", "📈",
                    "".join(build_stock_row(r, True) for r in gainers[:PM_TOP_GAINERS]),
                    min(len(gainers), PM_TOP_GAINERS))
        if gainers else
        "<p style='color:#888'>אין עולות משמעותיות ב-Pre-Market</p>"
    )

    losers_table = (
        build_table("TOP LOSERS", "📉",
                    "".join(build_stock_row(r, False) for r in losers[:PM_TOP_LOSERS]),
                    min(len(losers), PM_TOP_LOSERS))
        if losers else
        "<p style='color:#888'>אין יורדות משמעותיות ב-Pre-Market</p>"
    )

    # תמצית
    strong  = [r for r in gainers if r["above_ma150"] and r["ma_rising"]]
    hot_rsi = [r for r in gainers if r["rsi"] > 70]

    summary_items = []
    if strong:
        tickers_str = ", ".join(r["ticker"] for r in strong[:6])
        summary_items.append(
            f"<li>✅ <strong>{len(strong)} מניות</strong> עם MA150 עולה: "
            f"{tickers_str}</li>")
    if hot_rsi:
        tickers_str = ", ".join(r["ticker"] for r in hot_rsi[:5])
        summary_items.append(
            f"<li>🔥 <strong>{len(hot_rsi)} מניות</strong> RSI חם (>70): "
            f"{tickers_str}</li>")

    summary_html = ""
    if summary_items:
        summary_html = f"""
        <div style="margin-bottom:20px;padding:14px 16px;
                    background:#E8F4FD;border-radius:8px;
                    font-size:13px;color:#1F3864;direction:rtl;">
          <strong>📋 תמצית:</strong>
          <ul style="margin:8px 0 0 0;padding-right:18px;">
            {"".join(summary_items)}
          </ul>
        </div>"""

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;
             margin:0;padding:20px;">
<div style="max-width:980px;margin:0 auto;background:white;
            border-radius:12px;overflow:hidden;
            box-shadow:0 2px 8px rgba(0,0,0,0.1);">

  <div style="background:linear-gradient(135deg,#1F3864,#2E75B6);
              padding:24px 28px;color:white;
              direction:rtl;text-align:right;">
    <div style="font-size:24px;font-weight:bold;">🌅 Pre-Market Scanner v2</div>
    <div style="font-size:14px;margin-top:6px;opacity:0.85;">
      {today} · {hour} ET · נסרקו <strong>{total_scanned}</strong> מניות
      (S&P500 + S&P400) ·
      <strong>{len(gainers)}</strong> עולות /
      <strong>{len(losers)}</strong> יורדות
    </div>
  </div>

  <div style="padding:24px 20px;direction:rtl;text-align:right;">
    <div style="margin-bottom:16px;padding:10px 14px;
                background:#E1F5EE;border-radius:8px;
                font-size:13px;color:#085041;">
      📊 <strong>Google Sheets:</strong>
      <a href="{sheets_link}" style="color:#085041;font-weight:600;">
        {sheets_link}</a>
    </div>
    {summary_html}
    {gainers_table}
    {losers_table}
    <div style="margin-top:16px;padding:12px 16px;background:#f8f9fa;
                border-radius:8px;font-size:12px;color:#666;">
      <strong>מקרא:</strong>
      ✅ MA150 עולה ומחיר מעל |
      ⚠️ מחיר מעל MA150 |
      ❌ מתחת MA150 |
      🔥 RSI חם (>70)<br>
      <strong>פילטרים:</strong>
      שינוי >{PM_MIN_CHANGE}% · נפח >{PM_MIN_VOLUME:,} · 04:00–09:30 ET
    </div>
  </div>

  <div style="background:#f8f9fa;padding:14px 20px;font-size:11px;
              color:#999;direction:rtl;text-align:right;
              border-top:1px solid #eee;">
    נשלח אוטומטית ע"י GitHub Actions · זה אינו ייעוץ השקעות
  </div>
</div>
</body>
</html>"""

# ============================================================
# MAIN
# ============================================================
scan_time = datetime.now()
print(f"\n{'='*55}")
print(f"  PRE-MARKET SCANNER v2.0")
print(f"  S&P500 + S&P400 — ~900 מניות")
print(f"  {scan_time.strftime('%d/%m/%Y %H:%M')}")
print(f"{'='*55}")

# הורדת יוניברס
print("\n[1/3] טוען רשימת מניות...")
TICKERS = get_universe()

# סריקה
print("\n[2/3] סריקת Pre-Market...")
gainers, losers = scan_with_batches(TICKERS)

gainers = sorted(gainers, key=lambda x: x["pm_change"], reverse=True)
losers  = sorted(losers,  key=lambda x: x["pm_change"])

print(f"\n{'='*55}")
print(f"  📈 {len(gainers)} עולות | 📉 {len(losers)} יורדות")
print(f"{'='*55}")

# Google Sheets
print("\n[3/3] שומר ושולח...")
token = get_google_token()
save_to_sheets(
    gainers[:PM_TOP_GAINERS],
    losers[:PM_TOP_LOSERS],
    token, scan_time, len(TICKERS)
)

# מייל
total_active = len(gainers) + len(losers)
html_body    = build_email_html(gainers, losers, scan_time, len(TICKERS))

subject = (
    f"🌅 Pre-Market Scanner v2 — {scan_time.strftime('%d/%m/%Y')} — "
    f"📈{len(gainers)} עולות | 📉{len(losers)} יורדות"
    if total_active else
    f"🌅 Pre-Market Scanner v2 — {scan_time.strftime('%d/%m/%Y')} — "
    f"אין פעילות משמעותית"
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
    print(f"❌ שגיאה בשליחת מייל: {e}")
    raise

print(f"\n{'='*55}")
print(f"  הסתיים | {len(TICKERS)} מניות נסרקו")
print(f"{'='*55}")
