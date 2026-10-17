"""Bulk-load five incremental database sizes and collect actual PostgreSQL results.

The default run refuses to overwrite an existing database. Supply connection details
with --dsn or PGDSN; the DSN should connect to a maintenance database such as postgres.
The experiment creates its own database. Do not run concurrent database workloads.
"""
from pathlib import Path
from contextlib import ExitStack
from decimal import Decimal
import argparse
import csv
import datetime as dt
import hashlib
import io
import itertools
import json
import os
import platform
import random
import re
import statistics
import time
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
TABLES = ['town','hdb_block','hdb_flat','source_file','resale_transaction','hawker_centre','block_hawker_distance']
MEASUREMENT_FIELDS = ['phase','stage','transaction_rows','relation_bytes','database_bytes',
                      'query','run','execution_ms','planning_ms','client_elapsed_ms','result_rows']

def queries():
    source = (ROOT/'sql/03_Queries.sql').read_text(encoding='utf-8')
    pieces = re.split(r'-- QUERY (Q[1-6])\s*\n', source)
    return {pieces[i]:pieces[i+1].strip() for i in range(1,len(pieces),2)}

def serializable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    raise TypeError(type(value))

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=serializable), encoding='utf-8')

def export_result(connection, query, path):
    cursor = connection.execute(query)
    fields = [field.name for field in cursor.description]
    records = cursor.fetchall()
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(fields)
        writer.writerows(records)
    return fields, records

def size_info(connection):
    return dict(zip(['transaction_rows','relation_bytes','database_bytes'], connection.execute('''
        SELECT (SELECT count(*) FROM housing.resale_transaction),
               (SELECT sum(pg_total_relation_size(c.oid))::bigint FROM pg_class c
                JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='housing' AND c.relkind='r'),
               pg_database_size(current_database())''').fetchone()))

def configure(connection):
    connection.execute("SET work_mem = '32MB'")
    connection.execute('SET max_parallel_workers_per_gather = 0')
    connection.execute('SET jit = off')
    connection.execute("SET statement_timeout = '180s'")
    connection.execute("SET timezone = 'Asia/Singapore'")

def measure(connection, query_map, phase, stage, sizes, output, plan_folder):
    plan_folder.mkdir(parents=True, exist_ok=True)
    # Each query is warmed once. These unrecorded executions are not among the five trials.
    for query in query_map.values():
        connection.execute(query).fetchall()
    measurements = []
    for run in range(1,6):
        order = list(query_map)
        random.Random(6103+run).shuffle(order)
        for name in order:
            started = time.perf_counter()
            explained = connection.execute('EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, FORMAT JSON) ' + query_map[name]).fetchone()[0][0]
            elapsed = (time.perf_counter()-started)*1000
            row = dict(phase=phase, stage=stage, **sizes, query=name, run=run,
                       execution_ms=explained['Execution Time'], planning_ms=explained['Planning Time'],
                       client_elapsed_ms=round(elapsed,6), result_rows=explained['Plan']['Actual Rows'])
            measurements.append(row)
            if run == 1:
                write_json(plan_folder/(name+'.json'), explained)
        print(f'{phase}, stage {stage}, repetition {run}/5 complete', flush=True)
    with output.open('a', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=MEASUREMENT_FIELDS, lineterminator='\n')
        if stream.tell() == 0:
            writer.writeheader()
        writer.writerows(measurements)
    return measurements

def load_stage(connection, stage, streams):
    with connection.transaction():
        for table in TABLES:
            count = stage['new_rows'][table]
            if not count:
                continue
            # Prepared fields contain no line breaks; COPY reads fully quoted CSV records.
            with connection.cursor().copy(sql.SQL('COPY housing.{} FROM STDIN WITH (FORMAT CSV)').format(sql.Identifier(table))) as copy:
                remaining = count
                while remaining:
                    chunk = list(itertools.islice(streams[table], min(10000,remaining)))
                    if not chunk:
                        raise ValueError('Premature CSV end: '+table)
                    copy.write(''.join(chunk))
                    remaining -= len(chunk)
        # Explicit IDs loaded by COPY must advance each identity sequence.
        for table in TABLES[:-1]:
            identity = next(csv.reader((ROOT/'data/prepared'/(table+'.csv')).open(encoding='utf-8')))[0]
            connection.execute(sql.SQL("SELECT setval(pg_get_serial_sequence(%s,%s), max({}), true) FROM housing.{}").format(
                sql.Identifier(identity), sql.Identifier(table)), ('housing.'+table,identity))
    for table,expected in stage['cumulative_rows'].items():
        actual = connection.execute(sql.SQL('SELECT count(*) FROM housing.{}').format(sql.Identifier(table))).fetchone()[0]
        if actual != expected:
            raise AssertionError((table,actual,expected))
    connection.execute('VACUUM (ANALYZE)')

