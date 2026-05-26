name: Pre-Market Scanner

on:
  schedule:
    # 08:30 ET = 13:30 UTC (בחורף) / 12:30 UTC (בקיץ)
    # משתמשים ב-12:30 UTC = בקיץ 08:30 ET
    - cron: '30 12 * * 1-5'
  workflow_dispatch:  # הרצה ידנית דרך GitHub

jobs:
  pre-market-scan:
    runs-on: ubuntu-latest
    timeout-minutes: 30

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
          pip install yfinance pandas numpy pytz \
                      google-auth google-auth-httplib2 \
                      google-api-python-client

      - name: Run Pre-Market Scanner
        env:
          GMAIL_USER:          ${{ secrets.GMAIL_USER }}
          GMAIL_PASSWORD:      ${{ secrets.GMAIL_PASSWORD }}
          EMAIL_TO:            ${{ secrets.EMAIL_TO }}
          GOOGLE_CREDENTIALS:  ${{ secrets.GOOGLE_CREDENTIALS }}
        run: python pre_market_scanner.py

      - name: Upload log on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: pre-market-log
          path: '*.log'
