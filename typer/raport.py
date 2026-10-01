"""Raport przedmeczowy: nieobecni zawodnicy (BSD + Big Balls; API-Football tylko w planie płatnym),
najnowsze nagłówki (Google News RSS) i – gdy jest klucz Gemini – raport AI po polsku. Wszystko opcjonalne."""
import os, re, difflib, unicodedata, requests, xml.etree.ElementTree as ET
import pandas as pd
from urllib.parse import quote
import zrodla, ai_raport
from nazwy import pl, pl_powod, pl_txt

# Darmowy plan API-Football nie obejmuje bieżącego sezonu – używamy go tylko, gdy ustawisz zmienną API_FOOTBALL_PRO=1 (plan płatny)
KLUCZ = os.environ.get('API_FOOTBALL_KEY', '') if os.environ.get('API_FOOTBALL_PRO') == '1' else ''
URL = 'https://v3.football.api-sports.io'
PUCHARY = ('champions', 'europa', 'conference', 'cup', 'coupe', 'copa', 'coppa', 'pokal', 'beker', 'taça', 'taca', 'puchar', 'super')
licznik = {'zapytania': 0}
BLOK = set()  # endpointy niedostępne w darmowym planie (bieżący sezon) – nie marnujemy na nie zapytań
bledy = []   # błędy API-Football (np. brak dostępu do sezonu w darmowym planie) – widoczne w aplikacji

def _nrm(s):
    s = unicodedata.normalize('NFKD', str(s).replace('ø', 'o').replace('ł', 'l')).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\b(fc|cf|afc|sc|ac|fk|sk|club|de|the)\b', ' ', s.replace('&', ' and '))
    return re.sub(r'[^a-z0-9 ]', ' ', re.sub(r'\s+', ' ', s)).strip()

def _api(sciezka, **p):
    if not KLUCZ or licznik['zapytania'] >= 95 or sciezka in BLOK: return None
    try:
        r = requests.get(f'{URL}/{sciezka}', params=p, headers={'x-apisports-key': KLUCZ}, timeout=30); licznik['zapytania'] += 1
        j = r.json()
        if j.get('errors'):
            print('API-Football:', sciezka, j['errors'])
            if 'plan' in str(j['errors']).lower():
                BLOK.add(sciezka)
                bledy.append(f'darmowy plan nie obejmuje bieżącego sezonu ({sciezka})')
            else: bledy.append(f"{sciezka}: {j['errors']}")
            return None
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
            st = p['statistics'][0]; _strzelcy[k][p['player']['id']] = (i + 1, st['goals']['total'] or 0, st['team']['id'], p['player']['name'])
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

SMIECI = re.compile(r'live ?stream|watch|tv channel|kick-?off time|vpn|free|online today|【|】|highlights|betting|odds|prediction|\btips?\b|'
                    r'\bu-?(?:17|19|20|21|23)\b|mu-?21|youth|women|womens|\bwsl\b|kobiet|młodzież|mlodziez|juniors?|live score|'
                    r'play-by-play|live game updates|guess the score|win the prize|quiz', re.I)
ZLE_ZRODLA = re.compile(r'\.gov|gov\.|czechinvest|heavy\.com|yeni ?şafak|sportsbook|betting', re.I)
MIESIACE = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']
MECZ_VS = re.compile(r"\b(vs\.?|v)\b|\s[–-]\s", re.I)

PILKA = re.compile(r'football|soccer|nations league|league|cup|coach|manager|squad|injur|line-?up|team news|match|\bvs?\b|goal|striker|keeper|defender|midfield|fixture|trener|kadra|mecz|reprezentac|piłk|pilk|gol|skład|sklad|kontuzj|liga', re.I)

def _tytul_ok(tytul, druzyny, zrodlo='', start=None):
    """Odrzuca spam, tematy spoza piłki (młodzież, kobiety, wypadki), artykuły o innych meczach i o innych terminach."""
    if not tytul or SMIECI.search(tytul) or ZLE_ZRODLA.search(zrodlo or '') or ZLE_ZRODLA.search(tytul): return False
    t = _nrm(tytul); slowa = set(t.split())
    trafione = [d for d in druzyny if d and any(s in slowa for s in _nrm(d).split() if len(s) >= 4)]
    if start is not None:   # np. "Kazakhstan Slovakia 16 November" przy meczu 29 września
        mies = MIESIACE[start.month - 1]
        if any(m in t for m in MIESIACE if m != mies) and re.search(r'\b\d{1,2}\b', t): return False
    if len(trafione) >= 2: return True
    if len(druzyny) >= 2 and MECZ_VS.search(tytul): return False   # "Iceland vs Estonia" przy meczu z Luksemburgiem
    return bool(trafione) and bool(PILKA.search(tytul))

