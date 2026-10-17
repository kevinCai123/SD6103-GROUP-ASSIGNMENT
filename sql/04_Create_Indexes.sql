-- Task 4. Run only AFTER collecting the five-size Task 3 baseline.
-- Baseline retains all primary-key and UNIQUE indexes.
-- These additional B-tree indexes do not change query semantics.

-- INDEX I1 idx_resale_month_cover Q1
CREATE INDEX idx_resale_month_cover
ON housing.resale_transaction (transaction_month, flat_id) INCLUDE (resale_price);

-- INDEX I2 idx_flat_type_cover Q3
CREATE INDEX idx_flat_type_cover
ON housing.hdb_flat (flat_type, flat_id) INCLUDE (block_id, floor_area_sqm);

-- INDEX I3 idx_resale_flat_cover Q3
CREATE INDEX idx_resale_flat_cover
ON housing.resale_transaction (flat_id, transaction_month) INCLUDE (resale_price, source_file_id);

-- INDEX I4 idx_distance_order Q4
CREATE INDEX idx_distance_order
ON housing.block_hawker_distance (block_id, distance_m, hawker_id);
