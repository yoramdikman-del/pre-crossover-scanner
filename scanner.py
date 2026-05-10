# ============================================================
# Pre-Crossover Scanner — Nasdaq + S&P 500
# פלט: מייל HTML + Google Sheets
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
# אימות Google דרך Workload Identity Federation
# ============================================================
def get_google_token():
    try:
        import google.auth
        import google.auth.transport.requests
        from google.oauth2 import credentials as google_credentials
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
        print(f"⚠️ שגיאת Sheets API: {e}")
        return None

def save_to_sheets(results, token, scan_time):
    if not token:
        print("⚠️ אין token — מדלג על שמירה לשיטס")
        return

    timestamp = scan_time.strftime("%d/%m/%Y %H:%M")
    sheet_name = f"סריקה {scan_time.strftime('%d.%m %H:%M')}"

    # יצירת טאב חדש
    sheets_request("POST", ":batchUpdate", token, {
        "requests": [{
            "addSheet": {
                "properties": {"title": sheet_name}
            }
        }]
    })

    # כותרת ראשית
    headers = [
        "Ticker", "שם", "מגזר", "מחיר", "מרחק MA150%",
        "RSI", "Higher Highs", "Higher Lows", "נרות ירוקים/5",
        "Op.Margin%", "Rev.Growth%", "Rule of 40", "R40 Label",
        "FCF $M", "Mkt Cap $B", "Fwd P/E", "Upside%"
    ]

    rows = [[f"Pre-Crossover Scanner — {timestamp} — נמצאו {len(results)} מניות"]]
    rows.append(["מסנני כניסה: מתחת MA150 עד 5% · MA עולה · HH+HL · 3/5 נרות ירוקים · R40>40"])
    rows.append([])
    rows.append(headers)

    for r in results:
        rows.append([
            r["ticker"], r["name"], r["sector"],
            r["price"], r["dist"], r["rsi"],
            r["hh"], r["hl"], f"{r['green']}/5",
            r["op_m"], r["rev_g"], r["r40"], r["r40_lbl"],
            r["fcf"], r["mkt_cap"],
            r["fwd_pe"] if r["fwd_pe"] else "—",
            f"+{r['upside']}%" if r["upside"] else "—"
        ])

    # כתיבה לגיליון
    sheets_request("PUT",
        f"/values/{sheet_name}!A1?valueInputOption=RAW",
        token, {"values": rows})

    print(f"✅ נשמר בגוגל שיטס — טאב: {sheet_name}")
    print(f"🔗 https://docs.google.com/spreadsheets/d/{SHEET_ID}")

