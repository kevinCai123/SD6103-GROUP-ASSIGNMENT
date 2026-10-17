"""Download the assignment's public CSV snapshots; preserve existing downloads.

Requires Python 3.10+ and curl (included with current Windows installations).
The NTULearn hawker_geo.csv is supplied locally because it is course material.
"""
from pathlib import Path
import argparse
import csv
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import time

DATASETS = [
    'd_ebc5ab87086db484f88045b47411ebc5',
    'd_43f493c6c50d54243cc1eab0df142d6a',
    'd_2d5ff9ea31397b66239f245f57751537',
    'd_8b84c4ee58e3cfc0ece0d773c8ca6abc',
    'd_ea9ed51da2787afaf8e51f827c304208',
    'd_68a42f09f350881996d83f9cd73ab02f',
]

def fetch(url, path=None):
    command = ['curl', '--location', '--fail', '--silent', '--show-error',
               '--retry', '3', '--retry-delay', '15', '--max-time', '180',
               '--user-agent', 'Mozilla/5.0 SD6103 academic data loader']
    if path:
        command += ['--output', str(path)]
    command.append(url)
    result = subprocess.run(command, check=True, capture_output=True)
    return result.stdout

def describe(path, url, metadata=None):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.reader(stream)
        header = next(reader)
        rows = sum(1 for _ in reader)
    return dict(file=path.name, source_url=url,
                retrieved_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                bytes=path.stat().st_size, rows=rows, columns=header,
                metadata=metadata)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'data/raw')
    parser.add_argument('--hawker-geo', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / 'sources.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for dataset_id in DATASETS:
        filename = dataset_id + '.csv'
        target = args.output / filename
        if target.exists() and filename in manifest:
            assert hashlib.sha256(target.read_bytes()).hexdigest() == manifest[filename]['sha256']
            print('Using frozen snapshot:', filename, flush=True)
            continue
        metadata_url = f'https://api-production.data.gov.sg/v2/public/api/datasets/{dataset_id}/metadata'
        metadata = json.loads(fetch(metadata_url))['data']
        base = f'https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}'
        response = json.loads(fetch(base + '/initiate-download'))
        download_url = response.get('data', {}).get('url')
        while not download_url:
            time.sleep(15)
            response = json.loads(fetch(base + '/poll-download'))
            download_url = response.get('data', {}).get('url')
        fetch(download_url, target)
        manifest[filename] = describe(target, f'https://data.gov.sg/datasets/{dataset_id}/view', metadata)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(metadata['name'], ':', manifest[filename]['rows'], 'rows', flush=True)
        time.sleep(15)  # Respect the unauthenticated public download quota.

    filename = 'hdb_geo.csv'
    target = args.output / filename
    url = 'https://raw.githubusercontent.com/BlueSkyLT/siteselect_sg/main/dataset/hdb.csv'
    if not target.exists():
        fetch(url, target)
        manifest[filename] = describe(target, url)
    if args.hawker_geo:
        shutil.copyfile(args.hawker_geo, args.output / 'hawker_geo.csv')
    target = args.output / 'hawker_geo.csv'
    if not target.exists():
        raise FileNotFoundError('Provide the course hawker_geo.csv using --hawker-geo.')
    if 'hawker_geo.csv' not in manifest:
        manifest['hawker_geo.csv'] = describe(target, 'NTULearn: supplied hawker_geo.csv')
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Downloaded and fingerprinted all eight source CSV files.', flush=True)

if __name__ == '__main__':
    main()
