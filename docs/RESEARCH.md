# Research memo

## Hypothesis and scope

A sufficiently stable long-run relationship between two price series may yield
short-horizon residual reversion. This repository tests the implementation of
that idea on a controlled data-generating process. It does not test whether a
specific tradable pair has that relationship.

The synthetic generator combines a random-walk common factor with an AR(1)
spread. Observations 700 through 949 use persistence 0.98 and innovation scale
0.014, versus 0.88 and 0.008 otherwise. That regime is specified before running
the experiment. This is stress within a still mean-reverting world, not a
permanent relationship break or a comprehensive null test.

## Leakage controls

For trading start index s, formation uses [s-252, s), exclusively. The trained
model stays fixed until the next fold. A trade executed at t uses prices at
t-1 and receives no exposure to the t-1 to t move before execution. Today's
price affects today's execution notional and tomorrow's signal, not the signal
used to decide today's trade. The test suite modifies future prices and checks
the earlier observations remain bit-for-bit identical.

The known final observation of each fold is liquidated. Truncating a dataset
inside a fold therefore changes its terminal liquidation; invariance is tested
with a fixed horizon and perturbed future, not incompatible terminal policies.

## Deliberate omissions

- No selection of candidate pairs or formal cointegration significance gate.
- No bid/ask or order book, impact, capacity, partial fills, or auction slippage.
- No borrow availability, recalls, dividends owed on shorts, taxes or financing interest.
- Adjusted closes are treated as synthetic execution prices; real corporate
  actions require raw execution prices and explicit cash-flow handling.
- No market calendar or point-in-time security master.
- No calibration or performance claims against real market data.
- No hyperparameter optimizer: the report is descriptive, not a selection rule.

## Next empirical experiment

1. Choose a fixed economic universe before observing performance. Record source,
   licensing, symbols, adjustment convention, retrieval date and SHA-256.
2. Separate a final chronological holdout. Select pairs and parameters using only
   earlier formation/validation data. Correct for searching multiple pairs.
3. Compare against flat cash, a simple fixed spread strategy and the relevant
   market/sector benchmark with matched capital conventions.
4. Report per-fold performance, parameter neighborhoods, persistent-break and
   independent-random-walk nulls, turnover and executable dollar capacity.
5. Estimate realistic costs and locate constraints; then paper trade with a
   locked specification. Keep failed experiments as well as successful ones.

## Engineering tradeoff

Standard-library Python keeps the reference calculation short and inspectable.
Formation OLS and loop-based accounting favor auditability over throughput.
Before scaling to a large universe, profile, add typed array inputs and compare
an optimized implementation against this reference on adversarial fixtures.
