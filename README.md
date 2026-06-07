# PgCollationReindexChecker

Эта консольная утилита для PostgreSQL находит индексы, которые зависят от правил сортировки строк (`collation`), сравнивает сохранённую версию правила сортировки с текущей версией в PostgreSQL и отвечает на главный практический вопрос:

> мог ли этот индекс стать потенциально неправильным после обновления libc или ICU, и нужно ли делать `REINDEX`?

Запуск через команду `pgcollcheck`

Утилита ничего не перестраивает автоматически. Она читает системные каталоги,
показывает решение и может сгенерировать SQL-план восстановления с командами
`REINDEX INDEX CONCURRENTLY ...`

## Зачем это нужно
Для типов вроде `text`, `varchar`, `char`, `citext` порядок строк зависит от правила сравнения строк (`collation`), а не просто от сортировки по байтам

`collation` может приходить из:
- libc (системной локали Linux)
- ICU (библиотеки libicu)
- default collation базы данных

Если после обновления ОС, libc или ICU правила сравнения строк изменились, то PostgreSQL уже будет искать строки по новым правилам, а старый индекс может оставаться построенным по старому порядку. Тогда индекс нужно перестроить через команду `REINDEX`. А `pgcollcheck` помогает не перестраивать всё вслепую. Он показывает, какие индексы действительно зависят от collations с изменившейся версией

## Требования

- Python 3.10 или новее
- PostgreSQL 15 или новее
- Python-зависимость `psycopg[binary]`
- Для команд `verify` и `compare`: расширение PostgreSQL `amcheck`

## Установка

В каталоге проекта:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
```

Потом следует проверить, что команда установилась:

```bash
pgcollcheck --help
```

Если виртуальное окружение не активировано, можно запускать так:

```bash
.venv/bin/pgcollcheck --help
```

## Подключение к PostgreSQL
Самый простой вариант подключения, это просто запускать утилиту на том же сервере где работает PostgreSQL. Тогда подключение обычно идёт через локальный Unix socket:

```bash
pgcollcheck scan --database stars_lab
```

Можно передать параметры подключения явно:

```bash
pgcollcheck scan \
  --host localhost \
  --port 5432 \
  --user vlad \
  --database stars_lab
```

Можно использовать DSN:

```bash
pgcollcheck scan --dsn "postgresql://vlad@localhost:5432/stars_lab"
```

Для режима `--all-databases` утилита сначала подключается к служебной базе, чтобы получить список баз данных в кластере. По умолчанию используется база из переменной `PGDATABASE`, а если переменная не задана будет использоваться база `postgres`

```bash
pgcollcheck scan --all-databases --maintenance-db postgres
```

## Быстрый старт

Проверить одну базу:

```bash
pgcollcheck scan --database stars_lab
```

Проверить одну схему:

```bash
pgcollcheck scan --database stars_lab --schema collation_lab
```

Показать только индексы, где есть проблема или неизвестное состояние:

```bash
pgcollcheck scan --database stars_lab --only-mismatches
```

Пример вывода, когда найден индекс, которому нужен `REINDEX`:

```text
database   index                                                  table                                size     collations                                                              decision
---------  -----------------------------------------------------  -----------------------------------  -------  ----------------------------------------------------------------------  ----------------------------------------
stars_lab  "pgcollcheck_demo"."sample_strings_name_mismatch_idx"  "pgcollcheck_demo"."sample_strings"  16.0 KB  name:"pgcollcheck_demo"."en_us_mismatch"/libc/0->2.39/VERSION_MISMATCH  REINDEX_RECOMMENDED_BY_COLLATION_VERSION

REINDEX commands:
  REINDEX INDEX CONCURRENTLY pgcollcheck_demo.sample_strings_name_mismatch_idx;
