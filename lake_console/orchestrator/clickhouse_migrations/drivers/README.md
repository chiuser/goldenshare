# ClickHouse JDBC Driver

Flyway CLI uses this directory as `flyway.jarDirs` for local ClickHouse JDBC driver jars.

The jar files are intentionally ignored by Git. They are local development/runtime dependencies, not repository source.

Current local driver used for CH-1:

```text
clickhouse-jdbc-0.9.8-all.jar
```

Install example:

```bash
curl -L \
  https://repo.maven.apache.org/maven2/com/clickhouse/clickhouse-jdbc/0.9.8/clickhouse-jdbc-0.9.8-all.jar \
  -o clickhouse_migrations/drivers/clickhouse-jdbc-0.9.8-all.jar
```

