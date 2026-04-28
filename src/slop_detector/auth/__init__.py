"""
EXPERIMENTAL: Enterprise auth module (SSO, RBAC, Audit Logging).
Not yet integrated with core. Prototype status.
"""

from .. import __version__ as PACKAGE_VERSION
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

__version__ = PACKAGE_VERSION
