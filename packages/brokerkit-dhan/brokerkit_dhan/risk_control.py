"""Dhan risk-control extra: kill switch and P&L auto-exit."""

import asyncio
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from brokerkit_dhan.errors import check

# `broker.risk_control` — Dhan-exclusive risk tooling (Kill Switch + P&L
# based auto-exit), off the shared Broker base, same placement precedent as
# the other broker-exclusive extras. No Groww/Fyers/Upstox equivalent.


class KillSwitchStatus(BaseModel):
    """Current state of the account-wide kill switch."""
    status: str          # "ACTIVATE" / "DEACTIVATE" (or the message on a set call)


class PnlExitConfig(BaseModel):
    """P&L auto-exit thresholds: square off everything past a profit or loss."""
    status: str | None = None            # ACTIVE / INACTIVE
    profit: Decimal | None = None
    loss: Decimal | None = None
    product_type: Any = None
    kill_switch_enabled: bool | None = None


def _d(v: Any) -> Decimal | None:
    return None if v in (None, "") else Decimal(str(v))


class DhanRiskControl:
    """Dhan risk controls: the account-wide kill switch and P&L auto-exit.
    Adapter-local; no core equivalent exists."""
    def __init__(self, dhan):
        self._dhan = dhan

    async def activate_kill_switch(self) -> KillSwitchStatus:
        """Disables trading for the current day. Requires all positions
        closed and no pending orders (Dhan-side precondition)."""
        resp = await asyncio.to_thread(self._dhan.kill_switch, "ACTIVATE")
        data = check(resp) or {}
        return KillSwitchStatus(status=str(data.get("killSwitchStatus") or "ACTIVATE"))

    async def deactivate_kill_switch(self) -> KillSwitchStatus:
        resp = await asyncio.to_thread(self._dhan.kill_switch, "DEACTIVATE")
        data = check(resp) or {}
        return KillSwitchStatus(status=str(data.get("killSwitchStatus") or "DEACTIVATE"))

    async def kill_switch_status(self) -> KillSwitchStatus:
        resp = await asyncio.to_thread(self._dhan.status_kill_switch)
        data = check(resp) or {}
        return KillSwitchStatus(status=str(data.get("killSwitchStatus") or ""))

    async def set_pnl_exit(
        self,
        profit_value: Decimal | float,
        loss_value: Decimal | float,
        product_type: list[str] | None = None,
        enable_kill_switch: bool = False,
    ) -> PnlExitConfig:
        """Auto-exit all positions when cumulative profit/loss (absolute ₹,
        not %) crosses a threshold. Resets at end of the trading day.
        `product_type` defaults to ['INTRADAY']."""
        resp = await asyncio.to_thread(
            self._dhan.set_pnl_exit,
            float(profit_value),
            float(loss_value),
            product_type or ["INTRADAY"],
            enable_kill_switch,
        )
        data = check(resp) or {}
        return PnlExitConfig(status=data.get("pnlExitStatus") or data.get("message"))

    async def get_pnl_exit(self) -> PnlExitConfig:
        resp = await asyncio.to_thread(self._dhan.get_pnl_exit)
        data = check(resp) or {}
        return PnlExitConfig(
            status=data.get("pnlExitStatus"),
            profit=_d(data.get("profit")),
            loss=_d(data.get("loss")),
            product_type=data.get("productType"),
            kill_switch_enabled=data.get("enableKillSwitch") or data.get("enable_kill_switch"),
        )

    async def stop_pnl_exit(self) -> PnlExitConfig:
        resp = await asyncio.to_thread(self._dhan.stop_pnl_exit)
        data = check(resp) or {}
        return PnlExitConfig(status=data.get("pnlExitStatus") or data.get("message"))
