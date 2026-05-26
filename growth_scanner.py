# ============================================================
# Growth Stock Scanner v1.0
# מניות צמיחה — Nasdaq + Russell Growth
# פלט: מייל HTML + Google Sheets
# רץ: GitHub Actions כל יום ב-06:00 ET (ב-ו)
# ============================================================

import yfinance as yf
import pandas as pd
import numpy as np
import smtplib
import os
import json
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_PASSWORD = os.environ["GMAIL_PASSWORD"]
EMAIL_TO       = os.environ["EMAIL_TO"]
SHEET_ID       = "12606ZN0UVV1y2aGCAULbAWRs_aszOvd88M2FURiyv_k"

# ============================================================
# פרמטרים
# ============================================================
MIN_PRICE          = 5.0
MIN_MARKET_CAP     = 1_000_000_000    # $1B+
MAX_MARKET_CAP     = 50_000_000_000   # $50B — מתחת ל-Large Cap
MIN_AVG_VOLUME     = 300_000
MIN_DAILY_TURNOVER = 5_000_000        # $5M מחזור יומי
MIN_REV_GROWTH     = 20.0             # % צמיחה הכנסות מינימלית
MAX_DIST_MA150     = 15.0             # % מקסימלי מעל MA150
MIN_DIST_MA150     = -10.0            # % מקסימלי מתחת MA150
CROSS_LOOKBACK     = 10               # ימים לחפש חציית MA

# ============================================================
# רשימת מניות צמיחה
# ============================================================
def get_growth_universe():
    tickers = []
    ua = {"User-Agent": "Mozilla/5.0"}

    # S&P 500 — יש שם מניות צמיחה
    try:
        t = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            storage_options=ua)[0]["Symbol"]\
            .str.replace(".", "-", regex=False).tolist()
        tickers += t
        print(f"  ✓ S&P 500: {len(t)}")
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
        print(f"  ✓ S&P 400: {len(t)}")
    except Exception as e:
        print(f"  ⚠ S&P 400: {e}")

    # מניות צמיחה ידועות שלא במדדים הגדולים
    growth_extras = [
        # Space / Defense Tech
        "ASTS","RKLB","LUNR","PL","SPCE",
        # Fintech / Payments
        "AFRM","UPST","SOFI","HOOD","NU","DAVE","CLOV",
        # Cloud / SaaS
        "GTLB","BRZE","CFLT","SLAB","DOCN","FROG","S",
        "DOMO","NCNO","ALTR","VRNS","JAMF","SPSC","ESTB",
        # Cybersecurity
        "SWI","TENB","QLYS","CERT","CBLK","HACK",
        # AI / Data
        "AI","BBAI","GFAI","SOUN","CODA","OPEN",
        "PRCT","PATH","AMBA","SWKS","MTSI",
        # Biotech / Health Tech
        "RXRX","SDGR","ACHR","JOBY","LILM","EVGO",
        "BLNK","CHPT","NKLA","RIDE","GOEV",
        # E-commerce / Consumer
        "CART","RELY","TPVG","SEMR","DUOL","UDMY",
        "INFA","TASK","FLYW","CWAN","PCVX",
        # Israel ADR + Global Tech
        "CHKP","NICE","CYBR","MNDY","WIX","FVRR",
        "GLBE","RSKD","TOST","RELY","FOUR","PAYO",
        # Semiconductors Growth
        "CRUS","IREN","SMCI","ACLS","ONTO","FORM",
        "POWI","NOVT","ITRI","SLAB","ICHR","COHU",
        # Healthcare Growth
        "RXRX","RCKT","BEAM","EDIT","NTLA","CRSP",
        "PACB","ONEM","GDRX","HIMS","DOCS","PHVS",
        # Energy Transition
        "ARRY","SHLS","STEM","ENER","NOVA","RUN",
        "SPWR","FSLR","ENPH","SEDG","MAXN",
        # Gaming / Entertainment
        "RBLX","U","MTCH","BMBL","SNAP","PINS",
    ]
    tickers += growth_extras

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
    sheet_name = f"Growth {scan_time.strftime('%d.%m %H:%M')}"

    sheets_request("POST", ":batchUpdate", token, {
        "requests": [{"addSheet": {"properties": {"title": sheet_name}}}]
    })

    headers = [
        "Ticker","שם","מגזר","מצב MA",
        "מחיר","מרחק MA150%","RSI",
        "Rev Growth%","Market Cap $B","Mkt Cap Range",
        "נפח יומי $M","ציון","סיגנל"
    ]

    rows = [[f"Growth Scanner — {timestamp} — {len(results)} מניות"]]
    rows.append([
        f"פילטרים: RevGrowth>{MIN_REV_GROWTH}% · "
        f"Cap $1B-$50B · MA150 עולה · נפח>${MIN_DAILY_TURNOVER/1e6:.0f}M"
    ])
    rows.append([])
    rows.append(headers)

    for r in results:
        rows.append([
            r["ticker"], r["name"], r["sector"], r["ma_status"],
            r["price"], f"{r['dist_ma150']:+.1f}%",
            r["rsi"], f"{r['rev_growth']:.1f}%",
            r["mkt_cap_b"], r["cap_range"],
            r["turnover_m"], r["score"], r["signal"],
        ])

    sheets_request("PUT",
        f"/values/{sheet_name}!A1?valueInputOption=RAW",
        token, {"values": rows})

    print(f"✅ נשמר — {sheet_name}")
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

