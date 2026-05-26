# ============================================================
# Pre-Market Scanner — סריקה רחבה לפני פתיחת שוק
# פלט: מייל HTML + Google Sheets
# רץ: GitHub Actions כל יום ב-08:30 ET (ב-ו)
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
PM_MIN_CHANGE   = 1.5     # % שינוי מינימלי ב-Pre-Market
PM_MIN_VOLUME   = 50_000  # נפח Pre-Market מינימלי
PM_TOP_GAINERS  = 20      # כמה Gainers להציג
PM_TOP_LOSERS   = 10      # כמה Losers להציג
MAX_WORKERS     = 10      # threads מקבילים

# ============================================================
# רשימת מניות — S&P 500 + Nasdaq 100 + extras
# ============================================================
TICKERS = list(dict.fromkeys([
    # Mega Cap
    "AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","AVGO","JPM","V",
    "UNH","XOM","LLY","JNJ","WMT","MA","PG","HD","MRK","CVX",
    # Tech
    "ABBV","COST","PEP","KO","ADBE","CRM","TMO","ACN","MCD","CSCO",
    "QCOM","HON","IBM","GS","CAT","BA","INTU","AMAT","AMD","NOW",
    "ISRG","BLK","GILD","REGN","CI","SYK","ADI","VRTX","PANW","LRCX",
    "KLAC","MRVL","CRWD","DXCM","NET","NTAP","SNOW","DDOG","PLTR","OKTA",
    "ZS","MDB","HUBS","WDAY","VEEV","TEAM","CRM","FICO","ANSS","CDNS",
    "SNPS","FTNT","KEYS","ANET","ROP","TDY","ZBRA","PTC","VRSN",
    # Healthcare
    "A","ABT","AMGN","BAX","BDX","BMY","BSX","CAH","CNC","EW",
    "GEHC","HCA","HOLX","HUM","IQV","LH","MCK","MDT","MTD","PODD",
    "RMD","STE","TFX","WAT","ZBH","ZTS","BIIB","ILMN","MRNA","EXAS",
    "ALGN","BMRN","IDXX","ALNY","INCY","EXEL",
    # Financials
    "AFL","AIG","AJG","ALL","AMP","AON","AXP","BAC","BEN","BK",
    "BRO","C","CB","CBOE","CFG","CINF","CME","COF","DFS","EG",
    "FITB","HBAN","HIG","ICE","IVZ","KEY","MCO","MET","MMC","MS",
    "MTB","NTRS","PFG","PGR","PNC","PRU","RF","RJF","SCHW","SPGI",
    "STT","SYF","TFC","TRV","USB","WFC","WRB","IBKR","RNR",
    # Industrials
    "ALLE","AME","AOS","CARR","CHRW","CMI","CTAS","DAL","DE","DOV",
    "EMR","ETN","EXPD","FDX","FTV","GD","GE","GWW","HWM","IEX",
    "IR","ITW","JBHT","JCI","LHX","LMT","MAS","MMM","NOC","NSC",
    "OTIS","PH","PNR","PWR","ROK","ROL","RSG","RTX","SNA","SWK",
    "TDG","TT","UAL","UNP","UPS","URI","WAB","WM","XYL","BWXT",
    # Consumer Discretionary
    "AZO","BBY","BKNG","CMG","DHI","DPZ","DRI","ETSY","F","GM",
    "GPC","HAS","HLT","LEN","LKQ","LOW","LVS","MAR","MGM","NKE",
    "NVR","PHM","POOL","RCL","SBUX","TGT","TJX","ULTA","YUM","DECK",
    # Consumer Staples
    "ADM","BG","CAG","CHD","CL","CLX","CPB","EL","GIS","HRL",
    "HSY","K","KHC","KMB","KR","MDLZ","MKC","MO","MNST","STZ","TSN",
    # Energy
    "APA","BKR","COP","CTRA","DVN","EOG","EQT","FANG","HAL","HES",
    "KMI","LNG","MPC","MRO","OKE","OXY","PSX","SLB","VLO","WMB",
    # Materials
    "ALB","AVY","CF","ECL","EMN","FCX","IFF","LIN","LYB","MLM",
    "NEM","NUE","PKG","PPG","RPM","SHW","VMC",
    # Real Estate
    "AMT","ARE","AVB","BXP","CCI","CBRE","DLR","EQIX","EQR","ESS",
    "EXR","IRM","O","PSA","PLD","SPG","VTR","WELL",
    # Utilities
    "AEE","AEP","AES","AWK","CMS","CNP","D","DTE","DUK","ED",
    "EIX","ETR","EVRG","EXC","LNT","NEE","PCG","PEG","PPL","SRE","SO",
    # ADR ישראליות
    "CHKP","NICE","CYBR","MNDY","WIX","FVRR","GLBE",
    # נוספות
    "AFL","BNY","EXPD","DAL","BKR","KEYS","EG","IBKR",
]))

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