# ============================================================
# רשימת טיקרים — Nasdaq + S&P 500
# ============================================================
TICKERS = list(dict.fromkeys([
    # Nasdaq 100
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","AVGO","COST",
    "NFLX","ASML","AMD","ADBE","QCOM","INTC","INTU","AMAT","MU","LRCX",
    "KLAC","MRVL","SNPS","CDNS","CRWD","PANW","FTNT","ANSS","IDXX","REGN",
    "VRTX","BIIB","ILMN","MRNA","DXCM","ISRG","ALGN","BMRN","EXAS",
    "TTWO","EA","DOCU","OKTA","DDOG","NET","SNOW","PLTR","MDB","ESTB",
    "BILL","HUBS","VEEV","WDAY","NOW","CRM","TEAM","ZS","PAYC","PCTY",
    "SMAR","AZPN","MEDP","FICO","TMUS","CHTR","LULU","ROST","ORLY","FAST",
    "PAYX","CTSH","FISV","PYPL","ADSK","VRSK","CSGP","CPRT","EBAY","PCAR",
    "ODFL","NXPI","MCHP","SWKS","MPWR","ENTG","INCY","EXEL","ALNY",
    "CPAY","TPR","NDAQ","APH","ANET","MSCI","TROW","KEYS","CDAY","GWRE",
    "MANH","POWI","NOVT","ITRI","BRZE","CFLT","SLAB","FORM","ACLS","ONTO",
    "TXN","MRVL","LRCX","AMAT","AMD","INTC","QCOM","AVGO",
    # S&P 500 — Technology
    "ACN","ADP","AKAM","ANSS","BR","CDW","CSCO","CTSH","ENPH","FFIV",
    "FSLR","GEN","GDDY","GLW","HPE","HPQ","IBM","IT","JNPR","NTAP",
    "ON","ORCL","PTC","QRVO","ROP","TDY","TEL","TER","TYL","VRSN","ZBRA",
    # S&P 500 — Healthcare
    "A","ABT","AMGN","BAX","BDX","BMY","BSX","CAH","CI","CNC",
    "COO","CRL","CVS","ELV","EW","GEHC","GILD","HCA","HOLX","HSIC",
    "HUM","IQV","JNJ","LH","LLY","MCK","MDT","MRK","MTD","PODD",
    "RMD","STE","SYK","TFX","TMO","UHS","UNH","WAT","ZBH","ZTS",
    # S&P 500 — Financials
    "AFL","AIG","AIZ","AJG","ALL","AMP","AON","AXP","BAC","BEN",
    "BK","BLK","BRO","C","CB","CBOE","CFG","CINF","CME","CMA",
    "COF","DFS","EG","FITB","GS","HBAN","HIG","ICE","IVZ","JPM",
    "KEY","L","MCO","MET","MMC","MS","MTB","NTRS","PFG","PGR",
    "PNC","PRU","RF","RJF","SCHW","SPGI","STT","SYF","TFC","TRV",
    "USB","UNM","V","WFC","WRB","MA",
    # S&P 500 — Consumer Discretionary
    "AZO","BBY","BKNG","BWA","CCL","CMG","CZR","DHI","DPZ","DRI",
    "ETSY","F","GM","GPC","HAS","HD","HLT","LEN","LKQ","LOW",
    "LVS","MAR","MCD","MGM","MHK","NCLH","NKE","NVR","PHM","POOL",
    "PVH","RCL","SBUX","TGT","TJX","ULTA","VFC","WHR","WYNN","YUM","DECK",
    # S&P 500 — Industrials
    "ALLE","AME","AOS","BA","CARR","CAT","CHRW","CMI","CTAS","DAL",
    "DE","DOV","EMR","ETN","EFX","EXPD","FDX","FTV","GD","GE",
    "GWW","HON","HWM","IEX","IR","ITW","J","JBHT","JCI","LHX",
    "LMT","LUV","MAS","MMM","NOC","NSC","OTIS","PH","PNR","PWR",
    "RHI","ROK","ROL","RSG","RTX","SNA","SWK","TDG","TT","UAL",
    "UNP","UPS","URI","WAB","WM","XYL",
    # S&P 500 — Communication Services
    "CHTR","CMCSA","DIS","FOX","FOXA","IPG","LYV","NWS","NWSA",
    "OMC","PARA","T","VZ","WBD",
    # S&P 500 — Consumer Staples
    "ADM","BG","CAG","CHD","CL","CLX","CPB","EL","GIS","HRL",
    "HSY","K","KHC","KMB","KO","KR","MDLZ","MKC","MO","MNST",
    "PEP","PG","PM","SJM","STZ","SYY","TAP","TSN","WBA","WMT",
    # S&P 500 — Energy
    "APA","BKR","COP","CTRA","CVX","DVN","EOG","EQT","FANG","HAL",
    "HES","KMI","LNG","MPC","MRO","OKE","OXY","PSX","SLB","TRGP","VLO","WMB","XOM",
    # S&P 500 — Materials
    "ALB","AVY","BALL","CF","AMCR","CE","ECL","EMN","FCX","FMC",
    "IFF","IP","LIN","LYB","MLM","MOS","NEM","NUE","PKG","PPG","RPM","SHW","VMC",
    # S&P 500 — Real Estate
    "AMT","ARE","AVB","BXP","CCI","CBRE","DLR","EQIX","EQR","ESS",
    "EXR","FRT","HST","IRM","KIM","MAA","O","PSA","PLD","REG","SBAC","SPG","UDR","VTR","WELL","WY",
    # S&P 500 — Utilities
    "AEE","AEP","AES","AWK","CMS","CNP","D","DTE","DUK","ED",
    "EIX","ES","ETR","EVRG","EXC","FE","LNT","NEE","NI","PCG","PEG","PPL","SRE","SO","WEC","XEL",
]))

