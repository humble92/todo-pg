# Kubernetes deployment guide

## Prerequisites

- Kubernetes Cluster (1.19+)
- kubectl CLI tool
- Docker (for image building)
- Container Registry access privileges

## Quick start

### 1. Docker Image Build and Push

```bash
# Build FastAPI application image
docker build -f Dockerfile.fastapi -t humble92/todo-fastapi:latest .

# Build Worker image (uses worker/requirements.txt)
docker build -f worker/Dockerfile -t humble92/todo-worker:latest ./worker

# Build PostgreSQL with pg_cron image (optional)
docker build -f db/Dockerfile -t humble92/todo-pg:latest ./db

# Push images
docker push humble92/todo-fastapi:latest
docker push humble92/todo-worker:latest
docker push humble92/todo-pg:latest  # if using
```

### 2. Environments

#### 2.1 Secret Value Configuration

Create or edit the `k8s/secrets.yaml` file and enter the actual values:

```yaml
stringData:
  # PostgreSQL password (use strong password)
  POSTGRES_PASSWORD: "your-strong-postgres-password"
  DB_PASSWORD: "your-strong-db-user-password"
  
  # JWT secret (random string, minimum 32 characters)
  JWT_SECRET: "your-super-secret-jwt-key-at-least-32-chars"
  
  # Slack Bot Token
  SLACK_BOT_TOKEN: "xoxb-your-actual-slack-bot-token"
```

#### 2.2 Image Registry Configuration

Change to your actual Container Registry in the following files (if needed):
- `k8s/fastapi-deployment.yaml`
- `k8s/worker-deployment.yaml`
- `k8s/kustomization.yaml`

#### 2.3 Domain Configuration (when using Ingress)

Change the domain to the actual domain in `k8s/ingress.yaml`:
```yaml
rules:
  - host: api.your-actual-domain.com
  - host: admin.your-actual-domain.com
```

### 3. Deployment

```bash
# namespace
kubectl apply -f k8s/base/namespace.yaml

# Deploy all resources
kubectl apply -f k8s/base/

# Or using kustomize
kubectl apply -k k8s/base/
```

### 4. Deployment Status Check

#### Base Environment
```bash
# Check status of all resources
kubectl get all -n todo-app

# Check Pod logs
kubectl logs -n todo-app deployment/fastapi-app
kubectl logs -n todo-app deployment/reminder-worker
kubectl logs -n todo-app statefulset/postgres

# Test PostgreSQL connection
kubectl exec -it -n todo-app postgres-0 -- psql -U postgres -d slack_todo_db -c "SELECT version();"
```

#### Development Environment
```bash
# Check status of all resources
kubectl get all -n todo-app-dev

# Check Pod logs
kubectl logs -n todo-app-dev deployment/dev-fastapi-app
kubectl logs -n todo-app-dev deployment/dev-reminder-worker
kubectl logs -n todo-app-dev statefulset/dev-postgres

# Test PostgreSQL connection
kubectl exec -it -n todo-app-dev dev-postgres-0 -- psql -U postgres -d slack_todo_db -c "SELECT version();"
```

#### Production Environment
```bash
# Check status of all resources
kubectl get all -n todo-app-prod

# Check Pod logs
kubectl logs -n todo-app-prod deployment/prod-fastapi-app
kubectl logs -n todo-app-prod deployment/prod-reminder-worker
kubectl logs -n todo-app-prod statefulset/prod-postgres

# Test PostgreSQL connection
kubectl exec -it -n todo-app-prod prod-postgres-0 -- psql -U postgres -d slack_todo_db -c "SELECT version();"
```

## Detailed Configuration Guide

### PostgreSQL Configuration

#### Using pg_cron Extension

If the base PostgreSQL image doesn't include pg_cron, choose one of the following:

**Option 1: Use Custom Image**
```yaml
# in postgres-statefulset.yaml
image: humble92/todo-pg:latest
```

**Option 2: Install at Runtime**
```yaml
# Use initContainer to install pg_cron
# See comments in postgres-statefulset.yaml for details
```

#### Data Backup

```bash
# Database backup
kubectl exec -n todo-app postgres-0 -- pg_dump -U postgres slack_todo_db > backup.sql

# Restore backup
kubectl exec -i -n todo-app postgres-0 -- psql -U postgres slack_todo_db < backup.sql
```

### Scaling

```bash
# Scale FastAPI application (adjust deployment name based on environment)
# Base environment:
kubectl scale deployment fastapi-app -n todo-app --replicas=3
# Dev environment:
kubectl scale deployment dev-fastapi-app -n todo-app-dev --replicas=3
# Prod environment:
kubectl scale deployment prod-fastapi-app -n todo-app-prod --replicas=3

# Scale Worker (Note: verify duplicate processing prevention)
# Base environment:
kubectl scale deployment reminder-worker -n todo-app --replicas=2
# Dev environment:
kubectl scale deployment dev-reminder-worker -n todo-app-dev --replicas=2
# Prod environment:
kubectl scale deployment prod-reminder-worker -n todo-app-prod --replicas=2
```

### Monitoring and Logging

```bash
# Check real-time logs
kubectl logs -f -n todo-app deployment/fastapi-app
kubectl logs -f -n todo-app deployment/reminder-worker

# Check resource usage
kubectl top pods -n todo-app
kubectl top nodes
```

### SSL/TLS Configuration

Automatic SSL certificate setup using cert-manager:

```bash
# Install cert-manager (if needed)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# Create ClusterIssuer
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: your-email@domain.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: nginx
EOF
```

Then uncomment the SSL-related comments in `k8s/ingress.yaml`.

## Troubleshooting

### Common Issues

1. **Pod in Pending State**
   ```bash
   kubectl describe pod <pod-name> -n todo-app
   # Check for resource shortage or PVC mount issues
   ```

2. **Database Connection Failure**
   ```bash
   # Check PostgreSQL Pod logs
   kubectl logs -n todo-app postgres-0
   
   # Test network connection
   kubectl exec -n todo-app deployment/fastapi-app -- nc -zv postgres-service 5432
   ```

3. **Worker Not Sending Slack Messages**
   ```bash
   # Check Worker logs
   kubectl logs -n todo-app deployment/reminder-worker
   
   # Verify SLACK_BOT_TOKEN
   kubectl get secret todo-app-secrets -n todo-app -o yaml
   ```

### Useful Debugging Commands

```bash
# Decode Secret
kubectl get secret todo-app-secrets -n todo-app -o jsonpath='{.data.JWT_SECRET}' | base64 -d

# Check ConfigMap
kubectl get configmap todo-app-config -n todo-app -o yaml

# Check service endpoints
kubectl get endpoints -n todo-app

# Check events
kubectl get events -n todo-app --sort-by='.lastTimestamp'
```

## Environment-Specific Deployment

### Development Environment
```bash
kubectl apply -k k8s/overlays/dev/
```

### Production Environment
```bash
kubectl apply -k k8s/overlays/prod/
```

## Cleanup

Delete entire application:
```bash
kubectl delete namespace todo-app
```

Delete individual resources:
```bash
kubectl delete -f k8s/
```

## Security Considerations

1. 1. **Network Policy**: Set up NetworkPolicy as needed
2. **RBAC**: Configure ServiceAccount and Role according to the principle of least privilege
3. **Image Security**: Regularly update images and scan for vulnerabilities

## Additional Resources

- [Kubernetes Official Documentation](https://kubernetes.io/docs/)
- [FastAPI Official Documentation](https://fastapi.tiangolo.com/)
- [PostgreSQL Kubernetes Guide](https://kubernetes.io/docs/tutorials/stateful-application/basic-stateful-set/)
