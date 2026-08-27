# Random Stock Picker

A truly random stock picker from the complete universe of E*TRADE tradeable securities.

**Live Site:** [https://kevinrcartercodes.github.io/random-stock-picker/](https://kevinrcartercodes.github.io/random-stock-picker/)

![Bloomberg Terminal Style Interface](https://img.shields.io/badge/style-Bloomberg%20Terminal-ff6600)
![Securities](https://img.shields.io/badge/securities-12%2C302-blue)
![Randomness](https://img.shields.io/badge/randomness-cryptographic-green)

## Purpose

This tool provides a **truly random** stock selection from over 12,000 securities available on E*TRADE. No algorithms, no bias, no stock screeners—just pure randomness.

## My Investment Strategy

I use this tool as part of a personal investment strategy:

1. **Weekly Selection**: Pick one random stock per week and buy it
2. **Six-Month Review**: Every six months, review performance of all holdings
3. **Cull the Losers**: Sell all but the top 12 performing stocks
4. **Double Down on Winners**: Double the number of shares owned in the remaining 12
5. **Reinvest Dividends**: All dividends are automatically reinvested

This strategy combines the randomness of selection (removing emotional/cognitive bias) with a disciplined approach to portfolio management—letting winners run while cutting losers.

## Features

- **12,302 Securities**: Stocks and ETFs from NASDAQ, NYSE, NYSE ARCA, BATS, and AMEX
- **Cryptographic Randomness**: Uses `crypto.getRandomValues()` for true randomness (same quality as encryption keys)
- **Real-Time Data**: Live price charts and quotes via TradingView
- **Company Profiles**: Descriptions pulled from Wikipedia
- **Quick Links**: Direct links to E*TRADE, Yahoo Finance, Google Finance, Finviz, SEC filings, and news
- **Filter Options**: Filter by stocks, ETFs, or exchange

## Data Sources

| Data | Source |
|------|--------|
| Securities List | [NASDAQ Official Listings](https://www.nasdaqtrader.com/) |
| Company Descriptions | [Wikipedia REST API](https://www.wikipedia.org/) |
| Charts & Prices | [TradingView](https://www.tradingview.com/) |
| Randomization | Web Crypto API (`crypto.getRandomValues()`) |

## Refreshing the Data

Listings change constantly — companies IPO, delist, merge and get acquired,
and new ETFs launch weekly. To pull the current universe from NASDAQ's
official symbol directory and rewrite every file that carries a copy of it:

```bash
python3 build.py --dry-run   # report what would change, write nothing
python3 build.py             # rebuild the data files
git diff --stat              # review
git commit -am "Refresh securities" && git push   # publish
```

No dependencies beyond the Python 3 standard library. The script is
idempotent: running it twice against the same source data produces no diff.

Warrants, rights and units are excluded — see the comments in `build.py`,
which explain why the exclusion must be anchored to the ticker suffix rather
than matched as a substring.

## How the Randomness Works

Unlike `Math.random()` which uses a predictable pseudo-random algorithm, this tool uses the Web Crypto API:

```javascript
const array = new Uint32Array(1);
crypto.getRandomValues(array);
const randomIndex = array[0] % securities.length;
```

This pulls entropy from your operating system's random source (hardware events, timing jitter, etc.)—the same quality of randomness used for generating encryption keys.

## Disclaimer

This tool is for educational and personal use only. It is not financial advice. Always do your own research before making investment decisions. Past performance does not guarantee future results.

## Author

Built by [Kevin Carter](https://www.linkedin.com/in/kevinrcarter/)

## License

MIT License - Feel free to use, modify, and distribute.