def save_to_sheets(gainers, losers, token, scan_time):
    if not token:
        print("⚠️ אין token — מדלג על שמירה לשיטס")
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

    rows = [[f"Pre-Market Scanner — {timestamp} — {len(gainers)} עולות / {len(losers)} יורדות"]]
    rows.append([f"פילטרים: שינוי >{PM_MIN_CHANGE}% · נפח >{PM_MIN_VOLUME:,} · MA150 + RSI"])
    rows.append([])
    rows.append(["📈 TOP GAINERS"] + [""]*(len(headers)-1))
    rows.append(headers)

    for r in gainers:
        rows.append([
            r["ticker"],
            f"{r['pm_change']:+.2f}%",
            f"${r['pm_price']}",
            f"${r['prev_close']}",
            f"{r['pm_volume']:,}",
            "✅" if r["above_ma150"] else "❌",
            "✅" if r["ma_rising"]   else "❌",
            r["rsi"],
            "✅" if r["above_ma50"]  else "❌",
            r["sector"],
            r["signal"],
        ])

    rows.append([])
    rows.append(["📉 TOP LOSERS"] + [""]*(len(headers)-1))
    rows.append(headers)

    for r in losers:
        rows.append([
            r["ticker"],
            f"{r['pm_change']:+.2f}%",
            f"${r['pm_price']}",
            f"${r['prev_close']}",
            f"{r['pm_volume']:,}",
            "✅" if r["above_ma150"] else "❌",
            "✅" if r["ma_rising"]   else "❌",
            r["rsi"],
            "✅" if r["above_ma50"]  else "❌",
            r["sector"],
            r["signal"],
        ])

    sheets_request("PUT",
        f"/values/{sheet_name}!A1?valueInputOption=RAW",
        token, {"values": rows})

    print(f"✅ נשמר בגוגל שיטס — טאב: {sheet_name}")
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
    """בונה תיאור איכות הסיגנל"""
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
    quality = "🔥 חזק" if score == 3 else "✅ בינוני" if score == 2 else "⚠️ חלש"
    return f"{quality} | {' '.join(parts)}"

