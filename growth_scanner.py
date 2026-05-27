name: Momentum Scanner

on:
  schedule:
    # 06:30 ET = 11:30 UTC (בקיץ) = 13:30 ישראל
    # ← שונה מאחה"צ לבוקר ישראל
    - cron: '30 11 * * 1-5'
  workflow_dispatch:

jobs:
  macd-scan:
    runs-on: ubuntu-latest
    timeout-minutes: 45

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install yfinance pandas numpy \
                      google-auth google-auth-httplib2 \
                      google-api-python-client

      - name: Run MACD Momentum Scanner
        env:
          GMAIL_USER:         ${{ secrets.GMAIL_USER }}
          GMAIL_PASSWORD:     ${{ secrets.GMAIL_PASSWORD }}
          EMAIL_TO:           ${{ secrets.EMAIL_TO }}
          GOOGLE_CREDENTIALS: ${{ secrets.GOOGLE_CREDENTIALS }}
        run: python macd_momentum_scanner.py

      - name: Upload log on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: macd-log
          path: '*.log'
