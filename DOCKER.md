# Docker Setup for AstraGuard AI

This guide explains how to build and run AstraGuard AI using Docker.

## Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- 2GB RAM minimum
- 500MB disk space

## Quick Start

### 1. Build the Image

```bash
docker build -t astraguard-ai:latest .
```

### 2. Run with Docker Compose

**Production Mode:**
```bash
docker-compose up -d
```

**Development Mode (with hot reload):**
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

## Services

The docker-compose configuration includes:

### Core Services
- **astra-guard** (8000): FastAPI backend with distributed resilience
- **redis** (6379): In-memory cache and distributed coordination (Issue #18)

### Observability Services (Optional)
- **prometheus** (9090): Metrics collection
- **grafana** (3000): Visualization and dashboards

## Ports

| Service | Port | Purpose |
|---------|------|---------|
| AstraGuard Backend | 8000 | API and health endpoints |
| Redis | 6379 | Distributed state coordination |
| Prometheus | 9090 | Metrics scraping |
| Grafana | 3000 | Dashboard visualization |

## Health Checks

The container includes health checks for:
- **Liveness**: `GET /health/live` (Kubernetes liveness probe)
- **Readiness**: `GET /health/ready` (Kubernetes readiness probe)
- **Status**: `GET /health/state` (Comprehensive health snapshot)
- **Metrics**: `GET /health/metrics` (Prometheus metrics)

## Scaling

To run multiple AstraGuard instances for distributed testing:

```bash
docker-compose up -d --scale astra-guard=3
```

Edit `docker-compose.yml` and change `replicas: 1` to `replicas: 3`.

## Volumes

- **redis_data**: Redis persistence
- **prometheus_data**: Prometheus metrics storage
- **grafana_data**: Grafana configuration and dashboards
- **./backend**: Source code mount (development)
- **./config**: Configuration files
- **./logs**: Application logs

## Environment Variables

Set in `docker-compose.yml` or `.env`:

```bash
REDIS_URL=redis://redis:6379
LOG_LEVEL=INFO
PYTHONUNBUFFERED=1
```

## Monitoring

### View Logs

```bash
docker-compose logs -f astra-guard
docker-compose logs -f redis
```

### Access Dashboards

- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/admin)

## Troubleshooting

### Container won't start

```bash
docker-compose logs astra-guard
```

### Port already in use

Change port in `docker-compose.yml`:
```yaml
ports:
  - "8001:8000"  # Map to different host port
```

### Redis connection failed

Check Redis health:
```bash
docker-compose exec redis redis-cli ping
```

### Clear everything and restart

```bash
docker-compose down -v
docker-compose up -d
```

## Production Deployment

For production, use Kubernetes manifests (planned) or:

1. Use a separate database for Redis (e.g., AWS ElastiCache)
2. Set proper resource limits in docker-compose.yml
3. Use environment-specific .env files
4. Enable persistent volumes with proper backup

## Related

- [Technical Documentation](docs/TECHNICAL.md)
- [Distributed Architecture](docs/DISTRIBUTED.md)
- [GitHub Actions CI/CD](.github/workflows/tests.yml)
