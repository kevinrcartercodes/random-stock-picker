#!/usr/bin/env python3
"""Refresh the securities universe from NASDAQ's official symbol directory.

The picker's data goes stale as companies list, delist, merge and get acquired.
This script pulls the current official listings and rewrites every file that
carries a copy of the security list:

    nasdaq.txt           raw NASDAQ-listed dump (audit trail)
    other.txt            raw NYSE / NYSE ARCA / AMEX / BATS dump (audit trail)
    all_securities.json  stocks + ETFs
    all_stocks.json      stocks only
    index.html           the embedded `securities` array the page actually uses
    README.md            headline counts

Usage:
    python3 build.py            # fetch, rebuild, report what changed
    python3 build.py --dry-run  # report what would change, write nothing

Data source: https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs
"""

import json
import re
import sys
import urllib.request

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"

# Exchange code -> display name. Codes come from the `Exchange` column of
# otherlisted.txt. 'V' (IEX) is deliberately absent: it carries only test issues.
EXCHANGES = {'N': 'NYSE', 'A': 'AMEX', 'P': 'NYSE ARCA', 'Z': 'BATS'}

# Warrants, rights and units are excluded — they are derivatives, not the
# underlying security, and picking one is not the same as picking a company.
#
# Match on the naming convention, NOT on a bare substring. NASDAQ names these
# with an explicit " - Warrant/Right/Unit" delimiter; NYSE/AMEX spell them out
# as "Units, each consisting of ...". A looser rule silently eats legitimate
# securities whose *description* happens to contain the word "unit" — e.g.
# BSBR (Banco Santander Brasil ADS), CEF (Sprott Physical Gold and Silver
# Trust Units), GHI (Greystone Housing Impact Investors LP).
DERIVATIVE_NAME = re.compile(
    r'(\s-\s(warrants?|rights?|units?)\b'
    r'|\b(units?|warrants?|rights?),\s+each\b'
    r'|\bredeemable\s+warrants?\b)', re.I)

# NYSE/AMEX ticker suffix convention: SYM.WS, SYM.RT, SYM.U, SYM.W, SYM.R,
# optionally followed by a series letter (SYM.WS.A).
#
# This MUST stay anchored to the end of the ticker. Matching "WS"/"RT" anywhere
# in the symbol is the bug this script was written to fix: it silently dropped
# CART, CPRT, CERT, CORT, IHRT, WSM, NWS, FLWS and 16 others from the picker.
DERIVATIVE_SUFFIX = re.compile(r'\.(WS|RT|U|W|R)(\.[A-Z])?$')


def read_text(path):
    """Read a file without translating line endings, and report which it uses.

    README.md is CRLF; index.html is LF. Python's default text mode silently
    rewrites CRLF to LF on save, which turns a two-number edit into a diff that
    touches every line.
    """
    text = open(path, encoding='utf-8', newline='').read()
    return text, ('\r\n' if '\r\n' in text else '\n')


def write_text(path, text):
    open(path, 'w', encoding='utf-8', newline='').write(text)


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode('utf-8', errors='replace')


def parse(text):
    """Parse a pipe-delimited symbol directory file into a list of dicts."""
    lines = text.splitlines()
    header = lines[0].split('|')
    rows = []
    for line in lines[1:]:
        if line.startswith('File Creation Time'):
            continue
        parts = line.split('|')
        if len(parts) == len(header):
            rows.append(dict(zip(header, parts)))
    return rows


def is_tradeable(symbol, name):
    return not DERIVATIVE_NAME.search(name) and not DERIVATIVE_SUFFIX.search(symbol)


def build(nasdaq_text, other_text):
    out = []
    for row in parse(nasdaq_text):
        if row['Test Issue'] == 'Y':
            continue
        symbol, name = row['Symbol'].strip(), row['Security Name'].strip()
        if is_tradeable(symbol, name):
            out.append({'t': symbol, 'n': name, 'e': 'NASDAQ',
                        'y': 'ETF' if row['ETF'] == 'Y' else 'Stock'})
    for row in parse(other_text):
        if row['Test Issue'] == 'Y':
            continue
        exchange = EXCHANGES.get(row['Exchange'])
        if not exchange:
            continue
        symbol, name = row['ACT Symbol'].strip(), row['Security Name'].strip()
        if is_tradeable(symbol, name):
            out.append({'t': symbol, 'n': name, 'e': exchange,
                        'y': 'ETF' if row['ETF'] == 'Y' else 'Stock'})
    out.sort(key=lambda s: s['t'])
    return out


