WITH current_db AS (
    SELECT oid, datname, datlocprovider, datcollversion
    FROM pg_database
    WHERE datname = current_database()
),
index_keys AS (
    SELECT
        i.indexrelid,
        i.indrelid,
        key_pos.n AS zero_based_position,
        i.indkey[key_pos.n] AS attnum,
        i.indcollation[key_pos.n] AS collation_oid,
        i.indclass[key_pos.n] AS opclass_oid
    FROM pg_index i
    CROSS JOIN LATERAL generate_series(0, i.indnkeyatts - 1) AS key_pos(n)
)
SELECT
    current_database() AS database_name,
    idx.oid AS index_oid,
    idx_ns.nspname AS index_schema,
    idx.relname AS index_name,
    tbl_ns.nspname AS table_schema,
    tbl.relname AS table_name,
    am.amname AS access_method,
    pg_total_relation_size(idx.oid) AS index_size_bytes,
    i.indisunique AS is_unique,
    i.indisvalid AS is_valid,
    i.indisready AS is_ready,
    k.zero_based_position + 1 AS key_position,
    COALESCE(att.attname, '<expression>') AS key_name,
    COALESCE(att.atttypid::regtype::text, '<expression>') AS key_type,
    opc.opcname AS opclass_name,
    coll.oid AS collation_oid,
    coll_ns.nspname AS collation_schema,
    coll.collname AS collation_name,
    coll.collprovider AS collation_provider,
    CASE
        WHEN coll.collprovider = 'd' THEN db.datlocprovider
        ELSE coll.collprovider
    END AS effective_provider,
    CASE
        WHEN coll.collprovider = 'd' THEN db.datcollversion
        ELSE coll.collversion
    END AS stored_version,
    CASE
        WHEN coll.collprovider = 'd' THEN pg_database_collation_actual_version(db.oid)
        ELSE pg_collation_actual_version(coll.oid)
    END AS actual_version,
    CASE
        WHEN coll.collprovider = 'd' THEN 'pg_database.datcollversion'
        ELSE 'pg_collation.collversion'
    END AS version_source,
    pg_get_indexdef(idx.oid) AS index_definition,
    format('REINDEX INDEX CONCURRENTLY %%I.%%I;', idx_ns.nspname, idx.relname) AS reindex_sql,
    CASE
        WHEN coll.collprovider = 'd' THEN
            format('ALTER DATABASE %%I REFRESH COLLATION VERSION;', db.datname)
        ELSE
            format('ALTER COLLATION %%I.%%I REFRESH VERSION;', coll_ns.nspname, coll.collname)
    END AS refresh_sql
FROM index_keys k
JOIN pg_index i ON i.indexrelid = k.indexrelid
JOIN pg_class idx ON idx.oid = i.indexrelid
JOIN pg_namespace idx_ns ON idx_ns.oid = idx.relnamespace
JOIN pg_class tbl ON tbl.oid = i.indrelid
JOIN pg_namespace tbl_ns ON tbl_ns.oid = tbl.relnamespace
JOIN pg_am am ON am.oid = idx.relam
LEFT JOIN pg_attribute att ON att.attrelid = k.indrelid AND att.attnum = k.attnum
LEFT JOIN pg_opclass opc ON opc.oid = k.opclass_oid
JOIN pg_collation coll ON coll.oid = k.collation_oid
JOIN pg_namespace coll_ns ON coll_ns.oid = coll.collnamespace
CROSS JOIN current_db db
WHERE k.collation_oid <> 0
  AND am.amname = 'btree'
  AND idx.relkind = 'i'
  AND idx.relpersistence <> 't'
  AND i.indisvalid
  AND i.indisready
  AND (
      %(include_system)s
      OR (
          tbl_ns.nspname NOT IN ('pg_catalog', 'information_schema')
          AND idx_ns.nspname NOT IN ('pg_catalog', 'information_schema')
          AND tbl_ns.nspname NOT LIKE 'pg_toast%%'
          AND idx_ns.nspname NOT LIKE 'pg_toast%%'
      )
  )
  AND (
      %(schema)s::text IS NULL
      OR tbl_ns.nspname = %(schema)s::text
      OR idx_ns.nspname = %(schema)s::text
  )
  AND (
      %(provider)s::text = 'all'
      OR (
          CASE
              WHEN coll.collprovider = 'd' THEN db.datlocprovider
              ELSE coll.collprovider
          END
      ) = %(provider)s::text
  )
ORDER BY pg_total_relation_size(idx.oid) DESC,
         idx_ns.nspname,
         idx.relname,
         k.zero_based_position;
