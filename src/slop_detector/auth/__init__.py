"""
AI SLOP Detector - Authentication Module
Enterprise SSO, RBAC, and Audit Logging
"""

from .sso import SSOProvider, OAuth2Handler, SAMLHandler
from .rbac import RBACManager, Role, Permission, require_permission
from .session import SessionManager, TokenValidator
from .audit import AuditLogger, AuditEvent, AuditEventType, AuditSeverity

__all__ = [
    # SSO
    'SSOProvider',
    'OAuth2Handler',
    'SAMLHandler',
    
    # RBAC
    'RBACManager',
    'Role',
    'Permission',
    'require_permission',
    
    # Session
    'SessionManager',
    'TokenValidator',
    
    # Audit
    'AuditLogger',
    'AuditEvent',
    'AuditEventType',
    'AuditSeverity',
]

__version__ = '3.0.0'
