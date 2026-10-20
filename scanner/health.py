"""Per-provider last-good observations and bounded expiry. Atomic JSON files."""
import copy
import json
from datetime import timedelta
from pathlib import Path
from model import instant, stamp, identity
from providers import PartialProviderError

FAILURE_TTL = timedelta(days=7)
MISSING_TTL = timedelta(hours=48)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=1)+'\n')
    temp.replace(path)


class ProviderCache:
    def __init__(self, path, now, previous=None):
        self.path, self.now = path, now
        self.diagnostics = []
        if Path(path).exists():
            # Corrupt state must fail visibly, never silently reset provenance.
            self.data=json.loads(Path(path).read_text())
        else:
            self.data={}
            for e in (previous or {}).get('events',[]):
                provider='one' if e.get('org')=='ONE' else 'espn:'+({'UFC':'ufc','PFL':'pfl','Bellator':'bellator'}.get(e.get('org'),'other'))
                e=copy.deepcopy(e)
                e['scheduledStart']=e['date'] if e.get('datePrecision')=='time' else None
                e['eventDay']=e['date'][:10]
                e['lastSeen']=(previous or {}).get('generated', stamp(now))
                e['segments']=[]
                for p in e.get('watch',[]):p.update(confirmed=False,covered=False)
                record=self.data.setdefault(provider,{'events':[],'lastSuccess':e['lastSeen']})
                record['events'].append(e)

    def run(self, name, url, reader):
        old=self.data.get(name,{'events':[]})
        errors=[]
        try:
            fresh=reader()
            status='ok'
        except PartialProviderError as error:
            fresh=error.events;errors=error.failures;status='degraded'
        except Exception as error:
            fresh=[];status='failed'
            errors=[f'{type(error).__name__}: {error}']
        current={identity(e):e for e in fresh}
        current_ids={e['id'] for e in fresh}
        for e in fresh:
            e['sourceStale']=False
            e['lastSeen']=stamp(self.now)
            e['sources']=[{'provider':name,'url':e.get('link') or url,'verifiedAt':stamp(self.now)}]
        ttl=MISSING_TTL if status=='ok' else FAILURE_TTL
        retained=[]
        for previous in old.get('events',[]):
            if identity(previous) in current or previous['id'] in current_ids:continue
            seen=instant(previous.get('lastSeen'))
            if seen and self.now-seen <= ttl:
                e=copy.deepcopy(previous)
                e['sourceStale']=True
                retained.append(e)
        record={'events':fresh+retained,'lastAttempt':stamp(self.now),
                'lastSuccess':stamp(self.now) if status=='ok' else old.get('lastSuccess'),
                'status':status,'errors':errors}
        self.data[name]=record
        self.diagnostics.append({'provider':name,'url':url,'status':status,
                                 'found':len(fresh),'retained':len(retained),
                                 'lastSuccess':record['lastSuccess'],'errors':errors})
        print(f'  {name}: {status}, {len(fresh)} observations, {len(retained)} retained')
        return fresh+retained

    def save(self):
        write_json(self.path,self.data)
