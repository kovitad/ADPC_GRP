from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode, urlparse

import httpx
import jwt

from api.settings import Settings
from core.db import read_secret
from core.identity import VerifiedIdentity

ALLOWED_SIGNING_ALGORITHMS = {"RS256", "ES256"}

# Sign-in asks for the identity scopes plus a refresh token, so a SIG lookup started an hour
# into a GRP session does not need a new sign-in (ADR-0017). `offline_access` is dropped when
# the authorization server publishes a scope list that does not include it.
BASE_SCOPES = ("openid", "profile", "email")
OFFLINE_ACCESS_SCOPE = "offline_access"


class IdentityProviderError(RuntimeError):
    """A safe, detail-free identity-provider failure."""


@dataclass(frozen=True)
class OidcMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None
    registration_endpoint: str | None
    signing_algorithms: tuple[str, ...]
    token_auth_method: str
    supported_scopes: tuple[str, ...]


@dataclass(frozen=True)
class PublicClientRegistration:
    client_id: str
    issuer: str


@dataclass(frozen=True)
class RenewedAccessToken:
    """A refreshed upstream token. `refresh_token` is the rotated one when the server sends it."""

    access_token: str
    expires_in: int
    refresh_token: str | None


@dataclass(frozen=True)
class AuthenticatedIdentity:
    identity: VerifiedIdentity
    access_token: str
    expires_in: int
    refresh_token: str | None = None


class HumanIdentityProvider(Protocol):
    async def authorization_url(self, state: str, nonce: str, code_challenge: str) -> str: ...

    async def exchange_callback(
        self, code: str, nonce: str, code_verifier: str
    ) -> AuthenticatedIdentity: ...


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _optional_token(value: object) -> str | None:
    text = str(value).strip() if value else ""
    return text or None


def _validate_endpoint(value: str, *, allow_insecure_localhost: bool = False) -> str:
    parsed = urlparse(value)
    if not parsed.hostname or parsed.username or parsed.password:
        raise IdentityProviderError("Identity endpoint URL is invalid")
    local_http = (
        allow_insecure_localhost
        and parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost"}
    )
    if parsed.scheme != "https" and not local_http:
        raise IdentityProviderError("Identity endpoint must use HTTPS")
    return value


def _protected_resource_metadata_url(resource: str) -> str:
    parsed = urlparse(resource)
    suffix = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource{suffix}"


def _authorization_server_metadata_url(issuer: str) -> str:
    parsed = urlparse(issuer)
    suffix = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server{suffix}"


