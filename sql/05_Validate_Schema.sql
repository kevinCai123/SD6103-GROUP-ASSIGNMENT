-- Optional checks using synthetic data, never assignment observations.
-- Run against an EMPTY housing schema after 01_Create_Database.sql.
-- All fixture inserts are rolled back. Explicit IDs leave identity sequences alone.
BEGIN;

DO $check$
BEGIN
    IF EXISTS (SELECT 1 FROM housing.town)
       OR EXISTS (SELECT 1 FROM housing.hawker_centre)
       OR EXISTS (SELECT 1 FROM housing.source_file) THEN
        RAISE EXCEPTION 'Run these checks on an empty schema';
    END IF;
END;
$check$;

CREATE FUNCTION pg_temp.assert_true(ok boolean, label text)
RETURNS void LANGUAGE plpgsql AS $check$
BEGIN
    IF ok IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'FAILED: %', label;
    END IF;
END;
$check$;

CREATE FUNCTION pg_temp.expect_failure(statement text, expected_state text)
RETURNS void LANGUAGE plpgsql AS $check$
DECLARE caught_state text;
BEGIN
    BEGIN
        EXECUTE statement;
    EXCEPTION WHEN OTHERS THEN
        GET STACKED DIAGNOSTICS caught_state = RETURNED_SQLSTATE;
        IF caught_state = ANY(string_to_array(expected_state, ',')) THEN RETURN; END IF;
        RAISE EXCEPTION 'Expected SQLSTATE %, got %: %',
            expected_state, caught_state, statement;
    END;
    RAISE EXCEPTION 'Expected rejection but accepted: %', statement;
END;
$check$;

INSERT INTO housing.town VALUES (1, 'TEST TOWN');
INSERT INTO housing.hdb_block VALUES
    (1, 1, '1A', 'TEST ROAD', 1.3, 103.8),
    (2, 1, '2', 'TEST ROAD', NULL, NULL);
INSERT INTO housing.hdb_flat VALUES
    (1, 1, '4 ROOM', 'MODEL A', 90, 1, 3, 1990),
    (2, 2, '3 ROOM', 'MODEL A', 70, 4, 6, 1990);
INSERT INTO housing.source_file VALUES
    (1, 'synthetic.csv', repeat('a', 64), 'REGISTRATION');
INSERT INTO housing.resale_transaction VALUES
    (1, 1, 1, 1, DATE '2016-01-01', 400000, NULL, NULL),
    (2, 1, 1, 2, DATE '2016-01-01', 400000, NULL, NULL),
    (3, 2, 1, 3, DATE '2017-01-01', 300000, 736, 'MONTH'),
    (4, 1, 1, 4, DATE '2015-01-01', 390000, 888, 'YEAR');
INSERT INTO housing.hawker_centre VALUES
    (1, 'TEST FOOD CENTRE', '1 TEST STREET', 'HC', 20, 0, 1.3, 103.8),
    (2, 'TEST MARKET A', '2 TEST STREET', 'MHC', 20, 10, 1.3, 103.8),
    (3, 'TEST MARKET B', '3 TEST STREET', 'MHC', 20, 15, 1.3, 103.8),
    (4, 'TEST MARKET ONLY', '4 TEST STREET', 'MK', 0, 20, 1.3, 103.8);
-- Deliberately synthetic distances for testing selection, not geography.
INSERT INTO housing.block_hawker_distance VALUES
    (1, 1, 100), (1, 2, 800), (1, 3, 800), (1, 4, 50);

SELECT pg_temp.assert_true(housing.proximity_class(0) = 'NEAR', 'zero distance');
SELECT pg_temp.assert_true(housing.proximity_class(499.9999) = 'NEAR', 'below 500');
SELECT pg_temp.assert_true(housing.proximity_class(500) = 'MEDIUM', 'at 500');
SELECT pg_temp.assert_true(housing.proximity_class(999.9999) = 'MEDIUM', 'below 1000');
SELECT pg_temp.assert_true(housing.proximity_class(1000) = 'FAR', 'at 1000');
SELECT pg_temp.assert_true(housing.proximity_class(NULL) IS NULL, 'unknown is not far');
SELECT pg_temp.assert_true(housing.proximity_class(-1) IS NULL, 'negative invalid');
SELECT pg_temp.assert_true(housing.proximity_class('NaN'::float8) IS NULL, 'NaN invalid');