```

Это означает, что:
- индекс найден
- он зависит от collation `pgcollcheck_demo.en_us_mismatch`
- сохранённая версия collation — `0`
- текущая версия в PostgreSQL — `2.39`
- версии отличаются, поэтому утилита рекомендует `REINDEX`

Пример вывода, когда всё хорошо:

```text
database   index                                            table                                size     collations                                           decision
---------  -----------------------------------------------  -----------------------------------  -------  ---------------------------------------------------  --------
stars_lab  "collation_lab"."sample_strings_name_en_us_idx"  "collation_lab"."sample_strings"     16.0 KB  name:"pg_catalog"."en_US.utf8"/libc/2.39->2.39/OK      OK

No collation version mismatches were found.
```

## Реальные пременения
### Нужно проверить одну базу

Запустит `scan`, это основная команда

```bash
pgcollcheck scan --database stars_lab
```

`scan` читает системные каталоги PostgreSQL и сравнивает сохранённые версии collations с текущими (так как команда не читает строки таблиц и не проходит по страницам индексов она довольно дешёвая)

###  Нужно проверить только одну схему

```bash
pgcollcheck scan --database stars_lab --schema collation_lab
```

###  Нужно проверить все базы кластера

```bash
pgcollcheck scan --all-databases --progress
```

`--progress` печатает в `stderr`, какая база сейчас проверяется.

Если при `--all-databases` одна база недоступна, утилита не теряет результаты по остальным базам. Она покажет partial failure и вернёт exit code `4`

###  Нужно увидеть только проблемные индексы

```bash
pgcollcheck scan --database stars_lab --only-mismatches
```

Этот режим скрывает обычные `OK`-индексы и оставляет:

- индексы с рекомендацией `REINDEX`
- индексы со статусом `UNKNOWN`

Это самый удобный режим для большой базы

###  Нужно проверить только libc collations

```bash
pgcollcheck scan --database stars_lab --provider libc
```


### Нужно проверить только ICU collations

```bash
pgcollcheck scan --database stars_lab --provider icu
```

### Нужно проверить builtin collations

```bash
pgcollcheck scan --database stars_lab --provider builtin
```

Этот provider актуален для новых версий PostgreSQL, где есть встроенный поставщик collations

### Нужно получить JSON для скрипта или CI

```bash
pgcollcheck scan \
  --database stars_lab \
  --format json \
  --output scan-report.json
```

JSON всегда имеет общий envelope:

```json
{
  "tool": {
    "name": "pgcollcheck",
    "version": "0.1.0"
  },
  "command": "scan",
  "scope": {},
  "summary": {
    "result_count": 2,
    "failure_count": 0,
    "partial_failure": false,
    "reindex_count": 2,
    "unknown_count": 0
  },
  "results": [],
  "failures": []
}
```

При `--only-mismatches` структура JSON не меняется. Если проблем нет, `results` будет пустым массивом

### Нужно, чтобы команда возвращала ошибочный код, если нужен REINDEX

```bash
pgcollcheck scan --database stars_lab --strict-exit-code
```

Без `--strict-exit-code` найденная рекомендация `REINDEX` не считается ошибкой самой утилиты, поэтому exit code будет `0`

С `--strict-exit-code`:
- `2` означает, что найден verdict с `REINDEX`
- `3` означает, что найден `UNKNOWN` или skipped verification state
- `4` означает partial failure при проверке нескольких баз

### Нужно не печатать огромный отчёт

```bash
pgcollcheck scan --all-databases --largest 20
```

`--largest N` ограничивает только количество безопасных `OK`-индексов в выводе на одну базу. Проблемные `REINDEX` и `UNKNOWN` результаты не скрываются.

### Нужно включить системные схемы

```bash
pgcollcheck scan --database stars_lab --include-system
```

По умолчанию утилита пропускает `pg_catalog`, `information_schema` и `pg_toast`.

### Нужно посмотреть каталоговые зависимости не только B-tree индексов

```bash
pgcollcheck scan --database stars_lab --access-method all
```

По умолчанию `scan` проверяет B-tree индексы, потому что именно порядок B-tree является главным риском после изменения collations

`--access-method all` расширяет только каталоговый отчёт. Команды `verify` и `compare` всё равно проверяют только B-tree индексы, потому что используют B-tree-функции расширения `amcheck`.`