def safe_get(info, key, default=None):
    try:
        v = info.get(key, default)
        return v if v is not None else default
    except:
        return default

def get_ma_status(price, ma150_now, ma150_5d, ma150_10d):
    """מחזיר סטטוס MA ומרחק"""
    slope_5d  = (ma150_now - ma150_5d)  / ma150_5d  * 100 if ma150_5d  else 0
    slope_10d = (ma150_now - ma150_10d) / ma150_10d * 100 if ma150_10d else 0
    ma_rising = slope_5d > 0 or slope_10d > 0
    dist      = (price - ma150_now) / ma150_now * 100

    if dist > 0 and ma_rising:    return "✅ מעל MA עולה",  dist, True
    elif dist > 0:                 return "⚠️ מעל MA שטוח", dist, False
    elif dist > -5 and ma_rising:  return "🌊 לפני חציה",   dist, True
    elif dist > -10 and ma_rising: return "⏳ מתקרב",        dist, True
    else:                          return "❌ מתחת",         dist, False

def cap_range_label(mkt_cap):
    if mkt_cap < 2:   return "Small $1-2B"
    if mkt_cap < 5:   return "Small $2-5B"
    if mkt_cap < 10:  return "Mid $5-10B"
    if mkt_cap < 20:  return "Mid $10-20B"
    return             "Large $20-50B"

def score_growth(r):
    s = 0
    # MA status
    if "✅" in r["ma_status"]:   s += 25
    elif "🌊" in r["ma_status"]: s += 20
    elif "⏳" in r["ma_status"]: s += 12
    # צמיחה
    rev = r["rev_growth"]
    if rev >= 50:   s += 25
    elif rev >= 35: s += 20
    elif rev >= 20: s += 12
    # RSI
    rsi = r["rsi"]
    if 45 <= rsi <= 60:   s += 20
    elif 40 <= rsi <= 70: s += 12
    # מרחק MA
    dist = r["dist_ma150"]
    if -5 <= dist <= 8:   s += 15
    elif -10 <= dist <= 15: s += 8
    # נפח
    if r["turnover_m"] >= 20:  s += 10
    elif r["turnover_m"] >= 10: s += 6
    elif r["turnover_m"] >= 5:  s += 3
    return min(s, 100)

