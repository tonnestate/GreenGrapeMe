"""Verify external OIDC access JWTs using live HTTPS JWKS, never local secrets.

Tokens authenticate an OIDC subject ONLY. Tenant/role authorization is
done separately with TenantMemberships from the application's database.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import jwt

from .tenant_access import Principal


class AuthenticationFailure(Exception):
    """Intentionally hides details of failed token verification."""


def _https_url(value: str, name: str) -> str:
    if not isinstance(value, str) or not (8 <= len(value) <= 2048):
        raise ValueError(f"invalid {name}")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.fragment or parsed.port == 0
            or parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise ValueError(f"invalid HTTPS {name}")
    return value


@dataclass(frozen=True)
class IdentityConfig:
    issuer: str
    audience: str
    jwks_uri: str

    def __post_init__(self) -> None:
        _https_url(self.issuer, "issuer")
        _https_url(self.jwks_uri, "JWKS URI")
        if (not isinstance(self.audience, str)
                or not 1 <= len(self.audience) <= 256
                or self.audience != self.audience.strip()):
            raise ValueError("invalid expected audience")


class OIDCTokenVerifier:
    def __init__(self, config: IdentityConfig):
        self.config = config
        # The provider's JWKS is fetched over HTTPS and automatically
        # refreshed by PyJWKClient for unknown rotated key IDs. Do not
        # accept JWT-supplied jku, x5u, alg or tenant authorization.
        self._keys = jwt.PyJWKClient(
            config.jwks_uri, cache_jwk_set=True, lifespan=300,
            timeout=5,
        )

    def authenticate(self, bearer: object) -> Principal:
        if (not isinstance(bearer, str) or not 16 <= len(bearer) <= 8192
                or bearer.count(".") != 2 or any(ch.isspace() for ch in bearer)):
            raise AuthenticationFailure("authentication failed")
        try:
            key = self._keys.get_signing_key_from_jwt(bearer).key
            claims = jwt.decode(
                bearer, key=key, algorithms=["RS256"],
                audience=self.config.audience,
                issuer=self.config.issuer,
                leeway=30,
                options={"require": ["sub", "iss", "aud", "exp", "iat", "nbf"]},
            )
            subject = claims["sub"]
            if not isinstance(subject, str) or not 1 <= len(subject) <= 512:
                raise AuthenticationFailure("authentication failed")
            if not subject.strip() or subject != subject.strip():
                raise AuthenticationFailure("authentication failed")
            return Principal(self.config.issuer, subject)
        except (jwt.PyJWTError, ValueError, TypeError, KeyError,
                TimeoutError, OSError) as exc:
            raise AuthenticationFailure("authentication failed") from exc
