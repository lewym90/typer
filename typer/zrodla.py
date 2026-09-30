"""Kontuzje, zawieszenia i składy z darmowych API:
- BSD (sports.bzzoiro.com) – nieobecni zawodnicy przy każdym meczu (także reprezentacje), składy ok. 1 h przed meczem,
  krótka zapowiedź meczu (metadata). Bez limitu zapytań.
- Big Balls (api.bigballsdata.com) – lista kontuzji w 5 najlepszych ligach Europy i MLS (250–500 zapytań dziennie).
Wszystko opcjonalne: bez klucza albo przy błędzie program działa dalej, a powód trafia do status.json."""
import os, re, requests
import pandas as pd
from powiadomienia import podob
from nazwy import pl_powod

BSD_KEY = os.environ.get('BSD_API_KEY', '')
BB_KEY = os.environ.get('BIGBALLS_KEY', '')
BSD_URL = 'https://sports.bzzoiro.com/api/v2'
BB_URL = 'https://api.bigballsdata.com/v1'
STAN = {'bsd': dict(klucz=bool(BSD_KEY), zapytania=0, dopasowane=0, szukane=0, bledy=[], probka=None),
        'bigballs': dict(klucz=bool(BB_KEY), zapytania=0, kontuzji=0, bledy=[], as_of=None, probka=None)}
BB_LIGI = {'soccer_epl', 'soccer_spain_la_liga', 'soccer_italy_serie_a', 'soccer_germany_bundesliga', 'soccer_france_ligue_one', 'soccer_usa_mls'}

def _blad(zr, t):
    t = str(t)[:160]; print(zr, t)
    if t not in STAN[zr]['bledy']: STAN[zr]['bledy'].append(t)

# ---------------- BSD ----------------
def _bsd(sciezka, **p):
    if not BSD_KEY: return None
    try:
        r = requests.get(f'{BSD_URL}/{sciezka.strip("/")}/', params=p, timeout=30, headers={'Authorization': f'Token {BSD_KEY}'})
        STAN['bsd']['zapytania'] += 1
        if r.status_code != 200: _blad('bsd', f'{sciezka}: HTTP {r.status_code} {r.text[:100]}'); return None
        return r.json()
    except Exception as e:
        _blad('bsd', f'{sciezka}: {e}'); return None