# ============================================================
# ניתוח מניה בודדת
# ============================================================
def analyze_growth(ticker):
    try:
        tk   = yf.Ticker(ticker)
        info = tk.info or {}

        # Market Cap
        mkt_cap = safe_get(info, "marketCap", 0) or 0
        if mkt_cap < MIN_MARKET_CAP: return None, "mktcap_small"
        if mkt_cap > MAX_MARKET_CAP: return None, "mktcap_large"

        # צמיחה הכנסות
        rev_growth_raw = safe_get(info, "revenueGrowth", None)
        if rev_growth_raw is None: return None, "no_rev_growth"
        rev_growth = rev_growth_raw * 100 if abs(rev_growth_raw) < 2 else rev_growth_raw
        if rev_growth < MIN_REV_GROWTH: return None, f"rev_low({rev_growth:.1f}%)"

        # נתונים היסטוריים
        hist = tk.history(period="1y", interval="1d", auto_adjust=True)
        if hist.empty or len(hist) < 155: return None, "insufficient_history"

        closes  = hist["Close"]
        vols    = hist["Volume"]
        price   = float(closes.iloc[-1])

        if price < MIN_PRICE: return None, "price_low"

        avg_vol = float(vols.iloc[-21:-1].mean())
        turnover = price * avg_vol
        if avg_vol < MIN_AVG_VOLUME:      return None, "volume_low"
        if turnover < MIN_DAILY_TURNOVER: return None, "turnover_low"

        # MA150
        ma150    = closes.rolling(150).mean()
        ma150_now = float(ma150.iloc[-1])
        ma150_5d  = float(ma150.iloc[-6])  if not pd.isna(ma150.iloc[-6])  else None
        ma150_10d = float(ma150.iloc[-11]) if not pd.isna(ma150.iloc[-11]) else None

        if not ma150_5d or not ma150_10d: return None, "insufficient_ma"

        ma_status, dist_ma150, ma_ok = get_ma_status(
            price, ma150_now, ma150_5d, ma150_10d)

        # פילטר מרחק
        if dist_ma150 > MAX_DIST_MA150:  return None, f"too_extended({dist_ma150:.1f}%)"
        if dist_ma150 < MIN_DIST_MA150:  return None, f"too_far_below({dist_ma150:.1f}%)"

        # RSI
        rsi = calc_rsi(closes)
        if rsi > 78: return None, f"rsi_high({rsi})"

        # נתוני חברה
        name    = safe_get(info, "shortName",  ticker)[:25]
        sector  = safe_get(info, "sector",     "—") or "—"
        fwd_pe  = safe_get(info, "forwardPE",  None)
        analyst = safe_get(info, "targetMeanPrice", None)

        mkt_cap_b   = round(mkt_cap / 1e9, 1)
        turnover_m  = round(turnover / 1e6, 1)
        upside      = round((analyst - price) / price * 100, 1) if analyst else None

        result = {
            "ticker":      ticker,
            "name":        name,
            "sector":      sector,
            "price":       round(price, 2),
            "ma150":       round(ma150_now, 2),
            "dist_ma150":  round(dist_ma150, 1),
            "ma_status":   ma_status,
            "rsi":         rsi,
            "rev_growth":  round(rev_growth, 1),
            "mkt_cap_b":   mkt_cap_b,
            "cap_range":   cap_range_label(mkt_cap_b),
            "turnover_m":  turnover_m,
            "fwd_pe":      round(fwd_pe, 1) if fwd_pe and 0 < fwd_pe < 500 else None,
            "upside":      upside,
            "target":      round(analyst, 2) if analyst else None,
        }
        result["score"]  = score_growth(result)
        signal_map = {
            80: "🚀 חזק מאוד",
            60: "✅ חזק",
            40: "📊 בינוני",
        }
        result["signal"] = next(
            (v for k, v in signal_map.items() if result["score"] >= k),
            "🟡 חלש"
        )
        return result, None

    except Exception as e:
        return None, f"error:{str(e)[:40]}"

