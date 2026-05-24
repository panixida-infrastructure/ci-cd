# CI-CD
Тут хранятся общие шаблоны для пайплайнов, чтобы не дублировать код в каждом репозитории.

## SSH deploy folders

GitHub SSH deploy actions place files under `/opt` by default.

For example:

```yaml
with:
  service-folder: core-platform/edge
```

deploys to:

```text
/opt/core-platform/edge
```

Use `deploy-root` only when a repository intentionally needs another base directory.
