"""Candidate generation: exact → alias → name."""

from alpaca_gatherer.domain.mapping import CandidateKind
from alpaca_gatherer.domain.matching.candidates import AlpacaIndex
from tests.builders import asset, instrument


def kinds(index: AlpacaIndex, epic: str, symbol: str | None = None) -> dict[str, CandidateKind]:
    return {c.symbol: c.kind for c in index.identifier_candidates(instrument(epic, symbol))}


def test_exact_candidate() -> None:
    index = AlpacaIndex([asset("TSLA")])
    assert kinds(index, "TSLA") == {"TSLA": CandidateKind.EXACT}


def test_alias_candidates_from_epic_and_symbol() -> None:
    index = AlpacaIndex(
        [asset("BRK.B"), asset("AXON"), asset("MT"), asset("MTUS"), asset("GME.WS")]
    )
    assert kinds(index, "BRKB", "BRKb") == {"BRK.B": CandidateKind.ALIAS}
    assert kinds(index, "AXONUS", "AXONus") == {"AXON": CandidateKind.ALIAS}
    assert kinds(index, "MTUS", "MTus") == {"MTUS": CandidateKind.EXACT, "MT": CandidateKind.ALIAS}
    assert kinds(index, "GMEWS", "GME/WS") == {"GME.WS": CandidateKind.ALIAS}


def test_class_root_reaches_every_class() -> None:
    index = AlpacaIndex([asset("BRK.A"), asset("BRK.B")])
    assert kinds(index, "BRK") == {"BRK.A": CandidateKind.ALIAS, "BRK.B": CandidateKind.ALIAS}


def test_inactive_kept_only_without_active_candidates() -> None:
    index = AlpacaIndex([asset("TCBI.PRB", active=False), asset("TCBI.PRC", active=False)])
    assert set(kinds(index, "TCBI")) == {"TCBI.PRB", "TCBI.PRC"}
    index = AlpacaIndex([asset("ALL"), asset("ALL.PRZ", active=False)])
    assert set(kinds(index, "ALL")) == {"ALL"}


def test_non_tradable_assets_are_candidates() -> None:
    index = AlpacaIndex([asset("CHSN", tradable=False)])
    assert kinds(index, "CHSN") == {"CHSN": CandidateKind.EXACT}


def test_name_candidates_by_ratio_or_containment() -> None:
    index = AlpacaIndex(
        [
            asset("BALL", "Ball Corporation"),
            asset("CMRC", "Commerce.com, Inc. Series 1 Common Stock"),
            asset("BALLY", "Bally's Corp"),
            asset("OLD", "Ball Corporation", active=False),
        ]
    )
    ball = index.name_candidates(instrument("BLL", name="Ball Corp"), 0.9, 3)
    assert [(c.symbol, c.kind) for c in ball] == [("BALL", CandidateKind.NAME)]
    commerce = index.name_candidates(instrument("BIGC", name="Commerce.com Inc"), 0.9, 3)
    assert [c.symbol for c in commerce] == ["CMRC"]


def test_name_candidates_capped_and_excluding_identifier_symbols() -> None:
    index = AlpacaIndex([asset(f"WSO{i}", "Watsco Inc") for i in range(5)])
    found = index.name_candidates(instrument("WSOB", name="Watsco Inc"), 0.9, 3)
    assert len(found) == 3
    found = index.name_candidates(instrument("WSOB", name="Watsco Inc"), 0.9, 3, exclude={"WSO0"})
    assert [c.symbol for c in found] == ["WSO1", "WSO2"]


def test_short_or_missing_names_give_no_candidates() -> None:
    index = AlpacaIndex([asset("ABC", "Abc Inc")])
    assert index.name_candidates(instrument("X", name="Abc"), 0.5, 3) == []
    assert index.name_candidates(instrument("X", name=""), 0.5, 3) == []
