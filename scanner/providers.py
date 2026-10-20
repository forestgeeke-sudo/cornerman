"""Complementary official calendars. Parsers fail visibly when contracts change.

Fight Pass uses exactly its public web client's guest access (no user account).
The public client key is discovered each run, never stored; guest tokens stay in
memory. Entitlements are accepted only for an observed US guest market.
"""
import base64
import html
import json
import re
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urljoin, urlencode
from zoneinfo import ZoneInfo

import sources
from htmltree import document
from model import new_event, segment, stamp, instant, identity

UFC_INDEX = 'https://www.ufc.com/events'
FP_SITE = 'https://ufcfightpass.com'
FP_API = 'https://dce-frontoffice.imggaming.com/api/v2'


def platform(name, access='subscription', url=None):
    p = sources.resolve(name)
    p['access'] = 'ppv' if p['kind'] == 'ppv' else access
    if url:
        p['url'] = url
    return p


def bounded(events, now, end):
    return [e for e in events if now.date().isoformat() <= e['date'][:10] <= end.date().isoformat()]


def ufc_links(page):
    tree = document(page)
    sections = tree.find(id='events-list-upcoming')
    if not sections:
        raise ValueError('UFC upcoming calendar section missing')
    links = {urljoin(UFC_INDEX, a.attrs.get('href', '')) for a in sections[0].find('a')
             if a.attrs.get('href', '').startswith('/event/')}
    if not links:
        raise ValueError('UFC calendar has no event links')
    return sorted(links)


def parse_ufc(page, url, now):
    tree = document(page)
    containers = tree.find(cls='c-event-fight-card-broadcaster__container') + tree.find(cls='c-listing-viewing-option')
    if not containers:
        raise ValueError('UFC broadcast containers missing (not an event page)')
    h1 = tree.find('h1')
    name = h1[0].text if h1 else url.rsplit('/', 1)[-1].replace('-', ' ')
    segments = []
    names = {'Early Prelims':'Early prelims', 'Prelims':'Prelims', 'Main Card':'Main card'}
    for box in containers:
        labels = box.find(cls='c-event-fight-card-broadcaster__card-title') or box.find(cls='c-listing-viewing-option__fight-card')
        if not labels or labels[0].text not in names:
            continue
        label = names[labels[0].text]
        timed = box.find(cls='c-event-fight-card-broadcaster__time') or box.find(cls='c-listing-viewing-option__time')
        # The <time datetime=...Z> contains local Eastern wall time on UFC pages;
        # data-timestamp is the actual Unix instant. Never use the misleading Z.
        ts = timed[0].attrs.get('data-timestamp') if timed else None
        start = stamp(datetime.fromtimestamp(int(ts), timezone.utc)) if ts and ts.isdigit() else None
        watch = {}
        for a in box.find('a'):
            imgs = a.find('img')
            text = a.text or (imgs[0].attrs.get('alt', '') if imgs else '')
            text = re.sub(r'^watch\s+(?:on\s+)?', '', text, flags=re.I).strip()
            if text:
                p = platform(text, 'ppv' if re.search(r'\bppv\b|pay.per.view', text, re.I) else 'subscription', a.attrs.get('href'))
                if p['name'] not in ('Paramount+', 'UFC Fight Pass') and p['kind'] != 'ppv':
                    p['access'] = 'paid'
                watch[p['name']] = p
        segments.append(segment(label, start, list(watch.values()), url, now))
    if not segments:
        raise ValueError('UFC page has no recognized broadcast segments')
    # A published list of all event-page card sections defines this card's scope.
    # Missing field within any section stays explicitly unconfirmed.
    segments = list({s['name']:s for s in segments}.values())
    starts = [s['start'] for s in segments if s['start']]
    if not starts:
        raise ValueError('UFC page has no verifiable event date')
    day = min(starts)[:10]
    e = new_event(name, 'UFC', day, url)
    e.update(segments=segments, coverageComplete=True,
             tier='numbered' if re.search(r'\bufc\s+\d+', name, re.I) else 'fight_night')
    return e