SELECT pg_temp.assert_true(
    (SELECT hawker_id = 1 AND proximity_class = 'NEAR'
     FROM housing.v_nearest_hawker WHERE block_id = 1),
    'Q4 excludes market-only centres');
SELECT pg_temp.assert_true(
    (SELECT hawker_id = 2 AND proximity_class = 'MEDIUM'
     FROM housing.v_nearest_market_hawker WHERE block_id = 1),
    'Q5 filters fresh-market candidates before ranking; tie is deterministic');
SELECT pg_temp.assert_true(
    NOT EXISTS (SELECT 1 FROM housing.v_nearest_hawker WHERE block_id = 2),
    'unlocated block has no invented proximity class');
SELECT pg_temp.assert_true(
    (SELECT count(*) = 2 FROM housing.v_resale_analysis
     WHERE flat_id = 1 AND transaction_month = DATE '2016-01-01'),
    'identical published sales in different source rows remain separate');
SELECT pg_temp.assert_true(
    (SELECT count(*) = 3 FROM housing.v_resale_analysis r
     JOIN housing.v_nearest_hawker h USING (block_id)),
    'nearest-centre join counts each located sale exactly once');
SELECT pg_temp.assert_true(
    (SELECT remaining_lease_months = 876 AND remaining_lease_basis = 'ESTIMATED_YEAR'
     FROM housing.v_resale_analysis WHERE transaction_id = 1),
    'older file receives a flagged year-resolution estimate');
SELECT pg_temp.assert_true(
    (SELECT remaining_lease_months = 736 AND remaining_lease_basis = 'REPORTED_MONTH'
     FROM housing.v_resale_analysis WHERE transaction_id = 3),
    'published year-month lease is preserved');
SELECT pg_temp.assert_true(
    (SELECT remaining_lease_months = 888 AND remaining_lease_basis = 'REPORTED_YEAR'
     FROM housing.v_resale_analysis WHERE transaction_id = 4),
    'published whole-year precision is preserved');

SELECT pg_temp.expect_failure(
    $$INSERT INTO housing.town VALUES (2, 'TEST TOWN')$$, '23505');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.town SET town_name = ' test town ' WHERE town_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.hdb_block SET town_id = 99 WHERE block_id = 1$$, '23503');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.hdb_block SET longitude = NULL WHERE block_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.hdb_block SET latitude = 91 WHERE block_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.hdb_block SET latitude = 'NaN' WHERE block_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$INSERT INTO housing.hdb_block VALUES (3, 1, '1A', 'TEST ROAD', NULL, NULL)$$, '23505');
SELECT pg_temp.expect_failure(
    $$INSERT INTO housing.hdb_flat SELECT 3, block_id, flat_type, flat_model,
      floor_area_sqm, storey_lower, storey_upper, lease_commence_year
      FROM housing.hdb_flat WHERE flat_id = 1$$, '23505');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.hdb_flat SET floor_area_sqm = 0 WHERE flat_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.hdb_flat SET floor_area_sqm = 'NaN' WHERE flat_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.hdb_flat SET storey_lower = 4 WHERE flat_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.resale_transaction SET resale_price = -1 WHERE transaction_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.resale_transaction SET resale_price = 'NaN' WHERE transaction_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.resale_transaction SET transaction_month = DATE '2016-01-02'
      WHERE transaction_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.resale_transaction SET source_row_number = 1 WHERE transaction_id = 2$$, '23505');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.resale_transaction SET remaining_lease_precision = 'MONTH'
      WHERE transaction_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.resale_transaction SET remaining_lease_precision = 'YEAR'
      WHERE transaction_id = 3$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.resale_transaction SET remaining_lease_months_reported = 1189
      WHERE transaction_id = 3$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.hawker_centre SET market_produce_stalls = -1 WHERE hawker_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$INSERT INTO housing.block_hawker_distance VALUES (1, 1, 123)$$, '23505');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.block_hawker_distance SET distance_m = -1 WHERE hawker_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.block_hawker_distance SET distance_m = 'NaN' WHERE hawker_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$UPDATE housing.block_hawker_distance SET distance_m = 'Infinity' WHERE hawker_id = 1$$, '23514');
SELECT pg_temp.expect_failure(
    $$DELETE FROM housing.hdb_block WHERE block_id = 1$$, '23001,23503');

SELECT 'PASS: 16 behavioral assertions and 24 expected constraint rejections' AS validation_result;
ROLLBACK;