# ============================================================
# HTML למייל
# ============================================================
def build_email_html(results, scan_time, total_scanned):
    today = scan_time.strftime("%d/%m/%Y")
    hour  = scan_time.strftime("%H:%M")
    count = len(results)
    sheets_link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"

    if count == 0:
        body = """
        <div style="text-align:center;padding:40px;color:#888;">
          <div style="font-size:48px;">🔍</div>
          <div style="font-size:18px;margin-top:12px;">
            לא נמצאו מניות צמיחה כרגע
          </div>
          <div style="font-size:13px;margin-top:8px;color:#aaa;">
            נסה שוב מחר — השוק משתנה
          </div>
        </div>"""
    else:
        rows_html = ""
        for r in results:
            score = r["score"]
            if score >= 80:   row_bg = "#E8F5E9"
            elif score >= 60: row_bg = "#F1F8E9"
            elif score >= 40: row_bg = "#FFFDE7"
            else:             row_bg = "#FFFFFF"

            dist_color = ("#1D9E75" if r["dist_ma150"] > 0 else
                         "#D63B3B" if r["dist_ma150"] < -5 else "#BA7517")
            upside_str = f"+{r['upside']}%" if r.get("upside") else "—"
            pe_str     = str(r["fwd_pe"]) if r.get("fwd_pe") else "—"

            rows_html += f"""
            <tr style="border-bottom:1px solid #eee;background:{row_bg}">
              <td style="padding:9px 10px;font-weight:700;font-size:13px;">
                {r['ticker']}</td>
              <td style="padding:9px 10px;font-size:11px;color:#555;">
                {r['name'][:20]}</td>
              <td style="padding:9px 10px;font-size:11px;color:#777;">
                {r['sector'][:14]}</td>
              <td style="padding:9px 10px;font-size:12px;">
                {r['ma_status']}</td>
              <td style="padding:9px 10px;font-size:13px;">
                ${r['price']}</td>
              <td style="padding:9px 10px;font-size:13px;font-weight:600;
                         color:{dist_color};">
                {r['dist_ma150']:+.1f}%</td>
              <td style="padding:9px 10px;font-size:13px;">
                {r['rsi']}</td>
              <td style="padding:9px 10px;font-size:13px;font-weight:700;
                         color:#1D9E75;">
                {r['rev_growth']:.1f}%</td>
              <td style="padding:9px 10px;font-size:12px;">
                ${r['mkt_cap_b']}B</td>
              <td style="padding:9px 10px;font-size:11px;color:#666;">
                {r['cap_range']}</td>
              <td style="padding:9px 10px;font-size:12px;">
                {pe_str}</td>
              <td style="padding:9px 10px;font-size:12px;color:#1D9E75;
                         font-weight:600;">
                {upside_str}</td>
              <td style="padding:9px 10px;font-size:12px;font-weight:700;">
                {r['score']}</td>
              <td style="padding:9px 10px;font-size:12px;">
                {r['signal']}</td>
            </tr>"""

        body = f"""
        <div style="margin-bottom:12px;padding:10px 14px;background:#E1F5EE;
                    border-radius:8px;font-size:13px;color:#085041;">
          📊 <strong>Google Sheets:</strong>
          <a href="{sheets_link}" style="color:#085041;font-weight:600;">
            {sheets_link}</a>
        </div>
        <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;
                      font-family:Arial,sans-serif;">
          <thead>
            <tr style="background:#1F3864;color:white;">
              <th style="padding:8px 10px;text-align:right;font-size:11px;">Ticker</th>
              <th style="padding:8px 10px;text-align:right;font-size:11px;">שם</th>
              <th style="padding:8px 10px;text-align:right;font-size:11px;">מגזר</th>
              <th style="padding:8px 10px;text-align:right;font-size:11px;">מצב MA</th>
              <th style="padding:8px 10px;text-align:right;font-size:11px;">מחיר</th>
              <th style="padding:8px 10px;text-align:right;font-size:11px;">מרחק MA150</th>
              <th style="padding:8px 10px;text-align:right;font-size:11px;">RSI</th>
              <th style="padding:8px 10px;text-align:right;font-size:11px;">RevGrowth%</th>
              <th style="padding:8px 10px;text-align:right;font-size:11px;">Mkt Cap</th>
              <th style="padding:8px 10px;text-align:right;font-size:11px;">גודל</th>
              <th style="padding:8px 10px;text-align:right;font-size:11px;">Fwd P/E</th>
              <th style="padding:8px 10px;text-align:right;font-size:11px;">Upside</th>
              <th style="padding:8px 10px;text-align:right;font-size:11px;">ציון</th>
              <th style="padding:8px 10px;text-align:right;font-size:11px;">סיגנל</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
        </div>
        <div style="margin-top:14px;padding:12px;background:#f8f9fa;
                    border-radius:8px;font-size:12px;color:#666;">
          <strong>פילטרים:</strong>
          RevGrowth >{MIN_REV_GROWTH}% ·
          Cap $1B-$50B ·
          MA150 עולה ·
          מרחק MA150 {MIN_DIST_MA150}%-{MAX_DIST_MA150}% ·
          נפח >${MIN_DAILY_TURNOVER/1e6:.0f}M יומי<br>
          <strong>מצב MA:</strong>
          ✅ מעל MA עולה |
          🌊 לפני חציה (0%-5% מתחת) |
          ⏳ מתקרב (5%-10% מתחת)
        </div>"""

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;
             margin:0;padding:20px;">
