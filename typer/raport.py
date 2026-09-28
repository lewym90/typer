"""Raport przedmeczowy: kontuzje, zawieszenia, kluczowi zawodnicy, ryzyko rotacji (API-Football, darmowy plan)
oraz najnowsze nagłówki (Google News RSS). Wszystko opcjonalne – bez klucza działa tylko część z nagłówkami."""
import os, re, difflib, unicodedata, requests, xml.etree.ElementTree as ET
import pandas as pd
from urllib.parse import quote

KLUCZ = os.environ.get('API_FOOTBALL_KEY', '')
URL = 'https://v3.football.api-sports.io'
PUCHARY = ('champions', 'europa', 'conference', 'cup', 'coupe', 'copa', 'coppa', 'pokal', 'beker', 'taça', 'taca', 'puchar', 'super')
licznik = {'zapytania': 0}
bledy = []   # błędy API-Football (np. brak dostępu do sezonu w darmowym planie) – widoczne w aplikacji

def _nrm(s):
    s = unicodedata.normalize('NFKD', str(s).replace('ø', 'o').replace('ł', 'l')).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\b(fc|cf|afc|sc|ac|fk|sk|club|de|the)\b', ' ', s.replace('&', ' and '))
    return re.sub(r'[^a-z0-9 ]', ' ', re.sub(r'\s+', ' ', s)).strip()

def _api(sciezka, **p):
    if not KLUCZ or licznik['zapytania'] >= 95: return None
    try:
        r = requests.get(f'{URL}/{sciezka}', params=p, headers={'x-apisports-key': KLUCZ}, timeout=30); licznik['zapytania'] += 1
        j = r.json()
        if j.get('errors'):
            print('API-Football:', sciezka, j['errors']); bledy.append(f"{sciezka}: {j['errors']}"); return None
        return j.get('response', [])
    except Exception as e:
        print('API-Football błąd:', e); bledy.append(f'{sciezka}: {e}'); return None

_mecze_dnia, _strzelcy = {}, {}
def _znajdz_fixture(dom, gosc, data):
    if data not in _mecze_dnia: _mecze_dnia[data] = _api('fixtures', date=data, timezone='Europe/Warsaw') or []
    najl, wynik = 0, None
    for f in _mecze_dnia[data]:
        h, a = f['teams']['home']['name'], f['teams']['away']['name']
        s = min(difflib.SequenceMatcher(None, _nrm(dom), _nrm(h)).ratio(), difflib.SequenceMatcher(None, _nrm(gosc), _nrm(a)).ratio())
        if s > najl: najl, wynik = s, f
    return wynik if najl >= 0.6 else None

def _kluczowi(liga_id, sezon):
    k = (liga_id, sezon)
    if k not in _strzelcy:
        _strzelcy[k] = {}
        for i, p in enumerate(_api('players/topscorers', league=liga_id, season=sezon) or []):
            st = p['statistics'][0]; _strzelcy[k][p['player']['id']] = (i + 1, st['goals']['total'] or 0, st['team']['id'])
    return _strzelcy[k]

def _terminarz(team_id, fixture_id, start):
    """Mecze drużyny tuż przed i po dzisiejszym -> ryzyko rotacji / zmęczenia."""
    uwagi = []
    for par in ({'next': 3}, {'last': 2}):
        for f in _api('fixtures', team=team_id, **par) or []:
            if f['fixture']['id'] == fixture_id: continue
            d = (pd.Timestamp(f['fixture']['date']).tz_convert('Europe/Warsaw') - start).total_seconds() / 86400
            nazwa = f['league']['name']; puchar = any(w in nazwa.lower() for w in PUCHARY)
            if 0 < d <= 3.5 and puchar: uwagi.append(('rotacja', f'za {round(d)} dni gra w: {nazwa} – możliwa rotacja'))
            elif -3 <= d < 0: uwagi.append(('zmeczenie', f'grał {round(-d)} dni temu ({nazwa})'))
    return uwagi

SMIECI = re.compile(r'live ?stream|watch|tv channel|kick-?off time|vpn|free|online today|【|highlights|betting|odds|prediction|tip', re.I)

PILKA = re.compile(r'football|soccer|nations league|league|cup|coach|manager|squad|injur|line-?up|team news|match|\\bvs?\\b|goal|striker|keeper|defender|midfield|fixture|trener|kadra|mecz|reprezentac|piłk|pilk|gol|skład|sklad|kontuzj|liga', re.I)