def _rss(q, polski):
    url = (f'https://news.google.com/rss/search?q={quote(q)}&hl=pl&gl=PL&ceid=PL:pl' if polski
           else f'https://news.google.com/rss/search?q={quote(q)}&hl=en-GB&gl=GB&ceid=GB:en')
    root = ET.fromstring(requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'}).content)
    return [dict(tytul=it.findtext('title'), link=it.findtext('link'), data=(it.findtext('pubDate') or '')[:16], zrodlo=it.findtext('source') or '')
            for it in root.iter('item')]

def naglowki(druzyna, polski=False, ile=3, rywal=None, start=None):
    """Najnowsze wiadomości o drużynie (ostatnie 3 dni); najpierw te o konkretnym meczu, bez spamu i tematów spoza piłki."""
    try:
        wyniki, widziane = [], set()
        zapytania = ([f'"{druzyna}" "{rywal}" when:3d'] if rywal else []) + \
                    [f'"{druzyna}" when:3d' if polski else f'"{druzyna}" (football OR soccer) when:3d']
        for q in zapytania:
            for x in _rss(q, polski):
                if x['tytul'] in widziane or not _tytul_ok(x['tytul'], [druzyna] + ([rywal] if rywal else []), x['zrodlo'], start): continue
                widziane.add(x['tytul']); wyniki.append(x)
                if len(wyniki) >= ile: return wyniki
        return wyniki
    except Exception as e:
        print('nagłówki:', druzyna, e); return []

def _ostrzezenia_z_brakow(r, dom, gosc):
    """Poważne braki: 4+ pewnych nieobecnych w jednej drużynie albo ocena AI."""
    for s, kto in (('gosp', pl(dom)), ('gosc', pl(gosc))):
        pewni = [p for p in r['braki'][s] if not p.get('niepewny') and 'question' not in str(p.get('typ', '')).lower()]
        if len(pewni) >= 4: r['ostrzezenia'].append(f"{kto}: {len(pewni)} nieobecnych zawodników")
    ai = r.get('ai')
    if ai and ai.get('powazne'):
        kto = {'gosp': pl(dom), 'gosc': pl(gosc), 'oba': 'obie drużyny'}.get(ai.get('powazne_dla'), '')
        r['ostrzezenia'].append(f"poważne braki{(' – ' + kto) if kto else ''}: {ai.get('uzasadnienie') or 'wg raportu AI'}")
    r['powazne'] = bool(r['ostrzezenia'])
    r['werdykt'] = (ai or {}).get('werdykt')   # ✅ zgoda / ⚠️ ryzyko / ⛔ odradza (ocena typu przez AI)

def raport(dom, gosc, start, polski=False, sport_key=None, rozgrywki='', ai=False, typ=None, szanse=None):
    """start: pd.Timestamp (Europe/Warsaw). Zwraca słownik: braki, uwagi, ostrzeżenia, nagłówki i (opcjonalnie) raport AI."""
    r = dict(braki={'gosp': [], 'gosc': []}, uwagi=[], ostrzezenia=[], naglowki={}, dostepne=bool(KLUCZ) or zrodla.dostepne(), zrodla_brakow=[])
    # 1) nieobecni: BSD + Big Balls (darmowe)
    try:
        b, zapowiedz, bid, zr = zrodla.braki(sport_key, dom, gosc, start.strftime('%Y-%m-%d %H:%M'))
        r['braki'], r['zrodla_brakow'] = b, zr
        if bid: r['bsd'] = bid
        if zapowiedz: r['zapowiedz'] = zapowiedz
    except Exception as e:
        print('braki:', e); zapowiedz = None
    # 2) API-Football – tylko w planie płatnym (zmienna API_FOOTBALL_PRO=1)
    f = _znajdz_fixture(dom, gosc, start.strftime('%Y-%m-%d')) if KLUCZ else None
    if f:
        fid, lid, sez = f['fixture']['id'], f['league']['id'], f['league']['season']
        ids = {'gosp': f['teams']['home']['id'], 'gosc': f['teams']['away']['id']}
        r['api'] = dict(fixture=fid, liga=lid, sezon=sez, gosp=ids['gosp'], gosc=ids['gosc'])
        kluczowi = _kluczowi(lid, sez)
        for p in _api('injuries', fixture=fid) or []:
            strona = 'gosp' if p['team']['id'] == ids['gosp'] else 'gosc'
            if any(x['zawodnik'] == p['player']['name'] for x in r['braki'][strona]): continue
            k = kluczowi.get(p['player']['id'])
            r['braki'][strona].append(dict(zawodnik=p['player']['name'], typ=pl_powod(p['player'].get('type', '')), powod=pl_powod(p['player'].get('reason', '')),
                                           kluczowy=bool(k), gole=k[1] if k else None, niepewny='question' in str(p['player'].get('type', '')).lower()))
            if k and 'missing' in str(p['player'].get('type', '')).lower():
                r['ostrzezenia'].append(f"brak kluczowego zawodnika: {p['player']['name']} ({k[1]} goli, {k[0]}. strzelec ligi)")
        for strona in ('gosp', 'gosc'):
            for typ, opis in _terminarz(ids[strona], fid, start):
                kto = pl(dom) if strona == 'gosp' else pl(gosc)
                r['uwagi'].append(f'{kto}: {opis}')
                if typ == 'rotacja': r['ostrzezenia'].append(f'{kto}: {opis}')
    # 3) nagłówki
    mecz = naglowki(dom, polski, ile=3, rywal=gosc, start=start)
    tyt = {x['tytul'] for x in mecz}
    r['naglowki'] = {'gosp': mecz, 'gosc': [x for x in naglowki(gosc, polski, ile=4, start=start) if x['tytul'] not in tyt][:2]}
    # 4) raport AI po polsku (Gemini) – tylko dla meczów-kandydatów do Pewnych
    if ai:
        try:
            r['ai'] = ai_raport.raport_ai(dom, gosc, pl(dom), pl(gosc), rozgrywki, start, braki=r['braki'], zapowiedz=zapowiedz,
                                          naglowki=[x['tytul'] for v in r['naglowki'].values() for x in v], polski=polski, typ=typ, szanse=szanse)
        except Exception as e: print('raport AI:', e)
    _ostrzezenia_z_brakow(r, dom, gosc)
    return r

def odswiez_ai(r, m, polski=False):
    """Ponowny raport AI ok. 2 h przed meczem. Zwraca True, gdy przyniósł coś istotnie nowego."""
    start = pd.Timestamp(m['start'])
    try: b, zapowiedz, bid, zr = zrodla.braki(m.get('sport_key'), m['gospodarz'], m['gosc'], m['start'])
    except Exception: b, zapowiedz, zr = r.get('braki'), r.get('zapowiedz'), r.get('zrodla_brakow')
    nowy = ai_raport.raport_ai(m['gospodarz'], m['gosc'], pl(m['gospodarz']), pl(m['gosc']), m.get('liga', ''), start, braki=b,
                               zapowiedz=zapowiedz, naglowki=[x['tytul'] for v in (r.get('naglowki') or {}).values() for x in v], polski=polski,
                               typ=(pl_txt(m['zaklad'], m['gospodarz'], m['gosc']), m['szansa']) if m.get('zaklad') and m.get('szansa') else None,
                               szanse=m.get('szanse'), wymus=True)
    if not nowy: return False
    istotna = ai_raport.zmiana_istotna(r.get('ai'), nowy)
    r['ai'], r['braki'], r['zrodla_brakow'] = nowy, b or r.get('braki'), zr or r.get('zrodla_brakow')
    r['ostrzezenia'] = [o for o in r['ostrzezenia'] if not o.startswith('poważne braki') and 'nieobecnych zawodników' not in o]
    _ostrzezenia_z_brakow(r, m['gospodarz'], m['gosc'])
    return istotna


def sklady(api_info):
    """Oficjalne składy (zwykle ok. 60 min przed meczem) + kluczowi zawodnicy spoza pierwszej jedenastki."""
    if not KLUCZ or not api_info: return None
    lu = _api('fixtures/lineups', fixture=api_info['fixture'])
    if not lu: return None
    kluczowi = _kluczowi(api_info['liga'], api_info['sezon'])
    out = {'gosp': [], 'gosc': [], 'poza': []}
    for t in lu:
        strona = 'gosp' if t['team']['id'] == api_info['gosp'] else 'gosc'
        xi = {p['player']['id']: p['player']['name'] for p in t.get('startXI', [])}
        lawka = {p['player']['id']: p['player']['name'] for p in t.get('substitutes', [])}
        out[strona] = list(xi.values())
        for pid, (poz, gole, tid, imie) in kluczowi.items():
            if tid == t['team']['id'] and pid not in xi and poz <= 20:
                out['poza'].append(dict(strona=strona, zawodnik=imie, gole=gole, gdzie='na ławce' if pid in lawka else 'poza kadrą meczową'))
    return out if (out['gosp'] or out['gosc']) else None
