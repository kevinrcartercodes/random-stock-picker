#!/usr/bin/env python3
"""The Random Strategy: a public, self-updating model portfolio.

Rules
-----
1. Every Monday (from START), pick one security at random from the full
   universe in all_securities.json and buy 1 share at that day's close.
   If Monday is a market holiday, the buy fills at the next trading day's close.
2. Dividends are reinvested at the close on the ex-dividend date.
   Reinvested (DRIP) shares are tracked separately from purchased shares.
3. Every 26 weeks, rank every position by total return (market value incl.
   DRIP shares vs. cash paid in). Sell everything except the top 12.
4. Double the *purchased* share count of each of the 12 survivors (DRIP shares
   do not count toward the doubling). The review runs before that week's buy.

Benchmark: every dollar the strategy pays in (weekly buys and doublings) is
also put into SPY on the same day, with SPY dividends reinvested. The strategy
keeps sale proceeds as cash, so both sides are compared on total value against
the same contributions.

The ledger is recomputed from scratch on every run from picks.json and
split-adjusted price history, so a failed or late run never corrupts it.

Usage:
    python3 strategy/engine.py            # make any due pick, rebuild portfolio.json
    python3 strategy/engine.py --no-pick  # rebuild only
"""

import json
import os
import secrets
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo('America/New_York')
except Exception:  # pragma: no cover - tzdata missing
    ET = timezone(timedelta(hours=-5))

START = date(2026, 10, 12)       # first pick (a Monday)
REVIEW_WEEKS = 26                # cull + double every six months
KEEP = 12                        # survivors at each review
BENCHMARK = 'SPY'

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PICKS = os.path.join(HERE, 'picks.json')
OUT = os.path.join(HERE, 'portfolio.json')
UNIVERSE = os.path.join(ROOT, 'all_securities.json')


# ---------------------------------------------------------------- schedule

def pick_dates(today):
    """Scheduled Monday pick dates up to and including `today`."""
    out, d = [], START
    while d <= today:
        out.append(d)
        d += timedelta(weeks=1)
    return out


def review_dates(today):
    out, d = [], START + timedelta(weeks=REVIEW_WEEKS)
    while d <= today:
        out.append(d)
        d += timedelta(weeks=REVIEW_WEEKS)
    return out


def next_after(today, first, step_weeks):
    """First scheduled date strictly after `today`."""
    d = first
    while d <= today:
        d += timedelta(weeks=step_weeks)
    return d


# ---------------------------------------------------------------- prices

def yahoo_symbol(t):
    """NASDAQ symbol directory -> Yahoo: ABR$D -> ABR-PD, BRK.B -> BRK-B."""
    if '$' in t:
        base, series = t.split('$', 1)
        return f'{base}-P{series}'
    return t.replace('.', '-')


def fetch_history(ticker, start, end):
    """Daily split-adjusted closes, dividends and splits from Yahoo's chart API.

    Returns {'close': {date: px}, 'div': {date: amt}, 'split': {date: ratio}}
    or None if the symbol has no data.
    """
    p1 = int(datetime.combine(start - timedelta(days=7), datetime.min.time(),
                              tzinfo=timezone.utc).timestamp())
    p2 = int(datetime.combine(end + timedelta(days=2), datetime.min.time(),
                              tzinfo=timezone.utc).timestamp())
    sym = yahoo_symbol(ticker)
    last_err = None
    for attempt in range(4):
        host = 'query1' if attempt % 2 == 0 else 'query2'
        url = (f'https://{host}.finance.yahoo.com/v8/finance/chart/{sym}'
               f'?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit')
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last_err = e
        except Exception as e:  # network blip
            last_err = e
        time.sleep(2 ** attempt)
    else:
        raise RuntimeError(f'{ticker}: {last_err}')

    result = (data.get('chart') or {}).get('result')
    if not result:
        return None
    res = result[0]
    offset = res.get('meta', {}).get('gmtoffset', 0)

    def to_date(ts):
        return datetime.fromtimestamp(int(ts) + offset, tz=timezone.utc).date()

    closes = {}
    quote = (res.get('indicators', {}).get('quote') or [{}])[0]
    for ts, px in zip(res.get('timestamp') or [], quote.get('close') or []):
        if px is not None:
            closes[to_date(ts)] = float(px)
    events = res.get('events') or {}
    divs = {to_date(v['date']): float(v['amount'])
            for v in (events.get('dividends') or {}).values()}
    splits = {to_date(v['date']): float(v['numerator']) / float(v['denominator'])
              for v in (events.get('splits') or {}).values()
              if v.get('denominator')}
    if not closes:
        return None
    return {'close': closes, 'div': divs, 'split': splits}


# ---------------------------------------------------------------- ledger

def split_factor(hist, d):
    """Real shares bought on `d` -> split-adjusted shares today."""
    f = 1.0
    for sd, ratio in hist['split'].items():
        if sd > d:
            f *= ratio
    return f