def scan_ufc(fetch, now, end):
    out = []
    failures = []
    for url in ufc_links(fetch(UFC_INDEX)):
        try:
            out += bounded([parse_ufc(fetch(url), url, now)], now, end)
        except Exception as error:
            failures.append(f'{url}: {type(error).__name__}')
    if failures:
        # Partial event failures must not silently delete the prior observations.
        raise PartialProviderError(out, failures)
    return out


class PartialProviderError(Exception):
    def __init__(self, events, failures):
        self.events, self.failures = events, failures
        super().__init__('; '.join(failures))


def request_json(url, headers, data=None):
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_fightpass(fetch, now, end):
    page = fetch(FP_SITE + '/upcoming')
    scripts = document(page).find('script')
    app = next((s.attrs.get('src') for s in scripts if '/code/js/app.' in s.attrs.get('src', '')), None)
    if not app:
        raise ValueError('Fight Pass client bundle missing')
    js = fetch(urljoin(FP_SITE, app))
    key = re.search(r'API_KEY:"([^"\s]+)"', js)
    if not key:
        raise ValueError('Fight Pass public client key contract changed')
    headers = {'x-api-key': key[1], 'Realm':'dce.ufc', 'Content-Type':'application/json',
               'Accept-Language':'en-US', 'User-Agent':'Cornerman/2.0'}
    auth = request_json(FP_API+'/login/guest/checkin', headers, b'null')
    token = auth['authorisationToken']
    payload = token.split('.')[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + '='*(-len(payload)%4)))
    # lo2 is the server's geolocated market. Do not spoof country/IP headers.
    market = str(claims.get('lo2', '')).split(',')[0]
    if market != 'US':
        raise ValueError(f'Fight Pass guest market {market or "unknown"}; US rights not verifiable on this runner')
    headers['Authorization'] = 'Bearer '+token
    entries = []
    for p in range(1, 31):
        data = request_json(FP_API+'/event/upcoming?'+urlencode({'rpp':12,'p':p}), headers)
        if data.get('page') != p or not isinstance(data.get('events'), list):
            raise ValueError('Fight Pass pagination contract changed')
        entries.extend(data['events'])
        if p >= data['totalPages']:
            break
    else:
        raise ValueError('Fight Pass schedule exceeds 30 pages; raise monitored limit')
    if not entries:
        raise ValueError('Fight Pass returned an empty live calendar')
    return bounded(parse_fightpass(entries, now), now, end)


def fp_subscription(p):
    """Only the normal Fight Pass plan, never an arbitrary premium subscription."""
    codes = ' '.join(str(p.get(k, '')) for k in ('rokuIapCode','androidIAPCode','iOSIAPCode')).lower()
    return p.get('purchaseStrategy', {}).get('type') == 'SUBSCRIPTION' and 'fightpass' in codes


