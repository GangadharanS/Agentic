# MCP Tools Docker Deployment Guide

This guide explains how to build, configure, and deploy the MCP Tools Docker image to Artifactory and Kubernetes.

## 📋 Table of Contents

1. [Overview](#overview)
2. [Configuration System](#configuration-system)
3. [Building the Docker Image](#building-the-docker-image)
4. [Publishing to Artifactory](#publishing-to-artifactory)
5. [Kubernetes Deployment](#kubernetes-deployment)
6. [Troubleshooting](#troubleshooting)

## 🎯 Overview

The MCP Tools application provides a Model Context Protocol server with 40+ tools for:
- JIRA integration
- Bitbucket and GitHub PR analysis
- Email notifications
- MEND security analysis
- Automated code fixes

## ⚙️ Configuration System

### Properties Files

The application uses a layered configuration system:

```
application.properties         # Default configuration template
application-prod.properties   # Production-specific values
config_loader.py              # Configuration loader utility
```

### Environment Variables

Properties are automatically converted to environment variables:
- `jira.base.url` → `JIRA_BASE_URL`
- `github.token` → `GITHUB_TOKEN`
- `mend.user.key` → `MEND_USER_KEY`

### Configuration Priority

1. **Environment Variables** (highest priority)
2. **Properties Files** (`application-prod.properties` for production)
3. **Default Values** (from `application.properties`)

## 🔧 Setup Instructions

### 1. Configure Properties

#### Step 1: Copy and customize the production properties
```bash
cp application-prod.properties application-prod-local.properties
```

#### Step 2: Update with your actual values
```properties
# JIRA Configuration
jira.username=your_username@trimble.com
jira.api.token=your_actual_jira_token

# GitHub Configuration  
github.token=ghp_your_actual_github_token
github.owner=your_github_username

# MEND Configuration
mend.user.key=your_actual_mend_user_key
mend.org.token=your_actual_org_token
```

#### Step 3: Generate Docker environment file
```bash
python3 config_loader.py --config application-prod-local.properties --generate-env --env-file .env
```

### 2. Validate Configuration

```bash
# Validate all required properties are set
python3 config_loader.py --config application-prod-local.properties --validate

# View loaded configuration (sensitive values hidden)
python3 config_loader.py --config application-prod-local.properties
```

## 🐳 Building the Docker Image

### Prerequisites

- Docker installed and running
- Access to Artifactory
- Valid Artifactory credentials

### Manual Build

```bash
# Build locally
docker build -t custom_mcp_tools:1.0.0 .

# Test the image
docker run --rm -p 8000:8000 --env-file .env custom_mcp_tools:1.0.0
```

### Automated Build and Push

```bash
# Set Artifactory credentials
export ARTIFACTORY_USERNAME=your_username
export ARTIFACTORY_PASSWORD=your_password_or_api_key

# Build and push to Artifactory
chmod +x build-and-push.sh
./build-and-push.sh 1.0.0 production
```

#### Build Script Options

```bash
# Build specific version for production
./build-and-push.sh 1.2.3 production

# Build for staging environment
./build-and-push.sh 1.2.3-staging staging

# Show help
./build-and-push.sh --help
```

## 🏛️ Publishing to Artifactory

### Environment Variables Required

```bash
export ARTIFACTORY_URL="https://artifactory.trimble.tools"
export ARTIFACTORY_REPO="docker-local"
export ARTIFACTORY_PATH="trimble/mcp-tools"
export ARTIFACTORY_USERNAME="your_username"
export ARTIFACTORY_PASSWORD="your_api_key"
```

### Manual Push Process

```bash
# Login to Artifactory
echo $ARTIFACTORY_PASSWORD | docker login $ARTIFACTORY_URL --username $ARTIFACTORY_USERNAME --password-stdin

# Tag the image
docker tag custom_mcp_tools:1.0.0 artifactory.trimble.tools/docker-local/trimble/mcp-tools:1.0.0

# Push to Artifactory
docker push artifactory.trimble.tools/docker-local/trimble/mcp-tools:1.0.0
```

### Verify Push

```bash
# Pull the image from Artifactory
docker pull artifactory.trimble.tools/docker-local/trimble/mcp-tools:1.0.0

# Run from Artifactory
docker run --rm -p 8000:8000 --env-file .env artifactory.trimble.tools/docker-local/trimble/mcp-tools:1.0.0
```

## ☸️ Kubernetes Deployment

### Prerequisites

- Kubernetes cluster access
- kubectl configured
- Artifactory image pull secrets configured

### Step 1: Create Artifactory Secret

```bash
# Create image pull secret
kubectl create secret docker-registry artifactory-secret \
  --docker-server=artifactory.trimble.tools \
  --docker-username=$ARTIFACTORY_USERNAME \
  --docker-password=$ARTIFACTORY_PASSWORD \
  --docker-email=your_email@trimble.com
```

### Step 2: Update Secrets in deployment.yaml

```bash
# Copy deployment template
cp deployment.yaml deployment-prod.yaml

# Update the secrets section with your actual values
# Replace all "your_*" placeholders with real credentials
```

### Step 3: Deploy to Kubernetes

```bash
# Apply the deployment
kubectl apply -f deployment-prod.yaml

# Check deployment status
kubectl get deployments
kubectl get pods -l app=mcp-tools

# Check logs
kubectl logs -l app=mcp-tools --tail=100

# Port forward for testing
kubectl port-forward service/mcp-tools-service 8000:8000
```

### Step 4: Verify Deployment

```bash
# Check health endpoint
curl http://localhost:8000/health

# Check if all tools are loaded
curl http://localhost:8000/tools
```

## 🔍 Troubleshooting

### Common Issues

#### 1. Configuration Loading Issues

```bash
# Check if properties file exists
ls -la application*.properties

# Validate configuration
python3 config_loader.py --config application-prod.properties --validate --verbose

# Test environment variable conversion
python3 config_loader.py --config application-prod.properties --generate-env --env-file test.env
cat test.env
```

#### 2. Docker Build Issues

```bash
# Check Dockerfile syntax
docker build --no-cache -t test-build .

# Debug build process
docker build --progress=plain --no-cache -t test-build .

# Check if all required files exist
ls -la Dockerfile application.properties requirements.txt custom_mcp_tools.py
```

#### 3. Artifactory Push Issues

```bash
# Test Artifactory connectivity
curl -u $ARTIFACTORY_USERNAME:$ARTIFACTORY_PASSWORD $ARTIFACTORY_URL/artifactory/api/system/ping

# Check Docker login
docker login $ARTIFACTORY_URL --username $ARTIFACTORY_USERNAME

# Verify image was built correctly
docker images | grep custom_mcp_tools
```

#### 4. Kubernetes Deployment Issues

```bash
# Check pod status
kubectl describe pods -l app=mcp-tools

# Check events
kubectl get events --sort-by=.metadata.creationTimestamp

# Check secrets
kubectl get secrets
kubectl describe secret mcp-tools-secrets

# Check configmap
kubectl describe configmap mcp-tools-config
```

### Debug Container

```bash
# Run container in debug mode
docker run -it --env-file .env custom_mcp_tools:1.0.0 /bin/bash

# Check environment variables inside container
docker run --rm --env-file .env custom_mcp_tools:1.0.0 env | sort

# Check configuration loading
docker run --rm --env-file .env custom_mcp_tools:1.0.0 python3 config_loader.py --validate
```

## 📝 Configuration Templates

### Example .env file

```bash
# Generated from application properties
APP_NAME=custom_mcp_tools
APP_PORT=8000
JIRA_BASE_URL=https://jira.trimble.tools
JIRA_USERNAME=user@trimble.com
JIRA_API_TOKEN=your_token
GITHUB_TOKEN=ghp_your_token
GITHUB_OWNER=your_username
MEND_USER_KEY=your_user_key
MEND_ORG_TOKEN=your_org_token
```

### Example Kubernetes Secret (Base64 encoded)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: mcp-tools-secrets
type: Opaque
data:
  JIRA_USERNAME: dXNlckB0cmltYmxlLmNvbQ==  # user@trimble.com
  JIRA_API_TOKEN: eW91cl90b2tlbg==           # your_token
```

## 🚀 Production Deployment Checklist

- [ ] Properties files configured with production values
- [ ] Configuration validation passed
- [ ] Docker image built successfully
- [ ] Security scan completed
- [ ] Image pushed to Artifactory
- [ ] Kubernetes secrets created
- [ ] Deployment applied
- [ ] Health checks passing
- [ ] Logs showing successful startup
- [ ] Tools responding correctly

## 📞 Support

For issues with this deployment:

1. Check the troubleshooting section above
2. Review application logs: `kubectl logs -l app=mcp-tools`
3. Validate configuration: `python3 config_loader.py --validate`
4. Contact the DevOps team

## 🔄 Updates and Maintenance

### Updating the Application

```bash
# Build new version
./build-and-push.sh 1.1.0 production

# Update Kubernetes deployment
kubectl set image deployment/mcp-tools mcp-tools=artifactory.trimble.tools/docker-local/trimble/mcp-tools:1.1.0

# Monitor rollout
kubectl rollout status deployment/mcp-tools
```

### Rollback

```bash
# Rollback to previous version
kubectl rollout undo deployment/mcp-tools

# Rollback to specific revision
kubectl rollout undo deployment/mcp-tools --to-revision=2
```

---

**Last Updated**: $(date)
**Version**: 1.0.0 