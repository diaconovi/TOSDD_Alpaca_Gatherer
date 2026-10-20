"""Symbol, epic and company-name normalization.

Capital.com spells US share identifiers in a few recurring ways; these functions turn them into
the Alpaca spellings they imply.

>>> compact_key("BRK.B") == compact_key("BRK/B") == compact_key("BRKb")
True
>>> sorted(capital_aliases("HEIA", "HEIa"))
['HEI.A', 'HEIA']
>>> normalize_name("Commerce.com, Inc. Series 1 Common Stock")
'commerce com series 1'
"""

import re
from collections.abc import Iterable

__all__ = [
    "NAME_STOPWORDS",
    "capital_aliases",
    "class_root",
    "compact_key",
    "normalize_name",
    "sweep_epics",
]

NAME_STOPWORDS = frozenset(
    {
        "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc",
        "the", "class", "cl", "common", "stock", "shares", "share", "ordinary", "sa", "nv", "ag",
        "se", "llc", "lp", "holding", "holdings", "group", "usd", "adr", "ads", "sponsored",
        "american", "depositary", "receipts", "receipt", "each", "representing", "new", "de",
    }
)  # fmt: skip
"""Words dropped from company names: legal suffixes, share-class and depositary wording."""

_US_SUFFIX = re.compile(r"(?:\s+US|us)$")
_SHARE_CLASS = re.compile(r"([A-Z0-9]+)([a-z])")
_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_NAME_TOKEN = re.compile(r"[a-z0-9]+")


def compact_key(value: str) -> str:
    """Uppercase alphanumerics only: ``BRK.B``, ``BRK/B``, ``BRKb`` and ``BRK B`` → ``BRKB``.

    >>> compact_key("gme/ws")
    'GMEWS'
    """
    return _NON_ALNUM.sub("", value.upper())


def capital_aliases(epic: str, symbol: str | None) -> set[str]:
    """Alpaca-style spellings implied by Capital.com's epic and ``symbol`` field.

    Conventions: a lowercase ``us`` or `` US`` suffix marks the US line (``AXONus``, ``NLOP US``);
    a trailing lowercase letter is a share class (``BRKb`` → ``BRK.B``); ``/`` separates a suffix
    (``GME/WS`` → ``GME.WS``). The epic itself is always included.

    >>> sorted(capital_aliases("AXONUS", "AXONus"))
    ['AXON', 'AXONUS']
    >>> sorted(capital_aliases("BFBUS", "BFbus"))
    ['BF.B', 'BFB', 'BFBUS']
    """
    out = {epic.upper()}
    sym = (symbol or epic).strip()
    base = _US_SUFFIX.sub("", sym)
    if base != sym:
        out.add(base.upper())
        if epic.upper().endswith("US"):
            out.add(epic.upper()[:-2])
    match = _SHARE_CLASS.fullmatch(base)
    if match:
        out.add(f"{match.group(1)}.{match.group(2).upper()}")
    if "/" in base:
        out.add(base.upper().replace("/", "."))
    return {alias for alias in out if alias}


def class_root(symbol: str) -> str | None:
    """Root of a dotted Alpaca symbol (``BRK.B`` → ``BRK``), or ``None`` if it has no dot.

    >>> class_root("BRK.B"), class_root("TSLA")
    ('BRK', None)
    """
    return symbol.split(".", maxsplit=1)[0] if "." in symbol else None


def sweep_epics(symbols: Iterable[str]) -> set[str]:
    """Epic spellings Capital.com plausibly uses for Alpaca symbols: compact and ``…US`` forms.

    >>> sorted(sweep_epics(["BRK.B"]))
    ['BRKB', 'BRKBUS']
    """
    out: set[str] = set()
    for symbol in symbols:
        compact = compact_key(symbol)
        if compact:
            out.add(compact)
            out.add(compact + "US")
    return out


def normalize_name(name: str) -> str:
    """Lowercase alphanumeric tokens without legal suffixes or share-class words.

    >>> normalize_name("Procter & Gamble Co")
    'procter and gamble'
    """
    tokens = _NAME_TOKEN.findall(name.lower().replace("&", " and "))
    return " ".join(t for t in tokens if t not in NAME_STOPWORDS)
