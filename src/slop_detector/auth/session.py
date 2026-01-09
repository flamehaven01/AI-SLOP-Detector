"""
Session Management and Token Validation
JWT-based session handling with refresh tokens
"""

import jwt
import secrets
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict
import json
import hashlib


@dataclass
class Session:
    """User session information"""

    session_id: str
    user_id: str
    email: str
    roles: list
    created_at: datetime
    expires_at: datetime
    refresh_token: Optional[str] = None
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def is_expired(self) -> bool:
        """Check if session has expired"""
        return datetime.utcnow() > self.expires_at

    def to_dict(self) -> Dict:
        """Serialize session to dictionary"""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["expires_at"] = self.expires_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "Session":
        """Deserialize session from dictionary"""
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        data["expires_at"] = datetime.fromisoformat(data["expires_at"])
        return cls(**data)


class TokenValidator:
    """JWT token validation and generation"""

    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        self.secret_key = secret_key
        self.algorithm = algorithm

    def generate_access_token(
        self, user_id: str, email: str, roles: list, expires_in: int = 3600
    ) -> str:
        """Generate JWT access token"""

        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=expires_in)

        payload = {
            "user_id": user_id,
            "email": email,
            "roles": roles,
            "iat": now,
            "exp": expires_at,
            "type": "access",
        }

        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token

    def generate_refresh_token(self, user_id: str, expires_in: int = 604800) -> str:
        """Generate refresh token (7 days default)"""

        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=expires_in)

        payload = {
            "user_id": user_id,
            "iat": now,
            "exp": expires_at,
            "type": "refresh",
            "jti": secrets.token_urlsafe(32),  # Unique token ID
        }

        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token

    def validate_token(self, token: str, token_type: str = "access") -> Dict[str, Any]:
        """Validate and decode JWT token"""

        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Verify token type
            if payload.get("type") != token_type:
                raise jwt.InvalidTokenError(f"Invalid token type: expected {token_type}")

            return payload

        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise ValueError(f"Invalid token: {str(e)}")

    def refresh_access_token(self, refresh_token: str) -> str:
        """Generate new access token from refresh token"""

        payload = self.validate_token(refresh_token, token_type="refresh")
        user_id = payload["user_id"]

        # In production, fetch user roles from database
        # For now, assume roles are stored separately
        return self.generate_access_token(user_id, "", [])


