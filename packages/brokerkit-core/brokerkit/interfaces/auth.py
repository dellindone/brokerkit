"""The authentication provider interface."""

from abc import ABC, abstractmethod

from brokerkit.models.auth import AuthToken


class AuthProvider(ABC):
    """Owns a broker session: logging in and handing out a valid token.

    Each adapter\'s provider wraps whatever its broker actually requires --
    TOTP, TOTP plus a PIN, a refresh-token exchange, or a browser login whose
    result is passed back in -- behind these two methods, so nothing above
    the adapter needs to know which.

    Implementations keep the current token in a ``self._token`` attribute
    (``None`` before the first login); :meth:`get_token` relies on it.
    """

    _token: AuthToken | None

    @abstractmethod
    async def login(self) -> AuthToken:
        """Perform a full authentication and return a fresh token.

        Called on the first :meth:`get_token`, and again whenever the stored
        token has expired and cannot be refreshed. Raises
        :class:`~brokerkit.exceptions.auth.AuthenticationError` on failure.
        """

    async def get_token(self) -> AuthToken:
        """Return a valid token, logging in if necessary.

        Returns the cached token while it is still valid, otherwise logs in
        again. Adapters with a cheaper refresh path override this to use it
        before falling back to a full login.
        """
        if self._token is None or self._token.is_expired:
            return await self.login()
        return self._token
