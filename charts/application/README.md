# application Helm chart

Reusable Helm chart for PANiXiDA application workloads.

The chart owns common Kubernetes resources:

- `Deployment`
- `Service`
- optional Gateway API `HTTPRoute`
- optional External Secrets Operator `SecretStore` and `ExternalSecret`
- optional migration `Job`
- application and External Secrets `ServiceAccount`

Service repositories should keep only service-specific values, for example:

```yaml
nameOverride: my-service

image:
  repository: ghcr.io/example/my-service/api
  tag: "123"

env:
  secretName: my-service-api-env
  values:
    OTEL_SERVICE_NAME: my-service-api-development
    APP_ENVIRONMENT: development

gateway:
  enabled: true
  host: dev.api.my-service.example.com
  httpsSectionName: api-dev-my-service-https

externalSecrets:
  enabled: true
  openbao:
    role: my-service-development
  app:
    enabled: true
    targetName: my-service-api-env
    remoteKey: applications/my-service/development
    data:
      - secretKey: ConnectionStrings__PostgreSqlConnectionString
        remoteProperty: ConnectionStrings__PostgreSqlConnectionString
  registry:
    enabled: true
    targetName: my-service-registry
    remoteKey: applications/my-service/registry

migrations:
  enabled: true
  image:
    repository: ghcr.io/example/my-service/ef-migrator
    tag: "123"
```

Validate locally:

```bash
helm lint charts/application \
  --set image.repository=ghcr.io/example/api \
  --set image.tag=1

helm template example charts/application \
  --set image.repository=ghcr.io/example/api \
  --set image.tag=1
```
