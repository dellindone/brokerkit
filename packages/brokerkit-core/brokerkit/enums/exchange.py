"""Exchanges BrokerKit can address."""

from enum import StrEnum


class Exchange(StrEnum):
    """A stock or commodity exchange.

    Deliberately limited to the three exchanges every supported broker can
    trade on. Currency exchanges (NSE's CDS, BSE's BCD) are absent: they have
    no matching :class:`~brokerkit.enums.segment.Segment` value, so currency
    rows are dropped during instrument normalization rather than mapped to
    something inaccurate.
    """

    NSE = "NSE"
    BSE = "BSE"
    MCX = "MCX"
