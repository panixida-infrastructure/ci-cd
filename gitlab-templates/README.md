# GitLab CI/CD templates

Шаблоны синхронизированы с [infra/cicd](https://gitlab.spaceapp.ru/infra/cicd)
из ветки `master`, коммит `cd744f9e47c02f5599650013b17115e035519356`
(5 октября 2026 года). Имена файлов и существующих базовых jobs сохранены.

Включайте нужные файлы через `include:remote` и наследуйте jobs через `extends`:

```yaml
include:
  - remote: https://raw.githubusercontent.com/PANiXiDA-Infrastructure/ci-cd/main/gitlab-templates/.go-tests-template.yml

tests:
  stage: test
  extends: .go_tests
  variables:
    COVERAGE_THRESHOLD: "80"
```

Для воспроизводимой конфигурации замените `main` в URL на SHA коммита.
Секреты передаются только через CI/CD variables и file variables GitLab.

## Изменения поведения

- .NET: добавлены варианты format/Sonar, Microsoft.Testing.Platform, параллельные
  тесты, динамический дочерний пайплайн и сбор общего покрытия. Параллельные
  и динамические тесты подключаются отдельно; существующий `.dotnet_tests`
  остаётся доступен. `.build-sonar` по умолчанию исключает тест-проекты из сборки
  анализа; отключение — `SONAR_EXCLUDE_TESTS: "false"`.
- Go: добавлены `.go_tests` с JUnit/Cobertura и `.go_swagger_validate`.
  `.lint_go` использует Go 1.25 и golangci-lint v2.12.2; `STRICT_LINT` по умолчанию
  равен `"true"`, поэтому новые замечания линтера завершают job с ошибкой.
  Конфигурацию `.golangci.yml` версии v1 нужно перевести на формат v2.
  Для Swagger переопределите `SWAGGER_MAIN_FILE`, если точка входа отличается
  от `cmd/tutor/main.go`.
- Docker: `.docker_build` использует Docker 27 CLI, Buildx и BuildKit cache mount
  для NuGet. Job сбрасывает `DOCKER_HOST` и требует доступного локального Docker
  daemon; учитывайте это при использовании Docker-in-Docker.
  Образы публикуются в `$CI_REGISTRY_IMAGE/$SERVICE_NAME/$ENV_SUFFIX` с тегами
  `$CI_PIPELINE_ID` и `latest`. Старые `REGISTRY_PROJECT_PATH` и
  `LATEST_IMAGE_REGISTRY_PATH_WITH_ENV` больше не используются; обновите внешние
  ссылки на прежний путь и тег `latest-$ENV_SUFFIX`.
- Миграции: `.update_database` собирает и запускает Dockerfile мигратора;
  `.update_database_shell` доступен отдельно. `MIGRATOR_DB_HOST` позволяет
  переопределить хост БД только для запуска миграции.
- SSH: деплой сериализуется по сервису и окружению; доступны `EXTRA_VOLUMES`
  и `EXTRA_RUN_ARGS`. `.ssh_deploy_old` сохраняет предыдущий вариант.
- Telegram: `.notify_telegram` использует HTML с экранированием, учитывает
  дочерние пайплайны и поддерживает `TELEGRAM_EGRESS_PROXY`. Без прокси используется
  IP Telegram из исходного шаблона. `.notify_telegram_old` сохраняет Markdown-вариант.
- NuGet: добавлен `.nuget_publish_template` с ручной публикацией в GitLab registry.
  Настройте `NUGET_PROJECT`; `NUGET_BUILD_PROJECT` и `NUGET_PACK_PROJECT`
  позволяют разделить проекты сборки и упаковки.

## Отличия от источника

`.dotnet_tests_generate_dynamic` включает нашу копию `.dotnet-tests-template.yml`
через `include:remote` вместо GitLab-проекта `infra/cicd`. URL задаётся переменной
`DOTNET_TESTS_TEMPLATE_URL`, по умолчанию указывает на `main` этого репозитория.
При фиксации родительского include на SHA задайте той же версии и эту переменную.
Runner генератора и GitLab должны иметь доступ к `raw.githubusercontent.com`.

После проверки замечаний PR внесены локальные исправления:

- Проверка checklist получает полное описание MR через API и требует
  `GITLAB_API_TOKEN` с правом чтения MR; ошибка API завершает job с ошибкой.
- Go lint получает полную Git-историю (`GIT_DEPTH: "0"`) для сравнения с базой MR.
- `SKIP_BUILD_ON_PACK: "true"` включает `--no-build`; `false` или отсутствие
  переменной оставляют сборку во время pack.
- Динамическая матрица содержит `TEST_PROJECT` с путём к `.csproj`; проекты
  с одинаковым именем получают отдельные jobs и файлы отчётов. Ручные матрицы
  с `TEST_SUITE` по имени проекта остаются совместимы.
- Установка SonarScanner/format передаёт `--configfile` команде установки.
- Поясняющие комментарии удалены из YAML-шаблонов.

.NET jobs с persistent cache используют
каталоги `/dotnet-tools` и `/sonar`; права на них и установленные SDK/Java необходимо
проверить на выбранном runner. Это синхронизация шаблонов, выполнение сборок,
миграций и деплоя проверяется в подключающем проекте.

## Локальные проверки

Нужны Python 3, Git и Bash. На Windows укажите путь к Git Bash в
`GITLAB_TEST_BASH`. Проверки выполняют shell-код шаблонов с заглушками внешних
команд и воспроизводят сценарии из review без публикации пакетов и деплоя.

```shell
python -m pip install -r tests/requirements.txt
python -m unittest discover -s tests -p test_gitlab_templates.py -v
```
