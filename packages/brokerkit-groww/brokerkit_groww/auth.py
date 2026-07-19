import asyncio, pyotp
from datetime import time
from growwapi import GrowwAPI

from brokerkit.exceptions import AuthenticationError
from brokerkit.models.auth import AuthToken
from brokerkit.interfaces.auth import AuthProvider
from brokerkit.utils.datetime import next_occurrence

TOKEN_EXPIRY_TIME = time(6, 0)

class GrowwAuth(AuthProvider):
    def __init__(self, totp_key: str, totp_secret: str):
        if not totp_key or not totp_secret:
            raise AuthenticationError("totp_key and totp_secret are required")
        self.totp_key = totp_key
        self.totp_secret = totp_secret
        self._token = None

    async def login(self) -> AuthToken:
        otp = pyotp.TOTP(self.totp_secret).now()
        response = await asyncio.to_thread(GrowwAPI.get_access_token, api_key=self.totp_key, totp=otp)
        raw = response["token"] if isinstance(response, dict) else response
        self._token = AuthToken(token=raw, expires_at=next_occurrence(TOKEN_EXPIRY_TIME))
        return self._token
