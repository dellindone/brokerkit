import asyncio

from pydantic import BaseModel
from upstox_client import ApiClient, Configuration, UserApi

from brokerkit.exceptions.common import BrokerKitError
from brokerkit.interfaces.auth import AuthProvider

from brokerkit_upstox.errors import upstox_errors

# `broker.risk_control` — Upstox's Kill Switch (Trader's Control). Upstox
# has NO P&L-based auto-exit (unlike Dhan's risk_control, which also has
# set/get/stop_pnl_exit) — the only trader-control write Upstox exposes is
# the kill switch, so this class is kill-switch-only. Same off-the-shared-
# Broker-base placement as fundamentals/news/market_information/charges.
#
# Real semantics (verified from the Update Kill Switch doc): kill switch is
# PER-SEGMENT, not account-wide (unlike Dhan's). `action="DISABLE"` BLOCKS
# trading in that segment (cancels its pending orders + blocks new ones);
# `action="ENABLE"` restores it. Needs the OAuth token — it's an
# account-scoped write, the read-only Analytics Token can't do it.

# Segment values accepted by the API (from the doc): NSE_EQ / BSE_EQ /
# NSE_FO / BSE_FO / NCD_FO / BCD_FO / MCX_FO / NSE_COM.
_VALID_ACTIONS = {"ENABLE", "DISABLE"}


class KillSwitchSegment(BaseModel):
    segment: str
    segment_status: str | None = None       # account-level (independent of kill switch)
    kill_switch_enabled: bool | None = None  # True = trading blocked in this segment


class UpstoxRiskControl:
    def __init__(self, auth: AuthProvider, configuration: Configuration):
        self._auth = auth
        self._configuration = configuration
        self._api = UserApi(ApiClient(configuration))

    async def _refresh_token(self) -> None:
        token = await self._auth.get_token()
        self._configuration.access_token = token.token

    async def get_status(self) -> list[KillSwitchSegment]:
        """Per-segment kill-switch + segment status for the whole account."""
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(self._api.get_kill_switch)
        return [KillSwitchSegment(**d.to_dict()) for d in (resp.data or [])]

    async def update(self, segment: str, action: str) -> list[KillSwitchSegment]:
        """`action`: "ENABLE" (allow trading) or "DISABLE" (block trading in
        that segment). Returns the updated per-segment statuses."""
        action = action.upper()
        if action not in _VALID_ACTIONS:
            raise BrokerKitError(f"action must be ENABLE or DISABLE, got {action!r}")
        await self._refresh_token()
        with upstox_errors():
            # body is typed `object` in the SDK — a plain dict serializes
            # correctly via ApiClient.sanitize_for_serialization.
            resp = await asyncio.to_thread(
                self._api.update_kill_switch, {"segment": segment, "action": action}
            )
        return [KillSwitchSegment(**d.to_dict()) for d in (resp.data or [])]

    async def disable_trading(self, segment: str) -> list[KillSwitchSegment]:
        """Kill: block trading in `segment` (cancels its pending orders)."""
        return await self.update(segment, "DISABLE")

    async def enable_trading(self, segment: str) -> list[KillSwitchSegment]:
        """Restore trading in `segment`."""
        return await self.update(segment, "ENABLE")
