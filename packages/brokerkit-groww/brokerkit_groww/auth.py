import asyncio, pyotp
from datetime import time
from growwapi import GrowwAPI

from brokerkit.models.auth import AuthToken
from brokerkit.utils.datetime import next_occurrence

TOKEN_EXPIRY_TIME = time(6, 0)

class GrowwAuth:
    def __init__(self, totp_key: str, totp_secret: str):
        self.totp_key = totp_key
        self.totp_secret = totp_secret
        self._token = None

    async def login(self) -> str:
        if not self.totp_secret:
            return self._token

        otp = pyotp.TOTP(self.totp_secret).now()
        response = await asyncio.to_thread(GrowwAPI.get_access_token, api_key=self.totp_key, totp=otp)
        raw = response["token"] if isinstance(response, dict) else response
        self._token = AuthToken(token=raw, expires_at=next_occurrence(TOKEN_EXPIRY_TIME))
        return self._token

    async def get_token(self) -> str:
        if self._token is None or self._token.is_expired:
            return await self.login()
        return self._token
    