def parse_fightpass(entries, now):
    out = {}
    for raw in entries:
        name = re.sub(r'^\([^)]*\)\s*|^POLYMARKET\s+', '', raw.get('title', ''), flags=re.I)
        if re.search(r'press conference|weigh.?in|on the line|countdown|preview|interview', name, re.I):
            continue  # programmes surrounding an event are not sporting events
        if raw.get('type') != 'LIVE' or not raw.get('startDate'):
            continue
        start = stamp(datetime.fromtimestamp(raw['startDate']/1000, timezone.utc))
        label = 'Live event'
        if re.search(r'fight pass prelim|early prelim', name, re.I): label = 'Early prelims'
        elif re.search(r'prelim', name, re.I): label = 'Prelims'
        elif re.search(r'main card', name, re.I): label = 'Main card'
        title = re.sub(r':\s*(?:fight pass |early )?prelim\w*.*$|:\s*main card.*$', '', name, flags=re.I)
        org, _ = sources.identify(title)
        org = org or re.sub(r'\s+\d+.*', '', title).title()
        sport = category(title)
        url = f'{FP_SITE}/live/{raw["id"]}'
        e = new_event(title, org, start, url, sport)
        plans = raw.get('availablePurchases', [])
        access = ('subscription' if any(fp_subscription(p) for p in plans)
                  else 'free' if raw.get('accessLevel') == 'GRANTED'
                  else 'ppv' if any(p.get('purchaseStrategy', {}).get('type') == 'PAY_PER_VIEW' for p in plans)
                  else 'unconfirmed')
        p = platform('UFC Fight Pass', access, url)
        if access == 'ppv': p['kind'] = 'ppv'
        e['segments'] = [segment(label, start, [p], url, now)]
        e['coverageComplete'] = label == 'Live event'
        e['location'] = raw.get('location')
        e['scheduledEnd'] = stamp(datetime.fromtimestamp(raw['endDate']/1000, timezone.utc)) if raw.get('endDate') else None
        if org == 'UFC':
            e['tier'] = 'numbered' if re.search(r'ufc\s+\d+', title, re.I) else 'other'
        key = identity(e)
        if key in out:
            previous = out[key]
            if not any(s['name'] == label and s['start'] == start for s in previous['segments']):
                previous['segments'] += e['segments']
        else:
            out[key] = e
    return list(out.values())


def category(name):
    if re.search(r'bjj|grappling|invitational|fury pro|polaris|ebi\b|cjj', name, re.I):return 'grappling'
    if re.search(r'muay thai', name, re.I):return 'muay_thai'
    if re.search(r'kickbox|glory', name, re.I):return 'kickboxing'
    if re.search(r'boxing', name, re.I):return 'boxing'
    if re.search(r'ufc|mma|warriors|cffc|fury|lfa|combat fc|tuff.n.uff|apfc|pettis|ares|wow\s+\d', name, re.I):return 'mma'
    return 'combat_sports'


def json_events(page):
    out = []
    def walk(v):
        if isinstance(v, list):
            for i in v:walk(i)
        if isinstance(v, dict):
            if any(t in ('Event','SportsEvent','BroadcastEvent') for t in ([v.get('@type')] if isinstance(v.get('@type'), str) else v.get('@type', []))):
                out.append(v)
            else:
                for i in v.values():
                    if isinstance(i, (dict,list)):walk(i)
    for script in document(page).find('script'):
        if script.attrs.get('type') == 'application/ld+json':
            walk(json.loads(''.join(c for c in script.children if isinstance(c, str))))
    return out


def parse_structured(page, org, url, now):
    result = []
    for row in json_events(page):
        start = row.get('startDate')
        if not start:continue
        offers = row.get('offers') or {}
        if isinstance(offers, list): offers = offers[0] if offers else {}
        link = row.get('url') or offers.get('url') or url
        name = html.unescape(row.get('name') or document(page).find('title')[0].text)
        # Tribe Events marks all-day listings as midnight-to-23:59:59. The
        # website's server timezone is not a real viewing start time.
        all_day = str(start)[11:19] == '00:00:00' and str(row.get('endDate', ''))[11:19] == '23:59:59'
        timed = instant(start) if not all_day else None
        e = new_event(name, org, start, link, category(name))
        if timed:e['scheduledStart'] = stamp(timed)
        status = row.get('eventStatus', '')
        if status.endswith('EventCancelled'):e['status'] = 'cancelled'
        if status.endswith('EventPostponed'):e['status'] = 'postponed'
        if status.endswith('EventRescheduled'):e['status'] = 'rescheduled'
        place = row.get('location') or {}
        if isinstance(place, dict):
            e['venue'] = place.get('name');addr = place.get('address')
            e['location'] = addr if isinstance(addr,str) else ', '.join(str(addr.get(k)) for k in ('addressLocality','addressRegion','addressCountry') if addr.get(k)) if isinstance(addr,dict) else None
        # Ticket 'offers' and site footers never establish broadcast rights.
        desc = document(html.unescape(row.get('description',''))).text
        if org == 'LFA' and re.search(r'(?:United States|\bU\.S\.).{0,60}VICE TV', desc, re.I):
            ps = [platform('VICE TV','paid')]
            if re.search(r'North America on FloCombat',desc,re.I):ps.append(platform('FloCombat','paid','https://www.flocombat.com/'))
            e['segments'] = [segment('Main card', None, ps, link, now)]
            # Explicit ET broadcast times in event-specific descriptions.
            tm = re.search(r'(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\s*(?:ET|Eastern)',desc,re.I)
            if tm:
                hour=int(tm[1])%12+(12 if tm[3].lower()=='p' else 0)
                d=datetime.fromisoformat(start[:10]).replace(hour=hour,minute=int(tm[2] or 0),tzinfo=ZoneInfo('America/New_York'))
                e['segments'][0]['start']=stamp(d)
        result.append(e)
    if not result:raise ValueError(f'{org}: structured event data missing')
    return result