<div style="max-width:1100px;margin:0 auto;background:white;
            border-radius:12px;overflow:hidden;
            box-shadow:0 2px 8px rgba(0,0,0,0.1);">

  <div style="background:linear-gradient(135deg,#1B5E20,#2E7D32);
              padding:24px 28px;color:white;
              direction:rtl;text-align:right;">
    <div style="font-size:24px;font-weight:bold;">🚀 Growth Stock Scanner</div>
    <div style="font-size:14px;margin-top:6px;opacity:0.85;">
      {today} · {hour} · נסרקו <strong>{total_scanned}</strong> מניות ·
      נמצאו <strong>{count}</strong> מניות צמיחה
    </div>
    <div style="font-size:12px;margin-top:4px;opacity:0.7;">
      RevGrowth &gt;{MIN_REV_GROWTH}% · Cap $1B-$50B · MA150 עולה
    </div>
  </div>

  <div style="padding:24px 20px;direction:rtl;text-align:right;">
    {body}
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
print(f"  GROWTH STOCK SCANNER v1.0")
print(f"  RevGrowth>{MIN_REV_GROWTH}% · Cap $1B-$50B · MA150 עולה")
print(f"  {scan_time.strftime('%d/%m/%Y %H:%M')}")
print(f"{'='*55}")

print("\n[1/3] טוען יוניברס...")
TICKERS = get_growth_universe()

print(f"\n[2/3] סורק {len(TICKERS)} מניות...")
results = []
rejected = {}
total    = len(TICKERS)

for i, ticker in enumerate(TICKERS):
    result, reason = analyze_growth(ticker)
    if result:
        results.append(result)
        print(f"  ✅ [{i+1:>4}/{total}] {ticker:<7} "
              f"Rev:{result['rev_growth']:>5.1f}% "
              f"Cap:${result['mkt_cap_b']:>5.1f}B "
              f"MA:{result['dist_ma150']:>+5.1f}% "
              f"RSI:{result['rsi']:>5.1f} "
              f"Score:{result['score']:>3} "
              f"{result['signal']}")
    else:
        rejected[reason] = rejected.get(reason, 0) + 1

    if i % 50 == 49:
        time.sleep(1)

# מיון לפי ציון
results.sort(key=lambda x: x["score"], reverse=True)

print(f"\n{'='*55}")
print(f"  נמצאו {len(results)} מניות צמיחה מתוך {total}")
print(f"\n  סיבות פסילה (Top 8):")
for r, n in sorted(rejected.items(), key=lambda x: -x[1])[:8]:
    print(f"    {r:<45} {n:>5} ({n/total*100:.1f}%)")

print(f"\n  🚀 Top 10:")
for r in results[:10]:
    print(f"    {r['ticker']:<7} Rev:{r['rev_growth']:>5.1f}% "
          f"Score:{r['score']:>3} {r['ma_status']} {r['signal']}")

print("\n[3/3] שומר ושולח...")
token = get_google_token()
save_to_sheets(results, token, scan_time)

html_body = build_email_html(results, scan_time, total)
subject   = (
    f"🚀 Growth Scanner — {scan_time.strftime('%d/%m/%Y')} — "
    f"{len(results)} מניות צמיחה"
    if results else
    f"🚀 Growth Scanner — {scan_time.strftime('%d/%m/%Y')} — אין הזדמנויות"
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

print(f"\n{'='*55}")
print(f"  הסתיים | {len(results)} מניות צמיחה")
print(f"{'='*55}")
