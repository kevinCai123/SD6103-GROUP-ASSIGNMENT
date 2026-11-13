"""Reproducibly transform the eight frozen inputs into the seven schema CSVs.

No records are silently discarded. Unknown spatial matches retain NULL coordinates.
Identifiers are assigned on first appearance in the documented source loading order.
Only Python's standard library is required. Run from any working directory.
"""
from pathlib import Path
from collections import Counter, defaultdict
from contextlib import ExitStack
from decimal import Decimal
import argparse
import csv
import hashlib
import json
import math
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ('d_ebc5ab87086db484f88045b47411ebc5.csv', 'APPROVAL'),
    ('d_2d5ff9ea31397b66239f245f57751537.csv', 'REGISTRATION'),
    ('d_ea9ed51da2787afaf8e51f827c304208.csv', 'REGISTRATION'),
    ('d_8b84c4ee58e3cfc0ece0d773c8ca6abc.csv', 'REGISTRATION'),
    ('d_43f493c6c50d54243cc1eab0df142d6a.csv', 'APPROVAL'),
]
FIELDS = {
    'town': ['town_id', 'town_name'],
    'hdb_block': ['block_id', 'town_id', 'block_no', 'street_name', 'latitude', 'longitude'],
    'hdb_flat': ['flat_id', 'block_id', 'flat_type', 'flat_model', 'floor_area_sqm',
                 'storey_lower', 'storey_upper', 'lease_commence_year'],
    'source_file': ['source_file_id', 'file_name', 'sha256', 'date_basis'],
    'resale_transaction': ['transaction_id', 'flat_id', 'source_file_id', 'source_row_number',
                           'transaction_month', 'resale_price', 'remaining_lease_months_reported',
                           'remaining_lease_precision'],
    'hawker_centre': ['hawker_id', 'centre_name', 'address', 'centre_type',
                      'cooked_food_stalls', 'market_produce_stalls', 'latitude', 'longitude'],
    'block_hawker_distance': ['block_id', 'hawker_id', 'distance_m'],
}
FLAT_TYPES = {'1 ROOM', '2 ROOM', '3 ROOM', '4 ROOM', '5 ROOM', 'EXECUTIVE', 'MULTI-GENERATION'}
EXPANSIONS = {'RD':'ROAD', 'AVE':'AVENUE', 'DR':'DRIVE', 'CRES':'CRESCENT', 'CL':'CLOSE',
              'CT':'COURT', 'TER':'TERRACE', 'PL':'PLACE', 'HTS':'HEIGHTS', 'UPP':'UPPER',
              'LOR':'LORONG', 'JLN':'JALAN', 'BT':'BUKIT', 'TG':'TANJONG', 'PK':'PARK',
              'GDNS':'GARDENS', 'CTRL':'CENTRAL', 'IND':'INDUSTRIAL', 'EST':'ESTATE',
              'KG':'KAMPONG', 'NTH':'NORTH', 'STH':'SOUTH', 'ST':'STREET'}

def canonical(value): 

    return ' '.join(unicodedata.normalize('NFKC', str(value)).strip().upper().split())

def address_key(value): 

    text = canonical(value).replace("C'WEALTH", 'COMMONWEALTH').replace("ST.", 'SAINT')
    text = re.sub(r'[^A-Z0-9 ]', '', text) 

    return ' '.join(EXPANSIONS.get(word, word) for word in text.split())

def centre_key(value): 

    text = canonical(value).replace('&', 'AND').replace('CENTER', 'CENTRE') 

    return re.sub(r'[^A-Z0-9]', '', text)

def postal(value): 

    codes = re.findall(r'(?<!\d)\d{6}(?!\d)', value) 

    return codes[-1] if codes else None

def read_csv(path): 
    with path.open(encoding='utf-8-sig', newline='') as stream: 

        yield from csv.DictReader(stream)

def write_csv(path, header, rows): 

    with path.open('w', encoding='utf-8', newline='') as stream: 

        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(header)
        writer.writerows(rows)

