# dotnet-service Helm chart

Reusable Helm chart for PANiXiDA .NET HTTP services.

The chart owns common Kubernetes resources:

- `Deployment`
- `Service`
- optional Gateway API `HTTPRoute`
- optional External Secrets Operator `SecretStore` and `ExternalSecret`
- optional EF migration `Job`
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
    ASPNETCORE_ENVIRONMENT: Development
    DOTNET_ENVIRONMENT: Development
    ASPNETCORE_HTTP_PORTS: "8080"
    OTEL_SERVICE_NAME: my-service-api-development

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
helm lint charts/dotnet-service \
  --set image.repository=ghcr.io/example/api \
  --set image.tag=1

helm template example charts/dotnet-service \
  --set image.repository=ghcr.io/example/api \
  --set image.tag=1
```
