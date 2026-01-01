# Random Stock Picker

A truly random stock picker from the complete universe of E*TRADE tradeable securities.

**Live Site:** [https://kevinrcartercodes.github.io/random-stock-picker/](https://kevinrcartercodes.github.io/random-stock-picker/)

![Bloomberg Terminal Style Interface](https://img.shields.io/badge/style-Bloomberg%20Terminal-ff6600)
![Securities](https://img.shields.io/badge/securities-11%2C351-blue)
![Randomness](https://img.shields.io/badge/randomness-cryptographic-green)

## Purpose

This tool provides a **truly random** stock selection from over 11,000 securities available on E*TRADE. No algorithms, no bias, no stock screeners—just pure randomness.

## My Investment Strategy

I use this tool as part of a personal investment strategy:

1. **Weekly Selection**: Pick one random stock per week and buy it
2. **Six-Month Review**: Every six months, review performance of all holdings
3. **Cull the Losers**: Sell all but the top 12 performing stocks
4. **Double Down on Winners**: Double the number of shares owned in the remaining 12
5. **Reinvest Dividends**: All dividends are automatically reinvested

This strategy combines the randomness of selection (removing emotional/cognitive bias) with a disciplined approach to portfolio management—letting winners run while cutting losers.

## Features

- **11,351 Securities**: Stocks and ETFs from NYSE, NASDAQ, and AMEX
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