def parse_cw(pages, now):
    result = []
    for row in pages:
        title = html.unescape(row.get('title',{}).get('rendered',''))
        if not re.match(r'^CW (?:\d+|Amateur Academy)', title):continue
        if re.search(r'sign.up|pre.sale',title,re.I):continue
        content = html.unescape(row['content']['rendered'])
        content = re.sub(r'\[/?et_pb[^]]*\]', '', content)
        text = document(content).text
        m=re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})',text,re.I)
        if not m:continue
        day = datetime.strptime(f'{m[1]} {m[2]} {m[3]}','%B %d %Y').date().isoformat()
        e = new_event(title, 'Cage Warriors', day, row['link'])
        # Only event content's CTA (not a site-wide partnership/footer).
        if re.search(r'WATCH (?:ON )?UFC FIGHT PASS', text, re.I):
            e['segments'] = [segment('Live event',None,[platform('UFC Fight Pass')],row['link'],now)]
            e['coverageComplete'] = True
        result.append(e)
    if not result:raise ValueError('Cage Warriors REST returned no dated event pages')
    return result


def parse_fury(page, now):
    """Wix sections: event headings, local CT broadcast text, labelled links."""
    tree = document(page)
    # Each event is a distinct Wix section; pairing at this level prevents
    # YouTube links from a footer or a different card becoming evidence.
    result = []
    for section in tree.find('section'):
        headings = section.find('h4')
        names = [h.text for h in headings if re.match(r'^FURY\s',h.text)]
        if len(names)!=1:continue
        text = section.text
        date = re.search(r'(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+(\d{1,2})\s+(20\d{2})',text,re.I)
        if not date:continue
        day=datetime.strptime(' '.join(date.groups()),'%B %d %Y').date().isoformat()
        e=new_event(names[0], 'Fury Fighting Championship',day,'https://www.furyfc.tv/events')
        for label, key in [('Prelims','PRELIMS'),('Main card','MAIN CARD')]:
            tm=re.search(key+r':\s*.*?(\d{1,2}):(\d{2})\s*([ap])m\s*CT',text,re.I)
            if not tm:continue
            d=datetime.fromisoformat(day).replace(hour=int(tm[1])%12+(12 if tm[3].lower()=='p' else 0),minute=int(tm[2]),tzinfo=ZoneInfo('America/Chicago'))
            anchors=[a for a in section.find('a') if re.search('WATCH '+('PRELIMS' if label=='Prelims' else '(?:MAIN CARD|FIGHT CARD)'),a.text,re.I)]
            ps=[]
            for a in anchors:
                href=a.attrs.get('href','')
                if 'ufcfightpass.com' in href:ps.append(platform('UFC Fight Pass',url=href))
                if re.search(r'youtube\.com/watch|youtu\.be/',href):ps.append(platform('YouTube','free',href))
                if 'onlyfans.com' in href:ps.append(platform('OnlyFans','unconfirmed',href))
                if 'clearlife.live' in href:ps.append(platform('Clear Life','unconfirmed',href))
            e['segments'].append(segment(label,stamp(d),ps,e['link'],now))
        e['coverageComplete'] = any(s['name']=='Main card' for s in e['segments'])
        result.append(e)
    if not result:raise ValueError('Fury event sections/dated headings missing')
    return result


