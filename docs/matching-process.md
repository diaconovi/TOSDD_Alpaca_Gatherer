# Capital.com → Alpaca matching: the process as implemented

This document describes how Alpaca Gatherer maps every Capital.com US share **epic** to an Alpaca
**symbol** (FR-032). It is adapted from the documentation of the original research prototype and
checked against this service's code; the differences are listed at the end.

The code lives in `src/alpaca_gatherer/domain/matching/` (pure functions, no I/O). Data is fetched
by `application/runs/market_data.py` through the collector gateway and the Alpaca gateway.

## Overview

| Stage | Module | Output |
|---|---|---|
| 1. Universe | `universe.py` | Capital.com US shares (catalogs + epic sweep) |
| 2. Alpaca assets | Alpaca gateway | every `us_equity` asset, all statuses |
| 3. Candidates | `normalize.py`, `candidates.py` | exact → alias → name candidates per epic |
| 4. Window and alignment | `window.py` | the last N complete sessions; bars aligned on UTC hours |
| 5. Price check | `checks.py` | sanity filter on the median price difference |
| 6. Behavior check | `checks.py` | co-movement of returns (hourly, else session-close) |
| 7. Tradability | `checks.py` | checked last |
| 8. Classification | `classify.py` | `matched` / `ambiguous` / `unmatched` + reason |
| 9. Symbol-conflict pass | `classify.py` | one matched symbol per epic |

Every run covers the whole universe; the comparison window ends at the run's start time
(`price_window_end = started_at`, FR-008). A run writes a staging collection and swaps it in
atomically only when everything succeeded.

## 1. Capital.com US share universe

The collector exposes four ranked US catalogs (`most_traded`, `top_gainers`, `top_losers`,
`most_volatile`), each capped at 500 instruments by Capital.com. Their union misses large names that
are in the middle of every ranking, so the universe is built from two sources:

1. **Catalog union**: every `SHARES` instrument of the four `us` catalogs.
2. **Epic sweep**: for every *active* Alpaca symbol, the plausible epic spellings (`BRK.B` → `BRKB`,
   plus the `…US` suffix form `BRKBUS`) are looked up with `search_markets`, 50 epics per call
   (unknown epics are silently dropped by Capital.com; a batch rejected with HTTP 400 is split in
   half so one malformed epic cannot hide the others). A swept market is kept only if it is
   `SHARES`, priced in `USD`, and its weekday opening hours (UTC) end at the US cash close
   (20:00 or 21:00 UTC) or run 24 h.

An epic found by both sources keeps `source = catalog`.

## 2. Alpaca assets

`GET /v2/assets?asset_class=us_equity` returns every status. Inactive and non-tradable assets are
kept so that an epic whose only counterpart cannot be traded is reported as `not_tradable` rather
than `not_listed_on_alpaca`.

## 3. Candidates

| Kind | Rule | Example |
|---|---|---|
| `exact` | Alpaca symbol equals the epic | `TSLA` → `TSLA` |
| `alias` | Spellings implied by the epic and Capital.com's `symbol` field: uppercase alphanumerics (`BRK.B` = `BRK/B` = `BRKb`); a lowercase `us` or ` US` suffix marks the US line (`AXONus`, `NLOP US`); a trailing lowercase letter is a share class (`HEIa` → `HEI.A`); `/` becomes `.` (`GME/WS` → `GME.WS`); the class root reaches every class (`BRK` → `BRK.A`, `BRK.B`) | `MTUS` → `MT`, `BRKB` → `BRK.B` |
| `name` | Only when **no identifier candidate passes the price check**. The company name is normalized (lowercase, legal suffixes and share-class words removed) and compared with every active Alpaca name: accepted on a `difflib` ratio ≥ `name_ratio`, or when every token of the Capital.com name appears in the Alpaca name with the same first token. At most `max_name_candidates`. | `BLL` → `BALL`, `BIGC` → `CMRC` |

Inactive identifier candidates are kept only when no active one matched. Generation is
deliberately generous: a wrong candidate costs one comparison, and the checks reject it.

The name fallback is gated on "no identifier candidate passed price": without the gate a quiet
bond ETF whose own symbol failed the behavior check could be "rescued" by a ladder sibling with a
similar name and price.

## 4. Window and alignment

