"""Candidate generation: exact symbol, identifier aliases, then company name.

Generation is generous: a wrong candidate costs one comparison and the checks reject it.

>>> from alpaca_gatherer.domain.mapping import Source
>>> index = AlpacaIndex([AlpacaAsset("BRK.B", "Berkshire Hathaway", "NYSE", True, True)])
>>> inst = CapitalInstrument("BRKB", "BRKb", "Berkshire Hathaway Inc - B", "SHARES", Source.CATALOG)
>>> [(c.symbol, c.kind.value) for c in index.identifier_candidates(inst)]
[('BRK.B', 'alias')]
"""

import difflib
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from alpaca_gatherer.domain.mapping import CandidateKind
from alpaca_gatherer.domain.matching.models import AlpacaAsset, CapitalInstrument
from alpaca_gatherer.domain.matching.normalize import (
    capital_aliases,
    class_root,
    compact_key,
    normalize_name,
)

__all__ = ["AlpacaIndex", "CandidateRef"]

_MIN_NAME_LENGTH = 4


@dataclass(frozen=True, slots=True)
class CandidateRef:
    """An Alpaca asset proposed for an epic, and how it was found."""

    symbol: str
    kind: CandidateKind
    asset: AlpacaAsset


class AlpacaIndex:
    """Lookup tables over every Alpaca asset (all statuses)."""

    def __init__(self, assets: Sequence[AlpacaAsset]) -> None:
        self.by_symbol: dict[str, AlpacaAsset] = {a.symbol: a for a in assets}
        self.by_compact: dict[str, list[AlpacaAsset]] = defaultdict(list)
        self.by_root: dict[str, list[AlpacaAsset]] = defaultdict(list)
        for asset in assets:
            self.by_compact[compact_key(asset.symbol)].append(asset)
            root = class_root(asset.symbol)
            if root is not None:
                self.by_root[root].append(asset)
        self._active_names = [(normalize_name(a.name), a) for a in assets if a.active]

    def identifier_candidates(self, instrument: CapitalInstrument) -> list[CandidateRef]:
        """Exact symbol and alias candidates.

        Inactive assets are kept only when no active asset matched, so that an epic whose only
        counterpart is inactive is reported as such rather than as not listed.
        """
        out: dict[str, CandidateRef] = {}
        exact = self.by_symbol.get(instrument.epic)
        if exact is not None:
            out[instrument.epic] = CandidateRef(instrument.epic, CandidateKind.EXACT, exact)
        for alias in capital_aliases(instrument.epic, instrument.symbol):
            hits = [self.by_symbol[alias]] if alias in self.by_symbol else []
            hits += self.by_compact.get(compact_key(alias), [])
            # The class root lets epic "BRK" reach BRK.A and BRK.B; the price check decides.
            hits += self.by_root.get(alias, [])
            for asset in hits:
                out.setdefault(asset.symbol, CandidateRef(asset.symbol, CandidateKind.ALIAS, asset))
        candidates = list(out.values())
        active = [c for c in candidates if c.asset.active]
        return active or candidates

    def name_candidates(
        self,
        instrument: CapitalInstrument,
        ratio: float,
        limit: int,
        exclude: Collection[str] = (),
    ) -> list[CandidateRef]:
        """Active assets whose normalized name is close to the instrument's name.

        Accepted on a ``difflib`` ratio of at least ``ratio``, or when every token of the
        Capital.com name appears in the Alpaca name with the same first token. The best ``limit``
        are kept, then symbols in ``exclude`` (already identifier candidates) are dropped.
        """
        target = normalize_name(instrument.name or "")
        if len(target) < _MIN_NAME_LENGTH:
            return []
        target_tokens = target.split()
        scored: list[tuple[float, AlpacaAsset]] = []
        for norm, asset in self._active_names:
            if not norm or norm[0] != target[0]:
                continue
            similarity = difflib.SequenceMatcher(None, target, norm).ratio()
            tokens = norm.split()
            contained = (
                len(target_tokens) >= 2
                and tokens[0] == target_tokens[0]
                and set(target_tokens) <= set(tokens)
            )
            if similarity >= ratio or contained:
                scored.append((max(similarity, ratio if contained else 0.0), asset))
        scored.sort(key=lambda item: -item[0])
        best = [CandidateRef(a.symbol, CandidateKind.NAME, a) for _, a in scored[:limit]]
        return [c for c in best if c.symbol not in exclude]