_dni = {}
def _mecze_bsd(data):
    """Wszystkie mecze BSD danego dnia (UTC, z zapasem ±1 dzień na późne godziny)."""
    if data in _dni: return _dni[data]
    out, off = [], 0
    d0 = (pd.Timestamp(data) - pd.Timedelta(days=1)).strftime('%Y-%m-%d'); d1 = (pd.Timestamp(data) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    while off < 2000:
        j = _bsd('events', date_from=d0, date_to=d1, limit=200, offset=off)
        if not j: break
        wyn = j.get('results', j if isinstance(j, list) else [])
        out += wyn
        if not j.get('next') or not wyn: break
        off += 200
    _dni[data] = out
    return out

def _nazwa(x):
    if isinstance(x, dict): return x.get('name') or x.get('short_name') or ''
    return x or ''

def znajdz_bsd(dom, gosc, start):
    """start: 'YYYY-MM-DD HH:MM' (czas polski). Zwraca słownik meczu BSD albo None."""
    if not BSD_KEY: return None
    STAN['bsd']['szukane'] += 1
    t0 = pd.Timestamp(start).tz_localize('Europe/Warsaw')
    najl, wynik = 0, None
    for e in _mecze_bsd(t0.strftime('%Y-%m-%d')):
        h, a = _nazwa(e.get('home_team')), _nazwa(e.get('away_team'))
        s1, s2 = podob(dom, h), podob(gosc, a)
        try: dt = abs((pd.Timestamp(e.get('event_date')) - t0).total_seconds()) / 60
        except Exception: dt = 999
        ok = (s1 >= 0.6 and s2 >= 0.6 and dt <= 180) or (max(s1, s2) >= 0.85 and dt <= 20)
        if ok and s1 + s2 > najl: najl, wynik = s1 + s2, e
    if wynik: STAN['bsd']['dopasowane'] += 1
    return wynik

def _gracz(p):
    """Ujednolica wpis o nieobecnym zawodniku (BSD ma kilka wariantów pól)."""
    if isinstance(p, str): return dict(zawodnik=p, typ='', powod='')
    gr = p.get('player') if isinstance(p.get('player'), dict) else {}
    imie = p.get('name') or p.get('player_name') or gr.get('name') or gr.get('short_name') or '?'
    typ = str(p.get('type') or p.get('status') or p.get('availability') or '')
    powod = str(p.get('reason') or p.get('injury') or p.get('description') or p.get('injury_type') or '')
    return dict(zawodnik=imie, typ=typ, powod=powod, powrot=p.get('expected_return') or p.get('return_date'))

def _strony(u):
    """unavailable_players -> {'gosp': [...], 'gosc': [...]} niezależnie od kształtu odpowiedzi."""
    out = {'gosp': [], 'gosc': []}
    if not u: return out
    if isinstance(u, dict):
        for k, v in u.items():
            s = 'gosp' if str(k).lower().startswith('home') else ('gosc' if str(k).lower().startswith('away') else None)
            if s and isinstance(v, list): out[s] += [_gracz(p) for p in v]
    elif isinstance(u, list):
        for p in u:
            s = 'gosp' if str(p.get('side') or p.get('team_side') or '').lower().startswith('home') or p.get('home') is True else 'gosc'
            out[s].append(_gracz(p))
    return out

def _xi(lu, strona):
    """Pierwsza jedenastka z odpowiedzi /lineups/ (różne warianty kształtu)."""
    if not isinstance(lu, dict): return []
    t = lu.get(strona) or lu.get(strona + '_team') or {}
    lista = t.get('starters') or t.get('startXI') or t.get('starting_xi') or t.get('players') or [] if isinstance(t, dict) else t
    out = []
    for p in lista or []:
        if isinstance(p, dict):
            if p.get('substitute') is True or p.get('is_substitute') is True: continue
            gr = p.get('player') if isinstance(p.get('player'), dict) else {}
            out.append(p.get('name') or p.get('player_name') or gr.get('name') or '?')
        else: out.append(str(p))
    return out[:11]

def dane_bsd(dom, gosc, start):
    """Nieobecni + (gdy są) potwierdzone składy + zapowiedź meczu. None, gdy BSD nie zna meczu."""
    e = znajdz_bsd(dom, gosc, start)
    if not e: return None
    out = dict(id=e.get('id'), braki={'gosp': [], 'gosc': []}, sklad=None, zapowiedz=None)
    lu = _bsd(f"events/{e['id']}/lineups")
    if lu:
        if STAN['bsd']['probka'] is None:   # do diagnostyki: jak wygląda odpowiedź (tylko nazwy pól)
            STAN['bsd']['probka'] = dict(pola=sorted(lu.keys())[:15], status=lu.get('lineup_status'),
                                         braki_typ=type(lu.get('unavailable_players')).__name__)
        out['braki'] = _strony(lu.get('unavailable_players') or e.get('unavailable_players'))
        if lu.get('lineup_status') == 'confirmed':
            xi = {'gosp': _xi(lu.get('lineups'), 'home'), 'gosc': _xi(lu.get('lineups'), 'away')}
            if len(xi['gosp']) >= 7 or len(xi['gosc']) >= 7: out['sklad'] = xi
    else:
        out['braki'] = _strony(e.get('unavailable_players'))
    md = _bsd(f"events/{e['id']}/metadata")
    if isinstance(md, dict):
        z = md.get('preview') or md.get('ai_preview') or md.get('match_preview') or ''
        if isinstance(z, dict): z = z.get('text') or z.get('content') or ''
        out['zapowiedz'] = str(z)[:1500] or None
    return out

def sklad_bsd(dom, gosc, start):
    """Potwierdzone składy z BSD – zapas, gdy ESPN nie ma meczu."""
    d = dane_bsd(dom, gosc, start)
    if d and d.get('sklad'): return dict(gosp=d['sklad']['gosp'], gosc=d['sklad']['gosc'], zmiany={}, poza=[], zrodlo='BSD')
    return None

# ---------------- Big Balls ----------------
_bb = {}
def _kontuzje_bb():
    if 'lista' in _bb: return _bb['lista']
    _bb['lista'] = []
    if not BB_KEY: return []
    try:
        r = requests.get(f'{BB_URL}/injuries', params={'sport': 'football'}, timeout=30,
                         headers={'x-api-key': BB_KEY, 'Authorization': f'Bearer {BB_KEY}'})
        STAN['bigballs']['zapytania'] += 1
        if r.status_code != 200: _blad('bigballs', f'HTTP {r.status_code} {r.text[:100]}'); return []
        j = r.json()
        d = j.get('data', j) if isinstance(j, dict) else j
        lista = d.get('injuries', d.get('items', [])) if isinstance(d, dict) else (d if isinstance(d, list) else [])
        meta = (j.get('meta') if isinstance(j, dict) else None) or {}
        STAN['bigballs']['as_of'] = (meta.get('as_of') if isinstance(meta, dict) else None) or (d.get('as_of') if isinstance(d, dict) else None)
        tekst = lambda v: v if isinstance(v, str) else ((v.get('name') or v.get('short_name') or '') if isinstance(v, dict) else '')
        pominiete = 0
        for x in lista or []:
            if not isinstance(x, dict): pominiete += 1; continue   # nieznany kształt wpisu – pomijamy zamiast przerywać całość
            st = str(x.get('status') or '').lower()
            if st in ('active', 'unknown', ''): continue
            p = x.get('player')
            imie = tekst(p) or x.get('player_name') or x.get('name') or '?'
            druz = (p.get('team') if isinstance(p, dict) else None) or x.get('team') or x.get('team_name') or ''
            _bb['lista'].append(dict(zawodnik=imie, druzyna=tekst(druz), typ=x.get('status') or '',
                                     powod=tekst(x.get('injury_type')) or tekst(x.get('injury')) or tekst(x.get('comment')) or '',
                                     powrot=x.get('return_date') or x.get('expected_return')))
        if pominiete and STAN['bigballs'].get('probka') is None:
            STAN['bigballs']['probka'] = dict(typ_listy=type(lista).__name__, typ_wpisu=type(lista[0]).__name__ if lista else None,
                                              pominiete=pominiete, pola=sorted(j.keys())[:10] if isinstance(j, dict) else None)
        STAN['bigballs']['kontuzji'] = len(_bb['lista'])
    except Exception as e: _blad('bigballs', e)
    return _bb['lista']

def braki_bb(sport_key, dom, gosc):
    if not BB_KEY or sport_key not in BB_LIGI: return None
    lista = _kontuzje_bb()
    if not lista: return None
    out = {'gosp': [], 'gosc': []}
    for x in lista:
        for s, n in (('gosp', dom), ('gosc', gosc)):
            if x['druzyna'] and podob(x['druzyna'], n) >= 0.8: out[s].append({k: x[k] for k in ('zawodnik', 'typ', 'powod', 'powrot')})
    return out

# ---------------- razem ----------------
NIEPEWNY = re.compile(r'doubt|question|niepewn|day-to-day|50', re.I)

def braki(sport_key, dom, gosc, start):
    """Łączy BSD i Big Balls. Zwraca (braki, zapowiedź, id BSD, źródła)."""
    wynik, zapowiedz, bid, zr = {'gosp': [], 'gosc': []}, None, None, []
    d = dane_bsd(dom, gosc, start)
    if d:
        bid, zapowiedz = d['id'], d['zapowiedz']; zr.append('BSD')
        for s in wynik: wynik[s] += d['braki'][s]
    b = braki_bb(sport_key, dom, gosc)
    if b:
        zr.append('Big Balls')
        for s in wynik:
            znane = {x['zawodnik'].lower() for x in wynik[s]}
            wynik[s] += [x for x in b[s] if x['zawodnik'].lower() not in znane]
    for s in wynik:
        for x in wynik[s]:
            x['niepewny'] = bool(NIEPEWNY.search(f"{x.get('typ', '')} {x.get('powod', '')}"))
            x['typ'], x['powod'] = pl_powod(x.get('typ')), pl_powod(x.get('powod'))   # po polsku (w aplikacji i raporcie AI)
    return wynik, zapowiedz, bid, zr

def dostepne(): return bool(BSD_KEY or BB_KEY)