# ============================================================
# פונקציות עזר
# ============================================================

def get_slope(series, n=10):
    if len(series) < n:
        return 0
    y = series[-n:].values
    x = np.arange(n)
    return np.polyfit(x, y, 1)[0]

def detect_hh_hl(closes, highs, lows, window=63):
    if len(closes) < window:
        return 0, 0, False
    h = highs[-window:].values
    l = lows[-window:].values
    peaks, troughs = [], []
    for i in range(2, len(h) - 2):
        if h[i] > h[i-1] and h[i] > h[i-2] and h[i] > h[i+1] and h[i] > h[i+2]:
            peaks.append((i, h[i]))
        if l[i] < l[i-1] and l[i] < l[i-2] and l[i] < l[i+1] and l[i] < l[i+2]:
            troughs.append((i, l[i]))
    if len(peaks) < 2 or len(troughs) < 2:
        return 0, 0, False
    hh = sum(1 for i in range(1, len(peaks))   if peaks[i][1]   > peaks[i-1][1])
    hl = sum(1 for i in range(1, len(troughs)) if troughs[i][1] > troughs[i-1][1])
    return hh, hl, (hh >= 2 and hl >= 2)

def count_green_candles(opens, closes, n=5):
    if len(closes) < n:
        return 0
    o = opens[-n:].values
    c = closes[-n:].values
    return sum(1 for i in range(n) if c[i] > o[i])

def calc_rsi(closes, period=14):
    delta = closes.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def safe_get(info, key, default=None):
    try:
        v = info.get(key, default)
        return v if v is not None else default
    except:
        return default

def r40_label(score):
    if score >= 100: return "יוצא דופן 🚀"
    if score >= 75:  return "מצוין 💪"
    if score >= 50:  return "עובר ✅"
    return "בסיסי 📊"

# ============================================================
# הסורק הראשי
# ============================================================
results = []
total = len(TICKERS)
print(f"[{datetime.now().strftime('%H:%M:%S')}] סורק {total} מניות...")

for i, ticker in enumerate(TICKERS):
    try:
        tk   = yf.Ticker(ticker)
        hist = tk.history(period="1y", interval="1d")
        if hist is None or len(hist) < 150:
            continue

        closes = hist["Close"]
        highs  = hist["High"]
        lows   = hist["Low"]
        opens  = hist["Open"]
        price  = closes.iloc[-1]

        ma150         = closes.rolling(150).mean()
        ma150_current = ma150.iloc[-1]
        ma150_slope   = get_slope(ma150, n=10)
        dist_pct      = (price - ma150_current) / ma150_current * 100

        if not (-5.0 <= dist_pct <= 0):       continue
        if ma150_slope <= 0:                   continue

        rsi = calc_rsi(closes).iloc[-1]
        if not (35 <= rsi <= 65):             continue

        hh, hl, confirmed = detect_hh_hl(closes, highs, lows, window=63)
        if not confirmed:                      continue

        green = count_green_candles(opens, closes, n=5)
        if green < 3:                          continue

        info       = tk.info
        op_margin  = safe_get(info, "operatingMargins", 0)
        rev_growth = safe_get(info, "revenueGrowth",    0)
        fcf        = safe_get(info, "freeCashflow",     0)
        mkt_cap    = safe_get(info, "marketCap",        0)
        fwd_pe     = safe_get(info, "forwardPE",        None)
        name       = safe_get(info, "shortName",        ticker)
        sector     = safe_get(info, "sector",           "—")
        analyst_t  = safe_get(info, "targetMeanPrice",  None)

        op_m  = op_margin  * 100 if op_margin  and abs(op_margin)  < 2 else (op_margin  or 0)
        rev_g = rev_growth * 100 if rev_growth and abs(rev_growth) < 2 else (rev_growth or 0)

        if op_m  < 20:               continue
        if rev_g < 10:               continue
        if not fcf or fcf <= 0:      continue

        r40 = round(rev_g + op_m, 1)
        if r40 < 40:                 continue

        upside = round((analyst_t - price) / price * 100, 1) if analyst_t else None

        print(f"  ✅ {ticker} — R40={r40} dist={dist_pct:.2f}% green={green}/5")

        results.append({
            "ticker":  ticker,
            "name":    name,
            "sector":  sector,
            "price":   round(price, 2),
            "dist":    round(dist_pct, 2),
            "rsi":     round(rsi, 1),
            "hh":      hh,
            "hl":      hl,
            "green":   green,
            "op_m":    round(op_m,  1),
            "rev_g":   round(rev_g, 1),
            "r40":     r40,
            "r40_lbl": r40_label(r40),
            "fcf":     round(fcf / 1_000_000) if fcf else 0,
            "mkt_cap": round(mkt_cap / 1_000_000_000, 1) if mkt_cap else 0,
            "fwd_pe":  round(fwd_pe, 1) if fwd_pe else None,
            "upside":  upside,
            "target":  round(analyst_t, 2) if analyst_t else None,
        })

    except Exception as e:
        print(f"  ⚠️  {ticker}: {e}")

    time.sleep(0.25)

