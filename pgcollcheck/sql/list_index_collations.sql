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
),
collation_dependencies AS (
    SELECT
        k.indexrelid,
        k.indrelid,
        k.zero_based_position,
        k.attnum,
        k.collation_oid,
        k.opclass_oid,
        'index_key' AS dependency_source
    FROM index_keys k
    WHERE k.collation_oid <> 0

    UNION ALL

    SELECT
        i.indexrelid,
        i.indrelid,
        NULL::integer AS zero_based_position,
        NULL::smallint AS attnum,
        d.refobjid AS collation_oid,
        NULL::oid AS opclass_oid,
        'pg_depend' AS dependency_source
    FROM pg_depend d
    JOIN pg_index i ON i.indexrelid = d.objid
    WHERE d.classid = 'pg_class'::regclass
      AND d.refclassid = 'pg_collation'::regclass
      AND d.deptype IN ('n', 'a')
      AND NOT EXISTS (
          SELECT 1
          FROM index_keys k
          WHERE k.indexrelid = i.indexrelid
            AND k.collation_oid = d.refobjid
      )
),
eligible_indexes AS (
    SELECT DISTINCT
        i.indexrelid
    FROM collation_dependencies k
    JOIN pg_index i ON i.indexrelid = k.indexrelid
    JOIN pg_class idx ON idx.oid = i.indexrelid
    JOIN pg_namespace idx_ns ON idx_ns.oid = idx.relnamespace
    JOIN pg_class tbl ON tbl.oid = i.indrelid
    JOIN pg_namespace tbl_ns ON tbl_ns.oid = tbl.relnamespace
    JOIN pg_am am ON am.oid = idx.relam
    WHERE (%(access_method)s::text = 'all' OR am.amname = %(access_method)s::text)
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
),
index_metadata AS (
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
        pg_get_indexdef(idx.oid) AS index_definition,
        format('REINDEX INDEX CONCURRENTLY %%I.%%I;', idx_ns.nspname, idx.relname) AS reindex_sql
    FROM eligible_indexes e
    JOIN pg_index i ON i.indexrelid = e.indexrelid
    JOIN pg_class idx ON idx.oid = i.indexrelid
    JOIN pg_namespace idx_ns ON idx_ns.oid = idx.relnamespace
    JOIN pg_class tbl ON tbl.oid = i.indrelid
    JOIN pg_namespace tbl_ns ON tbl_ns.oid = tbl.relnamespace
    JOIN pg_am am ON am.oid = idx.relam
),
collation_versions AS (
    SELECT
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
        CASE
            WHEN coll.collprovider = 'd' THEN
                format('ALTER DATABASE %%I REFRESH COLLATION VERSION;', db.datname)
            ELSE
                format('ALTER COLLATION %%I.%%I REFRESH VERSION;', coll_ns.nspname, coll.collname)
        END AS refresh_sql
    FROM (
        SELECT DISTINCT collation_oid
        FROM collation_dependencies
    ) used_collations
    JOIN pg_collation coll ON coll.oid = used_collations.collation_oid
    JOIN pg_namespace coll_ns ON coll_ns.oid = coll.collnamespace
    CROSS JOIN current_db db
)
SELECT
    im.database_name,
    im.index_oid,
    im.index_schema,
    im.index_name,
    im.table_schema,
    im.table_name,
    im.access_method,
    im.index_size_bytes,
    im.is_unique,
    im.is_valid,
    im.is_ready,
    k.zero_based_position + 1 AS key_position,
    CASE
        WHEN k.dependency_source = 'pg_depend' THEN '<index dependency>'
        ELSE COALESCE(att.attname, '<expression>')
    END AS key_name,
    CASE
        WHEN k.dependency_source = 'pg_depend' THEN '<dependency>'
        ELSE COALESCE(att.atttypid::regtype::text, '<expression>')
    END AS key_type,
    opc.opcname AS opclass_name,
    k.dependency_source,
    cv.collation_oid,
    cv.collation_schema,
    cv.collation_name,
    cv.collation_provider,
    cv.effective_provider,
    cv.stored_version,
    cv.actual_version,
    cv.version_source,
    im.index_definition,
    im.reindex_sql,
    cv.refresh_sql
FROM collation_dependencies k
JOIN eligible_indexes e ON e.indexrelid = k.indexrelid
JOIN index_metadata im ON im.index_oid = k.indexrelid
LEFT JOIN pg_attribute att ON att.attrelid = k.indrelid AND att.attnum = k.attnum
LEFT JOIN pg_opclass opc ON opc.oid = k.opclass_oid
JOIN collation_versions cv ON cv.collation_oid = k.collation_oid
WHERE (
      %(provider)s::text = 'all'
      OR cv.effective_provider = %(provider)s::text
  )
  AND (
      e.indexrelid IS NOT NULL
  )
ORDER BY im.index_size_bytes DESC,
         im.index_schema,
         im.index_name,
         k.zero_based_position NULLS LAST,
         k.collation_oid;