def _tytul_ok(tytul, druzyny):
    """Odrzuca nagłówki niezwiązane z meczem (np. wiadomości o kraju) i spam o transmisjach."""
    if not tytul or SMIECI.search(tytul): return False
    t = _nrm(tytul); slowa = set(t.split())
    trafione = [d for d in druzyny if any(s in slowa for s in _nrm(d).split() if len(s) >= 4)]
    if len(trafione) >= 2: return True
    return bool(trafione) and bool(PILKA.search(tytul))

def _rss(q, polski):
    url = (f'https://news.google.com/rss/search?q={quote(q)}&hl=pl&gl=PL&ceid=PL:pl' if polski
           else f'https://news.google.com/rss/search?q={quote(q)}&hl=en-GB&gl=GB&ceid=GB:en')
    root = ET.fromstring(requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'}).content)
    return [dict(tytul=it.findtext('title'), link=it.findtext('link'), data=(it.findtext('pubDate') or '')[:16], zrodlo=it.findtext('source') or '')
            for it in root.iter('item')]

def naglowki(druzyna, polski=False, ile=3, rywal=None):
    """Najnowsze wiadomości o drużynie (ostatnie 3 dni); najpierw te o konkretnym meczu, bez spamu i tematów spoza piłki."""
    try:
        wyniki, widziane = [], set()
        zapytania = ([f'"{druzyna}" "{rywal}" when:3d'] if rywal else []) + \
                    [f'"{druzyna}" when:3d' if polski else f'"{druzyna}" (football OR soccer) when:3d']
        for q in zapytania:
            for x in _rss(q, polski):
                if x['tytul'] in widziane or not _tytul_ok(x['tytul'], [druzyna] + ([rywal] if rywal else [])): continue
                widziane.add(x['tytul']); wyniki.append(x)
                if len(wyniki) >= ile: return wyniki
        return wyniki
    except Exception as e:
        print('nagłówki:', druzyna, e); return []

def raport(dom, gosc, start, polski=False):
    """start: pd.Timestamp (Europe/Warsaw). Zwraca słownik z danymi i listą ostrzeżeń."""
    r = dict(braki={'gosp': [], 'gosc': []}, uwagi=[], ostrzezenia=[], naglowki={}, dostepne=bool(KLUCZ))
    f = _znajdz_fixture(dom, gosc, start.strftime('%Y-%m-%d')) if KLUCZ else None
    if f:
        fid, lid, sez = f['fixture']['id'], f['league']['id'], f['league']['season']
        ids = {'gosp': f['teams']['home']['id'], 'gosc': f['teams']['away']['id']}
        kluczowi = _kluczowi(lid, sez)
        for p in _api('injuries', fixture=fid) or []:
            strona = 'gosp' if p['team']['id'] == ids['gosp'] else 'gosc'
            k = kluczowi.get(p['player']['id'])
            wpis = dict(zawodnik=p['player']['name'], typ=p['player'].get('type', ''), powod=p['player'].get('reason', ''),
                        kluczowy=bool(k), gole=k[1] if k else None)
            r['braki'][strona].append(wpis)
            if k and 'missing' in wpis['typ'].lower():
                r['ostrzezenia'].append(f"brak kluczowego zawodnika: {wpis['zawodnik']} ({k[1]} goli, {k[0]}. strzelec ligi)")
        for strona in ('gosp', 'gosc'):
            for typ, opis in _terminarz(ids[strona], fid, start):
                kto = dom if strona == 'gosp' else gosc
                r['uwagi'].append(f'{kto}: {opis}')
                if typ == 'rotacja': r['ostrzezenia'].append(f'{kto}: {opis}')
        nb = sum(1 for s in r['braki'].values() for p in s if 'missing' in p['typ'].lower())
        if nb >= 4: r['ostrzezenia'].append(f'dużo braków w składach ({nb} zawodników)')
    elif KLUCZ:
        r['uwagi'].append('brak meczu w API-Football – kontuzje niedostępne')
    mecz = naglowki(dom, polski, ile=3, rywal=gosc)
    tyt = {x['tytul'] for x in mecz}
    r['naglowki'] = {'gosp': mecz, 'gosc': [x for x in naglowki(gosc, polski, ile=4) if x['tytul'] not in tyt][:2]}
    r['powazne'] = bool(r['ostrzezenia'])
    return r
