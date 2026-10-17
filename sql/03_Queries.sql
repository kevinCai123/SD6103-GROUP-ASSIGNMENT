-- SD6103 Assignment 1, Task 3. PostgreSQL 14+.
-- Q1 uses the same complete 36-month interval at every database size.
-- Q5 uses a fixed SGD 250,000 budget, checked at all five database sizes.
-- Run each statement independently in pgAdmin, or this entire file in psql.

-- QUERY Q1
-- Average of individual price/area ratios, not total price / total area.
SELECT t.town_name, f.flat_type,
       round(avg(r.resale_price / f.floor_area_sqm), 2) AS avg_price_per_sqm,
       count(*) AS transaction_volume
FROM housing.resale_transaction AS r
JOIN housing.hdb_flat AS f USING (flat_id)
JOIN housing.hdb_block AS b USING (block_id)
JOIN housing.town AS t USING (town_id)
WHERE r.transaction_month >= DATE '1997-01-01'
  AND r.transaction_month < DATE '2000-01-01'
  AND f.flat_type IN ('4 ROOM', '5 ROOM')
GROUP BY t.town_name, f.flat_type
ORDER BY t.town_name, f.flat_type;

-- QUERY Q2
-- Lease thresholds are half-open: [0,50), [50,70), [70,90), [90,99].
-- Preserve an explicit UNKNOWN group if an effective lease is unavailable.
WITH bucketed AS (
    SELECT *, CASE
        WHEN remaining_lease_months IS NULL THEN 'UNKNOWN'
        WHEN remaining_lease_months < 600 THEN '0-<50 years'
        WHEN remaining_lease_months < 840 THEN '50-<70 years'
        WHEN remaining_lease_months < 1080 THEN '70-<90 years'
        ELSE '90-99 years' END AS lease_bucket
    FROM housing.v_resale_analysis
)
SELECT town_name, lease_bucket,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY resale_price))::numeric, 2)
           AS median_resale_price,
       round(avg(price_per_sqm), 2) AS avg_price_per_sqm,
       count(*) AS transaction_volume,
       count(*) FILTER (WHERE remaining_lease_basis IN ('REPORTED_MONTH','REPORTED_YEAR'))
           AS reported_lease_count,
       count(*) FILTER (WHERE remaining_lease_basis = 'ESTIMATED_YEAR') AS estimated_lease_count
FROM bucketed
GROUP BY town_name, lease_bucket
ORDER BY town_name, lease_bucket;

-- QUERY Q3
-- Transaction-weighted average area; tie-break by town name for deterministic top 10.
WITH top_towns AS (
    SELECT b.town_id, t.town_name, avg(f.floor_area_sqm) AS avg_floor_area_sqm
    FROM housing.resale_transaction AS r
    JOIN housing.hdb_flat AS f USING (flat_id)
    JOIN housing.hdb_block AS b USING (block_id)
    JOIN housing.town AS t USING (town_id)
    WHERE f.flat_type = '3 ROOM'
    GROUP BY b.town_id, t.town_name
    ORDER BY avg_floor_area_sqm DESC, t.town_name
    LIMIT 10
)
SELECT tt.town_name, round(tt.avg_floor_area_sqm, 2) AS avg_floor_area_sqm,
       EXTRACT(YEAR FROM r.transaction_month)::integer AS sale_year,
       max(r.resale_price) AS highest_resale_price,
       count(*) AS transaction_volume
FROM top_towns AS tt
JOIN housing.hdb_block AS b ON b.town_id = tt.town_id
JOIN housing.hdb_flat AS f USING (block_id)
JOIN housing.resale_transaction AS r USING (flat_id)
WHERE f.flat_type = '3 ROOM'
GROUP BY tt.town_name, tt.avg_floor_area_sqm, EXTRACT(YEAR FROM r.transaction_month)
ORDER BY tt.avg_floor_area_sqm DESC, tt.town_name, sale_year;

-- QUERY Q4
-- The view selects one nearest eligible centre per block; a sale is never multiplied.
-- An absent NEAR/FAR comparison remains NULL, not zero.
WITH averages AS (
    SELECT t.town_name AS town, f.flat_type,
           avg(r.resale_price) FILTER (WHERE n.proximity_class = 'NEAR') AS near_price,
           avg(r.resale_price) FILTER (WHERE n.proximity_class = 'FAR') AS far_price
    FROM housing.resale_transaction AS r
    JOIN housing.hdb_flat AS f USING (flat_id)
    JOIN housing.hdb_block AS b USING (block_id)
    JOIN housing.town AS t USING (town_id)
    JOIN housing.v_nearest_hawker AS n USING (block_id)
    GROUP BY t.town_name, f.flat_type
)
SELECT town, flat_type,
       round(near_price, 2) AS avg_price_near_hawker,
       round(far_price, 2) AS avg_price_far_hawker,
       round((near_price - far_price) * 100 / NULLIF(far_price, 0), 2) AS price_diff_percentage
FROM averages
ORDER BY town, flat_type;

-- QUERY Q5
-- Eligible HC/MHC centres with market stalls are filtered BEFORE nearest selection.
-- HAVING applies the budget to each town/proximity-class average.
SELECT t.town_name, n.proximity_class,
       round(avg(r.resale_price), 2) AS avg_resale_price,
       count(*) AS transaction_volume
FROM housing.resale_transaction AS r
JOIN housing.hdb_flat AS f USING (flat_id)
JOIN housing.hdb_block AS b USING (block_id)
JOIN housing.town AS t USING (town_id)
JOIN housing.v_nearest_market_hawker AS n USING (block_id)
GROUP BY t.town_name, n.proximity_class
HAVING avg(r.resale_price) > 250000
ORDER BY t.town_name,
         CASE n.proximity_class WHEN 'NEAR' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END;

-- QUERY Q6
-- Additional question: Which nearest-centre catchments account for the most sales,
-- by town and source reporting basis, and what are their average price/m2 and distance?
-- All seven stored tables participate. Select one centre per block before aggregating.
WITH ranked_distances AS (
    SELECT d.block_id, d.hawker_id, d.distance_m,
           row_number() OVER (PARTITION BY d.block_id ORDER BY d.distance_m, d.hawker_id) AS rn
    FROM housing.block_hawker_distance AS d
    JOIN housing.hawker_centre AS eligible USING (hawker_id)
    WHERE eligible.centre_type IN ('HC', 'MHC')
)
SELECT t.town_name, h.centre_name, s.date_basis,
       count(*) AS transaction_volume,
       round(avg(r.resale_price / f.floor_area_sqm), 2) AS avg_price_per_sqm,
       round(avg(n.distance_m)::numeric, 1) AS avg_distance_m
FROM housing.resale_transaction AS r
JOIN housing.hdb_flat AS f USING (flat_id)
JOIN housing.hdb_block AS b USING (block_id)
JOIN housing.town AS t USING (town_id)
JOIN housing.source_file AS s USING (source_file_id)
JOIN ranked_distances AS n ON n.block_id = b.block_id AND n.rn = 1
JOIN housing.hawker_centre AS h ON h.hawker_id = n.hawker_id
GROUP BY t.town_name, h.centre_name, s.date_basis
ORDER BY transaction_volume DESC, t.town_name, h.centre_name, s.date_basis
LIMIT 20;
