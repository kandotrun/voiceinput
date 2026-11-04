import sys,json,time,os,statistics,urllib.request,uuid,argparse
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
def post(path,correct=True):
 env=dict(l.split('=',1) for l in (BASE/'.env').read_text().splitlines() if '=' in l and not l.startswith('#'))
 boundary=uuid.uuid4().hex
 body=b''
 for k,v in [('language','ja'),('correct','true' if correct else 'false')]:
  body+=f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
 body+=f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()+Path(path).read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
 req=urllib.request.Request('http://100.72.208.31:8791/transcribe',data=body,headers={'Authorization':'Bearer '+env['TRANSCRIBE_TOKEN'].strip(),'Content-Type':'multipart/form-data; boundary='+boundary})
 t=time.monotonic()
 with urllib.request.urlopen(req,timeout=600) as r: result=json.load(r)
 result['wall_s']=round(time.monotonic()-t,3)
 return result

parser=argparse.ArgumentParser()
parser.add_argument('--audio-dir',type=Path,default=BASE/'logs/v21-audio')
args=parser.parse_args()

ENV=BASE/'.env'
def set_mode(mode):
 lines=[l for l in ENV.read_text().splitlines() if not l.startswith('HINDSIGHT_MODE=')]
 tmp=ENV.with_name('.env.bench-tmp')
 tmp.write_text('\n'.join(lines)+'\nHINDSIGHT_MODE='+mode+'\n');tmp.chmod(0o600);os.replace(tmp,ENV)
results=[]
try:
 for repeat,modes in [(1,['off','live','cache']),(2,['cache','live','off'])]:
  for mode in modes:
   set_mode(mode)
   for duration in [5,15]:
    r=post(args.audio_dir/f'voiceinput-v2-{duration}.wav')
    assert r['hindsight']['mode']==mode
    results.append({'repeat':repeat,'mode':mode,'duration':duration,**r})
    print(json.dumps(results[-1],ensure_ascii=False),flush=True)
 for mode in ['off','live','cache']:
  set_mode(mode)
  r=post(args.audio_dir/'voiceinput-v2-mapbox.wav')
  results.append({'mode':mode,'test':'Mapbox',**r})
  print(json.dumps(results[-1],ensure_ascii=False),flush=True)
finally:
 set_mode('cache')
 target=BASE/'logs/v21-bench.json';target.write_text(json.dumps(results,ensure_ascii=False,indent=2));target.chmod(0o600)
for duration in [5,15]:
 for mode in ['off','live','cache']:
  items=[r for r in results if r.get('duration')==duration and r['mode']==mode]
  print('MEAN',duration,mode,round(statistics.mean(r['wall_s'] for r in items),3),flush=True)
