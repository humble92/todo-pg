# Makefile for Kubernetes deployment

# variables
REGISTRY ?= humble92
TAG ?= latest
ENV ?= dev

# Docker image names
FASTAPI_IMAGE = $(REGISTRY)/todo-fastapi:$(TAG)
WORKER_IMAGE = $(REGISTRY)/todo-worker:$(TAG)
POSTGRES_IMAGE = $(REGISTRY)/todo-pg:$(TAG)

.PHONY: help build push deploy clean status logs

help: ## print available commands
	@echo "available commands:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## build Docker images
	@echo "build Docker images..."
	docker build -f Dockerfile.fastapi -t $(FASTAPI_IMAGE) .
	docker build -f worker/Dockerfile -t $(WORKER_IMAGE) ./worker
	docker build -f db/Dockerfile -t $(POSTGRES_IMAGE) ./db
	@echo "build complete!"

push: ## push Docker images to registry
	@echo "pushing Docker images..."
	docker push $(FASTAPI_IMAGE)
	docker push $(WORKER_IMAGE)
	docker push $(POSTGRES_IMAGE)
	@echo "push complete!"

build-push: build push ## build and push

deploy: ## Kubernetes deployment (ENV=dev|prod)
	@echo "$(ENV) environment deployment..."
	@if [ "$(ENV)" = "dev" ]; then \
		kubectl apply -k k8s/overlays/dev/; \
	elif [ "$(ENV)" = "prod" ]; then \
		kubectl apply -k k8s/overlays/prod/; \
	else \
		kubectl apply -k k8s/base/; \
	fi
	@echo "deployment complete!"

deploy-base: ## base deployment
	@echo "base deployment..."
	kubectl apply -f k8s/base/namespace.yaml
	kubectl apply -f k8s/base/
	@echo "deployment complete!"

status: ## deployment status check
	@echo "deployment status check..."
	@if [ "$(ENV)" = "dev" ]; then \
		kubectl get all -n todo-app-dev; \
	elif [ "$(ENV)" = "prod" ]; then \
		kubectl get all -n todo-app-prod; \
	else \
		kubectl get all -n todo-app; \
	fi

logs: ## application logs check
	@echo "logs check (Ctrl+C to exit)..."
	@if [ "$(ENV)" = "dev" ]; then \
		kubectl logs -f -n todo-app-dev deployment/dev-fastapi-app; \
	elif [ "$(ENV)" = "prod" ]; then \
		kubectl logs -f -n todo-app-prod deployment/prod-fastapi-app; \
	else \
		kubectl logs -f -n todo-app deployment/fastapi-app; \
	fi

logs-worker: ## Worker logs check
	@echo "Worker logs check (Ctrl+C to exit)..."
	@if [ "$(ENV)" = "dev" ]; then \
		kubectl logs -f -n todo-app-dev deployment/dev-reminder-worker; \
	elif [ "$(ENV)" = "prod" ]; then \
		kubectl logs -f -n todo-app-prod deployment/prod-reminder-worker; \
	else \
		kubectl logs -f -n todo-app deployment/reminder-worker; \
	fi

logs-db: ## PostgreSQL logs check
	@echo "PostgreSQL logs check (Ctrl+C to exit)..."
	@if [ "$(ENV)" = "dev" ]; then \
		kubectl logs -f -n todo-app-dev statefulset/dev-postgres; \
	elif [ "$(ENV)" = "prod" ]; then \
		kubectl logs -f -n todo-app-prod statefulset/prod-postgres; \
	else \
		kubectl logs -f -n todo-app statefulset/postgres; \
	fi

clean: ## deleting deployed resources
	@echo "deleting resources..."
	@if [ "$(ENV)" = "dev" ]; then \
		kubectl delete namespace todo-app-dev; \
	elif [ "$(ENV)" = "prod" ]; then \
		kubectl delete namespace todo-app-prod; \
	else \
		kubectl delete namespace todo-app; \
	fi
	@echo "deletion complete!"

db-connect: ## PostgreSQL connection
	@echo "PostgreSQL connection..."
	@if [ "$(ENV)" = "dev" ]; then \
		kubectl exec -it -n todo-app-dev dev-postgres-0 -- psql -U postgres -d slack_todo_db; \
	elif [ "$(ENV)" = "prod" ]; then \
		kubectl exec -it -n todo-app-prod prod-postgres-0 -- psql -U postgres -d slack_todo_db; \
	else \
		kubectl exec -it -n todo-app postgres-0 -- psql -U postgres -d slack_todo_db; \
	fi

port-forward: ## local service access (port forwarding)
	@echo "port forwarding... (Ctrl+C to exit)"
	@echo "FastAPI: http://localhost:8000"
	@echo "Adminer: http://localhost:8080"
	@if [ "$(ENV)" = "dev" ]; then \
		kubectl port-forward -n todo-app-dev service/dev-fastapi-service 8000:8000 & \
		kubectl port-forward -n todo-app-dev service/dev-adminer-service 8080:8080; \
	elif [ "$(ENV)" = "prod" ]; then \
		kubectl port-forward -n todo-app-prod service/prod-fastapi-service 8000:8000 & \
		kubectl port-forward -n todo-app-prod service/prod-adminer-service 8080:8080; \
	else \
		kubectl port-forward -n todo-app service/fastapi-service 8000:8000 & \
		kubectl port-forward -n todo-app service/adminer-service 8080:8080; \
	fi

backup-db: ## database backup
	@echo "database backup..."
	@if [ "$(ENV)" = "dev" ]; then \
		kubectl exec -n todo-app-dev dev-postgres-0 -- pg_dump -U postgres slack_todo_db > backup-dev-$$(date +%Y%m%d_%H%M%S).sql; \
	elif [ "$(ENV)" = "prod" ]; then \
		kubectl exec -n todo-app-prod prod-postgres-0 -- pg_dump -U postgres slack_todo_db > backup-prod-$$(date +%Y%m%d_%H%M%S).sql; \
	else \
		kubectl exec -n todo-app postgres-0 -- pg_dump -U postgres slack_todo_db > backup-$$(date +%Y%m%d_%H%M%S).sql; \
	fi
	@echo "backup complete!"

# dev environment shortcut commands
dev-deploy: ## dev environment deployment
	$(MAKE) deploy ENV=dev

dev-status: ## dev environment status check
	$(MAKE) status ENV=dev

dev-logs: ## dev environment logs check
	$(MAKE) logs ENV=dev

dev-clean: ## dev environment cleanup
	$(MAKE) clean ENV=dev

# prod environment shortcut commands
prod-deploy: ## prod environment deployment
	$(MAKE) deploy ENV=prod

prod-status: ## prod environment status check
	$(MAKE) status ENV=prod

prod-logs: ## prod environment logs check
	$(MAKE) logs ENV=prod

prod-clean: ## prod environment cleanup
	$(MAKE) clean ENV=prod
