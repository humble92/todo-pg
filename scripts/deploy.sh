#!/bin/bash

# Kubernetes Deployment Script
# Usage: ./scripts/deploy.sh [dev|prod] [--build] [--push]

# To clean up and redeploy, run (example for dev environment):
# kubectl delete namespace todo-app-dev
# ./scripts/deploy.sh dev
# kubectl get all -n todo-app-dev

# Test: connect to postgres container
# kubectl exec -it dev-postgres-0 -n todo-app-dev -- bash
# psql -h dev-postgres-service -U slack_todo_user -d slack_todo_db
# OR
# kubectl exec -it dev-postgres-0 -n todo-app-dev -- psql -h dev-postgres-service -U slack_todo_user -d slack_todo_db
# cf. check DB_PASSWORD
# kubectl get secret dev-todo-app-secrets -n todo-app-dev -o jsonpath='{.data.DB_PASSWORD}' | base64 -d

set -e

# Set default values
REGISTRY="humble92"
TAG="latest"
ENVIRONMENT="dev"
BUILD=false
PUSH=false

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Help function
show_help() {
    echo "Usage: $0 [ENVIRONMENT] [OPTIONS]"
    echo ""
    echo "ENVIRONMENT:"
    echo "  dev     Deploy to development environment"
    echo "  prod    Deploy to production environment"
    echo "  base    Deploy with base configuration"
    echo ""
    echo "OPTIONS:"
    echo "  --build    Build Docker images"
    echo "  --push     Push Docker images"
    echo "  --help     Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 dev --build --push    # Development: build + push + deploy"
    echo "  $0 prod                  # Production: deploy only"
    echo "  $0 base                  # Base: deploy only"
}

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Environment validation
check_requirements() {
    log_info "Checking deployment requirements..."
    
    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed."
        exit 1
    fi
    
    # Check Docker (if build is needed)
    if [[ "$BUILD" == "true" || "$PUSH" == "true" ]] && ! command -v docker &> /dev/null; then
        log_error "Docker is not installed."
        exit 1
    fi
    
    # Check Kubernetes cluster connection
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster."
        exit 1
    fi
    
    log_success "All requirements are satisfied."
}

# Build Docker images
build_images() {
    log_info "Building Docker images..."
    
    REGISTRY=${REGISTRY:-"humble92"}
    TAG=${TAG:-"latest"}
    
    docker build -f Dockerfile.fastapi -t "${REGISTRY}/todo-fastapi:${TAG}" . || {
        log_error "Failed to build FastAPI image"
        exit 1
    }
    
    docker build -f worker/Dockerfile -t "${REGISTRY}/todo-worker:${TAG}" ./worker || {
        log_error "Failed to build Worker image"
        exit 1
    }
    
    docker build -f db/Dockerfile -t "${REGISTRY}/todo-pg:${TAG}" ./db || {
        log_error "Failed to build PostgreSQL image"
        exit 1
    }
    
    log_success "All images built successfully"
}

# Push Docker images
push_images() {
    log_info "Pushing Docker images..."
    
    REGISTRY=${REGISTRY:-"humble92"}
    TAG=${TAG:-"latest"}
    
    docker push "${REGISTRY}/todo-fastapi:${TAG}" || {
        log_error "Failed to push FastAPI image"
        exit 1
    }
    
    docker push "${REGISTRY}/todo-worker:${TAG}" || {
        log_error "Failed to push Worker image"
        exit 1
    }
    
    docker push "${REGISTRY}/todo-pg:${TAG}" || {
        log_error "Failed to push PostgreSQL image"
        exit 1
    }
    
    log_success "All images pushed successfully"
}

# Validate secret files
validate_secrets() {
    log_info "Checking secret configuration..."
    
    SECRET_FILE="k8s/base/secrets.yaml"
    
    if grep -q "your-.*-here" "$SECRET_FILE"; then
        log_warning "secrets.yaml contains default values."
        log_warning "Please change to actual values:"
        grep "your-.*-here" "$SECRET_FILE" | sed 's/^/  /'
        
        read -p "Do you want to continue? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Deployment cancelled."
            exit 0
        fi
    fi
    
    log_success "Secret configuration validation completed"
}