results.sort(key=lambda x: x["r40"], reverse=True)
print(f"\nנמצאו {len(results)} מניות עוברות מתוך {total}")

# ============================================================
# שמירה לגוגל שיטס
# ============================================================
scan_time = datetime.now()
print("\nמתחבר לגוגל שיטס...")
token = get_google_token()
save_to_sheets(results, token, scan_time)

# ============================================================
# HTML למייל
# ============================================================
def build_email_html(results, scan_time):
    count = len(results)
    today = scan_time.strftime("%d/%m/%Y")
    hour  = scan_time.strftime("%H:%M")

    if count == 0:
        body_content = """
        <div style="text-align:center;padding:40px 0;color:#888;">
            <div style="font-size:48px;">🔍</div>
            <div style="font-size:18px;margin-top:12px;">לא נמצאו מניות שעוברות את כל הפילטרים היום</div>
            <div style="font-size:14px;margin-top:8px;color:#aaa;">הסורק עובד — השוק לא מציע הזדמנויות כרגע</div>
        </div>"""
    else:
        rows = ""
        for r in results:
            dist_color = "#BA7517" if r["dist"] < -3 else "#1D9E75"
            green_bar  = "🟢" * r["green"] + "⚪" * (5 - r["green"])
            upside_str = f"+{r['upside']}%" if r["upside"] else "—"
            upside_col = "#1D9E75" if r["upside"] and r["upside"] > 10 else "#888"
            pe_str     = str(r["fwd_pe"]) if r["fwd_pe"] else "—"
            rows += f"""
            <tr style="border-bottom:1px solid #f0f0f0;">
              <td style="padding:10px 12px;font-weight:600;font-size:14px;">{r["ticker"]}</td>
              <td style="padding:10px 12px;font-size:13px;color:#555;">{r["name"][:22]}</td>
              <td style="padding:10px 12px;font-size:12px;color:#777;">{r["sector"][:16]}</td>
              <td style="padding:10px 12px;font-size:13px;">${r["price"]}</td>
              <td style="padding:10px 12px;font-size:13px;color:{dist_color};font-weight:600;">{r["dist"]}%</td>
              <td style="padding:10px 12px;font-size:13px;">{r["rsi"]}</td>
              <td style="padding:10px 12px;font-size:13px;">{r["hh"]}HH/{r["hl"]}HL</td>
              <td style="padding:10px 12px;font-size:13px;letter-spacing:2px;">{green_bar}</td>
              <td style="padding:10px 12px;font-size:13px;">{r["op_m"]}%</td>
              <td style="padding:10px 12px;font-size:13px;">{r["rev_g"]}%</td>
              <td style="padding:10px 12px;font-size:13px;font-weight:600;color:#1D9E75;">{r["r40"]}</td>
              <td style="padding:10px 12px;font-size:13px;">{pe_str}</td>
              <td style="padding:10px 12px;font-size:13px;color:{upside_col};font-weight:600;">{upside_str}</td>
            </tr>"""

        sheets_link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
        body_content = f"""
        <div style="margin-bottom:12px;padding:10px 14px;background:#E1F5EE;border-radius:8px;font-size:13px;color:#085041;">
          📊 <strong>גיליון Google Sheets מעודכן:</strong>
          <a href="{sheets_link}" style="color:#085041;font-weight:600;">{sheets_link}</a>
        </div>
        <table style="width:100%;border-collapse:collapse;font-family:Arial,sans-serif;">
          <thead>
            <tr style="background:#1F3864;color:white;">
              <th style="padding:10px 12px;text-align:right;font-size:12px;">Ticker</th>
              <th style="padding:10px 12px;text-align:right;font-size:12px;">שם</th>
              <th style="padding:10px 12px;text-align:right;font-size:12px;">מגזר</th>
              <th style="padding:10px 12px;text-align:right;font-size:12px;">מחיר</th>
              <th style="padding:10px 12px;text-align:right;font-size:12px;">מרחק MA150</th>
              <th style="padding:10px 12px;text-align:right;font-size:12px;">RSI</th>
              <th style="padding:10px 12px;text-align:right;font-size:12px;">HH/HL</th>
              <th style="padding:10px 12px;text-align:right;font-size:12px;">נרות 5Y</th>
              <th style="padding:10px 12px;text-align:right;font-size:12px;">Op.M%</th>
              <th style="padding:10px 12px;text-align:right;font-size:12px;">RevG%</th>
              <th style="padding:10px 12px;text-align:right;font-size:12px;">R40</th>
              <th style="padding:10px 12px;text-align:right;font-size:12px;">Fwd P/E</th>
              <th style="padding:10px 12px;text-align:right;font-size:12px;">Upside</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>"""

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:20px;">
  <div style="max-width:960px;margin:0 auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
    <div style="background:linear-gradient(135deg,#1F3864,#2E75B6);padding:24px 28px;color:white;direction:rtl;text-align:right;">
      <div style="font-size:22px;font-weight:bold;">📊 Pre-Crossover Scanner</div>
      <div style="font-size:14px;margin-top:6px;opacity:0.85;">{today} · {hour} · Nasdaq + S&P 500 · נמצאו <strong>{count}</strong> מניות</div>
    </div>
    <div style="padding:24px 20px;direction:rtl;text-align:right;overflow-x:auto;">
      {body_content}
      <div style="margin-top:16px;padding:12px 16px;background:#f8f9fa;border-radius:8px;font-size:12px;color:#666;">
        <strong>פילטרים:</strong> מתחת MA150 עד 5% · MA עולה · HH+HL ≥2 · 3/5 נרות ירוקים · RSI 35–65 · Op.Margin >20% · RevGrowth >10% · R40 >40
      </div>
    </div>
    <div style="background:#f8f9fa;padding:14px 20px;font-size:11px;color:#999;direction:rtl;text-align:right;border-top:1px solid #eee;">
      נשלח אוטומטית ע"י GitHub Actions · זה אינו ייעוץ השקעות
    </div>
  </div>
</body>
</html>"""

# ============================================================
# שליחת מייל
# ============================================================
html_body = build_email_html(results, scan_time)
subject   = (
    f"📊 Pre-Crossover Scanner — {scan_time.strftime('%d/%m/%Y')} — {len(results)} מניות עוברות"
    if results else
    f"📊 Pre-Crossover Scanner — {scan_time.strftime('%d/%m/%Y')} — אין הזדמנויות היום"
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
    print(f"✅ מייל נשלח ל-{EMAIL_TO}")
except Exception as e:
    print(f"❌ שגיאה: {e}")
    raise