### Нужно физически проверить B-tree индексы через PostgreSQL

```bash
pgcollcheck verify --database stars_lab --mode normal
```

`verify` запускает PostgreSQL `amcheck` для найденных B-tree индексов с collatable ключами.

Режимы:

- `quick`: `bt_index_check(index, false)`;
- `normal`: `bt_index_check(index, true)`;
- `deep`: `bt_index_parent_check(index, true, true)`.

Если расширение `amcheck` не установлено:

```bash
pgcollcheck verify --database stars_lab --install-extension
```

`verify` дороже, чем `scan`: он читает страницы индексов и может ждать PostgreSQL locks

Важно: успешный `amcheck` не отменяет mismatch версии collation. Он только говорит, что PostgreSQL не нашёл нарушения B-tree invariants на текущих данных

### Нужно совместить catalog scan и amcheck

```bash
pgcollcheck compare --database stars_lab --verify-mode normal
```

`compare` сначала запускает каталоговый `scan`, потом `amcheck`, а затем выдаёт финальное решение

Пример:

```text
database   index                                                  catalog                                   amcheck     final                                     reason
---------  -----------------------------------------------------  ----------------------------------------  ----------  ----------------------------------------  ----------------------------------------------------------------------
stars_lab  "pgcollcheck_demo"."sample_strings_name_mismatch_idx"  REINDEX_RECOMMENDED_BY_COLLATION_VERSION  AMCHECK_OK  REINDEX_RECOMMENDED_BY_COLLATION_VERSION  stored collation version differs from current operating-system version

REINDEX commands:
  REINDEX INDEX CONCURRENTLY pgcollcheck_demo.sample_strings_name_mismatch_idx;
```

Это нормальный результат. Если версия collation изменилась, финальное решение остаётся `REINDEX_RECOMMENDED_BY_COLLATION_VERSION`, даже когда `amcheck` прошёл успешно

### Нужно получить SQL-план для восстановления

```bash
pgcollcheck plan-reindex --database stars_lab --schema pgcollcheck_demo
```

Команда печатает SQL, но не выполняет его

Пример:

```sql
-- Generated by pgcollcheck.
-- Run REINDEX first. Run REFRESH VERSION only after successful rebuild.

REINDEX INDEX CONCURRENTLY pgcollcheck_demo.sample_strings_name_icu_mismatch_idx;
REINDEX INDEX CONCURRENTLY pgcollcheck_demo.sample_strings_name_mismatch_idx;

-- After successful REINDEX:
ALTER COLLATION pgcollcheck_demo.und_icu_mismatch REFRESH VERSION;
ALTER COLLATION pgcollcheck_demo.en_us_mismatch REFRESH VERSION;
```

Порядок важен:

1. Сначала перестроить затронутые индексы.
2. Только после успешного `REINDEX` обновить сохранённую версию collation через
   `ALTER COLLATION ... REFRESH VERSION` или
   `ALTER DATABASE ... REFRESH COLLATION VERSION`

Для нескольких баз:

```bash
pgcollcheck plan-reindex --all-databases --schema pgcollcheck_demo
```

В таком случае план содержит переключения базы для `psql`:

```sql
-- Database: stars_lab
\connect stars_lab

REINDEX INDEX CONCURRENTLY pgcollcheck_demo.sample_strings_name_mismatch_idx;
```

Сохранить SQL-план в файл:

```bash
pgcollcheck plan-reindex \
  --database stars_lab \
  --schema pgcollcheck_demo \
  --sql-output reindex-plan.sql
```


## Решения и статусы

### Итоговые решения `scan`

