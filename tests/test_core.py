import math
import unittest
from dataclasses import replace
from spreadlab.core import Bar, Config, backtest, fit, synthetic, validate


class ResearchInvariants(unittest.TestCase):
    def setUp(self):
        self.bars = synthetic(650)
        self.cfg = Config(train=126, test=63)

    def test_future_prices_do_not_change_past_decisions(self):
        original, _ = backtest(self.bars, self.cfg)
        changed = self.bars[:400] + [replace(b, a=b.a*1.5) for b in self.bars[400:]]
        altered, _ = backtest(changed, self.cfg)
        self.assertEqual(original[:274], altered[:274])
        # A shock at close 400 cannot affect the signal computed at close 399.
        self.assertEqual(original[274]['z_signal'], altered[274]['z_signal'])

    def test_return_accounting_uses_previous_holdings(self):
        rows, _ = backtest(self.bars, self.cfg)
        for i in range(1, len(rows)):
            t = i+self.cfg.train
            expected = rows[i-1]['weight_a']*(self.bars[t].a/self.bars[t-1].a-1)
            expected += rows[i-1]['weight_b']*(self.bars[t].b/self.bars[t-1].b-1)
            self.assertAlmostEqual(rows[i]['gross_return'], expected)
            self.assertAlmostEqual(rows[i]['net_return'], rows[i]['gross_return']-rows[i]['cost_return'])

    def test_fold_boundaries_and_gross_exposure(self):
        rows, folds = backtest(self.bars, self.cfg)
        for fold in folds:
            self.assertLess(fold['train_end'], fold['test_start'])
            last = next(r for r in rows if r['date'] == fold['test_end'])
            self.assertEqual(last['weight_a'], 0)
            self.assertEqual(last['weight_b'], 0)
        for r in rows:
            self.assertLessEqual(abs(r['weight_a'])+abs(r['weight_b']), 1+1e-12)

    def test_flat_prices_stay_flat(self):
        bars = [replace(b, a=100, b=100) for b in self.bars]
        self.assertIsNone(fit(bars[:126]))
        rows, _ = backtest(bars, self.cfg)
        self.assertTrue(all(r['equity'] == 1 for r in rows))

    def test_validation(self):
        for price in (0, -1, math.inf, math.nan):
            with self.assertRaises(ValueError):
                validate([Bar('2020-01-01', price, 100)])
        with self.assertRaises(ValueError):
            validate([self.bars[0], self.bars[0]])
        with self.assertRaises(ValueError):
            Config(entry=0)

    def test_reproducibility(self):
        self.assertEqual(synthetic(100), synthetic(100))
        self.assertEqual(backtest(self.bars, self.cfg), backtest(self.bars, self.cfg))

    def test_costs_reduce_fixture_performance(self):
        cheap, _ = backtest(self.bars, replace(self.cfg, cost_bps=0))
        costly, _ = backtest(self.bars, replace(self.cfg, cost_bps=20))
        self.assertLess(costly[-1]['equity'], cheap[-1]['equity'])


if __name__ == '__main__':
    unittest.main()
