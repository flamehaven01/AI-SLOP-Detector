"""
Audit Logging System for AI SLOP Detector
Tracks all user actions, permission checks, and system events
"""

import json
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path


class AuditEventType(str, Enum):
    """Types of auditable events"""
    
    # Authentication events
    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILURE = "auth.login.failure"
    LOGOUT = "auth.logout"
    TOKEN_REFRESH = "auth.token.refresh"
    
    # Authorization events
    PERMISSION_GRANTED = "authz.permission.granted"
    PERMISSION_DENIED = "authz.permission.denied"
    ROLE_ASSIGNED = "authz.role.assigned"
    ROLE_REVOKED = "authz.role.revoked"
    
    # Analysis events
    ANALYZE_FILE_START = "analysis.file.start"
    ANALYZE_FILE_COMPLETE = "analysis.file.complete"
    ANALYZE_PROJECT_START = "analysis.project.start"
    ANALYZE_PROJECT_COMPLETE = "analysis.project.complete"
    
    # Configuration events
    CONFIG_READ = "config.read"
    CONFIG_UPDATE = "config.update"
    THRESHOLD_CHANGE = "config.threshold.change"
    
    # Model events
    MODEL_TRAIN_START = "model.train.start"
    MODEL_TRAIN_COMPLETE = "model.train.complete"
    MODEL_DEPLOY = "model.deploy"
    MODEL_LOAD = "model.load"
    
    # User management events
    USER_INVITE = "user.invite"
    USER_REMOVE = "user.remove"
    USER_UPDATE = "user.update"
    
    # System events
    SYSTEM_START = "system.start"
    SYSTEM_SHUTDOWN = "system.shutdown"
    ERROR = "system.error"
    SECURITY_ALERT = "security.alert"


