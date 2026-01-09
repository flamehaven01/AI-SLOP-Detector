# REST API Documentation

## Overview

AI SLOP Detector v2.4.0+ includes a production-ready REST API built with FastAPI.

**Base URL**: `http://localhost:8000` (configurable)

---

## Quick Start

### Start Server

```bash
# Command line
slop-api --host 0.0.0.0 --port 8000

# Python
python -m slop_detector.api.server

# Docker
docker run -p 8000:8000 flamehaven/ai-slop-detector:2.4.0
```

### Access Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## Endpoints

### Health Check

```http
GET /health
```

**Response**:
```json
{
  "status": "healthy",
  "timestamp": "2026-05-15T10:00:00Z"
}
```

---

### Analyze Single File

```http
POST /analyze/file
Content-Type: application/json

{
  "file_path": "/path/to/file.py",
  "save_history": true,
  "metadata": {
    "commit": "abc123",
    "branch": "main",
    "author": "john@example.com"
  }
}
```

**Response**:
```json
{
  "file_path": "/path/to/file.py",
  "slop_score": 12.3,
  "grade": "A",
  "ldr_score": 0.92,
  "bcr_score": 0.15,
  "ddc_score": 0.95,
  "patterns": [
    {
      "type": "mutable_default_arg",
      "severity": "critical",
      "line": 42,
      "message": "Mutable default argument detected"
    }
  ],
  "ml_prediction": 8.5,
  "timestamp": "2026-05-15T10:00:00Z"
}
```

---

### Analyze Project

```http
POST /analyze/project
Content-Type: application/json

{
  "project_path": "/path/to/project",
  "save_history": true,
  "metadata": {}
}
```

**Response**: Array of AnalysisResponse objects

**Note**: Runs asynchronously for large projects. Results saved to history.

---

### Get File History

```http
GET /history/file/{file_path}?limit=10
```

**Example**:
```bash
curl "http://localhost:8000/history/file/src%2Fmain.py?limit=5"
```

**Response**: Array of historical analysis results

---

### Get Project Trends

```http
GET /trends/project?project_path=/path/to/project&days=30
```

**Response**:
```json
{
  "project_path": "/path/to/project",
  "period_days": 30,
  "data_points": [
    {"date": "2026-04-15", "score": 85.2},
    {"date": "2026-04-16", "score": 86.1},
    ...
  ],
  "average_score": 85.5,
  "trend_direction": "improving",
  "regression_count": 2
}
```

---

### GitHub Webhook

```http
POST /webhook/github
Content-Type: application/json

{
  "ref": "refs/heads/main",
  "before": "abc123...",
  "after": "def456...",
  "repository": {...},
  "commits": [...]
}
```

**Response**:
```json
{
  "status": "accepted",
  "job_id": "def456"
}
```

**Note**: Analysis runs in background. Results posted back to GitHub (planned).

---

## Data Models

### AnalysisRequest

```typescript
{
  file_path?: string;
  project_path?: string;
  save_history?: boolean;  // default: true
  metadata?: Record<string, any>;
}
```

### AnalysisResponse

```typescript
{
  file_path: string;
  slop_score: number;
  grade: string;  // S++, S, A, B, C, D, F
  ldr_score: number;
  bcr_score: number;
  ddc_score: number;
  patterns: Pattern[];
  ml_prediction?: number;
  timestamp: string;
}
```

### Pattern

```typescript
{
  type: string;
  severity: "critical" | "high" | "medium" | "low";
  line: number;
  message: string;
  suggestion?: string;
}
```

---

## Error Responses

### 404 Not Found

```json
{
  "detail": "File not found"
}
```

### 500 Internal Server Error

```json
{
  "detail": "Error message here"
}
```

---

## Authentication

**Current**: No authentication (development mode)

**Production**: Configure API keys or OAuth2

```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

security = HTTPBearer()

async def verify_token(token: str = Depends(security)):
    if token.credentials != "your-secret-key":
        raise HTTPException(status_code=403)
```

---

## Rate Limiting

**Planned for v3.0**

```python
from slowapi import Limiter

limiter = Limiter(key_func=get_remote_address)

@app.post("/analyze/file")
@limiter.limit("10/minute")
async def analyze_file(...):
    ...
```

---

## CORS Configuration

**Development** (current):
```python
allow_origins=["*"]
```

**Production** (recommended):
```python
allow_origins=[
    "https://dashboard.company.com",
    "https://app.company.com"
]
```

Edit in `src/slop_detector/api/server.py`.

