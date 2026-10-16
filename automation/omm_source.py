#!/usr/bin/env python3
"""GVSA official CelesTrak OMM source and validation library.
Downloads official CelesTrak data and produces only validated ISS / Starlink JSON.
No credentials, no remote uploads, no fabricated orbital elements.
"""
import argparse
import csv
from datetime import datetime, timezone
import io
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler

ISS_URL = 'https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=JSON'
STAR_URL = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=STARLINK&FORMAT=CSV'
RETRY_SECONDS = 7200
MAX_BYTES = 30_000_000
SAMPLE_SIZE = 36
TIME_FIELDS = ('EPOCH',)
REQUIRED = ('NORAD_CAT_ID', 'EPOCH', 'OBJECT_NAME', 'MEAN_MOTION', 'ECCENTRICITY',
            'INCLINATION', 'RA_OF_ASC_NODE', 'ARG_OF_PERICENTER', 'MEAN_ANOMALY',
            'BSTAR', 'MEAN_MOTION_DOT', 'MEAN_MOTION_DDOT')
NUMERIC = ('MEAN_MOTION', 'ECCENTRICITY', 'INCLINATION', 'RA_OF_ASC_NODE',
           'ARG_OF_PERICENTER', 'MEAN_ANOMALY', 'BSTAR', 'MEAN_MOTION_DOT', 'MEAN_MOTION_DDOT')


def dt(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('EMPTY_EPOCH')
    value = text.strip()
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).timestamp()


def validated(row, kind, now):
    if not isinstance(row, dict) or any(k not in row for k in REQUIRED):
        return None
    if str(row.get('TEST_FIXTURE', row.get('test_fixture', 'false'))).lower() in ('true','1'):
        return None
    try:
        catalog = int(row['NORAD_CAT_ID'])
        if catalog < 1 or catalog > 999999999 or str(row['NORAD_CAT_ID']).strip() not in (str(catalog),):
            return None
        if kind == 'iss' and catalog != 25544:
            return None
        if kind == 'starlink' and not str(row['OBJECT_NAME']).upper().startswith('STARLINK'):
            return None
        epoch = dt(row['EPOCH'])
        if epoch > now + 300 or now-epoch > 72*3600:
            return None
        values = {}
        for key in NUMERIC:
            item = row[key]
            if item is None or (isinstance(item, str) and not item.strip()):
                return None
            x = float(item)
            if not math.isfinite(x):
                return None
            values[key] = x
        if not (0 < values['MEAN_MOTION'] <= 20 and
                0 <= values['ECCENTRICITY'] < 1 and 0 <= values['INCLINATION'] <= 180):
            return None
    except (ValueError, TypeError, OverflowError):
        return None
    return epoch, catalog


def sample(records, kind, now=None):
    if now is None:
        now = time.time()
    retained = {}
    for row in records:
        ok = validated(row, kind, now)
        if ok is None:
            continue
        epoch, catalog = ok
        prev = retained.get(catalog)
        if prev is None or epoch > prev[0]:
            retained[catalog] = (epoch, row)
    minimum = 1 if kind == 'iss' else SAMPLE_SIZE
    if kind == 'iss' and (len(retained) != 1 or 25544 not in retained):
        raise ValueError('ISS_MISSING_OR_AMBIGUOUS')
    if len(retained) < minimum:
        raise ValueError(f'NOT_ENOUGH_VALID_{kind.upper()}_OMM_{len(retained)}_OF_{minimum}')
    rows = sorted(retained.items(), key=lambda x: (-x[1][0], x[0]))[:minimum]
    # JSON is pure official row fields. No synthetic payloads or fictitious timestamps.
    return [dict(row) for _, (_, row) in rows]


def download(url, max_bytes=MAX_BYTES, timeout=65):
    if urlparse(url).hostname != 'celestrak.org':
        raise ValueError('INVALID_SOURCE_HOST')
    req = Request(url, headers={'User-Agent': 'GVSA-IQ200/AUTO-UPDATE-1.0 (research; official-OMM only)', 'Accept': 'application/json,text/csv'})
    # Prevent silent redirects to unknown domains or HTML sign-in responses.
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = build_opener(NoRedirect(), HTTPSHandler())
    try:
        with opener.open(req, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f'UPSTREAM_HTTP_{response.status}')
            if response.url != url:
                raise RuntimeError('UPSTREAM_REDIRECT_REJECTED')
            blocks=[]
            size=0
            while True:
                part=response.read(1024*256)
                if not part:
                    break
                size+=len(part)
                if size>max_bytes:
                    raise RuntimeError('UPSTREAM_PAYLOAD_TOO_LARGE')
                blocks.append(part)
            return b''.join(blocks)
    except HTTPError as exc:
        raise RuntimeError(f'UPSTREAM_HTTP_{exc.code}') from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError('UPSTREAM_NETWORK_OR_TLS_FAILURE: '+type(exc).__name__) from exc


