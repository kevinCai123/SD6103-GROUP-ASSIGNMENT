-- Optional full-database loader for psql, as an alternative to the experiment runner.
-- Run from the PACKAGE ROOT so the relative CSV paths resolve correctly.
-- Start with the empty database created by SupplementaryTask1/01_Create_Database.sql.
-- Do not use this loader before run_experiment.py: that script creates its own DB
-- and loads five incremental sizes, which is required for the timing experiment.
\set ON_ERROR_STOP on
BEGIN;
\copy housing.town FROM 'data/prepared/town.csv' WITH (FORMAT CSV, HEADER true)
\copy housing.hdb_block FROM 'data/prepared/hdb_block.csv' WITH (FORMAT CSV, HEADER true)
\copy housing.hdb_flat FROM 'data/prepared/hdb_flat.csv' WITH (FORMAT CSV, HEADER true)
\copy housing.source_file FROM 'data/prepared/source_file.csv' WITH (FORMAT CSV, HEADER true)
\copy housing.resale_transaction FROM 'data/prepared/resale_transaction.csv' WITH (FORMAT CSV, HEADER true)
\copy housing.hawker_centre FROM 'data/prepared/hawker_centre.csv' WITH (FORMAT CSV, HEADER true)
\copy housing.block_hawker_distance FROM 'data/prepared/block_hawker_distance.csv' WITH (FORMAT CSV, HEADER true)
SELECT setval(pg_get_serial_sequence('housing.town','town_id'), max(town_id), true) FROM housing.town;
SELECT setval(pg_get_serial_sequence('housing.hdb_block','block_id'), max(block_id), true) FROM housing.hdb_block;
SELECT setval(pg_get_serial_sequence('housing.hdb_flat','flat_id'), max(flat_id), true) FROM housing.hdb_flat;
SELECT setval(pg_get_serial_sequence('housing.source_file','source_file_id'), max(source_file_id), true) FROM housing.source_file;
SELECT setval(pg_get_serial_sequence('housing.resale_transaction','transaction_id'), max(transaction_id), true) FROM housing.resale_transaction;
SELECT setval(pg_get_serial_sequence('housing.hawker_centre','hawker_id'), max(hawker_id), true) FROM housing.hawker_centre;
COMMIT;
VACUUM (ANALYZE);
