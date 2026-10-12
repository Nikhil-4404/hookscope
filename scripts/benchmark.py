"""Disposable capture/read benchmark; simulated records, no external deliveries."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--events',type=int,default=49000)
parser.add_argument('--requests',type=int,default=100)
parser.add_argument('--concurrency',type=int,default=10)
args=parser.parse_args()
if not 0<=args.events<49900 or not 1<=args.requests<=100 or not 1<=args.concurrency<=20:
    raise SystemExit('Use <49,900 fixture events, 1–100 requests and 1–20 concurrent clients.')

with tempfile.TemporaryDirectory(prefix='hookscope-benchmark-') as temporary:
    os.environ['HOOKSCOPE_DATA']=temporary
    os.environ['HOOKSCOPE_DISABLE_WORKER']='1'
    os.environ['HOOKSCOPE_ENV']='development'
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
    from fastapi.testclient import TestClient
    from sqlalchemy import text
    from app.main import app
    from app.store import engine
    with TestClient(app) as client:
        client.post('/api/setup',json={'password':'benchmark-fixture-password'})
        endpoint=client.post('/api/endpoints',json={'name':'Benchmark capture only'}).json()
        body=json.dumps({'type':'benchmark.fixture','data':'x'*400}).encode()
        with engine.begin() as conn:
            for first in range(0,args.events,1000):
                conn.execute(text("INSERT INTO events(id,endpoint_id,created,method,headers,body,kind,source) VALUES(:id,:endpoint,:now,'POST','{}',:body,'benchmark.fixture','test')"),
                    [{'id':'evt_bench_'+str(n),'endpoint':endpoint['id'],'now':time.time()-3600,'body':body} for n in range(first,min(first+1000,args.events))])
        def capture(n):
            start=time.perf_counter()
            response=client.post('/hooks/'+endpoint['token'],content=body,headers={'x-hookscope-idempotency-key':'bench-'+str(n)})
            if response.status_code!=202:raise RuntimeError('Capture failed: '+str(response.status_code))
            return (time.perf_counter()-start)*1000
        started=time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:latencies=list(pool.map(capture,range(args.requests)))
        elapsed=time.perf_counter()-started
        reads={}
        for route in ('/api/events','/api/stats','/api/operations'):
            times=[]
            for _ in range(5):
                start=time.perf_counter();response=client.get(route)
                if response.status_code!=200:raise RuntimeError('Read failed.')
                times.append((time.perf_counter()-start)*1000)
            reads[route]=round(max(times),2)
        result={'fixture_events':args.events,'new_captures':args.requests,'concurrency':args.concurrency,
                'capture_p50_ms':round(statistics.median(latencies),2),'capture_p95_ms':round(sorted(latencies)[int(len(latencies)*.95)-1],2),
                'capture_max_ms':round(max(latencies),2),'captures_per_second':round(args.requests/elapsed,2),
                'read_max_ms':reads,'limitations':'In-process TestClient, one workspace, synthetic records; excludes network, TLS, delivery, other tenants and cloud hardware.'}
        print(json.dumps(result,indent=2))
    engine.dispose()
