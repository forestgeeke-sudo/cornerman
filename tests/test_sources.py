import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scanner'))
import providers
from model import access,identity,merge_events,new_event,segment,stamp
from health import ProviderCache

FIX=Path(__file__).parent/'fixtures'
NOW=datetime(2026,10,20,12,tzinfo=timezone.utc)
class SourceTests(unittest.TestCase):
    def ufc(self,f='ufc333'):
        return providers.parse_ufc((FIX/(f+'.html')).read_text(),'https://www.ufc.com/event/'+f,NOW)
    def test_real_ufc333_early_prelims_and_main_are_distinct(self):
        e=access(self.ufc(),NOW)
        self.assertEqual(e['earliestBroadcastStart'],'2026-10-24T14:00:00Z')
        self.assertEqual(e['mainCardStart'],'2026-10-24T18:00:00Z')
        self.assertEqual(e['availability'],'included')
        segs={s['name']:s for s in e['segments']}
        self.assertEqual(segs['Prelims']['start'],'2026-10-24T16:00:00Z')
        self.assertEqual({p['name'] for p in segs['Early prelims']['platforms']},{'Paramount+','UFC Fight Pass'})
        self.assertEqual({p['name'] for p in segs['Main card']['platforms']},{'Paramount+'})
    def test_future_ufc_alternate_watch_container_and_dst(self):
        e=access(self.ufc('ufc335'),NOW)
        self.assertEqual(len(e['segments']),3)
        self.assertEqual(e['mainCardStart'],'2026-12-13T02:00:00Z')
        e=access(self.ufc('ufc336'),NOW)
        self.assertEqual(len(e['segments']),2)
        self.assertEqual(e['availability'],'included')
    def test_no_timestamp_does_not_parse_false_local_Z_attribute(self):
        page=(FIX/'ufc333.html').read_text()
        import re
        page=re.sub(r'data-timestamp="\d+"','',page)
        with self.assertRaises(ValueError):providers.parse_ufc(page,'https://www.ufc.com/event/test',NOW)
    def test_fightpass_real_regional_events_and_no_auxiliary_programmes(self):
        es=providers.parse_fightpass(json.loads((FIX/'fightpass.json').read_text()),NOW)
        titles=[e['name'] for e in es]
        self.assertIn('SAMOURAI MMA 22',titles)
        self.assertIn('UAE WARRIORS 74',titles)
        self.assertIn('UFC BJJ 13',titles)
        self.assertEqual(titles.count('UFC 333'),1)
        self.assertFalse(any('PRESS CONFERENCE' in n or 'ON THE LINE' in n for n in titles))
        self.assertEqual(len([e for e in es if e['name']=='INKA MMA 62']),1)
    def test_fury_real_prelims_onlyfans_not_assumed_youtube(self):
        es=providers.parse_fury((FIX/'fury.html').read_text(),NOW)
        e=access(es[1],NOW)
        self.assertEqual(e['availability'],'partial')
        self.assertEqual(e['segments'][0]['platforms'][0]['name'],'OnlyFans')
        self.assertFalse(any(p['name']=='YouTube' for seg in e['segments'] for p in seg['platforms']))
    def test_youtube_link_must_belong_to_event_section(self):
        page=(FIX/'fury.html').read_text()+'<footer><a href="https://youtube.com/watch?v=unrelated">WATCH PRELIMS</a></footer>'
        es=providers.parse_fury(page,NOW)
        self.assertFalse(any(p['name']=='YouTube' for e in es for seg in e['segments'] for p in seg['platforms']))
        page=page.replace('https://onlyfans.com/furyfighting','https://youtube.com/watch?v=event-prelims')
        es=providers.parse_fury(page,NOW)
        self.assertEqual(es[1]['segments'][0]['platforms'][0]['name'],'YouTube')
        self.assertEqual(access(es[1],NOW)['availability'],'partial')
        self.assertFalse(es[1]['segments'][0]['platforms'][0].get('access')=='free')
        es=providers.parse_fury(page.replace('WATCH PRELIMS','WATCH FREE PRELIMS'),NOW)
        self.assertEqual(es[1]['segments'][0]['platforms'][0]['access'],'free')
    def test_cw_calendar_is_scoped_before_partnership_footer(self):
        fixture=(FIX/'cw-calendar.json').read_text()
        es=providers.fetch_cw(lambda url:fixture,NOW,NOW+timedelta(days=180))
        self.assertEqual(len(es),6)
        self.assertEqual(sum(bool(e['segments']) for e in es),1)
        self.assertTrue(any('214' in e['name'] and e['segments'] for e in es))
    def test_same_segment_multiple_event_specific_services_keep_provenance(self):
        a=self.ufc();b=self.ufc()
        s=a['segments'][0]
        s['platforms']=[providers.platform('UFC Fight Pass')]
        s['verifiedAt']=stamp(NOW-timedelta(days=4))
        e=merge_events([a,b],NOW)[0]
        p=next(p for p in e['segments'][0]['platforms'] if p['name']=='UFC Fight Pass')
        self.assertFalse(p['confirmed'])
    def test_ppv_and_premium_subscription_never_included(self):
        row=json.loads((FIX/'fightpass.json').read_text())[1]
        row['availablePurchases']=[{'purchaseStrategy':{'type':'PAY_PER_VIEW'},'name':'PPV'}]
        e=access(providers.parse_fightpass([row],NOW)[0],NOW)
        self.assertEqual(e['availability'],'other_service')
        self.assertFalse(e['segments'][0]['covered'])
        row['availablePurchases']=[{'purchaseStrategy':{'type':'SUBSCRIPTION'},'rokuIapCode':'premium.different.package'}]
        e=access(providers.parse_fightpass([row],NOW)[0],NOW)
        self.assertEqual(e['availability'],'unconfirmed')
    def test_full_partial_free_and_unknown(self):
        e=new_event('Test card','Test','2026-10-24','https://example.com')
        e['segments']=[segment('Prelims',None,[providers.platform('YouTube','free','https://youtube.com/watch?v=test')],e['link'],NOW),segment('Main card',None,[],e['link'],NOW)]
        e['coverageComplete']=True
        self.assertEqual(access(e,NOW)['availability'],'partial')
        e['segments'].pop()
        self.assertEqual(access(e,NOW)['availability'],'free')
        e['segments'][0]['platforms']=[]
        self.assertEqual(access(e,NOW)['availability'],'unconfirmed')
    def test_partnership_is_not_event_evidence(self):
        import sources
        self.assertEqual(sources.identify('LFA 244')[1],[])
        e=providers.parse_structured((FIX/'eternal.html').read_text(),'Eternal MMA','https://eternalmma.com/events/',NOW)[0]
        self.assertEqual(access(e,NOW)['availability'],'unconfirmed')
    def test_lfa_current_us_vice_and_all_day_midnight(self):
        es=providers.parse_structured((FIX/'lfa.html').read_text(),'LFA','https://www.lfa.com/events/',NOW)
        e=access(es[0],NOW)
        self.assertEqual(e['availability'],'other_service')
        self.assertEqual(e['datePrecision'],'day')
        self.assertIsNone(e['earliestBroadcastStart'])
        e=access(es[1],NOW)
        self.assertEqual(e['earliestBroadcastStart'],'2026-10-31T01:00:00Z')
    def test_bjj_duplicate_day_shift_and_ufc_bouts_preserved(self):
        a=new_event('UFC BJJ 13','UFC BJJ','2026-10-29','https://ufc.com/ufcbjj')
        b=new_event('UFC BJJ 13','UFC BJJ','2026-10-30','https://ufcfightpass.com/live/1')
        self.assertEqual(len(merge_events([a,b],NOW)),1)
        a=new_event('UFC 333: Volkanovski vs Evloev','UFC','2026-10-24','https://espn.com')
        a['id']='ufc-legacy';a['card']=[{'fighters':['A','B']}];a['art']=[{'url':'https://art'}]
        e=merge_events([a,self.ufc()],NOW)[0]
        self.assertEqual(e['id'],'ufc-legacy');self.assertEqual(e['card'],a['card']);self.assertEqual(e['art'],a['art'])
    def test_rights_stale_independent_of_cache_expiry(self):
        e=access(self.ufc(),NOW+timedelta(days=4))
        self.assertEqual(e['availability'],'unconfirmed')
        self.assertIsNone(e['earliestBroadcastStart'])
    def test_cancelled_and_postponed_not_upcoming(self):
        a=self.ufc();a['status']='cancelled'
        self.assertEqual(merge_events([a],NOW),[])
        a['status']='postponed';self.assertEqual(merge_events([a],NOW),[])
    def test_cross_provider_explicit_cancellation_wins_over_calendar(self):
        a=self.ufc();a['status']='cancelled'
        self.assertEqual(merge_events([a,self.ufc()],NOW),[])
        b=self.ufc();b['status']='rescheduled'
        self.assertEqual(len(merge_events([a,b],NOW)),1)
    def test_unnumbered_reschedule_keeps_one_stable_publisher_id(self):
        a=new_event('Regional Showcase','Regional','2026-10-24','https://official.test/event/123')
        b=new_event('Regional Showcase','Regional','2026-10-31','https://official.test/event/123')
        es=merge_events([a,b],NOW)
        self.assertEqual(len(es),1);self.assertEqual(es[0]['eventDay'],'2026-10-31')
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'p.json';c=ProviderCache(path,NOW)
            c.run('official','url',lambda:[a]);c.save()
            c=ProviderCache(path,NOW+timedelta(hours=1))
            es=c.run('official','url',lambda:[b])
            self.assertEqual(len(es),1);self.assertEqual(es[0]['eventDay'],'2026-10-31')
    def test_provider_failure_preserves_then_expires(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'providers.json'
            c=ProviderCache(path,NOW);es=c.run('ufc','https://ufc.com',lambda:[self.ufc()]);c.save()
            def broken():raise ValueError('layout changed')
            c=ProviderCache(path,NOW+timedelta(days=2));self.assertEqual(len(c.run('ufc','https://ufc.com',broken)),1)
            self.assertEqual(c.diagnostics[0]['status'],'failed')
            c=ProviderCache(path,NOW+timedelta(days=8));self.assertEqual(c.run('ufc','https://ufc.com',broken),[])
    def test_successful_missing_listing_has_bounded_retention(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'providers.json';c=ProviderCache(path,NOW)
            c.run('ufc','url',lambda:[self.ufc()]);c.save()
            c=ProviderCache(path,NOW+timedelta(hours=49));self.assertEqual(c.run('ufc','url',lambda:[]),[])
    def test_partial_provider_keeps_observations_and_failure_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            c=ProviderCache(Path(d)/'p.json',NOW)
            def partial():raise providers.PartialProviderError([self.ufc()],['other page failed'])
            self.assertEqual(len(c.run('ufc','url',partial)),1)
            self.assertEqual(c.diagnostics[0]['status'],'degraded')

if __name__=='__main__':unittest.main()
