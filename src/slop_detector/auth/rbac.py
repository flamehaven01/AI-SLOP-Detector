"""
Role-Based Access Control (RBAC) System
Supports hierarchical roles and fine-grained permissions
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set


class Permission(str, Enum):
    """Fine-grained permissions for SLOP Detector operations"""

    # Analysis permissions
    ANALYZE_FILE = "analyze:file"
    ANALYZE_PROJECT = "analyze:project"
    VIEW_RESULTS = "view:results"

    # Configuration permissions
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"
    THRESHOLD_MODIFY = "threshold:modify"

    # History permissions
    HISTORY_READ = "history:read"
    HISTORY_DELETE = "history:delete"
    HISTORY_EXPORT = "history:export"

    # ML Model permissions
    MODEL_TRAIN = "model:train"
    MODEL_DEPLOY = "model:deploy"
    MODEL_VIEW = "model:view"

    # Team permissions
    TEAM_VIEW = "team:view"
    TEAM_MANAGE = "team:manage"
    USER_INVITE = "user:invite"
    USER_REMOVE = "user:remove"

    # Admin permissions
    AUDIT_VIEW = "audit:view"
    SYSTEM_CONFIG = "system:config"
    ROLE_MANAGE = "role:manage"


@dataclass
class Role:
    """Role definition with hierarchical permissions"""

    name: str
    permissions: Set[Permission]
    description: str = ""
    inherits_from: Optional["Role"] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def has_permission(self, permission: Permission) -> bool:
        """Check if role has specific permission (including inherited)"""
        if permission in self.permissions:
            return True

        if self.inherits_from:
            return self.inherits_from.has_permission(permission)

        return False

    def get_all_permissions(self) -> Set[Permission]:
        """Get all permissions including inherited ones"""
        all_perms = self.permissions.copy()

        if self.inherits_from:
            all_perms.update(self.inherits_from.get_all_permissions())

        return all_perms

    def to_dict(self) -> Dict:
        """Serialize role to dictionary"""
        return {
            "name": self.name,
            "permissions": [p.value for p in self.permissions],
            "description": self.description,
            "inherits_from": self.inherits_from.name if self.inherits_from else None,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict, roles_registry: Dict[str, "Role"]) -> "Role":
        """Deserialize role from dictionary"""
        inherits_from = None
        if data.get("inherits_from"):
            inherits_from = roles_registry.get(data["inherits_from"])

        return cls(
            name=data["name"],
            permissions={Permission(p) for p in data["permissions"]},
            description=data.get("description", ""),
            inherits_from=inherits_from,
            created_at=datetime.fromisoformat(data["created_at"]),
        )


class RBACManager:
    """RBAC Manager with predefined and custom roles"""

    def __init__(self):
        self.roles: Dict[str, Role] = {}
        self.user_roles: Dict[str, Set[str]] = {}  # user_id -> role_names
        self._init_default_roles()

    def _init_default_roles(self):
        """Initialize default role hierarchy"""

        # Viewer - Read-only access
        viewer = Role(
            name="viewer",
            permissions={
                Permission.VIEW_RESULTS,
                Permission.CONFIG_READ,
                Permission.HISTORY_READ,
                Permission.MODEL_VIEW,
                Permission.TEAM_VIEW,
            },
            description="Read-only access to analysis results",
        )
        self.roles["viewer"] = viewer

        # Analyzer - Can run analysis
        analyzer = Role(
            name="analyzer",
            permissions={
                Permission.ANALYZE_FILE,
                Permission.ANALYZE_PROJECT,
                Permission.HISTORY_EXPORT,
            },
            inherits_from=viewer,
            description="Can perform analysis and export results",
        )
        self.roles["analyzer"] = analyzer

        # Developer - Can modify configurations
        developer = Role(
            name="developer",
            permissions={
                Permission.CONFIG_WRITE,
                Permission.THRESHOLD_MODIFY,
                Permission.MODEL_TRAIN,
            },
            inherits_from=analyzer,
            description="Can configure and train models",
        )
        self.roles["developer"] = developer

        # Team Lead - Can manage team members
        team_lead = Role(
            name="team_lead",
            permissions={
                Permission.TEAM_MANAGE,
                Permission.USER_INVITE,
                Permission.HISTORY_DELETE,
            },
            inherits_from=developer,
            description="Can manage team and configurations",
        )
        self.roles["team_lead"] = team_lead

        # Admin - Full system access
        admin = Role(
            name="admin",
            permissions={
                Permission.MODEL_DEPLOY,
                Permission.USER_REMOVE,
                Permission.AUDIT_VIEW,
                Permission.SYSTEM_CONFIG,
                Permission.ROLE_MANAGE,
            },
            inherits_from=team_lead,
            description="Full system administration access",
        )
        self.roles["admin"] = admin

    def create_role(
        self,
        name: str,
        permissions: Set[Permission],
        description: str = "",
        inherits_from: Optional[str] = None,
    ) -> Role:
        """Create custom role"""
        parent_role = self.roles.get(inherits_from) if inherits_from else None

        role = Role(
            name=name, permissions=permissions, description=description, inherits_from=parent_role
        )

        self.roles[name] = role
        return role

    def assign_role(self, user_id: str, role_name: str) -> bool:
        """Assign role to user"""
        if role_name not in self.roles:
            return False

        if user_id not in self.user_roles:
            self.user_roles[user_id] = set()

        self.user_roles[user_id].add(role_name)
        return True

    def revoke_role(self, user_id: str, role_name: str) -> bool:
        """Revoke role from user"""
        if user_id not in self.user_roles:
            return False

        if role_name in self.user_roles[user_id]:
            self.user_roles[user_id].remove(role_name)
            return True

        return False

    def check_permission(self, user_id: str, permission: Permission) -> bool:
        """Check if user has specific permission"""
        if user_id not in self.user_roles:
            return False

        for role_name in self.user_roles[user_id]:
            role = self.roles.get(role_name)
            if role and role.has_permission(permission):
                return True

        return False

    def get_user_permissions(self, user_id: str) -> Set[Permission]:
        """Get all permissions for user"""
        all_permissions = set()

        if user_id in self.user_roles:
            for role_name in self.user_roles[user_id]:
                role = self.roles.get(role_name)
                if role:
                    all_permissions.update(role.get_all_permissions())

        return all_permissions

    def get_user_roles(self, user_id: str) -> List[Role]:
        """Get all roles assigned to user"""
        if user_id not in self.user_roles:
            return []

        return [self.roles[name] for name in self.user_roles[user_id] if name in self.roles]

    def export_config(self, filepath: str):
        """Export RBAC configuration to JSON"""
        config = {
            "roles": {name: role.to_dict() for name, role in self.roles.items()},
            "user_roles": {user: list(roles) for user, roles in self.user_roles.items()},
        }

        with open(filepath, "w") as f:
            json.dump(config, f, indent=2)

    def import_config(self, filepath: str):
        """Import RBAC configuration from JSON"""
        with open(filepath, "r") as f:
            config = json.load(f)

        # First pass: create all roles without inheritance
        for name, role_data in config["roles"].items():
            if role_data["inherits_from"] is None:
                self.roles[name] = Role.from_dict(role_data, self.roles)

        # Second pass: set up inheritance
        for name, role_data in config["roles"].items():
            if role_data["inherits_from"] is not None:
                self.roles[name] = Role.from_dict(role_data, self.roles)

        # Import user role assignments
        self.user_roles = {user: set(roles) for user, roles in config["user_roles"].items()}


def require_permission(permission: Permission):
    """Decorator to enforce permission checks"""

    def decorator(func):
        def wrapper(self, user_id: str, *args, **kwargs):
            if not isinstance(self, RBACManager):
                rbac = kwargs.get("rbac_manager")
                if not rbac:
                    raise ValueError("RBAC manager not provided")
            else:
                rbac = self

            if not rbac.check_permission(user_id, permission):
                raise PermissionError(
                    f"User {user_id} does not have permission: {permission.value}"
                )

            return func(self, user_id, *args, **kwargs)

        return wrapper

    return decorator
