from pathlib import Path
import sys
import types

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES = REPO_ROOT / "packages"
CORE_PATH = PACKAGES / "brokerkit-core"

# Make brokerkit-core and every adapter importable *by name* without a prior
# `pip install`. The adapters are separate distributions under packages/, and
# no single venv holds all of them (groww/fyers can't even coexist — their
# SDKs pin incompatible aiohttp), so the suite puts the source dirs on the
# path itself rather than depending on what happens to be installed.
for _pkg in ("core", "groww", "fyers", "upstox", "dhan", "angelone", "zerodha"):
    _dir = PACKAGES / f"brokerkit-{_pkg}"
    if _dir.is_dir() and str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))


def _install_smartapi_stub() -> None:
    """Angel One's `SmartApi` SDK is the one vendor package that isn't
    pip-installable in a bare CI env. The adapter only *calls* it at
    ``create()`` time, but the contract + type-hint sweeps import the modules,
    which read names like ``SmartWebSocketV2.QUOTE`` and
    ``from SmartApi.smartExceptions import ...`` at module scope. A recursive
    stub makes those resolve without pretending to be the real SDK. Never
    installed when the real SmartApi is present."""
    try:
        import SmartApi  # noqa: F401

        return
    except ImportError:
        pass

    class _AnyMeta(type):
        # class-attribute reads (SmartWebSocketV2.QUOTE) fabricate on demand
        def __getattr__(cls, name):
            return _AnyMeta(name, (Exception,), {})

    class _StubModule(types.ModuleType):
        # `from SmartApi.smartExceptions import DataException` fabricates too
        def __getattr__(self, name):
            obj = _AnyMeta(name, (Exception,), {})
            setattr(self, name, obj)
            return obj

    for name in (
        "SmartApi",
        "SmartApi.smartConnect",
        "SmartApi.smartExceptions",
        "SmartApi.smartWebSocketV2",
    ):
        sys.modules.setdefault(name, _StubModule(name))


_install_smartapi_stub()


@pytest.fixture
def cash_instrument():
    from brokerkit.enums import Exchange, InstrumentType, Segment
    from brokerkit.models.instrument import Instrument

    return Instrument(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        segment=Segment.CASH,
        instrument_type=InstrumentType.EQ,
        exchange_token="2885",
    )


@pytest.fixture
def option_instrument():
    from brokerkit.enums import Exchange, InstrumentType, Segment
    from brokerkit.models.instrument import Instrument

    return Instrument(
        symbol="NIFTY26JUL24000CE",
        exchange=Exchange.NSE,
        segment=Segment.FNO,
        instrument_type=InstrumentType.CE,
        exchange_token="57336",
        underlying="NIFTY",
    )
