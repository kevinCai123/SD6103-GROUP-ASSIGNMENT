"""Sensitivity of the Q4 proximity comparison to the choice of hawker-centre population.

The database uses the NEA catalogue (the brief's hawker-centre dataset) as the authority for
centre identity, type and stall counts; hawker_geo.csv only supplies coordinates. This script
asks what Q4 would show if the 25 hawker_geo.csv centres that have no catalogue entry were
also treated as eligible hawker centres. It changes nothing in the database.

Output: results/hawker_sensitivity.json (cited in Section 3.1.4 of the report).
"""
from pathlib import Path
import json

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PREPARED = ROOT / 'data/prepared'
EARTH_RADIUS_M = 6_371_000


def nearest_distance(blocks, centres):
    """Haversine distance (m) from every block to its nearest centre, vectorised."""
    lat1 = np.radians(blocks.latitude.to_numpy())[:, None]
    lon1 = np.radians(blocks.longitude.to_numpy())[:, None]
    lat2 = np.radians(centres.latitude.to_numpy())[None, :]
    lon2 = np.radians(centres.longitude.to_numpy())[None, :]
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    a = np.clip(a, 0, 1)  # same clamp as the loader
    return (2 * EARTH_RADIUS_M * np.arctan2(np.sqrt(a), np.sqrt(1 - a))).min(axis=1)


def proximity_class(distance):
    """Project thresholds: NEAR [0,500), MEDIUM [500,1000), FAR [1000,inf)."""
    return np.where(distance < 500, 'NEAR', np.where(distance < 1000, 'MEDIUM', 'FAR'))


def q4_summary(sales, column):
    """Mirror Q4: NEAR vs FAR mean price per town and flat type, then count comparable rows."""
    means = (sales[sales[column].isin(['NEAR', 'FAR'])]
             .groupby(['town_name', 'flat_type', column]).resale_price.mean().unstack())
    both = means.dropna(subset=['NEAR', 'FAR']) if {'NEAR', 'FAR'} <= set(means.columns) else means.iloc[:0]
    diff = 100 * (both.NEAR - both.FAR) / both.FAR
    return dict(town_flat_type_rows=int(sales.groupby(['town_name', 'flat_type']).ngroups),
                comparable_rows=int(len(both)), positive=int((diff > 0).sum()),
                negative=int((diff < 0).sum()), median_difference_percent=round(float(diff.median()), 2))


def main():
    town = pd.read_csv(PREPARED / 'town.csv')
    blocks = pd.read_csv(PREPARED / 'hdb_block.csv').dropna(subset=['latitude'])
    centres = pd.read_csv(PREPARED / 'hawker_centre.csv')
    eligible = centres[centres.centre_type.isin(['HC', 'MHC'])].dropna(subset=['latitude'])

    # hawker_geo.csv rows never matched to a catalogue centre (see results/data_quality/hawker_matches.csv).
    geo = pd.read_csv(ROOT / 'data/raw/hawker_geo.csv', encoding='utf-8-sig')
    matched = set(pd.read_csv(ROOT / 'results/data_quality/hawker_matches.csv').geo_name.dropna())
    extra = geo[~geo.NAME.isin(matched)].dropna(subset=['latitude', 'longitude'])

    blocks['class_submitted'] = proximity_class(nearest_distance(blocks, eligible))
    blocks['class_with_geo_only'] = proximity_class(
        nearest_distance(blocks, pd.concat([eligible[['latitude', 'longitude']], extra[['latitude', 'longitude']]])))

    flats = pd.read_csv(PREPARED / 'hdb_flat.csv', usecols=['flat_id', 'block_id', 'flat_type'])
    sales = (pd.read_csv(PREPARED / 'resale_transaction.csv', usecols=['flat_id', 'transaction_month', 'resale_price'])
             .merge(flats, on='flat_id')
             .merge(blocks[['block_id', 'town_id', 'class_submitted', 'class_with_geo_only']], on='block_id')
             .merge(town, on='town_id'))

    submitted = q4_summary(sales, 'class_submitted')
    # Guard: the submitted classification must reproduce the actual Q4 result exactly.
    q4 = pd.read_csv(ROOT / 'results/queries/stage_5/Q4.csv')
    assert submitted['comparable_rows'] == q4.price_diff_percentage.notna().sum()
    assert submitted['positive'] == (q4.price_diff_percentage > 0).sum()

    changed = sales.class_submitted != sales.class_with_geo_only
    far_towns = (sales.groupby('town_name').class_submitted.apply(lambda s: (s == 'FAR').mean()))
    recent = sales[sales.transaction_month >= '2017-01-01']
    result = dict(
        geo_only_centres=sorted(extra.NAME),
        geo_only_centre_count=int(len(extra)),
        geocoded_sales=int(len(sales)),
        sales_changing_class=int(changed.sum()),
        far_sales_submitted=int((sales.class_submitted == 'FAR').sum()),
        far_sales_with_geo_only=int((sales.class_with_geo_only == 'FAR').sum()),
        towns_all_far_submitted=sorted(far_towns[far_towns == 1].index),
        q4_all_years=dict(submitted=submitted, with_geo_only=q4_summary(sales, 'class_with_geo_only')),
        q4_from_2017=dict(submitted=q4_summary(recent, 'class_submitted'),
                          with_geo_only=q4_summary(recent, 'class_with_geo_only')),
    )
    (ROOT / 'results/hawker_sensitivity.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'geo_only_centres'}, indent=2))


if __name__ == '__main__':
    main()
