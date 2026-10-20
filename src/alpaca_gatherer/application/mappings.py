"""Mapping lookup by exactly one of ``capital_epic`` or ``alpaca_symbol`` (FR-021 to FR-023)."""

from alpaca_gatherer.application.ports import MappingRepository
from alpaca_gatherer.domain.errors import InstrumentNotFound, InvalidRequest, MappingNotAvailable
from alpaca_gatherer.domain.mapping import InstrumentMapping

__all__ = ["LookupMapping"]


class LookupMapping:
    """Return the stored record for one identifier.

    By epic any status is returned; by symbol only ``matched`` records are. Before any run has
    succeeded every lookup reports ``MappingNotAvailable`` instead of ``InstrumentNotFound``.
    """

    def __init__(self, mappings: MappingRepository) -> None:
        self._mappings = mappings

    async def __call__(
        self, *, capital_epic: str | None = None, alpaca_symbol: str | None = None
    ) -> InstrumentMapping:
        """Look up a mapping; raises ``InvalidRequest``, ``InstrumentNotFound`` or
        ``MappingNotAvailable``."""
        if bool(capital_epic) == bool(alpaca_symbol):
            raise InvalidRequest(
                "capital_epic", "give exactly one of capital_epic or alpaca_symbol"
            )
        if capital_epic:
            record = await self._mappings.find_by_epic(capital_epic)
            wanted = f"epic {capital_epic!r}"
        else:
            assert alpaca_symbol is not None
            record = await self._mappings.find_matched_by_symbol(alpaca_symbol)
            wanted = f"matched symbol {alpaca_symbol!r}"
        if record is not None:
            return record
        if not await self._mappings.has_snapshot():
            raise MappingNotAvailable()
        raise InstrumentNotFound(f"The stored mapping has no {wanted}.")