def fetch_cw(fetch, now, end):
    index_url='https://cagewarriors.com/wp-json/wp/v2/pages/9707'
    index = json.loads(fetch(index_url))
    content=html.unescape(index['content']['rendered'])
    content=re.sub(r'\[/?et_pb[^]]*\]', '', content)
    tree=document(content)
    # The calendar exposes separate h2 headings followed by date, venue and
    # event description. Split before the next heading or partnership footer.
    text=tree.text.split('WATCH US ON UFC FIGHT PASS')[0]
    starts=list(re.finditer(r'\bCW (?:\d+|Amateur Academy \d+)',text))
    links=sorted(set(re.findall(r'https://cagewarriors.com/cw-[\w-]+/',index['content']['rendered'])))
    if not starts:raise ValueError('Cage Warriors dated calendar rows missing')
    result=[]
    for i,m in enumerate(starts):
        chunk=text[m.start():starts[i+1].start() if i+1<len(starts) else None]
        date=re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})',chunk,re.I)
        if not date:continue
        day=datetime.strptime(' '.join(date.groups()),'%B %d %Y').date().isoformat()
        title=chunk.split('')[0].strip()
        number=re.search(r'CW (\d+)',title)
        link=next((l for l in links if number and '/cw-'+number[1]+'-' in l), 'https://cagewarriors.com/cage-warriors-events/')
        e=new_event(title,'Cage Warriors',day,link)
        if re.search(r'Available to watch exclusively on UFC Fight Pass',chunk,re.I):
            e['segments']=[segment('Live event',None,[platform('UFC Fight Pass')],index_url,now)]
            e['coverageComplete']=True
        result.append(e)
    if not result:raise ValueError('Cage Warriors calendar contains no dates')
    return bounded(result,now,end)


def parse_cffc_product(page, url, now):
    tree=document(page)
    blocks=tree.find(cls='ProductItem-details-excerpt')
    if not blocks:raise ValueError('CFFC product event description missing')
    text=blocks[0].text
    date=re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})',text,re.I)
    title=tree.find('h1',cls='ProductItem-details-title')
    if not date or not title:raise ValueError('CFFC event title/date missing')
    day=datetime.strptime(' '.join(date.groups()),'%B %d %Y').date().isoformat()
    e=new_event(re.sub(r'\s+Tickets$','',title[0].text,flags=re.I),'CFFC',day,url,category(title[0].text))
    for label,key in [('Prelims',r'FIRST BELL\s*\(PRELIMS\)'),('Main card','MAIN CARD')]:
        tm=re.search(key+r'\s*:?\s*(\d{1,2}):(\d{2})\s*([ap])m\s*ET',text,re.I)
        if not tm:continue
        d=datetime.fromisoformat(day).replace(hour=int(tm[1])%12+(12 if tm[3].lower()=='p' else 0),minute=int(tm[2]),tzinfo=ZoneInfo('America/New_York'))
        # Ticket first bell is a venue schedule, not evidence of a stream.
        if label=='Prelims':e['scheduledStart']=stamp(d)
        s=segment(label,None,[],url,now)
        s['scheduledStart']=stamp(d)
        e['segments'].append(s)
    return e


