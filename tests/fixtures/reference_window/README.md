# Reference window (golden test, SC-006)

Inputs of one matching window, recorded with this service's own gateways, plus the classification
the original research prototype produced for the same window. `tests/golden/test_reference_window.py`
runs the matching domain over these inputs and requires at least 99 % agreement on `status`,
`match_type` and `alpaca_symbol` over the epics present on both sides. Epics present on only one
side (catalog churn between the two recordings) are reported, not failed.

| Item | Value |
|---|---|
| Window end (`--end`) | `2026-10-08T06:00:00+00:00` (outside market hours) |
| Window | 20 sessions, 2026-09-10 13:00 → 2026-10-07 20:00 UTC, 1-hour bars, SIP feed |
| Thresholds | the defaults in `config/thresholds.yaml` |
| Baseline | prototype re-run on 2026-10-18 with `--end 2026-10-08T06:00:00+00:00` from its own cache of the 2026-10-08 reference run (its working tree has no commit); 3,587 epics: 3,423 exact, 52 alias, 1 ambiguous, 111 unmatched |
| Inputs recorded | 2026-10-18 with this service's gateways: 3,587 epics, 33,577 Alpaca assets, 3,585 Capital.com histories, 3,858 symbols with bars (`meta.json`) |
| Result | 3,580 epics in common, 3,577 agree (99.92 %); 7 epics only on each side (catalog churn) |

The three differences come from inputs that changed between 2026-10-08 and 2026-10-18, not from the
matching logic:

| Epic | Baseline | Service | Why |
|---|---|---|---|
| `BRUN` | matched (diff 0.06 %) | unmatched, `failed_price_check` (diff 56 %, 60 aligned bars) | the recorded bar history for the window differs (a corporate action since 2026-10-08 changed one side's past prices) |
| `TCBI` | unmatched, `not_listed_on_alpaca` | matched exact | Alpaca now lists the common stock `TCBI`; on 2026-10-08 it had only preferreds |
| `TFPN` | unmatched, `failed_behavior_check` | matched exact | the Capital.com quotes recorded for the window differ (different spread and moves) |

## Files

| File | Content |
|---|---|
| `meta.json` | window end, window, thresholds, record time, counts |
| `sessions.json` | the 20 sessions as `[open, close]` UTC |
| `universe.json` | the Capital.com US share universe (catalogs + sweep) |
| `assets.json.gz` | every Alpaca `us_equity` asset |
| `capital_bars.json.gz` | hourly bid/ask closes per epic, or why there are none |
| `alpaca_bars.json.gz` | hourly closes per candidate symbol |
| `expected_mapping.json` | baseline classification per epic |

Large inputs are gzip-compressed JSON (rather than one file per epic) to keep the fixture small.

## Refreshing

Do all steps in one session on the same day, with the same window end:

1. Pick a past window end outside market hours, e.g. `2026-10-08T06:00:00+00:00`.
2. Record the inputs with this service's gateways:

   ```bash
   ALPACA_API_KEY=… ALPACA_API_SECRET=… COLLECTOR_URL=http://localhost:8001 \
       uv run python -m scripts.record_reference_window --end 2026-10-08T06:00:00+00:00
   ```

3. Run the prototype outside this repository with the same `--end` and default thresholds.
4. Convert its `mapping.csv`:
   `uv run python scripts/convert_baseline.py path/to/mapping.csv`
   (`matched_exact` → `matched/exact`, `matched_alias` → `matched/alias`; other statuses keep
   their reason code).
5. Update this README, then run `uv run pytest tests/golden`.
