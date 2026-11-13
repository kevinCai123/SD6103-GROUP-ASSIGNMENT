"""Task 4: measure each optional index alone, then all optional indexes together.

Run after run_experiment.py, using the same maintenance DSN/connection options.
Only indexes named in 04_Create_Indexes.sql are created/dropped by this script.
"""
from pathlib import Path
import argparse
import csv
import json
import os
import re
import statistics
import time
import psycopg
from psycopg import sql
from run_experiment import ROOT, configure, queries, size_info, measure, write_json, export_result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn', default=os.environ.get('PGDSN',''))
    parser.add_argument('--connection-file',type=Path)
    parser.add_argument('--database',default='sd6103_hdb_hawker')
    args = parser.parse_args()
    connection_args = json.loads(args.connection_file.read_text()) if args.connection_file else {}
    connection_args['dbname'] = args.database
    source = (ROOT/'sql/04_Create_Indexes.sql').read_text()
    parts = re.split(r'-- INDEX (I\d) (\w+) (Q\d)\s*\n',source)
    candidates = [(parts[i],parts[i+1],parts[i+2],parts[i+3].strip()) for i in range(1,len(parts),4)]
    output = ROOT/'results'

    for name in ['index_individual_measurements.csv','indexed_measurements.csv']:
        if (output/name).exists():
            raise RuntimeError('Existing measurements must be archived before rerunning: '+name)
    baseline = {row['query']:[] for row in csv.DictReader((output/'baseline_measurements.csv').open())}

    for row in csv.DictReader((output/'baseline_measurements.csv').open()):
        if int(row['stage'])==5:
            baseline[row['query']].append(float(row['execution_ms']))

    with psycopg.connect(args.dsn,**connection_args,autocommit=True) as connection:
        configure(connection)
        assert connection.execute('SELECT count(*) FROM housing.source_file').fetchone()[0] == 5
        for _,name,_,_ in candidates:
            assert connection.execute('SELECT to_regclass(%s)',('housing.'+name,)).fetchone()[0] is None

        query_map = queries()
        index_statistics = []

        for label,name,target,ddl in candidates:

            start = time.perf_counter()
            connection.execute(ddl)

            build_seconds = time.perf_counter()-start
            
            index_bytes = connection.execute('SELECT pg_relation_size(%s::regclass)',('housing.'+name,)).fetchone()[0]
            runs = measure(connection,{target:query_map[target]},label,5,size_info(connection),
                           
                           output/'index_individual_measurements.csv',output/'plans'/('index_'+label))
            mean = statistics.mean(row['execution_ms'] for row in runs)
            index_statistics.append(dict(index=label,name=name,target_query=target,bytes=index_bytes,
                                         build_seconds=build_seconds,mean_execution_ms=mean,
                                         baseline_mean_ms=statistics.mean(baseline[target]),
                                         reduction_percent=100*(1-mean/statistics.mean(baseline[target]))))
            
            # Drop only the optional index just created; all key indexes remain in place.
            connection.execute(sql.SQL('DROP INDEX housing.{}').format(sql.Identifier(name)))

        for _,_,_,ddl in candidates:
            connection.execute(ddl)
        # Existing visibility maps/statistics are unchanged by index creation.
        indexed = measure(connection,query_map,'all_indexes',5,size_info(connection),
                          output/'indexed_measurements.csv',output/'plans/indexed_stage_5')
        (output/'queries/indexed').mkdir(parents=True,exist_ok=True)

        for query,text in query_map.items():
            path = output/'queries/indexed'/(query+'.csv')
            export_result(connection,text,path)
            assert path.read_bytes() == (output/'queries/stage_5'/(query+'.csv')).read_bytes(), query+' changed result'
        summary = []

        for query in query_map:
            before = statistics.mean(baseline[query])
            after = statistics.mean(row['execution_ms'] for row in indexed if row['query']==query)
            summary.append(dict(query=query,baseline_ms=before,indexed_ms=after,
                                reduction_percent=100*(1-after/before),speedup=before/after))
            
        write_json(output/'index_summary.json',dict(individual=index_statistics,combined=summary,
                                                   total_index_bytes=sum(r['bytes'] for r in index_statistics),
                                                   indexed_results_identical=True))
        print(json.dumps(summary,indent=2),flush=True)

if __name__ == '__main__':
    main()
