"""
Single Sign-On (SSO) Provider Integration
Supports OAuth2 (Google, GitHub, Azure AD) and SAML 2.0
"""

import base64
import hashlib
import secrets
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict
from urllib.parse import urlencode


@dataclass
class SSOUser:
    """Unified user information from SSO providers"""

    user_id: str
    email: str
    name: str
    provider: str
    provider_user_id: str
    roles: list = None
    metadata: dict = None
    created_at: datetime = None

    def __post_init__(self):
        if self.roles is None:
            self.roles = []
        if self.metadata is None:
            self.metadata = {}
        if self.created_at is None:
            self.created_at = datetime.utcnow()

    def to_dict(self) -> Dict:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "name": self.name,
            "provider": self.provider,
            "provider_user_id": self.provider_user_id,
            "roles": self.roles,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


class SSOProvider(ABC):
    """Abstract base class for SSO providers"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client_id = config.get("client_id")
        self.client_secret = config.get("client_secret")
        self.redirect_uri = config.get("redirect_uri")

    @abstractmethod
    def get_authorization_url(self, state: str) -> str:
        """Generate authorization URL for user redirect"""
        pass

    @abstractmethod
    def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access token"""
        pass

    @abstractmethod
    def get_user_info(self, access_token: str) -> SSOUser:
        """Fetch user information using access token"""
        pass

    def generate_state(self) -> str:
        """Generate secure random state for CSRF protection"""
        return secrets.token_urlsafe(32)

    def validate_state(self, received_state: str, expected_state: str) -> bool:
        """Validate state parameter"""
        return secrets.compare_digest(received_state, expected_state)


class OAuth2Handler(SSOProvider):
    """OAuth 2.0 provider (Google, GitHub, Azure AD, etc.)"""

    PROVIDER_CONFIGS = {
        "google": {
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
            "scope": "openid email profile",
        },
        "github": {
            "auth_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "userinfo_url": "https://api.github.com/user",
            "scope": "read:user user:email",
        },
        "azure": {
            "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            "userinfo_url": "https://graph.microsoft.com/v1.0/me",
            "scope": "openid email profile",
        },
    }

    def __init__(self, provider_name: str, config: Dict[str, Any]):
        super().__init__(config)

        if provider_name not in self.PROVIDER_CONFIGS:
            raise ValueError(f"Unsupported OAuth2 provider: {provider_name}")

        self.provider_name = provider_name
        self.provider_config = self.PROVIDER_CONFIGS[provider_name]

    def get_authorization_url(self, state: str) -> str:
        """Generate OAuth2 authorization URL"""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.provider_config["scope"],
            "state": state,
        }

        if self.provider_name == "google":
            params["access_type"] = "offline"
            params["prompt"] = "consent"

        auth_url = self.provider_config["auth_url"]
        return f"{auth_url}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access token"""
        # In production, use requests library
        # This is a simulation for demonstration

        token_data = {
            "access_token": f"oauth2_{self.provider_name}_{secrets.token_urlsafe(32)}",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": f"refresh_{secrets.token_urlsafe(32)}",
            "scope": self.provider_config["scope"],
        }

        return token_data

    def get_user_info(self, access_token: str) -> SSOUser:
        """Fetch user information from OAuth2 provider"""
        # In production, make actual HTTP request
        # This is simulated response

        if self.provider_name == "google":
            user_data = {
                "id": "google_12345",
                "email": "user@example.com",
                "name": "John Doe",
                "picture": "https://example.com/photo.jpg",
            }
        elif self.provider_name == "github":
            user_data = {
                "id": "github_67890",
                "email": "user@example.com",
                "name": "Jane Smith",
                "login": "janesmith",
            }
        elif self.provider_name == "azure":
            user_data = {
                "id": "azure_abcdef",
                "mail": "user@company.com",
                "displayName": "Bob Johnson",
            }

        return self._map_to_sso_user(user_data)

    def _map_to_sso_user(self, user_data: Dict) -> SSOUser:
        """Map provider-specific user data to SSOUser"""

        if self.provider_name == "google":
            return SSOUser(
                user_id=hashlib.sha256(
                    f"{self.provider_name}:{user_data['id']}".encode()
                ).hexdigest()[:16],
                email=user_data["email"],
                name=user_data["name"],
                provider=self.provider_name,
                provider_user_id=user_data["id"],
                metadata={"picture": user_data.get("picture")},
            )

        elif self.provider_name == "github":
            return SSOUser(
                user_id=hashlib.sha256(
                    f"{self.provider_name}:{user_data['id']}".encode()
                ).hexdigest()[:16],
                email=user_data["email"],
                name=user_data["name"],
                provider=self.provider_name,
                provider_user_id=user_data["id"],
                metadata={"login": user_data.get("login")},
            )

        elif self.provider_name == "azure":
            return SSOUser(
                user_id=hashlib.sha256(
                    f"{self.provider_name}:{user_data['id']}".encode()
                ).hexdigest()[:16],
                email=user_data["mail"],
                name=user_data["displayName"],
                provider=self.provider_name,
                provider_user_id=user_data["id"],
            )