# Validate image registry
validate_registry() {
    log_info "Checking image registry configuration..."
    
    if grep -q "your-registry" k8s/base/*.yaml; then
        log_warning "Some files contain default registry settings."
        log_warning "Please change to actual registry:"
        grep -l "your-registry" k8s/base/*.yaml | sed 's/^/  /'
        
        read -p "Do you want to continue? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Deployment cancelled."
            exit 0
        fi
    fi
    
    log_success "Image registry configuration validation completed"
}

# Deploy to Kubernetes
deploy_kubernetes() {
    local env=$1
    
    log_info "Deploying to ${env} environment..."
    
    case $env in
        "dev")
            NAMESPACE="todo-app-dev"
            kubectl apply -k k8s/overlays/dev/ || {
                log_error "Failed to deploy to development environment"
                exit 1
            }
            ;;
        "prod")
            NAMESPACE="todo-app-prod"
            kubectl apply -k k8s/overlays/prod/ || {
                log_error "Failed to deploy to production environment"
                exit 1
            }
            ;;
        "base")
            NAMESPACE="todo-app"
            kubectl apply -f k8s/base/namespace.yaml
            kubectl apply -f k8s/base/ || {
                log_error "Failed to deploy to base environment"
                exit 1
            }
            ;;
        *)
            log_error "Unknown environment: $env"
            exit 1
            ;;
    esac
    
    log_success "${env} environment deployment completed"
    
    # Check deployment status
    log_info "Checking deployment status..."
    sleep 5
    kubectl get pods -n "$NAMESPACE" -o wide
    
    # Check service status
    log_info "Checking service status..."
    kubectl get services -n "$NAMESPACE"
}

# Verify deployment
verify_deployment() {
    local namespace=$1
    
    log_info "Verifying deployment..."
    
    # Check Pod status
    local ready_pods
    ready_pods=$(kubectl get pods -n "$namespace" --no-headers | grep -c "Running" || echo "0")
    local total_pods
    total_pods=$(kubectl get pods -n "$namespace" --no-headers | wc -l)
    
    if [[ $ready_pods -eq $total_pods ]] && [[ $total_pods -gt 0 ]]; then
        log_success "All Pods are running successfully. ($ready_pods/$total_pods)"
    else
        log_warning "Some Pods are not ready. ($ready_pods/$total_pods)"
        kubectl get pods -n "$namespace"
    fi
    
    # Service health check (using port forwarding)
    log_info "Performing health check..."
    
    # Wait briefly (5 seconds) then perform health check
    local service_name="fastapi-service"
    if [[ "$namespace" == "todo-app-dev" ]]; then
        service_name="dev-fastapi-service"
    elif [[ "$namespace" == "todo-app-prod" ]]; then
        service_name="prod-fastapi-service"
    fi
    
    timeout 30s bash -c "
        kubectl port-forward -n $namespace service/$service_name 8000:8000 &
        PF_PID=\$!
        trap 'kill $PF_PID 2>/dev/null' EXIT

        sleep 5
        if curl -f http://localhost:8000/healthz &>/dev/null; then
            echo 'FastAPI health check succeeded'
        else
            echo 'FastAPI health check failed'
        fi
        # kill \$PF_PID 2>/dev/null || true
    " || log_warning "Health check timeout"
}

# Main function
main() {

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            dev|prod|base)
                ENVIRONMENT="$1"
                shift
                ;;
            --build)
                BUILD=true
                shift
                ;;
            --push)
                PUSH=true
                shift
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    # Check environment configuration
    if [[ -z "$ENVIRONMENT" ]]; then
        log_error "Please specify deployment environment."
        show_help
        exit 1
    fi
    
    log_info "Starting Todo App Kubernetes deployment"
    log_info "Environment: $ENVIRONMENT"
    log_info "Build: $BUILD"
    log_info "Push: $PUSH"
    echo ""
    
    # Check requirements
    check_requirements
    
    # Validate secrets and registry
    validate_secrets
    validate_registry
    
    # Build Docker images
    if [[ "$BUILD" == "true" ]]; then
        build_images
    fi
    
    # Push Docker images
    if [[ "$PUSH" == "true" ]]; then
        push_images
    fi
    
    # Deploy to Kubernetes
    deploy_kubernetes "$ENVIRONMENT"
    
    # Verify deployment
    case $ENVIRONMENT in
        "dev") verify_deployment "todo-app-dev" ;;
        "prod") verify_deployment "todo-app-prod" ;;
        "base") verify_deployment "todo-app" ;;
    esac
    
    log_success "Deployment completed successfully!"
    
    # Output connection information
    echo ""
    log_info "Connection information:"
    log_info "  Local access via port forwarding: make port-forward ENV=$ENVIRONMENT"
    log_info "  Check logs: make logs ENV=$ENVIRONMENT"
    log_info "  Check status: make status ENV=$ENVIRONMENT"
}

# Execute script
main "$@"