def parse_payload(kind, payload, now):
    if len(payload)<30:
        raise ValueError('EMPTY_UPSTREAM_PAYLOAD')
    if kind == 'iss':
        raw=json.loads(payload.decode('utf-8-sig'))
        if not isinstance(raw, list):
            raise ValueError('ISS_JSON_SCHEMA')
        return sample(raw, 'iss', now)
    text = payload.decode('utf-8-sig')
    reader=csv.DictReader(io.StringIO(text, newline=''))
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError('BAD_CSV_HEADER')
    if any(name not in reader.fieldnames for name in REQUIRED):
        raise ValueError('MISSING_CSV_COLUMNS')
    if len(reader.fieldnames)>64:
        raise ValueError('OVERSIZED_CSV_HEADER')
    rows=[]
    for count, row in enumerate(reader, start=1):
        if count>35000:
            raise ValueError('EXCESSIVE_CSV_ROWS')
        if None in row:
            continue
        rows.append(row)
    return sample(rows, 'starlink', now)


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp=tempfile.mkstemp(prefix='.gvsa-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as fp:
            json.dump(data, fp, ensure_ascii=False, separators=(',', ':'))
            fp.write('\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Update real GVSA ISS and Starlink OMM snapshots locally.')
    parser.add_argument('--out',type=Path,default=Path(__file__).parent/'PUBLISH_TO_SITE')
    parser.add_argument('--kind',choices=['iss','starlink','all'],default='all')
    parser.add_argument('--self-test',action='store_true',help='Run validation tests without network or publishing')
    args=parser.parse_args(argv)
    if args.self_test:
        now=time.time()
        test={'NORAD_CAT_ID':'25544','OBJECT_NAME':'ISS (ZARYA)','EPOCH':datetime.fromtimestamp(now-3600,timezone.utc).isoformat(),
              'MEAN_MOTION':'15.5','ECCENTRICITY':'0.0001','INCLINATION':'51.6','RA_OF_ASC_NODE':'120',
              'ARG_OF_PERICENTER':'3','MEAN_ANOMALY':'200','BSTAR':'0.0001',
              'MEAN_MOTION_DOT':'0.0001','MEAN_MOTION_DDOT':'0'}
        assert len(sample([test],'iss',now))==1
        assert sample([dict(test, NORAD_CAT_ID=str(30000+i), OBJECT_NAME='STARLINK-TEST-'+str(i)) for i in range(36)],'starlink',now) and len(sample([dict(test, NORAD_CAT_ID=str(30000+i), OBJECT_NAME='STARLINK-TEST-'+str(i)) for i in range(36)],'starlink',now))==36
        assert validated(dict(test,EPOCH='2001-01-01T00:00:00Z'),'iss',now) is None
        assert validated(dict(test,BSTAR=''),'iss',now) is None
        print('LOCAL SELF-TEST PASS (mock rows never written or published)')
        return 0
    # Keep anti-repeat state outside PUBLISH_TO_SITE (never upload rate-limit state).
    work=Path(__file__).parent
    state_path=work/'.gvsa_download_state.json'
    try:state=json.loads(state_path.read_text('utf-8'))
    except (OSError,ValueError):state={}
    now=time.time()
    kinds=['iss','starlink'] if args.kind=='all' else [args.kind]
    result={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'source':'Official CelesTrak GP OMM (no simulation)', 'feeds':{}}
    failure=False
    stop_rest=False
    for kind in kinds:
        if stop_rest:
            result['feeds'][kind]={'status':'SKIPPED_AFTER_UPSTREAM_ERROR'}
            continue
        previous=float(state.get(kind,0) or 0)
        remaining=max(0,int(RETRY_SECONDS-(now-previous)))
        if remaining:
            print(f'{kind}: SKIPPED, CelesTrak cooldown {remaining} seconds. Do not retry yet.')
            result['feeds'][kind]={'status':'COOLDOWN','retry_after_seconds':remaining}
            continue
        # Persist *before* making the HTTP request: a timeout still counts.
        state[kind]=now
        write_atomic(state_path,state)
        url=ISS_URL if kind=='iss' else STAR_URL
        try:
            body=download(url)
            rows=parse_payload(kind,body,time.time())
            path=args.out/'assets'/'orbital'/('iss.json' if kind=='iss' else 'starlink-sample.json')
            write_atomic(path,rows)
            source_ages=[(time.time()-dt(row['EPOCH']))/3600 for row in rows]
            print(f'{kind}: SUCCESS, {len(rows)} original OMM elements, max epoch age {max(source_ages):.2f} h, saved to {path}')
            result['feeds'][kind]={'status':'SUCCESS','count':len(rows),'max_epoch_age_hours':round(max(source_ages),3),'relative_path':str(path.relative_to(args.out)).replace('\\','/'),'source_sha256':hashlib.sha256(body).hexdigest(),'normalized_json_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        except (ValueError,UnicodeError,RuntimeError) as exc:
            print(f'{kind}: FAILED ({exc}). Old validated snapshots, if any, were NOT overwritten.',file=sys.stderr)
            result['feeds'][kind]={'status':'FAILED','error':str(exc)}
            failure=True
            if any(str(exc).startswith(x) for x in ('UPSTREAM_HTTP_','UPSTREAM_NETWORK_OR_TLS_FAILURE')):
                stop_rest=True
                print('Remaining official requests are cancelled after an upstream failure. No retry loop.',file=sys.stderr)
    write_atomic(work/'LAST_UPDATER_REPORT.json',result)
    print('Upload only files under PUBLISH_TO_SITE/assets/orbital/ to identical website paths. Do not upload local state or report.')
    return 1 if failure else 0


if __name__=='__main__':
    sys.exit(main())
