#!/usr/bin/env python3
"""Publish official verified ISS and 36 Starlink OMM records to THIS public repo.
No host credentials, no website deployment, no fabricated EPOCH, no retry loops.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys
from time import time
from omm_source import ISS_URL, STAR_URL, download, parse_payload, dt, sample

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / 'automation' / 'state.json'
DEST = ROOT / 'orbital'
SOURCES = {'iss': (ISS_URL,'iss.json'), 'starlink': (STAR_URL,'starlink-sample.json')}
INTERVAL = 6 * 3600
ERROR_BACKOFF = 24 * 3600


def utc(ts:float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')


def safe_read(path:Path, default):
    try:
        return json.loads(path.read_text('utf-8'))
    except (ValueError, OSError):
        return default


def atomic_json(path:Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    tmp.replace(path)


def valid_existing(kind, payload):
    if not isinstance(payload,list) or len(payload)!=(1 if kind=='iss' else 36):
        return False
    try:
        # Structural comparison only. Accept older files for no-regression check.
        ids=[]
        for r in payload:
            if not isinstance(r,dict): return False
            ident=int(r['NORAD_CAT_ID']); ids.append(ident)
            epoch=dt(r['EPOCH'])
            if epoch>time()+300: return False
            if kind=='iss' and ident!=25544: return False
            if kind=='starlink' and not str(r.get('OBJECT_NAME','')).upper().startswith('STARLINK'):return False
        return len(ids)==len(set(ids))
    except (KeyError,ValueError,TypeError,OverflowError):
        return False


def incoming_is_newer(kind, rows, old):
    if not valid_existing(kind,old):
        return True
    # Compare oldest EPOCH in entire sample, not upload time.
    return min(dt(r['EPOCH']) for r in rows) > min(dt(r['EPOCH']) for r in old) + 1


def execute(now=None, downloader=download):
    now=time() if now is None else now
    state=safe_read(STATE,{'schema':'gvsa-public-orbit-1','feeds':{}})
    if state.get('schema')!='gvsa-public-orbit-1' or not isinstance(state.get('feeds'),dict):
        raise RuntimeError('INVALID_STORED_STATE')
    DEST.mkdir(exist_ok=True)
    result={'schema':'gvsa-public-orbit-1','updated_at_utc':utc(now), 'source':'CelesTrak GP (original OMM; sample of 36 Starlink objects)', 'feeds':{}}
    ordered=sorted(SOURCES.items(),key=lambda p:float(state['feeds'].get(p[0],{}).get('last_attempt_unix',0)))
    stopped=False; failed=False
    for kind,(url,filename) in ordered:
        row=state['feeds'].setdefault(kind,{})
        last=float(row.get('last_attempt_unix') or 0)
        retry=float(row.get('no_request_before_unix') or 0)
        if stopped:
            message='SKIPPED_AFTER_PROVIDER_ERROR'
        elif now<retry:
            message='PROVIDER_BACKOFF'; print(f'{kind}: {message}, until {utc(retry)}')
        elif now-last<INTERVAL:
            message='SIX_HOUR_COOLDOWN'; print(f'{kind}: {message}')
        else:
            # Mark before requesting. No requests to any other feed after an error.
            row['last_attempt_unix']=now
            row['last_attempt_utc']=utc(now)
            message='FAILED'
            try:
                # Network requests are exactly one per feed, no redirects/retries.
                data=downloader(url)
                rows=parse_payload(kind,data,now)
                old=safe_read(DEST/filename,[])
                if incoming_is_newer(kind,rows,old):
                    atomic_json(DEST/filename,rows)
                    message='PUBLISHED'
                    row['last_success_utc']=utc(now)
                    row['last_epoch_utc']=utc(min(dt(r['EPOCH']) for r in rows))
                    print(f'{kind}: PUBLISHED {len(rows)} official OMM records; oldest EPOCH '+row['last_epoch_utc'])
                else:
                    message='UNCHANGED_OLDER_OR_EQUAL_EPOCH'
                    print(f'{kind}: official response was not newer; existing data kept.')
                row.pop('last_error',None)
                row.pop('no_request_before_unix',None)
            except (RuntimeError,ValueError,UnicodeError,OverflowError,TypeError) as exc:
                message='FAILED_PROVIDER_OR_SCHEMA'
                row['last_error']=str(exc)[:200]
                row['no_request_before_unix']=now+ERROR_BACKOFF
                print(f'{kind}: ERROR: {row["last_error"]}; no further requests this run.',file=sys.stderr)
                stopped=True; failed=True
        row['status']=message
        result['feeds'][kind]={'status':message, 'last_attempt_utc':row.get('last_attempt_utc'), 'last_success_utc':row.get('last_success_utc'), 'epoch_utc':row.get('last_epoch_utc'), 'error':row.get('last_error')}
    atomic_json(STATE,state)
    # Public status is not a replacement for OMM EPOCH / scientific validation.
    atomic_json(DEST/'update-status.json',result)
    return 1 if failed else 0

if __name__=='__main__':
    sys.exit(execute())