def current_symbols(path='index.html'):
    """Symbols currently embedded in index.html, for the change report."""
    try:
        html, _ = read_text(path)
    except FileNotFoundError:
        return set()
    return set(re.findall(r'\{t:"([^"]+)"', html))


def write_index(securities, path='index.html'):
    """Replace the embedded `securities` array, leaving all other markup alone."""
    text, newline = read_text(path)
    lines = text.split(newline)
    start = next(i for i, l in enumerate(lines) if l.strip() == 'const securities = [')
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == '];')

    def esc(s):
        return s.replace('\\', '\\\\').replace('"', '\\"')

    body = [f'            {{t:"{esc(s["t"])}",n:"{esc(s["n"])}",e:"{s["e"]}",y:"{s["y"]}"}}'
            for s in securities]
    body = [b + ',' for b in body[:-1]] + [body[-1]]

    html = newline.join(lines[:start + 1] + body + lines[end:])

    # The page derives these at load via refreshCounts(); keeping the initial
    # markup correct avoids a flash of stale numbers on first paint.
    total = len(securities)
    stocks = sum(1 for s in securities if s['y'] == 'Stock')
    etfs = sum(1 for s in securities if s['y'] == 'ETF')
    html = re.sub(r'(data-filter="all">)ALL \([\d,]+\)', rf'\g<1>ALL ({total:,})', html)
    html = re.sub(r'(data-filter="Stock">)STOCKS \([\d,]+\)', rf'\g<1>STOCKS ({stocks:,})', html)
    html = re.sub(r'(data-filter="ETF">)ETFs \([\d,]+\)', rf'\g<1>ETFs ({etfs:,})', html)
    html = re.sub(r'[\d,]+ securities available', f'{total:,} securities available', html)
    html = re.sub(r'(id="stat-total">)[\d,]+<', rf'\g<1>{total:,}<', html)
    html = re.sub(r'(id="stat-filtered">)[\d,]+<', rf'\g<1>{total:,}<', html)

    write_text(path, html)


def write_readme(securities, path='README.md'):
    total = len(securities)
    text, _ = read_text(path)
    text = re.sub(r'securities-[\d%A-Za-z,]+-blue',
                  f'securities-{total:,}-blue'.replace(',', '%2C'), text)
    text = re.sub(r'\*\*[\d,]+ Securities\*\*', f'**{total:,} Securities**', text)
    text = re.sub(r'over [\d,]+ securities', f'over {total // 1000:,},000 securities', text)
    write_text(path, text)


def main():
    dry_run = '--dry-run' in sys.argv

    print('Fetching NASDAQ symbol directory ...')
    nasdaq_text, other_text = fetch(NASDAQ_URL), fetch(OTHER_URL)
    stamp = next((l.split(': ', 1)[1].split('|')[0]
                  for l in nasdaq_text.splitlines() if l.startswith('File Creation Time')), '?')
    print(f'  source file creation time: {stamp}  (MMDDYYYYHH:MM)')

    securities = build(nasdaq_text, other_text)
    new_syms = {s['t'] for s in securities}
    old_syms = current_symbols()

    added, removed = sorted(new_syms - old_syms), sorted(old_syms - new_syms)
    stocks = sum(1 for s in securities if s['y'] == 'Stock')
    etfs = len(securities) - stocks

    print(f'\n  {len(old_syms):,} -> {len(securities):,} securities '
          f'({stocks:,} stocks / {etfs:,} ETFs)')
    print(f'  added:   {len(added):,}')
    print(f'  removed: {len(removed):,}')
    if added:
        print(f'    e.g. added   {", ".join(added[:8])}')
    if removed:
        print(f'    e.g. removed {", ".join(removed[:8])}')

    if dry_run:
        print('\n--dry-run: no files written.')
        return

    open('nasdaq.txt', 'w', encoding='utf-8').write(nasdaq_text)
    open('other.txt', 'w', encoding='utf-8').write(other_text)
    json.dump([{'symbol': s['t'], 'name': s['n'], 'exchange': s['e'], 'type': s['y']}
               for s in securities], open('all_securities.json', 'w'))
    json.dump([{'symbol': s['t'], 'name': s['n'].split(' - ')[0].strip(), 'exchange': s['e']}
               for s in securities if s['y'] == 'Stock'], open('all_stocks.json', 'w'))
    write_index(securities)
    write_readme(securities)

    print('\nWrote nasdaq.txt, other.txt, all_securities.json, all_stocks.json, '
          'index.html, README.md')
    print('Review with `git diff --stat`, then commit and push to publish.')


if __name__ == '__main__':
    main()