- `OK`: по catalog scan индекс перестраивать не нужно
- `REINDEX_RECOMMENDED_BY_COLLATION_VERSION`: хотя бы одна collation dependency
  имеет mismatch версии
- `UNKNOWN`: PostgreSQL не дал достаточно информации о версии

### Статусы отдельных collation dependencies

- `OK`: сохранённая и текущая версии совпадают
- `OK_UNVERSIONED`: PostgreSQL не хранит версию для этого collation, например
  для `C`
- `VERSION_MISMATCH`: сохранённая версия отличается от текущей
- `UNKNOWN_NO_STORED_VERSION`: сохранённая версия отсутствует
- `UNKNOWN_NO_ACTUAL_VERSION`: текущую версию не удалось получить

### Статусы `amcheck`

- `AMCHECK_OK`;
- `AMCHECK_FAILED`;
- `AMCHECK_TIMEOUT`;
- `SKIPPED_EXTENSION_MISSING`;
- `SKIPPED_PERMISSION_DENIED`;
- `UNKNOWN_ERROR`.

### Итоговые решения `compare`

- `OK`;
- `REINDEX_RECOMMENDED_BY_COLLATION_VERSION`;
- `REINDEX_REQUIRED_BY_AMCHECK`;
- `REINDEX_REQUIRED_BY_BOTH`;
- `UNKNOWN`.

## Exit codes

- `0`: команда выполнена. В non-strict режиме отчёт всё ещё может содержать
  рекомендации `REINDEX`
- `1`: ошибка утилиты, подключения, SQL или неподдержанная версия PostgreSQL.
- `2`: при `--strict-exit-code` найден verdict с `REINDEX`
- `3`: при `--strict-exit-code` найден `UNKNOWN` или skipped verification
  state
- `4`: partial failure при проверке нескольких баз

Partial failure важнее strict verdict, потому что запрошенный scope проверен не
полностью

## Права

Для `scan` и `plan-reindex` обычно достаточно:

- права подключиться к базе
- видимости проверяемых схем и объектов
- обычного доступа к системным каталогам PostgreSQL

Для `verify` и `compare` нужны права на выполнение функций расширения
`amcheck`. Если прав нет, утилита вернёт `SKIPPED_PERMISSION_DENIED`

Для `--install-extension` нужны права на создание extension в базе

SQL, сгенерированный `plan-reindex`, выполняется вручную пользователем, у
которого есть права на `REINDEX` целевых индексов

## Как это работает внутри

Основной SQL-запрос лежит в `pgcollcheck/sql/list_index_collations.sql`.

Утилита читает:

- `pg_index`: ключи индексов и `indcollation`;
- `pg_depend`: зависимости индекса от collations в выражениях и partial
  indexes;
- `pg_class`, `pg_namespace`, `pg_am`: метаданные индексов;
- `pg_collation`: сохранённые версии обычных collations;
- `pg_database`: сохранённую версию default collation базы.

Для обычных collations сравниваются:

```sql
pg_collation.collversion
pg_collation_actual_version(pg_collation.oid)
```

Для default collation базы сравниваются:

```sql
pg_database.datcollversion
pg_database_collation_actual_version(pg_database.oid)
```

Зависимости от collations находятся двумя путями:

- через `pg_index.indcollation`, когда collation относится к ключу индекса
- через `pg_depend`, когда collation находится в выражении или predicate
  partial index

Поэтому `scan` дешёвый: он опирается на каталоги PostgreSQL и встроенные
функции версий, а не читает содержимое индексов

## Текущие границы

- Утилита не выполняет `REINDEX` автоматически
- Утилита не выполняет `ALTER COLLATION ... REFRESH VERSION` автоматически
- `verify` и `compare` используют B-tree функции `amcheck`
- Параллельного режима `--jobs` пока нет
- Фильтров `--exclude-database` и `--exclude-schema` пока нет