def last_close(hist, d):
    """Most recent close on or before d (holds the price through halts)."""
    best = None
    for cd, px in hist['close'].items():
        if cd <= d and (best is None or cd > best[0]):
            best = (cd, px)
    return best


def compute(picks, histories, as_of):
    """Replay the strategy day by day. Pure function: no I/O.

    picks:      [{'date': 'YYYY-MM-DD', 'ticker': ..., ...}]
    histories:  {ticker: fetch_history(...) result}; must include BENCHMARK
    as_of:      date - last day to process
    """
    bench = histories[BENCHMARK]
    days = sorted(d for d in bench['close'] if START <= d <= as_of)
    reviews = review_dates(as_of)

    positions = {}            # ticker -> dict
    pending = []              # picks waiting for their first fill
    queue = sorted(picks, key=lambda p: p['date'])
    tx = []
    invested = cash = dividends = 0.0
    realized = 0.0
    bench_shares = 0.0
    series = []
    done_reviews = set()

    def close_on(t, d):
        h = histories.get(t)
        return h['close'].get(d) if h else None

    for d in days:
        # 1. dividends (ex-date d; positions held before d)
        for t, p in positions.items():
            h = histories[t]
            amt = h['div'].get(d)
            px = close_on(t, d)
            if amt and px:
                shares = p['bought'] + p['drip']
                c = shares * amt
                new = c / px
                p['drip'] += new
                p['div_cash'] += c
                dividends += c
                tx.append({'date': d.isoformat(), 'type': 'DIV', 'ticker': t,
                           'shares': round(new, 6), 'price': round(px, 4),
                           'amount': round(c, 2)})
        bamt = bench['div'].get(d)
        if bamt and bench_shares:
            bench_shares += bench_shares * bamt / bench['close'][d]

        def contribute(amount):
            nonlocal invested, bench_shares
            invested += amount
            bench_shares += amount / bench['close'][d]

        # 2. six-month review: cull to top KEEP, double survivors' bought shares
        due = [r for r in reviews if r <= d and r not in done_reviews]
        if due:
            done_reviews.update(due)
            ranked = []
            for t, p in positions.items():
                lc = last_close(histories[t], d)
                value = (p['bought'] + p['drip']) * lc[1]
                ranked.append(((value - p['cost']) / p['cost'], t, lc[1]))
            ranked.sort(key=lambda r: (-r[0], r[1]))
            for ret, t, px in ranked[KEEP:]:
                p = positions.pop(t)
                shares = p['bought'] + p['drip']
                proceeds = shares * px
                cash += proceeds
                realized += proceeds - p['cost']
                tx.append({'date': d.isoformat(), 'type': 'SELL', 'ticker': t,
                           'shares': round(shares, 6), 'price': round(px, 4),
                           'amount': round(proceeds, 2),
                           'return_pct': round(ret * 100, 2)})
            for ret, t, px in ranked[:KEEP]:
                p = positions[t]
                add = p['bought']
                cost = add * px
                p['bought'] += add
                p['cost'] += cost
                contribute(cost)
                tx.append({'date': d.isoformat(), 'type': 'DOUBLE', 'ticker': t,
                           'shares': round(add, 6), 'price': round(px, 4),
                           'amount': round(cost, 2),
                           'return_pct': round(ret * 100, 2)})

        # 3. buys: this week's pick, plus any earlier pick that had no price yet
        while queue and date.fromisoformat(queue[0]['date']) <= d:
            pending.append(queue.pop(0))
        still = []
        for pk in pending:
            t = pk['ticker']
            px = close_on(t, d)
            if px is None:
                still.append(pk)
                continue
            f = split_factor(histories[t], d)   # 1 real share, in adjusted units
            cost = px * f
            p = positions.setdefault(t, {
                'ticker': t, 'name': pk.get('name', ''), 'exchange': pk.get('exchange', ''),
                'type': pk.get('type', ''), 'bought': 0.0, 'drip': 0.0, 'cost': 0.0,
                'div_cash': 0.0, 'first_bought': d.isoformat()})
            p['bought'] += f
            p['cost'] += cost
            contribute(cost)
            tx.append({'date': d.isoformat(), 'type': 'BUY', 'ticker': t,
                       'shares': round(f, 6), 'price': round(px, 4),
                       'amount': round(cost, 2), 'week': pk.get('week')})
        pending = still

        mv = sum((p['bought'] + p['drip']) * last_close(histories[p['ticker']], d)[1]
                 for p in positions.values())
        series.append({'date': d.isoformat(), 'value': round(mv + cash, 2),
                       'invested': round(invested, 2),
                       'benchmark': round(bench_shares * bench['close'][d], 2)})

    holdings = []
    last_day = days[-1] if days else as_of
    for t, p in positions.items():
        lc = last_close(histories[t], last_day)
        shares = p['bought'] + p['drip']
        value = shares * lc[1]
        holdings.append({
            'ticker': t, 'name': p['name'], 'exchange': p['exchange'], 'type': p['type'],
            'bought_shares': round(p['bought'], 6), 'drip_shares': round(p['drip'], 6),
            'shares': round(shares, 6), 'cost': round(p['cost'], 2),
            'price': round(lc[1], 4), 'price_date': lc[0].isoformat(),
            'value': round(value, 2), 'dividends': round(p['div_cash'], 2),
            'return_pct': round((value - p['cost']) / p['cost'] * 100, 2),
            'first_bought': p['first_bought']})
    holdings.sort(key=lambda h: -h['return_pct'])

    market_value = sum(h['value'] for h in holdings)
    total = market_value + cash
    bench_value = series[-1]['benchmark'] if series else 0.0
    pct = lambda v: round((v - invested) / invested * 100, 2) if invested else 0.0
    return {
        'as_of': last_day.isoformat() if days else None,
        'summary': {
            'invested': round(invested, 2), 'market_value': round(market_value, 2),
            'cash': round(cash, 2), 'total_value': round(total, 2),
            'total_return_pct': pct(total), 'realized_pl': round(realized, 2),
            'dividends': round(dividends, 2), 'positions': len(holdings),
            'benchmark': BENCHMARK, 'benchmark_value': round(bench_value, 2),
            'benchmark_return_pct': pct(bench_value),
        },
        'holdings': holdings,
        'pending': [{'ticker': p['ticker'], 'name': p.get('name', ''), 'date': p['date']}
                    for p in pending + queue],
        'transactions': tx[::-1],
        'series': series,
    }