# ============================================================
# ניתוח מניה בודדת ב-Pre-Market
# ============================================================
def analyze_premarket(ticker):
    try:
        tk = yf.Ticker(ticker)

        # Pre-Market + After-Hours
        hist_pm = tk.history(period="1d", interval="1m",
                             prepost=True, auto_adjust=True)
        if hist_pm.empty: return None

        # המר ל-ET
        hist_pm.index = hist_pm.index.tz_convert("America/New_York")

        # Pre-Market בלבד: 04:00–09:30
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

        closes    = hist_daily["Close"]
        prev_close = round(float(closes.iloc[-1]), 2)
        ma150     = closes.rolling(150).mean()
        ma50      = closes.rolling(50).mean()

        ma150_now = float(ma150.iloc[-1])
        ma150_5d  = float(ma150.iloc[-6]) if not pd.isna(ma150.iloc[-6]) else ma150_now
        ma50_now  = float(ma50.iloc[-1])

        slope_5d  = (ma150_now - ma150_5d) / ma150_5d * 100
        ma_rising = slope_5d > 0

        pm_change = round((pm_price - prev_close) / prev_close * 100, 2)
        if abs(pm_change) < PM_MIN_CHANGE: return None

        rsi = calc_rsi(closes)

        # סקטור
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
# הסורק הראשי
# ============================================================
scan_time = datetime.now()
print(f"[{scan_time.strftime('%H:%M:%S')}] Pre-Market Scanner מתחיל — {len(TICKERS)} מניות")

gainers = []
losers  = []

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {executor.submit(analyze_premarket, t): t for t in TICKERS}
    done    = 0
    for future in as_completed(futures):
        done += 1
        result = future.result()
        if result:
            if result["pm_change"] > 0:
                gainers.append(result)
                print(f"  📈 {result['ticker']:6s} {result['pm_change']:+.2f}% "
                      f"Vol:{result['pm_volume']//1000}K {result['signal']}")
            else:
                losers.append(result)
                print(f"  📉 {result['ticker']:6s} {result['pm_change']:+.2f}% "
                      f"Vol:{result['pm_volume']//1000}K")
        if done % 50 == 0:
            print(f"  [{done}/{len(TICKERS)}] ממשיך...")

gainers = sorted(gainers, key=lambda x: x["pm_change"], reverse=True)
losers  = sorted(losers,  key=lambda x: x["pm_change"])

print(f"\n✅ {len(gainers)} עולות | 📉 {len(losers)} יורדות")

# ============================================================
# Google Sheets
# ============================================================
print("\nמתחבר לגוגל שיטס...")
token = get_google_token()
save_to_sheets(gainers[:PM_TOP_GAINERS], losers[:PM_TOP_LOSERS], token, scan_time)

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
      <td style="padding:9px 12px;font-size:14px;font-weight:700;color:{change_color};">{r['pm_change']:+.2f}%</td>
      <td style="padding:9px 12px;font-size:13px;">${r['pm_price']}</td>
      <td style="padding:9px 12px;font-size:13px;color:#888;">${r['prev_close']}</td>
      <td style="padding:9px 12px;font-size:12px;">{vol_k}</td>
      <td style="padding:9px 12px;font-size:13px;text-align:center;">{ma_icon}</td>
      <td style="padding:9px 12px;font-size:13px;color:{rsi_color};font-weight:600;">{r['rsi']}</td>
      <td style="padding:9px 12px;font-size:11px;color:#777;">{sector_short}</td>
      <td style="padding:9px 12px;font-size:11px;">{r['signal']}</td>
    </tr>"""

def build_table(title, emoji, rows_html, count):
    return f"""
    <div style="margin-bottom:28px;">
      <div style="font-size:16px;font-weight:700;color:#1F3864;margin-bottom:10px;padding-bottom:6px;border-bottom:2px solid #2E75B6;">
        {emoji} {title} ({count})
      </div>
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-family:Arial,sans-serif;">
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