def fetch_cffc(fetch,now,end):
    url='https://cffc.tv/tickets'
    tree=document(fetch(url))
    links=[urljoin(url,a.attrs['href']) for a in tree.find('a',cls='ProductList-item-link')]
    if not links:raise ValueError('CFFC ticket calendar links missing')
    # Sorted newest first by official shop. Stop after six past entries;
    # bounded to avoid crawling the shop's multi-year archive every six hours.
    result,failures=[],[]
    past=0
    for link in links[:16]:
        try:
            e=parse_cffc_product(fetch(link),link,now)
            if e['eventDay']<now.date().isoformat():
                past+=1
                if past>=3:break
            result.extend(bounded([e],now,end))
        except Exception:failures.append(link)
    if failures:raise PartialProviderError(result,failures)
    return result


def parse_bfl(page,now):
    tree=document(page)
    main=tree.find('main') or [tree]
    text=main[0].text
    # Upcoming calendar text explicitly advertises this dated event on FP.
    title=re.search(r'\bBFL\s*(\d+)\s+Tickets',text,re.I)
    date=re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})',text,re.I)
    if not title or not date:raise ValueError('BFL upcoming event/date contract missing')
    day=datetime.strptime(' '.join(date.groups()),'%B %d %Y').date().isoformat()
    url='https://battlefieldfl.com/bfl-event-type/upcoming-events/'
    e=new_event('BFL '+title[1],'Battlefield Fight League',day,url)
    if re.search(r'MAIN CARD LIVE ON UFC FIGHT PASS',text,re.I):
        e['segments']=[segment('Main card',None,[platform('UFC Fight Pass')],url,now)]
    return [e]


def parse_bjj(page,now):
    tree=document(page)
    result=[]
    # UFC Experience cards include nonbroadcast local open tournaments too.
    # Keep only numbered UFC BJJ televised cards, never registration events.
    # Date-bearing cards have their own heading; selecting their immediate
    # containers is safer than reading the hero's date as every card's start.
    for m in re.finditer(r'<time datetime="(20\d{2}-\d{2}-\d{2})T[^"<]+">',page):
        tail=page[m.end():m.end()+4500]
        next_time=tail.find('<time ')
        if next_time>=0:tail=tail[:next_time]
        title=re.search(r'\bUFC BJJ\s+(\d+)\b',document(tail).text)
        if title:
            name='UFC BJJ '+title[1]
            result.append(new_event(name,'UFC BJJ',m[1],'https://www.ufc.com/ufcbjj','grappling'))
    if not result:raise ValueError('UFC BJJ numbered calendar cards missing')
    return result


def parse_lux(page,url,now):
    tree=document(page)
    headings=tree.find('h1')+tree.find('h3')
    name=next((h.text for h in headings if re.search(r'LUX\s*\d+',h.text,re.I)),None)
    timers=tree.find(cls='elementor-countdown-wrapper')
    if not name or not timers or not timers[0].attrs.get('data-date','').isdigit():
        raise ValueError('Lux event title/countdown date missing')
    d=datetime.fromtimestamp(int(timers[0].attrs['data-date']),timezone.utc)
    day=d.astimezone(ZoneInfo('America/Monterrey')).date().isoformat()
    e=new_event(name,'Lux Fight League',day,url)
    # Countdown is an event schedule, not a verified stream or individual fight.
    e['scheduledStart']=stamp(d)
    return e


def fetch_lux(fetch,now,end):
    url='https://luxfightleague.com/eventos/'
    tree=document(fetch(url))
    links=sorted({a.attrs['href'] for a in tree.find('a') if re.search(r'/eventos/lux-\d+',a.attrs.get('href',''))})
    if not links:raise ValueError('Lux calendar event links missing')
    out,failures=[],[]
    for link in links[:12]:
        try:out.extend(bounded([parse_lux(fetch(link),link,now)],now,end))
        except Exception:failures.append(link)
    if failures:raise PartialProviderError(out,failures)
    return out