* **Window**: the last `window.sessions` *complete* sessions of the Alpaca trading calendar, each
  closed at least `window.embargo_minutes` before the window end (this also keeps requests outside
  the free tier's 15-minute SIP embargo). Both brokers are queried over
  `[floor(first open), last close]` in UTC; the window is stored on the run.
* **Bars**: 1-hour bars on both sides, labelled by their UTC start. Capital.com: mid close
  `(bid + ask) / 2` and relative spread `(ask − bid) / mid`. Alpaca: close (last trade), requested
  with `adjustment=raw` (Capital.com quotes are not split- or dividend-adjusted) and the
  `window.feed` feed.
* **Regular session only**: a bar is kept when it starts in `[floor(open), close)` of a calendar
  session (DST and half days come from the calendar).
* **Join**: inner join on identical UTC timestamps; bars with a non-positive price are dropped.
  Fewer than `window.min_bars` aligned bars → `insufficient_data`, with each side's bar count.

## 5. Price check (sanity filter)

```
price_diff_pct = median over aligned bars of |cap_mid − alpaca_close| / alpaca_close × 100
tolerance      = price.price_tol_pct + price.spread_mult × median(cap_spread / cap_mid) × 100
```

The median makes one stale bar harmless. The base tolerance absorbs timing noise (last trade vs
last quote); the half-spread allowance covers asymmetric markups on low-priced names. Share-class
siblings (`LEN` vs `LEN.B`) correlate almost perfectly, so the price check is the only guard
against them: **do not loosen it much beyond ~1.5 %.**

## 6. Behavior check (decisive)

Log returns between consecutive aligned bars, at two horizons built from the same timestamps:

* **Hourly**: every consecutive aligned pair. Direction agreement counts only *significant* pairs,
  where both sides moved and at least one move exceeds the Capital.com median relative spread
  (smaller moves are bid/ask bounce).
* **Session**: the last aligned bar of each session (session-close to session-close); every
  non-flat pair counts.

Metrics: `return_correlation` (Pearson) and `direction_agreement` (share of significant pairs moving
the same way).

1. **Hourly passes** with at least `behavior.min_sig_moves` significant moves, correlation ≥
   `behavior.corr_threshold` and direction ≥ `behavior.dir_threshold`; otherwise
2. **Session passes** with at least `behavior.min_session_returns` non-flat returns and the same two
   thresholds; otherwise
3. **Fail**: `failed_behavior_check`, or `insufficient_data` if neither horizon had enough moves.

The reported metrics and `horizon` come from the horizon that decided.

## 7. Tradability

Checked last, so a correct but untradable counterpart is reported as `not_tradable` instead of
being hidden behind a data failure: the asset must be `active` and `tradable`.

## 8. Classification

| Status | `match_type` | Rule |
|---|---|---|
| `matched` | `exact` | the exact candidate passes every check (preferred even if an alias also passes) |
| `matched` | `alias` | no exact pass; exactly one alias or name candidate passes |
| `ambiguous` | — | several non-exact candidates pass (`multiple_candidates`), or only a name candidate passes while an identifier candidate could not be checked for lack of data (`name_only_with_unchecked_identifier`), or a conflict (below) |
| `unmatched` | — | nothing passes |

For `unmatched`, the reason comes from the candidate that got furthest (behavior > passed price
but too quiet > price > no data); if nothing got past price and an exact candidate exists, the
exact one is reported.

| Reason | Meaning |
|---|---|
| `not_listed_on_alpaca` | no identifier or name candidate exists |
| `not_tradable` | the counterpart passes the data checks but is not tradable or not active, or only inactive Alpaca assets match |
| `insufficient_data` | no Capital.com hourly history (HTTP 404), too few aligned bars (both counts given), no Alpaca bars, or too few moves to judge |
| `failed_price_check` | every candidate is outside the price tolerance |
| `failed_behavior_check` | price is fine but the returns do not co-move enough at either horizon |
| `multiple_candidates` | (ambiguous) several candidates pass |
| `name_only_with_unchecked_identifier` | (ambiguous) the identifier points elsewhere but has no data |
| `symbol_conflict` | (ambiguous) another epic matched the same symbol |

`ambiguous` records carry no `alpaca_symbol`; their `candidates` list the candidates that passed
(plus the unchecked identifier candidates for `name_only_with_unchecked_identifier`).

## 9. One symbol per match

After classification, if several epics are matched to the same symbol, all of them become
`ambiguous` with reason `symbol_conflict` listing the competing epics. A symbol lookup therefore
returns at most one epic (the database also enforces it with a unique partial index).

## Thresholds

Loaded from `THRESHOLDS_FILE` (default `config/thresholds.yaml`) at startup; `GET
/api/v1/thresholds` returns them.

| Group | Field | Default | Meaning |
|---|---|---|---|
| `candidates` | `name_ratio` | 0.90 | minimum `difflib` ratio for a name candidate |
| `candidates` | `max_name_candidates` | 3 | name candidates kept per epic |
| `window` | `sessions` | 20 | complete sessions in the window |
| `window` | `embargo_minutes` | 20 | a session must have closed this long before the window end |
| `window` | `min_bars` | 60 | minimum aligned regular-session hourly bars (~43 % of ~140) |
| `window` | `feed` | `sip` | Alpaca data feed (`sip` or `iex`; IEX is ~2–3 % of volume) |
| `price` | `price_tol_pct` | 1.0 | base price tolerance, % of the Alpaca price |
| `price` | `spread_mult` | 0.5 | extra tolerance per unit of Capital.com relative spread |
| `behavior` | `corr_threshold` | 0.70 | minimum Pearson correlation of returns |
| `behavior` | `dir_threshold` | 0.75 | minimum direction agreement |
| `behavior` | `min_sig_moves` | 10 | significant hourly moves needed to judge the hourly horizon |
| `behavior` | `min_session_returns` | 12 | non-flat session returns needed for the session fallback |

The defaults are the values the reference run validated: accepted matches had a median price
difference of 0.027 % (max 1.34 %), wrong candidates rejected on price were at least 1.60 % away,
and 276 of 3,475 matches (quiet bond and T-bill ETFs, thin small caps) passed only on the session
horizon.

## Retries, rate limits and caching

* **Collector**: every call runs in a worker thread with at most 4 in flight (the collector also
  rate-limits globally); connection errors, HTTP 5xx and 429 are retried with exponential backoff
  and jitter, 5 attempts. Persistent failure ends the run as `collector_unavailable`. HTTP 404 on
  prices means "no hourly history" and is not retried.
* **Alpaca**: assets and calendar once; bars 100 symbols per request, following `next_page_token`;
  same retry policy. 401/403 ends the run as `alpaca_auth_failed`; persistent 429/5xx/network
  errors as `alpaca_unavailable`. A batch rejected with 400/422 is split so one bad symbol is
  skipped alone.
* **No local cache**: the service is stateless, so every run fetches everything (about 20 minutes
  for the full universe, inside the 30-minute budget of SC-005).

## Run outcomes

| `error.code` | Cause |
|---|---|
| `collector_unavailable` | the collector could not be reached or kept failing |
| `collector_incomplete_data` | no US catalogs, a catalog failed, or the universe is empty |
| `alpaca_unavailable` | Alpaca could not be reached, kept failing, returned no assets, or the calendar lacks enough complete sessions |
| `alpaca_auth_failed` | Alpaca rejected the credentials |
| `credentials_missing` | a scheduled run fired before credentials were registered |
| `credentials_undecryptable` | the encryption key changed; update the credentials |
| `skipped_concurrent_run` | a scheduled run fired while another run was running |
| `interrupted_by_restart` | the service stopped during the run |
| `internal_error` | anything unexpected (details only in the service log) |

A failed run never touches the live mapping.

## Known limitations

* **Universe completeness**: a Capital.com US share is found only if it is in a top-500 catalog or
  its epic is a spelling derived from an active Alpaca symbol. A stale ticker outside every catalog
  (e.g. `BLL`) is invisible to that run. Catalogs churn daily, so repeated runs widen coverage.
* **Hourly-history gaps on Capital.com**: some epics (`BIL`, `XLB`, `BOND`, …) return HTTP 404 for
  hourly prices; they stay `insufficient_data`.
* **Sparse Capital.com quotes**: for many low-volatility ETFs Capital.com emits a bar only when its
  quote changes, so as few as 2–3 bars exist in 20 sessions.
* **Feed differences**: Alpaca's close is the last trade, Capital.com's is a quote mid; illiquid
  names show more price noise and lower hourly correlation.
* **Share classes are separated by price, not behavior** (see §5). If two classes ever traded within
  ~1.5 % of each other the result would be `ambiguous`, not a silent mis-mapping.
* **Corporate actions inside the window** (splits, ticker changes) break the price comparison for
  that window; a later run whose window excludes the action resolves it.
* **Renamed tickers**: Capital.com keeps the old epic after a ticker change (`BAM` → `BN`); these
  are matched by name and are the mappings most likely to change, so run regularly.
* **Single instance**: a schedule change reaches other instances only after their restart.

## Agreement with the prototype (SC-006)

On the reference window ending 2026-10-08 06:00 UTC, the service agrees with the prototype on
3,577 of 3,580 common epics (99.92 %). The three differences (`BRUN`, `TCBI`, `TFPN`) are caused by
inputs that changed between the two recordings, not by the matching logic; see
`tests/fixtures/reference_window/README.md`.

## Differences from the prototype

* Status `matched_exact` / `matched_alias` became `status = matched` with `match_type = exact|alias`.
* Matched symbols are one-to-one: competing epics become `ambiguous/symbol_conflict` (the prototype
  never met this case).
* `ambiguous` and `unmatched` records carry no `alpaca_symbol`; the symbols remain in `candidates`.
* A matched record has no reason; when an alias also passed next to the exact symbol, it is visible
  in `candidates` instead of a free-text note.
* A collector or Alpaca failure that persists after retries fails the whole run (the previous
  mapping stays live) instead of marking the affected epics `insufficient_data`.
* No on-disk cache; the window always ends at the run's start time.