class SessionManager:
    """Manage user sessions with in-memory and persistent storage"""

    def __init__(
        self, secret_key: str, session_duration: int = 3600, refresh_duration: int = 604800
    ):
        self.token_validator = TokenValidator(secret_key)
        self.session_duration = session_duration
        self.refresh_duration = refresh_duration

        self.active_sessions: Dict[str, Session] = {}
        self.refresh_tokens: Dict[str, str] = {}  # refresh_token_hash -> user_id

    def create_session(
        self, user_id: str, email: str, roles: list, metadata: Dict = None
    ) -> Dict[str, str]:
        """Create new session and return tokens"""

        session_id = secrets.token_urlsafe(32)

        # Generate tokens
        access_token = self.token_validator.generate_access_token(
            user_id, email, roles, self.session_duration
        )

        refresh_token = self.token_validator.generate_refresh_token(user_id, self.refresh_duration)

        # Store refresh token hash for validation
        refresh_token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        self.refresh_tokens[refresh_token_hash] = user_id

        # Create session
        session = Session(
            session_id=session_id,
            user_id=user_id,
            email=email,
            roles=roles,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=self.session_duration),
            refresh_token=refresh_token_hash,
            metadata=metadata or {},
        )

        self.active_sessions[session_id] = session

        return {
            "session_id": session_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": self.session_duration,
        }

    def validate_session(self, access_token: str) -> Session:
        """Validate access token and return session"""

        payload = self.token_validator.validate_token(access_token)
        user_id = payload["user_id"]

        # Find active session for this user
        for session in self.active_sessions.values():
            if session.user_id == user_id and not session.is_expired():
                return session

        raise ValueError("No active session found")

    def refresh_session(self, refresh_token: str) -> Dict[str, str]:
        """Refresh session using refresh token"""

        # Validate refresh token
        payload = self.token_validator.validate_token(refresh_token, token_type="refresh")
        user_id = payload["user_id"]

        # Verify refresh token exists
        refresh_token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

        if refresh_token_hash not in self.refresh_tokens:
            raise ValueError("Invalid refresh token")

        if self.refresh_tokens[refresh_token_hash] != user_id:
            raise ValueError("Refresh token user mismatch")

        # Find existing session
        user_session = None
        for session in self.active_sessions.values():
            if session.user_id == user_id:
                user_session = session
                break

        if not user_session:
            raise ValueError("No session found for user")

        # Generate new access token
        new_access_token = self.token_validator.generate_access_token(
            user_id, user_session.email, user_session.roles, self.session_duration
        )

        # Update session expiry
        user_session.expires_at = datetime.utcnow() + timedelta(seconds=self.session_duration)

        return {
            "access_token": new_access_token,
            "expires_in": self.session_duration,
        }

    def revoke_session(self, session_id: str) -> bool:
        """Revoke (logout) a session"""

        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]

        # Remove refresh token
        if session.refresh_token and session.refresh_token in self.refresh_tokens:
            del self.refresh_tokens[session.refresh_token]

        # Remove session
        del self.active_sessions[session_id]

        return True

    def revoke_user_sessions(self, user_id: str) -> int:
        """Revoke all sessions for a user"""

        sessions_to_remove = [
            sid for sid, session in self.active_sessions.items() if session.user_id == user_id
        ]

        for session_id in sessions_to_remove:
            self.revoke_session(session_id)

        return len(sessions_to_remove)

    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions (run periodically)"""

        expired_sessions = [
            sid for sid, session in self.active_sessions.items() if session.is_expired()
        ]

        for session_id in expired_sessions:
            self.revoke_session(session_id)

        return len(expired_sessions)

    def get_active_sessions(self, user_id: str) -> list:
        """Get all active sessions for a user"""

        return [
            session.to_dict()
            for session in self.active_sessions.values()
            if session.user_id == user_id and not session.is_expired()
        ]

    def export_sessions(self, filepath: str):
        """Export sessions to JSON (for backup/migration)"""

        data = {
            "sessions": {sid: session.to_dict() for sid, session in self.active_sessions.items()},
            "refresh_tokens": self.refresh_tokens,
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    def import_sessions(self, filepath: str):
        """Import sessions from JSON"""

        with open(filepath, "r") as f:
            data = json.load(f)

        self.active_sessions = {
            sid: Session.from_dict(session_data) for sid, session_data in data["sessions"].items()
        }

        self.refresh_tokens = data["refresh_tokens"]


class AuditLogger:
    """Audit logging for authentication events"""

    def __init__(self, log_file: str = "auth_audit.log"):
        self.log_file = log_file

    def log_event(self, event_type: str, user_id: str, details: Dict = None):
        """Log authentication event"""

        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "user_id": user_id,
            "details": details or {},
        }

        with open(self.log_file, "a") as f:
            f.write(json.dumps(event) + "\n")

    def log_login(self, user_id: str, provider: str, ip_address: str = None):
        """Log successful login"""
        self.log_event(
            "login",
            user_id,
            {
                "provider": provider,
                "ip_address": ip_address,
            },
        )

    def log_logout(self, user_id: str):
        """Log logout"""
        self.log_event("logout", user_id)

    def log_failed_auth(self, user_id: str, reason: str):
        """Log failed authentication attempt"""
        self.log_event("auth_failed", user_id, {"reason": reason})

    def log_permission_denied(self, user_id: str, permission: str, resource: str):
        """Log permission denied event"""
        self.log_event(
            "permission_denied",
            user_id,
            {
                "permission": permission,
                "resource": resource,
            },
        )
