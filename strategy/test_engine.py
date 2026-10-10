"""Rule tests for the Random Strategy ledger, on synthetic price data.

    python3 -m unittest strategy/test_engine.py
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import engine  # noqa: E402
from engine import START, compute, yahoo_symbol  # noqa: E402


def weekdays(start, n_days):
    d, out = start, []
    while len(out) < n_days:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = weekdays(START, 300)


def flat(px, div=None, split=None):
    return {'close': {d: px for d in DAYS}, 'div': div or {}, 'split': split or {}}


def picks_for(tickers):
    return [{'week': i + 1, 'date': (START + timedelta(weeks=i)).isoformat(), 'ticker': t}
            for i, t in enumerate(tickers)]


class Rules(unittest.TestCase):
    def test_weekly_buy_one_share(self):
        h = {'SPY': flat(100), 'AAA': flat(10), 'BBB': flat(20)}
        r = compute(picks_for(['AAA', 'BBB']), h, START + timedelta(days=10))
        self.assertEqual(r['summary']['invested'], 30)
        self.assertEqual({x['ticker']: x['shares'] for x in r['holdings']}, {'AAA': 1, 'BBB': 1})

    def test_holiday_monday_fills_next_trading_day(self):
        h = {'SPY': flat(100), 'AAA': flat(10)}
        del h['SPY']['close'][START]
        del h['AAA']['close'][START]
        r = compute(picks_for(['AAA']), h, START + timedelta(days=3))
        buy = [t for t in r['transactions'] if t['type'] == 'BUY'][0]
        self.assertEqual(buy['date'], (START + timedelta(days=1)).isoformat())

    def test_dividends_reinvested_but_not_doubled(self):
        ex = START + timedelta(days=15)
        h = {'SPY': flat(100), 'AAA': flat(10, div={ex: 1.0})}
        tickers = ['AAA'] + [f'Z{i}' for i in range(25)]
        for t in tickers[1:]:
            h[t] = flat(10)
        review = START + timedelta(weeks=26)
        r = compute(picks_for(tickers), h, review)
        a = next(x for x in r['holdings'] if x['ticker'] == 'AAA')
        self.assertAlmostEqual(a['drip_shares'], 0.1)      # $1 div / $10 px
        self.assertAlmostEqual(a['bought_shares'], 2)      # 1 doubled, DRIP excluded
        self.assertAlmostEqual(a['shares'], 2.1)

    def test_review_keeps_top_12_and_doubles(self):
        h = {'SPY': flat(100)}
        tickers = [f'T{i:02d}' for i in range(26)]
        review = START + timedelta(weeks=26)
        for i, t in enumerate(tickers):
            # each ticker ends up i% above its purchase price at review time
            h[t] = {'close': {d: (10 if d < review else 10 * (1 + i / 100)) for d in DAYS},
                    'div': {}, 'split': {}}
        picks = picks_for(tickers + ['NEW'])
        h['NEW'] = flat(5)
        r = compute(picks, h, review)
        held = {x['ticker']: x for x in r['holdings']}
        self.assertEqual(set(held), set(tickers[-12:]) | {'NEW'})  # NEW bought after review
        for t in tickers[-12:]:
            self.assertEqual(held[t]['bought_shares'], 2)
        self.assertEqual(held['NEW']['bought_shares'], 1)
        sells = [t for t in r['transactions'] if t['type'] == 'SELL']
        self.assertEqual(len(sells), 14)
        # 26 x $10 buys + 12 doublings at survivor prices + $5 NEW
        doubled = sum(10 * (1 + i / 100) for i in range(14, 26))
        self.assertAlmostEqual(r['summary']['invested'], 260 + doubled + 5, places=2)

    def test_split_counts_real_shares(self):
        sd = START + timedelta(days=20)
        # adjusted series: $50 throughout (was $100 real before 2:1 split)
        h = {'SPY': flat(100), 'AAA': flat(50, split={sd: 2.0})}
        r = compute(picks_for(['AAA']), h, START + timedelta(days=30))
        a = r['holdings'][0]
        self.assertEqual(a['shares'], 2)       # bought 1 real share -> 2 after split
        self.assertEqual(a['cost'], 100)       # paid the real $100
        self.assertEqual(a['return_pct'], 0)

    def test_benchmark_matches_contributions(self):
        h = {'SPY': flat(100), 'AAA': flat(10)}
        h['SPY']['close'] = {d: 100 + i for i, d in enumerate(DAYS)}
        r = compute(picks_for(['AAA']), h, DAYS[10])
        self.assertAlmostEqual(r['summary']['benchmark_value'], 10 * 110 / 100, places=2)

    def test_due_picks_redraw_when_no_data(self):
        calls = []

        def fake_fetch(t, a, b):
            calls.append(t)
            return None if len(calls) == 1 else flat(1)
        picks = []
        made = engine.make_due_picks(picks, START + timedelta(days=8), fetch=fake_fetch)
        self.assertEqual([p['date'] for p in made],
                         [START.isoformat(), (START + timedelta(weeks=1)).isoformat()])
        self.assertEqual(made[0]['redrawn_no_data'], [calls[0]])
        self.assertEqual(engine.make_due_picks(picks, START + timedelta(days=8), fetch=fake_fetch), [])
        self.assertEqual(engine.make_due_picks([], START - timedelta(days=1), fetch=fake_fetch), [])

    def test_yahoo_symbols(self):
        self.assertEqual(yahoo_symbol('ABR$D'), 'ABR-PD')
        self.assertEqual(yahoo_symbol('BRK.B'), 'BRK-B')
        self.assertEqual(yahoo_symbol('AAPL'), 'AAPL')

    def test_schedule(self):
        self.assertEqual(START.weekday(), 0)
        self.assertEqual(engine.next_after(START - timedelta(days=2), START, 1), START)
        self.assertEqual(engine.next_after(START, START, 1), START + timedelta(weeks=1))


if __name__ == '__main__':
    unittest.main()