def build_email_html(gainers, losers, scan_time):
    today = scan_time.strftime("%d/%m/%Y")
    hour  = scan_time.strftime("%H:%M")
    total_g = len(gainers)
    total_l = len(losers)
    sheets_link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"

    # Gainers table
    if gainers:
        g_rows = "".join(build_stock_row(r, True)  for r in gainers[:PM_TOP_GAINERS])
        gainers_table = build_table("TOP GAINERS","📈", g_rows, min(total_g, PM_TOP_GAINERS))
    else:
        gainers_table = "<p style='color:#888'>אין עולות משמעותיות ב-Pre-Market</p>"

    # Losers table
    if losers:
        l_rows = "".join(build_stock_row(r, False) for r in losers[:PM_TOP_LOSERS])
        losers_table = build_table("TOP LOSERS","📉", l_rows, min(total_l, PM_TOP_LOSERS))
    else:
        losers_table = "<p style='color:#888'>אין יורדות משמעותיות ב-Pre-Market</p>"

    # סיכום מהיר
    strong_gainers = [r for r in gainers if r["above_ma150"] and r["ma_rising"]]
    hot_rsi        = [r for r in gainers if r["rsi"] > 70]

    summary_items = []
    if strong_gainers:
        tickers_str = ", ".join(r["ticker"] for r in strong_gainers[:5])
        summary_items.append(
            f"<li>✅ <strong>{len(strong_gainers)} מניות</strong> עולות עם MA150 בעלייה: {tickers_str}</li>")
    if hot_rsi:
        tickers_str = ", ".join(r["ticker"] for r in hot_rsi[:5])
        summary_items.append(
            f"<li>🔥 <strong>{len(hot_rsi)} מניות</strong> עם RSI חם (>70): {tickers_str}</li>")

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

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:20px;">
<div style="max-width:980px;margin:0 auto;background:white;border-radius:12px;
            overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1F3864,#2E75B6);
              padding:24px 28px;color:white;direction:rtl;text-align:right;">
    <div style="font-size:24px;font-weight:bold;">🌅 Pre-Market Scanner</div>
    <div style="font-size:14px;margin-top:6px;opacity:0.85;">
      {today} · {hour} ET · נסרקו {len(TICKERS)} מניות ·
      <strong>{total_g}</strong> עולות /
      <strong>{total_l}</strong> יורדות
    </div>
  </div>

  <!-- Body -->
  <div style="padding:24px 20px;direction:rtl;text-align:right;">

    <!-- Sheets link -->
    <div style="margin-bottom:16px;padding:10px 14px;background:#E1F5EE;
                border-radius:8px;font-size:13px;color:#085041;">
      📊 <strong>Google Sheets:</strong>
      <a href="{sheets_link}" style="color:#085041;font-weight:600;">{sheets_link}</a>
    </div>

    {summary_html}
    {gainers_table}
    {losers_table}

    <!-- Legend -->
    <div style="margin-top:16px;padding:12px 16px;background:#f8f9fa;
                border-radius:8px;font-size:12px;color:#666;">
      <strong>מקרא:</strong>
      ✅ MA150 עולה ומחיר מעל |
      ⚠️ מחיר מעל MA150 אבל לא עולה |
      ❌ מחיר מתחת MA150 |
      🔥 RSI חם (>70)<br>
      <strong>פילטרים:</strong>
      שינוי >{PM_MIN_CHANGE}% · נפח >{PM_MIN_VOLUME:,} · 04:00–09:30 ET
    </div>
  </div>

  <!-- Footer -->
  <div style="background:#f8f9fa;padding:14px 20px;font-size:11px;color:#999;
              direction:rtl;text-align:right;border-top:1px solid #eee;">
    נשלח אוטומטית ע"י GitHub Actions · זה אינו ייעוץ השקעות
  </div>
</div>
</body>
</html>"""

# ============================================================
# שליחת מייל
# ============================================================
total_active = len(gainers) + len(losers)
html_body = build_email_html(gainers, losers, scan_time)

if total_active == 0:
    subject = f"🌅 Pre-Market Scanner — {scan_time.strftime('%d/%m/%Y')} — אין פעילות משמעותית"
else:
    subject = (f"🌅 Pre-Market Scanner — {scan_time.strftime('%d/%m/%Y')} — "
               f"📈{len(gainers)} עולות | 📉{len(losers)} יורדות")

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
    print(f"📧 {subject}")
except Exception as e:
    print(f"❌ שגיאה בשליחת מייל: {e}")
    raise