def verify_stage(connection, query_map, stage, folder):
    folder.mkdir(parents=True, exist_ok=True)
    sizes = size_info(connection)
    checks = {}
    result_data = {}
    for name,query in query_map.items():
        fields,records = export_result(connection,query,folder/(name+'.csv'))
        assert records, f'{name}: empty result'
        result_data[name] = (fields,records)
        checks[name+'_rows'] = len(records)
    town_count = connection.execute('SELECT count(DISTINCT b.town_id) FROM housing.resale_transaction r JOIN housing.hdb_flat f USING(flat_id) JOIN housing.hdb_block b USING(block_id)').fetchone()[0]
    q5_towns = len({row[0] for row in result_data['Q5'][1]})
    assert 0 < q5_towns < town_count, (q5_towns,town_count)
    checks['q5_towns_above_budget'] = q5_towns
    checks['all_sale_towns'] = town_count
    checks['q2_transaction_total'] = sum(row[4] for row in result_data['Q2'][1])
    assert checks['q2_transaction_total'] == sizes['transaction_rows']
    assert len({row[0] for row in result_data['Q3'][1]}) == 10
    assert result_data['Q4'][0] == ['town','flat_type','avg_price_near_hawker','avg_price_far_hawker','price_diff_percentage']
    nearest = connection.execute('SELECT count(*), count(DISTINCT block_id) FROM housing.v_nearest_hawker').fetchone()
    assert nearest[0] == nearest[1]
    checks['nearest_block_rows'] = nearest[0]
    expected_q1 = connection.execute("SELECT count(*) FROM housing.resale_transaction r JOIN housing.hdb_flat f USING(flat_id) WHERE transaction_month >= DATE '1997-01-01' AND transaction_month < DATE '2000-01-01' AND flat_type IN ('4 ROOM','5 ROOM')").fetchone()[0]
    assert sum(row[3] for row in result_data['Q1'][1]) == expected_q1
    checks['q1_transaction_total'] = expected_q1
    assert all(row[2] > 250000 for row in result_data['Q5'][1])
    assert all(row[4] is None for row in result_data['Q4'][1] if row[2] is None or row[3] is None)
    write_json(folder/'validation.json', checks)
    return checks

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn', default=os.environ.get('PGDSN',''))
    parser.add_argument('--connection-file', type=Path)
    parser.add_argument('--database', default='sd6103_hdb_hawker')
    args = parser.parse_args()
    output = ROOT/'results'
    output.mkdir(exist_ok=True)
    baseline = output/'baseline_measurements.csv'
    if baseline.exists():
        raise RuntimeError('Measurement output already exists; archive it before a new experiment.')
    connect = json.loads(args.connection_file.read_text()) if args.connection_file else {}
    with psycopg.connect(args.dsn, **connect, autocommit=True) as maintenance:
        exists = maintenance.execute('SELECT 1 FROM pg_database WHERE datname=%s',(args.database,)).fetchone()
        if exists:
            raise RuntimeError('Database already exists; use a new --database name. Existing data will not be overwritten.')
        maintenance.execute(sql.SQL("CREATE DATABASE {} WITH ENCODING='UTF8' TEMPLATE=template0").format(sql.Identifier(args.database)))
    connect['dbname'] = args.database
    with psycopg.connect(args.dsn, **connect, autocommit=True) as connection:
        configure(connection)
        schema = (ROOT/'sql/01_Create_Database.sql').read_text(encoding='utf-8')
        schema = schema[schema.index('\nBEGIN;'):]
        connection.execute(schema)
        environment = dict(postgresql_version=connection.execute('SELECT version()').fetchone()[0],
                           platform=platform.platform(), processor=platform.processor(), logical_processors=os.cpu_count(),
                           started_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                           settings=dict(connection.execute("SELECT name,setting FROM pg_settings WHERE name IN ('work_mem','shared_buffers','max_parallel_workers_per_gather','jit','effective_cache_size','fsync','block_size','server_encoding','lc_collate','lc_ctype')").fetchall()),
                           warmup_runs=1, measured_runs=5,
                           metric='EXPLAIN ANALYZE server Execution Time in milliseconds; per-node timing disabled',
                           query_sha256=hashlib.sha256((ROOT/'sql/03_Queries.sql').read_bytes()).hexdigest())
        write_json(output/'environment.json', environment)
        query_map = queries()
        stages = json.loads((ROOT/'data/prepared/load_plan.json').read_text())
        summaries = []
        with ExitStack() as stack:
            streams = {}
            for table in TABLES:
                streams[table] = stack.enter_context((ROOT/'data/prepared'/(table+'.csv')).open(encoding='utf-8',newline=''))
                next(streams[table])
            for stage in stages:
                started = time.perf_counter()
                load_stage(connection,stage,streams)
                load_seconds = time.perf_counter()-started
                sizes = size_info(connection)
                print(f'Loaded stage {stage["stage"]}: {sizes["transaction_rows"]:,} sales',flush=True)
                checks = verify_stage(connection,query_map,stage['stage'],output/'queries'/f'stage_{stage["stage"]}')
                measurements = measure(connection,query_map,'baseline',stage['stage'],sizes,
                                       baseline,output/'plans'/f'baseline_stage_{stage["stage"]}')
                summaries.append(dict(stage=stage['stage'], **sizes, load_seconds=load_seconds, validation=checks,
                    mean_execution_ms={q:statistics.mean(x['execution_ms'] for x in measurements if x['query']==q) for q in query_map}))
                write_json(output/'baseline_summary.json',summaries)
        write_json(output/'experiment_state.json',dict(database=args.database,baseline_complete=True))
        print('All 150 baseline measurements completed.',flush=True)

if __name__ == '__main__':
    main()