def point(latitude, longitude):

    try:
        lat, lon = float(latitude), float(longitude)
        if math.isfinite(lat) and math.isfinite(lon) and 1 <= lat <= 1.6 and 103.5 <= lon <= 104.2:
            return lat, lon 
        
    except (TypeError, ValueError):
        pass 
    
    return None

def haversine(a, b): 

    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2 
    value = min(1., max(0., value))

    return 2 * 6371000 * math.atan2(math.sqrt(value), math.sqrt(1-value))

def remaining_lease(raw): 

    value = str(raw or '').strip().lower() 

    if not value:
        return None, None 
    
    if re.fullmatch(r'\d+(?:\.0+)?', value):
        months, precision = int(Decimal(value)) * 12, 'YEAR' 

    else: 
        match = re.fullmatch(r'(\d+)\s+years?(?:\s+(\d+)\s+months?)?', value) 

        if not match: 
            raise ValueError('Unrecognized remaining lease: ' + value) 
        years, extra = int(match[1]), int(match[2] or 0) 

        if extra >= 12: 
            raise ValueError('Remaining lease month component exceeds 11: ' + value)
        months, precision = years * 12 + extra, 'MONTH' 

    if not 0 <= months <= 1188:
        raise ValueError('Remaining lease outside 0..1188 months: ' + value)
    return months, precision

def money_or_area(raw): 

    value = Decimal(raw)

    if not value.is_finite() or value <= 0 or value != value.quantize(Decimal('.01')):
        raise ValueError('Invalid positive decimal: ' + str(raw))
    
    return str(value.quantize(Decimal('.01')))