async def _discover_authorization_server(
    client: httpx.AsyncClient,
    resource: str,
    configured_issuer: str | None = None,
) -> str:
    try:
        response = await client.get(
            _protected_resource_metadata_url(resource),
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        document = response.json()
        advertised_resource = str(document["resource"]).rstrip("/")
        if not hmac.compare_digest(advertised_resource, resource):
            raise IdentityProviderError("MCP resource metadata mismatch")
        servers = tuple(str(value).rstrip("/") for value in document["authorization_servers"])
        if not servers:
            raise IdentityProviderError("MCP resource has no authorization server")
        if configured_issuer:
            issuer = configured_issuer.rstrip("/")
            if not any(hmac.compare_digest(issuer, server) for server in servers):
                raise IdentityProviderError(
                    "Configured issuer is not authorized for the MCP resource"
                )
            return issuer
        return servers[0]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        raise IdentityProviderError("SIG MCP authorization metadata is unavailable") from error


async def _openid_document(client: httpx.AsyncClient, issuer: str) -> dict[str, object]:
    try:
        response = await client.get(
            f"{issuer}/.well-known/openid-configuration",
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        document = response.json()
        discovered_issuer = str(document["issuer"]).rstrip("/")
        if not hmac.compare_digest(discovered_issuer, issuer):
            raise IdentityProviderError("Identity issuer mismatch")
        return document
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        raise IdentityProviderError("SERVIR sign-in metadata is unavailable") from error


async def _oauth_document(client: httpx.AsyncClient, issuer: str) -> dict[str, object]:
    try:
        response = await client.get(
            _authorization_server_metadata_url(issuer),
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        document = response.json()
        discovered_issuer = str(document["issuer"]).rstrip("/")
        if not hmac.compare_digest(discovered_issuer, issuer):
            raise IdentityProviderError("OAuth issuer mismatch")
        return document
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        raise IdentityProviderError("SERVIR OAuth metadata is unavailable") from error


class ServirSigIdentityProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not settings.servir_auth_client_id:
            raise IdentityProviderError("SERVIR client ID is not configured")
        if not settings.servir_auth_redirect_uri:
            raise IdentityProviderError("SERVIR redirect URI is not configured")
        self.allow_insecure_localhost = settings.grp_env == "dev"
        self.resource = _validate_endpoint(settings.sig_mcp_base_url).rstrip("/")
        self.configured_issuer = (
            _validate_endpoint(settings.servir_auth_issuer).rstrip("/")
            if settings.servir_auth_issuer
            else None
        )
        self.client_id = settings.servir_auth_client_id
        self.client_secret = (
            read_secret(settings.servir_auth_client_secret_file)
            if settings.servir_auth_client_secret_file.is_file()
            else None
        )
        self.redirect_uri = _validate_endpoint(
            settings.servir_auth_redirect_uri,
            allow_insecure_localhost=self.allow_insecure_localhost,
        )
        self.client = client or httpx.AsyncClient(timeout=10.0, follow_redirects=False)
        self._owns_client = client is None

    async def _metadata(self) -> OidcMetadata:
        issuer = await _discover_authorization_server(
            self.client, self.resource, self.configured_issuer
        )
        document = await _openid_document(self.client, issuer)
        try:
            algorithms = tuple(
                algorithm
                for algorithm in document.get("id_token_signing_alg_values_supported", [])
                if algorithm in ALLOWED_SIGNING_ALGORITHMS
            )
            if not algorithms:
                raise IdentityProviderError("No approved ID-token signing algorithm")
            auth_methods = document.get(
                "token_endpoint_auth_methods_supported", ["client_secret_basic"]
            )
            preferred_methods = (
                ("client_secret_basic", "client_secret_post")
                if self.client_secret
                else ("none",)
            )
            token_auth_method = next(
                (method for method in preferred_methods if method in auth_methods), None
            )
            if token_auth_method is None:
                raise IdentityProviderError("No approved token endpoint authentication method")
            userinfo_endpoint = document.get("userinfo_endpoint")
            registration_endpoint = document.get("registration_endpoint")
            supported_scopes = tuple(
                str(scope) for scope in document.get("scopes_supported", []) or []
            )
            return OidcMetadata(
                issuer=issuer,
                authorization_endpoint=_validate_endpoint(str(document["authorization_endpoint"])),
                token_endpoint=_validate_endpoint(str(document["token_endpoint"])),
                jwks_uri=_validate_endpoint(str(document["jwks_uri"])),
                userinfo_endpoint=(
                    _validate_endpoint(str(userinfo_endpoint)) if userinfo_endpoint else None
                ),
                registration_endpoint=(
                    _validate_endpoint(str(registration_endpoint))
                    if registration_endpoint
                    else None
                ),
                signing_algorithms=algorithms,
                token_auth_method=token_auth_method,
                supported_scopes=supported_scopes,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise IdentityProviderError("SERVIR sign-in metadata is unavailable") from error

    def _apply_client_auth(
        self, metadata: OidcMetadata, token_data: dict[str, str]
    ) -> tuple[str, str] | None:
        """Add the client credentials the server asked for; return HTTP Basic auth when used."""

        if metadata.token_auth_method == "client_secret_basic":
            if self.client_secret is None:
                raise IdentityProviderError("SERVIR client secret is unavailable")
            return (self.client_id, self.client_secret)
        if metadata.token_auth_method == "client_secret_post":
            if self.client_secret is None:
                raise IdentityProviderError("SERVIR client secret is unavailable")
            token_data.update({"client_id": self.client_id, "client_secret": self.client_secret})
            return None
        token_data["client_id"] = self.client_id
        return None

    def _requested_scope(self, metadata: OidcMetadata) -> str:
        """Ask for a refresh token unless the server publishes a scope list without it."""

        scopes = list(BASE_SCOPES)
        if not metadata.supported_scopes or OFFLINE_ACCESS_SCOPE in metadata.supported_scopes:
            scopes.append(OFFLINE_ACCESS_SCOPE)
        return " ".join(scopes)

    async def authorization_url(self, state: str, nonce: str, code_challenge: str) -> str:
        metadata = await self._metadata()
        parameters = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": self._requested_scope(metadata),
                "resource": self.resource,
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{metadata.authorization_endpoint}?{parameters}"

    async def exchange_callback(
        self, code: str, nonce: str, code_verifier: str
    ) -> AuthenticatedIdentity:
        metadata = await self._metadata()
        try:
            token_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": code_verifier,
                "resource": self.resource,
            }
            token_auth = self._apply_client_auth(metadata, token_data)
            token_response = await self.client.post(
                metadata.token_endpoint,
                data=token_data,
                auth=token_auth,
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            token_document = token_response.json()
            id_token = str(token_document["id_token"])
            access_token = str(token_document["access_token"])

            jwks_response = await self.client.get(
                metadata.jwks_uri, headers={"Accept": "application/json"}
            )
            jwks_response.raise_for_status()
            key_set = jwt.PyJWKSet.from_dict(jwks_response.json())
            header = jwt.get_unverified_header(id_token)
            algorithm = str(header.get("alg", ""))
            if algorithm not in metadata.signing_algorithms:
                raise IdentityProviderError("ID-token algorithm is not approved")
            key_id = str(header.get("kid", ""))
            signing_key = next((key.key for key in key_set.keys if key.key_id == key_id), None)
            if signing_key is None:
                raise IdentityProviderError("ID-token signing key is unknown")
            claims = jwt.decode(
                id_token,
                signing_key,
                algorithms=[algorithm],
                audience=self.client_id,
                issuer=metadata.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
                leeway=30,
            )
            if not hmac.compare_digest(str(claims["nonce"]), nonce):
                raise IdentityProviderError("ID-token nonce mismatch")

            identity_claims = claims
            if not claims.get("email") or claims.get("email_verified") is not True:
                if metadata.userinfo_endpoint is None:
                    raise IdentityProviderError("SERVIR verified email is unavailable")
                userinfo_response = await self.client.get(
                    metadata.userinfo_endpoint,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {access_token}",
                    },
                )
                userinfo_response.raise_for_status()
                identity_claims = userinfo_response.json()
                if not hmac.compare_digest(
                    str(identity_claims.get("sub", "")), str(claims["sub"])
                ):
                    raise IdentityProviderError("SERVIR user-info subject mismatch")
            if identity_claims.get("email_verified") is not True:
                raise IdentityProviderError("SERVIR email is not verified")
            email = str(identity_claims["email"]).strip().lower()
            if len(email) > 320 or email.count("@") != 1:
                raise IdentityProviderError("SERVIR email claim is invalid")
            display_name = identity_claims.get("name") or claims.get("name")
            return AuthenticatedIdentity(
                identity=VerifiedIdentity(
                    issuer=str(claims["iss"]),
                    subject=str(claims["sub"]),
                    verified_email=email,
                    display_name=str(display_name) if display_name else None,
                ),
                access_token=access_token,
                expires_in=int(token_document.get("expires_in", 3600)),
                refresh_token=_optional_token(token_document.get("refresh_token")),
            )
        except (httpx.HTTPError, jwt.PyJWTError, KeyError, TypeError, ValueError) as error:
            raise IdentityProviderError("SERVIR sign-in could not be verified") from error

    async def renew_access_token(self, refresh_token: str) -> RenewedAccessToken:
        """Exchange a refresh token for a new access token for the same SIG MCP resource."""

        metadata = await self._metadata()
        try:
            token_data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "resource": self.resource,
            }
            token_auth = self._apply_client_auth(metadata, token_data)
            response = await self.client.post(
                metadata.token_endpoint,
                data=token_data,
                auth=token_auth,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            document = response.json()
            access_token = str(document["access_token"])
            if not access_token:
                raise IdentityProviderError("SERVIR returned an empty access token")
            # Servers that rotate refresh tokens send a new one; keep the old one when they do not.
            rotated = _optional_token(document.get("refresh_token"))
            return RenewedAccessToken(
                access_token=access_token,
                expires_in=int(document.get("expires_in", 3600)),
                refresh_token=rotated or refresh_token,
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise IdentityProviderError("SERVIR access token could not be renewed") from error

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()


async def register_public_client(
    *,
    resource: str,
    redirect_uri: str,
    client_name: str,
    issuer: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> PublicClientRegistration:
    """Register a PKCE public client through the SIG authorization server's DCR endpoint."""

    validated_resource = _validate_endpoint(resource).rstrip("/")
    validated_redirect = _validate_endpoint(redirect_uri, allow_insecure_localhost=True)
    configured_issuer = _validate_endpoint(issuer).rstrip("/") if issuer else None
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=10.0, follow_redirects=False)
    try:
        discovered_issuer = await _discover_authorization_server(
            http_client, validated_resource, configured_issuer
        )
        document = await _openid_document(http_client, discovered_issuer)
        registration_endpoint = document.get("registration_endpoint")
        if not registration_endpoint:
            document = await _oauth_document(http_client, discovered_issuer)
            registration_endpoint = document.get("registration_endpoint")
        if not registration_endpoint:
            raise IdentityProviderError("SERVIR dynamic client registration is unavailable")
        response = await http_client.post(
            _validate_endpoint(str(registration_endpoint)),
            json={
                "client_name": client_name,
                "redirect_uris": [validated_redirect],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": " ".join((*BASE_SCOPES, OFFLINE_ACCESS_SCOPE)),
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        registration = response.json()
        if registration.get("token_endpoint_auth_method", "none") != "none":
            raise IdentityProviderError("SERVIR did not register a public client")
        client_id = str(registration["client_id"]).strip()
        if not client_id:
            raise IdentityProviderError("SERVIR registration returned no client ID")
        return PublicClientRegistration(client_id=client_id, issuer=discovered_issuer)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        raise IdentityProviderError("SERVIR client registration failed") from error
    finally:
        if owns_client:
            await http_client.aclose()


def write_client_id(path: Path, client_id: str) -> None:
    """Persist the non-secret OAuth client identifier without overwriting another client."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing and not hmac.compare_digest(existing, client_id):
            raise IdentityProviderError(f"A different client ID already exists at {path}")
        if existing:
            return
    path.write_text(f"{client_id}\n", encoding="utf-8")
