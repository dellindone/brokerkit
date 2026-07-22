"""The tradeable-instrument model."""

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from brokerkit.enums import Exchange, InstrumentType, Segment


class Instrument(BaseModel):
    """A single tradeable instrument, normalized across brokers.

    Produced by
    :meth:`~brokerkit.interfaces.instrument.InstrumentProvider.fetch_instruments`
    and passed to nearly every other call, so the adapter always has the
    identifiers its broker needs without the caller having to know them.

    Joining these across brokers comes down to one rule: **join on
    ``(exchange, exchange_token)``**. That pair is the exchange's own
    identification of the instrument, so every broker reports the same value for
    it, and it exists for derivatives and indices as well as equities.

    The two obvious alternatives both fall short:

    * ``symbol`` is broker-specific and never a key. The same contract is
      ``RELIANCE`` at one broker and ``RELIANCE-EQ`` at another,
      ``NIFTY2672123900CE`` against ``NIFTY-Jul2026-23900-CE``. Orders must use
      whichever spelling the broker published.
    * ``isin`` covers only equities, and only some brokers: Angel One and
      Zerodha publish no ISIN column at all, and no instrument that is not a
      cash security has one. It is useful as a corroborating field, not as the
      primary key.

    Use ``broker_token``, not ``exchange_token``, when calling a broker's API.
    """

    model_config = ConfigDict(extra="forbid")

    symbol: str
    """The broker's own trading symbol, exactly as published. Broker-specific,
    so not a cross-broker key -- join on ``exchange_token`` instead, which is
    exact and covers derivatives and Angel One too.

    Deliberately never rewritten. Stripping the exchange series suffix to make
    symbols comparable was tried and removed: the series a broker appends is not
    always a settlement variant of the same scrip, so the rule merged genuinely
    different securities (a warrant into its equity, three separate debentures
    into one). Any such normalization is a presentation choice, and belongs to
    the application that knows which spelling it wants to show."""

    exchange: Exchange
    """Exchange the instrument is listed on."""

    segment: Segment
    """Market segment within that exchange."""

    instrument_type: InstrumentType
    """Equity, futures, option or index."""

    name: str = ""
    """Human-readable name, where the broker provides one."""

    isin: str | None = None
    """ISIN, the natural cross-broker key for equities. ``None`` on brokers
    whose master omits it (Angel One, Zerodha) and for derivatives."""

    exchange_token: str | None = None
    """The token the **exchange** assigns, not the broker -- RELIANCE on NSE is
    2885 everywhere.

    This is the reliable cross-broker key. Verified 2026-07-22 across the live
    Upstox, Fyers, Angel One and Dhan masters: of 22,218 NSE cash instruments
    where two or more brokers publish an ISIN against the same token, the ISINs
    agreed on all 22,218, with no disagreement. It beats ``isin`` as a join key
    because it also exists for derivatives and for Angel One, neither of which
    has an ISIN at all.

    Pair it with ``exchange`` when joining: NSE and BSE number their scrips
    independently, so a token alone is not unique.

    Use ``broker_token`` -- never this -- when calling a broker's own API."""

    broker_token: str | None = None
    """The handle this broker's own API addresses the instrument by.

    Separate from ``exchange_token`` because the two are often different values:
    Upstox addresses everything by ``instrument_key`` ("NSE_EQ|INE002A01018"),
    Fyers by ``fyToken``, while Angel One and Dhan happen to use the exchange
    token itself. Populated on every adapter even where it duplicates
    ``exchange_token``, so callers have one unambiguous rule -- joins use
    ``exchange_token``, API calls use ``broker_token`` -- rather than having to
    remember which brokers conflate them."""

    lot_size: int = 1
    """Contract size. 1 for equities, the real lot for derivatives."""

    tick_size: Decimal = Decimal("0.05")
    """Minimum price increment, in rupees. Several brokers publish this in
    paise; adapters convert, so this is always rupees."""

    expiry: date | None = None
    """Expiry date. Set for futures and options, ``None`` otherwise."""

    strike: Decimal | None = None
    """Strike price, in rupees. Set for options only."""

    underlying: str | None = None
    """Underlying symbol for derivatives, ``None`` for cash instruments."""

    # --- Reference attributes ------------------------------------------------
    #
    # Everything below is optional and broker-dependent: a master that does not
    # publish a value leaves it ``None``, exactly as ``isin`` already does. They
    # live here rather than in ``raw`` because at least two masters carry each
    # one, so callers can rely on a single spelling and type instead of learning
    # every broker's column name. Coverage as verified against live masters on
    # 2026-07-22 is noted per field -- treat those as "known present", not as a
    # promise that no other broker will ever supply them.

    series: str | None = None
    """Exchange series/group code -- NSE's ``EQ``/``BE``/``BZ``, BSE's ``A``/``B``.
    Worth carrying because it distinguishes normally-traded scrips from
    trade-to-trade and surveillance ones. Present on Fyers and Dhan."""

    face_value: Decimal | None = None
    """Par value per share, in rupees. Needed to read dividend percentages,
    which companies declare against face value rather than market price.
    Present on Fyers."""

    freeze_quantity: Decimal | None = None
    """Exchange freeze limit: single orders above this size are rejected.
    Present on all four of Fyers, Upstox, Angel One and Dhan."""

    upper_circuit: Decimal | None = None
    """Upper price band for the session, in rupees. Present on Fyers and Dhan."""

    lower_circuit: Decimal | None = None
    """Lower price band for the session, in rupees. Present on Fyers and Dhan."""

    previous_close: Decimal | None = None
    """Previous session's closing price, in rupees, as published in the master.
    A convenience only -- the historical provider is the authority on closes.
    Present on Fyers."""

    mtf_enabled: bool | None = None
    """Whether margin trading facility is available on this instrument.
    Present on Fyers, Upstox and Dhan."""

    mtf_leverage: Decimal | None = None
    """Leverage multiplier offered under MTF, where the broker publishes one.
    Brokers differ on whether this is a multiplier or a margin percentage, so
    compare across brokers with care. Present on Fyers, Upstox and Dhan."""

    qty_multiplier: Decimal | None = None
    """Quantity multiplier applied to the traded lot. 1 for ordinary equities.
    Present on Fyers and Upstox."""

    security_type: str | None = None
    """The master's own security classification, kept verbatim because the
    vocabularies differ per broker (Upstox's ``NORMAL``, for instance).
    Present on Upstox."""

    has_options: bool | None = None
    """Whether options are listed on this underlying. Lets callers find the
    F&O universe without downloading every contract. Present on Fyers."""

    has_futures: bool | None = None
    """Whether futures are listed on this underlying. Present on Fyers."""

    raw: dict[str, Any] = Field(default_factory=dict)
    """The broker's own master row, untouched.

    Empty unless the instrument came from
    :meth:`~brokerkit.interfaces.instrument.InstrumentProvider.fetch_instruments`
    with ``include_raw=True``. Normalization is lossy by nature -- masters carry
    three to four times the fields modelled above, and which of those matter
    depends entirely on what the caller is building -- so this is the escape
    hatch for anything not promoted to a field, and it survives brokers adding
    columns without an adapter change.

    Off by default because it is expensive: a full Dhan master is nearly 200,000
    rows, and keeping every raw row costs hundreds of megabytes that callers who
    only want symbols and tokens should not pay for.

    Keys and value types are the broker's, not brokerkit's, and can change
    whenever the broker changes its file. Nothing in brokerkit reads this back;
    treat it as opaque and validate anything taken out of it.
    """
