"""Reproducible experiment runner and standalone HTML report."""
import argparse
import csv
from dataclasses import asdict, replace
import hashlib
import html
import json
from pathlib import Path

from .core import Config, backtest, bootstrap_mean_ci, read_csv, summary, synthetic


def chart(rows):
    values = [1.0] + [r['equity'] for r in rows]
    low, high = min(values), max(values)
    span = max(high-low, 0.001)
    points = ' '.join(f'{65+i/(len(values)-1)*810:.1f},{230-(v-low)/span*185:.1f}' for i,v in enumerate(values))
    baseline = 230-(1-low)/span*185
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 920 280" role="img" aria-label="Net equity on synthetic or supplied data">
<rect width="920" height="280" fill="#101e31"/>
<line x1="65" x2="875" y1="{baseline}" y2="{baseline}" stroke="#72839c" stroke-dasharray="5 5"/>
<polyline points="{points}" fill="none" stroke="#54ddbc" stroke-width="2"/>
<g fill="#b6c5da" font-family="sans-serif" font-size="13"><text x="10" y="50">{high:.2f}</text>
<text x="10" y="230">{low:.2f}</text><text x="65" y="260">{rows[0]['date']}</text>
<text x="790" y="260">{rows[-1]['date']}</text></g></svg>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, help='Adjusted closes: date,a,b; sorted and aligned')
    parser.add_argument('--out', type=Path, default=Path('reports/demo'))
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--cost-bps', type=float, default=5)
    args = parser.parse_args()
    bars = read_csv(args.csv) if args.csv else synthetic(seed=args.seed)
    cfg = Config(cost_bps=args.cost_bps)
    rows, folds = backtest(bars, cfg)
    metrics = summary(rows)
    sensitivity = []
    for cost in (0, 2, 5, 10, 20):
        trial, _ = backtest(bars, replace(cfg, cost_bps=cost))
        sensitivity.append({'one_way_cost_bps': cost, **summary(trial)})
    ci = bootstrap_mean_ci(rows)
    canonical = '\n'.join(f'{b.date},{b.a:.17g},{b.b:.17g}' for b in bars)
    source = 'USER-SUPPLIED CSV (provenance not independently verified)' if args.csv else 'SYNTHETIC DATA — SOFTWARE DEMONSTRATION ONLY'
    payload = {'source': source, 'seed': None if args.csv else args.seed,
               'input_sha256': hashlib.sha256(canonical.encode()).hexdigest(),
               'config': asdict(cfg), 'metrics': metrics, 'folds': folds,
               'annualized_mean_ci_95': ci, 'cost_sensitivity': sensitivity}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'summary.json').write_text(json.dumps(payload, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    with (args.out/'daily.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    svg = chart(rows)
    (args.out/'equity.svg').write_text(svg, encoding='utf-8')
    cards = ''.join(f'<article><small>{label}</small><strong>{value}</strong></article>' for label,value in (
        ('Net return',f"{metrics['total_return']:.1%}"), ('Sharpe · zero risk-free',f"{metrics['sharpe_zero_rf']:.2f}"),
        ('Max drawdown',f"{metrics['max_drawdown']:.1%}"), ('OOS observations',str(len(rows)))))
    table = ''.join(f"<tr><td>{r['one_way_cost_bps']}</td><td>{r['total_return']:.1%}</td><td>{r['sharpe_zero_rf']:.2f}</td><td>{r['max_drawdown']:.1%}</td></tr>" for r in sensitivity)
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SpreadLab | Research tear sheet</title><style>
body{{background:#091322;color:#eaf0f9;font:16px/1.6 system-ui;margin:0}}main{{max-width:1040px;margin:auto;padding:48px 24px}}
h1{{font-size:52px;margin:12px 0}}h2{{font-size:22px;margin-top:36px}}.eyebrow,small{{color:#9cb1ce}}.badge{{color:#ffd184}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}}article{{padding:20px;background:#101e31;border-radius:10px}}strong{{display:block;font-size:30px}}
svg{{width:100%;border-radius:10px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:12px;text-align:left;border-bottom:1px solid #28374c}}p{{max-width:850px}}code{{overflow-wrap:anywhere}}</style>
<main><div class="eyebrow">QUANTITATIVE RESEARCH / WALK-FORWARD EXPERIMENT</div><h1>SpreadLab</h1>
<p class="badge">{html.escape(source)}</p><p>Can a lagged residual-reversion signal survive execution delay, regime stress and trading costs?</p>
<div class="cards">{cards}</div><h2>Net equity · initial capital = 1</h2>{svg}
<h2>Cost sensitivity</h2><p>Basis points per unit of one-way traded notional. Every scenario retains 100 bps/year borrow on short exposure.</p>
<table><tr><th>Cost (bps)</th><th>Net return</th><th>Sharpe</th><th>Max drawdown</th></tr>{table}</table>
<h2>Research protocol</h2><p>252 observations for formation; 63 for trading. Frozen OLS hedge and residual scale within each fold.
Signal from the previous close; trade at the current close; returns accrue only after execution. Each fold liquidates with costs. Gross exposure is capped at one.</p>
<h2>Uncertainty and limits</h2><p>95% circular block-bootstrap interval for annualized arithmetic mean: {ci[0]:.1%} to {ci[1]:.1%}.
1,000 samples, 20-day blocks, fixed seed. This conditional interval omits model selection and refitting uncertainty and is unreliable across structural breaks.</p>
<p>Synthetic mean reversion is built into the generator. This result does not establish tradable alpha. No formal cointegration gate, market impact, locate availability, interest on cash or short-sale proceeds is modeled. Stops execute with a delay and do not cap losses.</p>
<h2>Reproducibility</h2><p>Input SHA-256: <code>{payload['input_sha256']}</code>. Full fold boundaries, settings and metrics are in summary.json; all portfolio observations are in daily.csv.</p></main></html>'''
    (args.out/'index.html').write_text(page, encoding='utf-8')
    print(json.dumps(metrics, indent=2))
    print(f'Report: {args.out / "index.html"}')