def prepare(raw, output, evidence):

    output.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((raw / 'sources.json').read_text(encoding='utf-8'))

    for name, info in manifest.items():
        assert hashlib.sha256((raw/name).read_bytes()).hexdigest() == info['sha256'], name

    # Exact source-address matching; no fuzzy assignment of block coordinates.
    geo_candidates = defaultdict(list)
    geo_issues = []

    for number, row in enumerate(read_csv(raw/'hdb_geo.csv'), 1):
        key = (canonical(row['blk_no']), address_key(row['street']))
        coordinates = point(row['lat'], row['lng'])
        expected = address_key(key[0] + ' ' + row['street'])
        actual = address_key(row['addr'])

        if coordinates is None:
            geo_issues.append([number, *key, 'INVALID_COORDINATES', row['addr']])
        elif not (actual == expected or actual.startswith(expected + ' ')):
            geo_issues.append([number, *key, 'GEOCODE_ADDRESS_MISMATCH', row['addr']])
        else:
            geo_candidates[key].append(coordinates)

    geocodes = {}

    for key, coordinates in geo_candidates.items():

        distinct = set(coordinates)

        if len(distinct) == 1:
            geocodes[key] = distinct.pop()

        else:
            geo_issues.append(['', *key, 'CONFLICTING_COORDINATES', ''])

    write_csv(evidence/'hdb_geocode_issues.csv',
              ['geo_source_row','block_no','street_key','issue','geocoded_address'], geo_issues)

    # Hawker matching uses unique exact normalized names, then unique postal codes.
    hawker_geo = list(read_csv(raw/'hawker_geo.csv'))
    by_name, by_postal = defaultdict(list), defaultdict(list)

    for row in hawker_geo:
        by_name[centre_key(row['NAME'])].append(row)

        if postal(row['ADDRESS_MYENV']):
            by_postal[postal(row['ADDRESS_MYENV'])].append(row)

    centres, centre_points, matching = [], {}, []
    catalogue = list(read_csv(raw/'d_68a42f09f350881996d83f9cd73ab02f.csv'))

    for identifier, row in enumerate(catalogue, 1):

        name = canonical(row['name_of_centre'])
        candidates = by_name.get(centre_key(name), [])
        method = 'EXACT_NORMALIZED_NAME' 

        if len(candidates) != 1: 

            candidates = by_postal.get(postal(row['location_of_centre']), [])
            method = 'UNIQUE_POSTAL_CODE' 

        match = candidates[0] if len(candidates) == 1 else None
        coordinates = point(match['latitude'], match['longitude']) if match else None 

        if coordinates:
            centre_points[identifier] = coordinates 

        else:
            method = 'UNMATCHED_OR_INVALID'
        cooked, market = int(row['no_of_cooked_food_stalls']), int(row['no_of_mkt_produce_stalls']) 

        assert cooked >= 0 and market >= 0
        assert cooked + market == int(row['no_of_stalls']) 

        centre_type = canonical(row['type_of_centre']) 

        assert centre_type in {'HC', 'MHC', 'MK'} 

        centres.append([identifier, name, ' '.join(row['location_of_centre'].split()),
                        centre_type, cooked, market, *(coordinates or [None, None])]) 
        
        matching.append([identifier, name, method, match['NAME'] if match else '',
                         row['location_of_centre'], match['ADDRESS_MYENV'] if match else '',
                         *(coordinates or [None,None])]) 
        
    assert len({row[1] for row in centres}) == len(centres) 

    write_csv(evidence/'hawker_matches.csv',
              ['hawker_id','catalogue_name','method','geo_name','catalogue_address','geo_address',
               'latitude','longitude'], matching)

    # A single town per block is a declared snapshot assumption, checked across all sources.
    block_towns = defaultdict(set)
    latest_town = {} 

    for filename, basis in SOURCES: 

        for row in read_csv(raw/filename): 

            key = canonical(row['block']), canonical(row['street_name'])
            town = canonical(row['town'])
            block_towns[key].add(town)
            item = row['month'], town
            
            if key not in latest_town or item > latest_town[key]:
                latest_town[key] = item 

    town_conflicts = [[*key, '; '.join(sorted(towns)), latest_town[key][1]]
                     for key,towns in block_towns.items() if len(towns) > 1] 
    
    write_csv(evidence/'town_conflicts.csv', ['block_no','street_name','source_towns','snapshot_town'], town_conflicts)

    counts = {name:0 for name in FIELDS} 

    towns, blocks, flats = {}, {}, {}
    block_points, block_names, block_sales = {}, {}, Counter()
    stages, profiles = [], []
    precisions = Counter()
    total_exact_duplicates = 0 

    with ExitStack() as stack: 

        writers = {}
        for table, fields in FIELDS.items():
            stream = stack.enter_context((output/(table+'.csv')).open('w', encoding='utf-8', newline=''))
            writers[table] = csv.writer(stream, lineterminator='\n')
            writers[table].writerow(fields) 

        def emit(table, row):
            writers[table].writerow(row)
            counts[table] += 1 

        for row in centres:
            emit('hawker_centre', row) 

        for stage, (filename, basis) in enumerate(SOURCES, 1):
            before = dict(counts)
            if stage == 1:
                before['hawker_centre'] = 0 

            emit('source_file', [stage, filename, manifest[filename]['sha256'], basis])
            raw_rows, geocoded_sales, duplicate_rows = 0, 0, 0
            signatures = set()
            months = Counter() 

            for source_row, row in enumerate(read_csv(raw/filename), 1):
                raw_rows += 1
                signature = tuple(row.values()) 

                if signature in signatures:
                    duplicate_rows += 1
                signatures.add(signature)
                key = canonical(row['block']), canonical(row['street_name'])
                town = latest_town[key][1] 

                if town not in towns:
                    towns[town] = len(towns)+1
                    emit('town', [towns[town], town]) 

                if key not in blocks:
                    block_id = len(blocks)+1
                    blocks[key] = block_id
                    block_names[block_id] = (*key, town)
                    coordinates = geocodes.get((key[0], address_key(key[1]))) 

                    if coordinates:
                        block_points[block_id] = coordinates 

                    emit('hdb_block', [block_id, towns[town], *key, *(coordinates or [None,None])]) 

                    if coordinates:
                        for hawker_id, hawker_point in centre_points.items():
                            emit('block_hawker_distance', [block_id, hawker_id,
                                                          format(haversine(coordinates, hawker_point), '.12f')])
                block_id = blocks[key]
                block_sales[block_id] += 1
                geocoded_sales += block_id in block_points
                flat_type = canonical(row['flat_type']).replace('MULTI GENERATION','MULTI-GENERATION') 

                if flat_type not in FLAT_TYPES:
                    raise ValueError(f'{filename}:{source_row}: invalid flat type {flat_type}') 
                
                model = canonical(row['flat_model']) 

                assert model 

                band = re.fullmatch(r'(\d+)\s+TO\s+(\d+)', canonical(row['storey_range'])) 

                if not band:
                    raise ValueError(f'{filename}:{source_row}: invalid storey band') 
                
                lower, upper = int(band[1]), int(band[2])
                lease_year = int(row['lease_commence_date']) 

                assert 1 <= lower <= upper and 1900 <= lease_year <= 9999
                area = money_or_area(row['floor_area_sqm']) 

                profile_key = (block_id, flat_type, model, area, lower, upper, lease_year) 

                if profile_key not in flats:
                    flats[profile_key] = len(flats)+1
                    emit('hdb_flat', [flats[profile_key], *profile_key]) 

                month = row['month']
                assert re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month) 

                months[month] += 1
                lease, precision = remaining_lease(row.get('remaining_lease'))
                precisions[precision or 'MISSING'] += 1 

                emit('resale_transaction', [counts['resale_transaction']+1, flats[profile_key],                                            
                     stage, source_row, month+'-01', money_or_area(row['resale_price']), lease, precision]) 
                
            assert raw_rows == manifest[filename]['rows'] 

            total_exact_duplicates += duplicate_rows 

            profiles.append(dict(stage=stage, file=filename, date_basis=basis, rows=raw_rows,
                                 first_month=min(months), last_month=max(months),
                                 distinct_months=len(months), exact_duplicate_records_retained=duplicate_rows,
                                 geocoded_transactions=geocoded_sales)) 
            
            stages.append(dict(stage=stage, source=filename, cumulative_rows=dict(counts),
                               new_rows={k:counts[k]-before[k] for k in FIELDS}, previous_rows=before,
                               geocoded_blocks=len(block_points))) 
            
            print(f'Stage {stage}: {raw_rows:,} source rows; {counts["resale_transaction"]:,} cumulative sales', flush=True)

    write_csv(evidence/'unmatched_blocks.csv', ['block_id','block_no','street_name','town','transactions'],
              ([identifier,*block_names[identifier],block_sales[identifier]]
               for identifier in block_names if identifier not in block_points)) 
    
    summary = dict(table_counts=counts, stages=stages, sources=profiles, 
                   
                   hdb_geo_input_rows=manifest['hdb_geo.csv']['rows'],
                   hdb_geo_excluded_rows=len(geo_issues), hawker_geo_input_rows=len(hawker_geo), 

                   hawker_match_methods=dict(Counter(row[2] for row in matching)),
                   geocoded_centres=len(centre_points), geocoded_blocks=len(block_points), 

                   unmatched_blocks=len(blocks)-len(block_points),
                   geocoded_transactions=sum(v for k,v in block_sales.items() if k in block_points), 

                   exact_duplicate_records_retained=total_exact_duplicates,
                   town_conflicts=len(town_conflicts), reported_lease_precision=dict(precisions), 

                   distance_rule='Haversine, R=6371000 m; NEAR [0,500), MEDIUM [500,1000), FAR [1000,infinity)',
                   preparation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()) 
    
    assert counts['block_hawker_distance'] == len(block_points)*len(centre_points) 

    (evidence/'quality_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    (output/'load_plan.json').write_text(json.dumps(stages, indent=2), encoding='utf-8') 

    print(json.dumps({k:v for k,v in summary.items() if k not in {'stages','sources'}}, indent=2))

if __name__ == '__main__': 

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, default=ROOT/'data/raw')
    parser.add_argument('--output', type=Path, default=ROOT/'data/prepared')
    parser.add_argument('--evidence', type=Path, default=ROOT/'results/data_quality')
    args = parser.parse_args() 

    prepare(args.raw, args.output, args.evidence)