---

## Deployment

### Development

```bash
slop-api --host 127.0.0.1 --port 8000
```

### Production (Uvicorn)

```bash
uvicorn slop_detector.api.server:create_app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --log-level info
```

### Production (Gunicorn + Uvicorn)

```bash
gunicorn slop_detector.api.server:create_app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  -b 0.0.0.0:8000
```

### Docker

```bash
docker run -p 8000:8000 \
  -v $(pwd)/config:/config \
  -e CONFIG_PATH=/config/slop.yaml \
  flamehaven/ai-slop-detector:2.4.0
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: slop-detector-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: slop-detector
  template:
    metadata:
      labels:
        app: slop-detector
    spec:
      containers:
      - name: api
        image: flamehaven/ai-slop-detector:2.4.0
        ports:
        - containerPort: 8000
        env:
        - name: CONFIG_PATH
          value: /config/slop.yaml
        volumeMounts:
        - name: config
          mountPath: /config
      volumes:
      - name: config
        configMap:
          name: slop-config
---
apiVersion: v1
kind: Service
metadata:
  name: slop-detector-api
spec:
  selector:
    app: slop-detector
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer
```

---

## Integration Examples

### Python Client

```python
import requests

class SlopDetectorClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
    
    def analyze_file(self, file_path, **metadata):
        response = requests.post(
            f"{self.base_url}/analyze/file",
            json={
                "file_path": file_path,
                "save_history": True,
                "metadata": metadata
            }
        )
        response.raise_for_status()
        return response.json()
    
    def get_trends(self, project_path, days=30):
        response = requests.get(
            f"{self.base_url}/trends/project",
            params={"project_path": project_path, "days": days}
        )
        response.raise_for_status()
        return response.json()

# Usage
client = SlopDetectorClient()
result = client.analyze_file("src/main.py", commit="abc123")
print(f"Score: {result['slop_score']}")
```

### JavaScript Client

```javascript
class SlopDetectorClient {
  constructor(baseUrl = 'http://localhost:8000') {
    this.baseUrl = baseUrl;
  }
  
  async analyzeFile(filePath, metadata = {}) {
    const response = await fetch(`${this.baseUrl}/analyze/file`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_path: filePath,
        save_history: true,
        metadata
      })
    });
    return response.json();
  }
  
  async getTrends(projectPath, days = 30) {
    const params = new URLSearchParams({ project_path: projectPath, days });
    const response = await fetch(`${this.baseUrl}/trends/project?${params}`);
    return response.json();
  }
}

// Usage
const client = new SlopDetectorClient();
const result = await client.analyzeFile('src/main.py', { commit: 'abc123' });
console.log(`Score: ${result.slop_score}`);
```

### cURL Examples

```bash
# Analyze file
curl -X POST http://localhost:8000/analyze/file \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/path/to/file.py"}'

# Get trends
curl "http://localhost:8000/trends/project?project_path=/path/to/project&days=30"

# Health check
curl http://localhost:8000/health
```

---

## Performance

### Benchmarks

- **Single file analysis**: ~50ms (small file)
- **Project analysis**: ~2s per 100 files
- **API overhead**: ~5ms
- **Concurrent requests**: Handles 100+ req/s

### Optimization Tips

1. **Use background tasks** for large projects
2. **Cache results** in history database
3. **Filter changed files** with Git integration
4. **Horizontal scaling** with multiple workers

---

## Monitoring

### Health Endpoint

```bash
# Check if API is up
curl http://localhost:8000/health

# In monitoring system
if ! curl -f http://localhost:8000/health; then
  alert "SLOP Detector API is down"
fi
```

### Metrics (Planned)

```python
from prometheus_client import Counter, Histogram

analysis_count = Counter('slop_analyses_total', 'Total analyses')
analysis_duration = Histogram('slop_analysis_duration_seconds', 'Analysis duration')
```

---

## Troubleshooting

### API Won't Start

```bash
# Check port is free
lsof -i :8000

# Try different port
slop-api --port 8001
```

### Slow Response

```bash
# Increase workers
uvicorn slop_detector.api.server:create_app --workers 8

# Check system resources
top
```

### CORS Errors

Update `allow_origins` in `server.py`:
```python
allow_origins=["http://localhost:3000"]
```

---

## See Also

- [CHANGELOG.md](../CHANGELOG.md) - Version history
- [RELEASE_v2.4.0.md](../RELEASE_v2.4.0.md) - Release notes
- [README.md](../README.md) - Main documentation