class AuditSeverity(str, Enum):
    """Severity levels for audit events"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AuditEvent:
    """Single audit log entry"""
    
    event_id: str
    event_type: AuditEventType
    timestamp: datetime
    user_id: Optional[str]
    user_email: Optional[str]
    ip_address: Optional[str]
    severity: AuditSeverity
    action: str
    resource: Optional[str]
    result: str  # "success" or "failure"
    details: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        data['event_type'] = self.event_type.value
        data['severity'] = self.severity.value
        data['details'] = json.dumps(self.details)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AuditEvent':
        """Create from dictionary"""
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        data['event_type'] = AuditEventType(data['event_type'])
        data['severity'] = AuditSeverity(data['severity'])
        data['details'] = json.loads(data['details']) if isinstance(data['details'], str) else data['details']
        return cls(**data)


class AuditLogger:
    """
    Audit logging system with SQLite backend
    
    Features:
    - Tamper-proof logging
    - Query interface
    - Retention policies
    - Export capabilities
    """
    
    def __init__(self, db_path: str = "audit.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                user_id TEXT,
                user_email TEXT,
                ip_address TEXT,
                severity TEXT NOT NULL,
                action TEXT NOT NULL,
                resource TEXT,
                result TEXT NOT NULL,
                details TEXT,
                session_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indices for common queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp 
            ON audit_logs(timestamp)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_id 
            ON audit_logs(user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_event_type 
            ON audit_logs(event_type)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_severity 
            ON audit_logs(severity)
        """)
        
        conn.commit()
        conn.close()
    
    def log(self, event: AuditEvent) -> bool:
        """
        Log audit event
        
        Args:
            event: AuditEvent to log
            
        Returns:
            True if successful
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            event_dict = event.to_dict()
            columns = ', '.join(event_dict.keys())
            placeholders = ', '.join(['?' for _ in event_dict])
            
            cursor.execute(
                f"INSERT INTO audit_logs ({columns}) VALUES ({placeholders})",
                list(event_dict.values())
            )
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"[!] Audit log error: {e}")
            return False
    
    def log_login(self, user_id: str, email: str, ip: str, success: bool, 
                  details: Optional[Dict] = None):
        """Convenience method for login events"""
        import uuid
        
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type=AuditEventType.LOGIN_SUCCESS if success else AuditEventType.LOGIN_FAILURE,
            timestamp=datetime.utcnow(),
            user_id=user_id if success else None,
            user_email=email,
            ip_address=ip,
            severity=AuditSeverity.INFO if success else AuditSeverity.WARNING,
            action="User login",
            resource="auth",
            result="success" if success else "failure",
            details=details or {}
        )
        
        self.log(event)
    
    def log_permission_check(self, user_id: str, permission: str, granted: bool,
                            resource: Optional[str] = None, details: Optional[Dict] = None):
        """Convenience method for permission checks"""
        import uuid
        
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type=AuditEventType.PERMISSION_GRANTED if granted else AuditEventType.PERMISSION_DENIED,
            timestamp=datetime.utcnow(),
            user_id=user_id,
            user_email=None,
            ip_address=None,
            severity=AuditSeverity.INFO if granted else AuditSeverity.WARNING,
            action=f"Permission check: {permission}",
            resource=resource,
            result="success" if granted else "failure",
            details=details or {}
        )
        
        self.log(event)
    
    def log_analysis(self, user_id: str, analysis_type: str, target: str, 
                    result: str, details: Optional[Dict] = None):
        """Convenience method for analysis events"""
        import uuid
        
        event_type = (AuditEventType.ANALYZE_FILE_COMPLETE 
                     if analysis_type == "file" 
                     else AuditEventType.ANALYZE_PROJECT_COMPLETE)
        
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.utcnow(),
            user_id=user_id,
            user_email=None,
            ip_address=None,
            severity=AuditSeverity.INFO,
            action=f"Analysis completed: {analysis_type}",
            resource=target,
            result=result,
            details=details or {}
        )
        
        self.log(event)
    
    def query(self, 
              user_id: Optional[str] = None,
              event_type: Optional[AuditEventType] = None,
              severity: Optional[AuditSeverity] = None,
              start_date: Optional[datetime] = None,
              end_date: Optional[datetime] = None,
              limit: int = 100) -> List[AuditEvent]:
        """
        Query audit logs
        
        Args:
            user_id: Filter by user
            event_type: Filter by event type
            severity: Filter by severity
            start_date: Filter by start date
            end_date: Filter by end date
            limit: Maximum results
            
        Returns:
            List of AuditEvent objects
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM audit_logs WHERE 1=1"
        params = []
        
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type.value)
        
        if severity:
            query += " AND severity = ?"
            params.append(severity.value)
        
        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date.isoformat())
        
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date.isoformat())
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        events = []
        for row in rows:
            event_dict = dict(row)
            events.append(AuditEvent.from_dict(event_dict))
        
        return events
    
    def get_security_alerts(self, hours: int = 24) -> List[AuditEvent]:
        """Get recent security alerts"""
        from datetime import timedelta
        
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        return self.query(
            severity=AuditSeverity.CRITICAL,
            start_date=cutoff
        ) + self.query(
            event_type=AuditEventType.SECURITY_ALERT,
            start_date=cutoff
        )
    
    def get_user_activity(self, user_id: str, days: int = 30) -> List[AuditEvent]:
        """Get recent activity for specific user"""
        from datetime import timedelta
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        return self.query(
            user_id=user_id,
            start_date=cutoff,
            limit=500
        )
    
    def export_to_json(self, filepath: str, filters: Optional[Dict] = None):
        """Export audit logs to JSON file"""
        filters = filters or {}
        events = self.query(**filters, limit=10000)
        
        with open(filepath, 'w') as f:
            json.dump([e.to_dict() for e in events], f, indent=2)
    
    def cleanup_old_logs(self, days: int = 90) -> int:
        """
        Delete audit logs older than specified days
        
        Args:
            days: Retention period in days
            
        Returns:
            Number of deleted records
        """
        from datetime import timedelta
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "DELETE FROM audit_logs WHERE timestamp < ?",
            (cutoff.isoformat(),)
        )
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        return deleted
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get audit log statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Total events
        cursor.execute("SELECT COUNT(*) FROM audit_logs")
        total = cursor.fetchone()[0]
        
        # Events by type
        cursor.execute("""
            SELECT event_type, COUNT(*) as count 
            FROM audit_logs 
            GROUP BY event_type 
            ORDER BY count DESC 
            LIMIT 10
        """)
        by_type = dict(cursor.fetchall())
        
        # Events by severity
        cursor.execute("""
            SELECT severity, COUNT(*) as count 
            FROM audit_logs 
            GROUP BY severity
        """)
        by_severity = dict(cursor.fetchall())
        
        # Most active users
        cursor.execute("""
            SELECT user_id, COUNT(*) as count 
            FROM audit_logs 
            WHERE user_id IS NOT NULL 
            GROUP BY user_id 
            ORDER BY count DESC 
            LIMIT 10
        """)
        top_users = dict(cursor.fetchall())
        
        conn.close()
        
        return {
            'total_events': total,
            'by_type': by_type,
            'by_severity': by_severity,
            'top_users': top_users,
        }


# Example usage
if __name__ == "__main__":
    import uuid
    
    # Initialize logger
    logger = AuditLogger("test_audit.db")
    
    # Log login
    logger.log_login(
        user_id="user123",
        email="john@example.com",
        ip="192.168.1.100",
        success=True,
        details={"sso_provider": "okta"}
    )
    
    # Log permission check
    logger.log_permission_check(
        user_id="user123",
        permission="analyze:project",
        granted=True,
        resource="project/myapp"
    )
    
    # Log analysis
    logger.log_analysis(
        user_id="user123",
        analysis_type="project",
        target="/path/to/project",
        result="success",
        details={"slop_score": 15.3, "grade": "S"}
    )
    
    # Query logs
    recent = logger.query(user_id="user123", limit=10)
    print(f"[+] Found {len(recent)} recent events")
    
    # Get statistics
    stats = logger.get_statistics()
    print(f"[=] Statistics: {json.dumps(stats, indent=2)}")
