"""
AI SLOP Detector - Authentication Module
Enterprise SSO, RBAC, and Audit Logging
"""

from .audit import AuditEvent, AuditEventType, AuditLogger, AuditSeverity
from .rbac import Permission, RBACManager, Role, require_permission
from .session import SessionManager, TokenValidator
from .sso import OAuth2Handler, SAMLHandler, SSOProvider

__all__ = [
    # SSO
    "SSOProvider",
    "OAuth2Handler",
    "SAMLHandler",
    # RBAC
    "RBACManager",
    "Role",
    "Permission",
    "require_permission",
    # Session
    "SessionManager",
    "TokenValidator",
    # Audit
    "AuditLogger",
    "AuditEvent",
    "AuditEventType",
    "AuditSeverity",
]

__version__ = "3.0.0"