# ---------------------------------------------------------------- runner

def today_et():
    return datetime.now(ET).date()


def make_due_picks(picks, today, fetch=fetch_history):
    """Append a random pick for every scheduled Monday that lacks one."""
    universe = json.load(open(UNIVERSE))
    have = {p['date'] for p in picks}
    made = []
    for i, d in enumerate(pick_dates(today)):
        if d.isoformat() in have:
            continue
        # Redraw until the pick has market data; record every draw for audit.
        rejected = []
        while True:
            s = universe[secrets.randbelow(len(universe))]
            try:
                ok = fetch(s['symbol'], d - timedelta(days=30), today) is not None
            except RuntimeError:
                ok = False
            if ok:
                break
            rejected.append(s['symbol'])
            if len(rejected) > 25:
                raise RuntimeError('price source unavailable; refusing to pick')
        pick = {'week': i + 1, 'date': d.isoformat(), 'ticker': s['symbol'],
                'name': s['name'], 'exchange': s['exchange'], 'type': s['type'],
                'universe_size': len(universe),
                'picked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'rng': 'python secrets.randbelow'}
        if rejected:
            pick['redrawn_no_data'] = rejected
        picks.append(pick)
        made.append(pick)
    return made


def main():
    today = today_et()
    picks = json.load(open(PICKS)) if os.path.exists(PICKS) else []
    if '--no-pick' not in sys.argv:
        for p in make_due_picks(picks, today):
            print(f"week {p['week']}: picked {p['ticker']} ({p['name']})")
        json.dump(picks, open(PICKS, 'w'), indent=2)
        open(PICKS, 'a').write('\n')

    base = {
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'rules': {'start': START.isoformat(), 'review_weeks': REVIEW_WEEKS,
                  'keep': KEEP, 'benchmark': BENCHMARK},
        'next_pick': next_after(today, START, 1).isoformat(),
        'next_review': next_after(today, START + timedelta(weeks=REVIEW_WEEKS),
                                  REVIEW_WEEKS).isoformat(),
        'picks': picks,
    }

    if not picks:
        result = {'status': 'not_started', 'as_of': None, 'holdings': [], 'pending': [],
                  'transactions': [], 'series': [], 'summary': None}
    else:
        tickers = sorted({p['ticker'] for p in picks} | {BENCHMARK})
        histories = {}
        for t in tickers:
            h = fetch_history(t, START, today)
            if h is None:
                print(f'warning: no data for {t}; position valued at last known price')
                h = {'close': {}, 'div': {}, 'split': {}}
            histories[t] = h
            time.sleep(0.5)
        result = compute(picks, histories, today)
        result['status'] = 'active'
        s = result['summary']
        print(f"{result['as_of']}: {s['positions']} positions, value ${s['total_value']:,.2f} "
              f"on ${s['invested']:,.2f} ({s['total_return_pct']:+.2f}%) "
              f"vs {BENCHMARK} {s['benchmark_return_pct']:+.2f}%")

    base.update(result)
    json.dump(base, open(OUT, 'w'), indent=1)
    open(OUT, 'a').write('\n')


if __name__ == '__main__':
    main()