class SAMLHandler(SSOProvider):
    """SAML 2.0 provider (Okta, OneLogin, AD FS)"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        self.idp_entity_id = config.get("idp_entity_id")
        self.sso_url = config.get("sso_url")
        self.x509_cert = config.get("x509_cert")
        self.sp_entity_id = config.get("sp_entity_id", "slop-detector")

    def get_authorization_url(self, state: str) -> str:
        """Generate SAML authentication request"""

        # Create SAML AuthnRequest
        authn_request = f"""
        <samlp:AuthnRequest
            xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
            xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
            ID="_{secrets.token_urlsafe(32)}"
            Version="2.0"
            IssueInstant="{datetime.utcnow().isoformat()}Z"
            Destination="{self.sso_url}"
            AssertionConsumerServiceURL="{self.redirect_uri}">
            <saml:Issuer>{self.sp_entity_id}</saml:Issuer>
        </samlp:AuthnRequest>
        """

        # Base64 encode and URL encode
        saml_request = base64.b64encode(authn_request.encode()).decode()

        params = {
            "SAMLRequest": saml_request,
            "RelayState": state,
        }

        return f"{self.sso_url}?{urlencode(params)}"

    def exchange_code_for_token(self, saml_response: str) -> Dict[str, Any]:
        """Parse SAML response (already contains user info)"""

        # Decode SAML response
        decoded_response = base64.b64decode(saml_response)

        # Parse XML (simplified - production needs signature verification)
        root = ET.fromstring(decoded_response)

        # Extract assertion
        ns = {
            "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
            "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
        }

        assertion = root.find(".//saml:Assertion", ns)

        if assertion is None:
            raise ValueError("Invalid SAML response: No assertion found")

        # Extract attributes
        attributes = {}
        for attr in assertion.findall(".//saml:Attribute", ns):
            attr_name = attr.get("Name")
            attr_value = attr.find("saml:AttributeValue", ns)
            if attr_value is not None:
                attributes[attr_name] = attr_value.text

        return {
            "assertion": attributes,
            "name_id": assertion.find(".//saml:NameID", ns).text,
        }

    def get_user_info(self, saml_data: Dict[str, Any]) -> SSOUser:
        """Extract user info from SAML assertion"""

        attributes = saml_data["assertion"]
        name_id = saml_data["name_id"]

        # Map common SAML attribute names
        email = attributes.get("email") or attributes.get("mail") or attributes.get("emailAddress")
        name = attributes.get("displayName") or attributes.get("cn") or attributes.get("name")

        return SSOUser(
            user_id=hashlib.sha256(f"saml:{name_id}".encode()).hexdigest()[:16],
            email=email,
            name=name,
            provider="saml",
            provider_user_id=name_id,
            metadata=attributes,
        )


class SSOManager:
    """Central SSO management for multiple providers"""

    def __init__(self):
        self.providers: Dict[str, SSOProvider] = {}
        self.active_states: Dict[str, Dict] = {}  # state -> {provider, timestamp}

    def register_oauth2_provider(self, name: str, provider_type: str, config: Dict):
        """Register OAuth2 provider (Google, GitHub, Azure)"""
        self.providers[name] = OAuth2Handler(provider_type, config)

    def register_saml_provider(self, name: str, config: Dict):
        """Register SAML provider"""
        self.providers[name] = SAMLHandler(config)

    def initiate_login(self, provider_name: str) -> Dict[str, str]:
        """Initiate SSO login flow"""

        if provider_name not in self.providers:
            raise ValueError(f"Unknown SSO provider: {provider_name}")

        provider = self.providers[provider_name]
        state = provider.generate_state()

        # Store state with timestamp for validation
        self.active_states[state] = {
            "provider": provider_name,
            "timestamp": datetime.utcnow(),
        }

        auth_url = provider.get_authorization_url(state)

        return {
            "auth_url": auth_url,
            "state": state,
        }

    def handle_callback(self, provider_name: str, code: str, state: str) -> SSOUser:
        """Handle SSO callback and authenticate user"""

        # Validate state
        if state not in self.active_states:
            raise ValueError("Invalid or expired state")

        state_info = self.active_states[state]

        # Check state hasn't expired (15 minutes)
        if datetime.utcnow() - state_info["timestamp"] > timedelta(minutes=15):
            del self.active_states[state]
            raise ValueError("State expired")

        if state_info["provider"] != provider_name:
            raise ValueError("Provider mismatch")

        # Clean up state
        del self.active_states[state]

        # Get provider and complete authentication
        provider = self.providers[provider_name]

        token_data = provider.exchange_code_for_token(code)

        if isinstance(provider, OAuth2Handler):
            access_token = token_data["access_token"]
            user = provider.get_user_info(access_token)
        else:  # SAML
            user = provider.get_user_info(token_data)

        return user

    def cleanup_expired_states(self):
        """Remove expired states (run periodically)"""
        now = datetime.utcnow()
        expired = [
            state
            for state, info in self.active_states.items()
            if now - info["timestamp"] > timedelta(minutes=15)
        ]

        for state in expired:
            del self.active_states[state]
