from abc import ABC, abstractmethod
from brokerkit.models.auth import AuthToken

class AuthProvider(ABC):
    @abstractmethod
    async def login(self) -> AuthToken:
        """Authenticate a user and return an authentication token."""

    async def get_token(self) -> AuthToken:
        if self._token is None or self._token.is_expired:
            return await self.login()
        return self._token
    