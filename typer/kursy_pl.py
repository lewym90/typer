"""Kursy polskich bukmacherów – Superbet (publiczna oferta, bez logowania).
Pozostali (Betclic, STS, Fortuna) blokują serwery spoza Polski – test 30.09: 403/Cloudflare/Geoblock.

Działa jako osobny krok workflow (błąd tutaj nie dotyka reszty programu):
1. pobiera ofertę przedmeczową Superbetu (jedno zapytanie, cała oferta),
2. dopasowuje mecze z naszych list (piłka, tenis, walki) po nazwach i godzinie,
3. dla dopasowanych meczów piłki pobiera wszystkie rynki meczu,
4. dopisuje do każdego typu pole  kursy_pl = {"Superbet": kurs}  w dzis.json i inne.json,
5. zapisuje szczegóły w docs/data/kursy_pl.json (także diagnostykę: nazwy rynków, niedopasowane mecze).
Częstotliwość: po każdym pełnym liczeniu (12:00), przy push / ręcznym uruchomieniu i co ok. 2 godziny."""
import os, re, json, time, unicodedata, difflib, datetime as dt
from zoneinfo import ZoneInfo

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
TZ = ZoneInfo('Europe/Warsaw')
LIMIT_CZASU = 200
TIMEOUT = 25
CO_ILE_MIN = 115
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/128.0.0.0 Safari/537.36')
SB = 'https://production-superbet-offer-pl.freetls.fastly.net/v2/pl-PL'
START = time.time()
DIAG = dict(bledy=[], rynki_przyklad={}, niedopasowane=[], sporty={}, czas_offset=[])

# ---------------------------------------------------------------- nazwy
TLUMACZ = {'munich': 'monachium', 'cologne': 'kolonia', 'koln': 'kolonia', 'milan': 'mediolan', 'lisbon': 'lizbona',
           'prague': 'praga', 'belgrade': 'belgrad', 'copenhagen': 'kopenhaga', 'moscow': 'moskwa', 'bucharest': 'bukareszt',
           'kyiv': 'kijow', 'kiev': 'kijow', 'athens': 'ateny', 'warsaw': 'warszawa', 'rome': 'rzym', 'turin': 'turyn',
           'seville': 'sewilla', 'naples': 'neapol', 'florence': 'florencja', 'genoa': 'genua', 'vienna': 'wieden',
           'zurich': 'zurych', 'brussels': 'bruksela', 'saint': 'st', 'united': 'utd'}
STOP = {'fc', 'cf', 'sc', 'afc', 'ac', 'cd', 'ssc', 'sv', 'fk', 'sk', 'if', 'bk', 'club', 'de', 'the', 'and', 'of',
        'calcio', 'kv', 'kaa', 'krc', 'rsc', 'vfb', 'vfl', 'tsg', 'rb', 'as', 'us', 'ud', 'sd', 'rcd', 'ca', 'nk', 'hnk',
        'gnk', 'cfr', 'ks', 'mks', 'gks', 'sa', 'spa', 'ssd'}

def _bez_ogonkow(s):
    s = str(s or '').replace('ł', 'l').replace('Ł', 'L')
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()

def tokeny(s):
    s = _bez_ogonkow(s).lower()
    s = re.sub(r'\((w|z|k|f|kob\.?|women)\)', ' kobiety ', s)
    t = re.findall(r'[a-z0-9]+', s)
    return [TLUMACZ.get(x, x) for x in t if x not in STOP and (len(x) > 1 or x.isdigit())]

def podobne(a, b):
    """0..1 – jak bardzo nazwy są podobne (tokeny + sekwencja znaków)."""
    ta, tb = tokeny(a), tokeny(b)
    if not ta or not tb: return 0.0
    sa, sb = set(ta), set(tb)
    wspolne = sum(1 for x in sa if x in sb or any(len(x) >= 4 and len(y) >= 4 and (x.startswith(y) or y.startswith(x)) for y in sb))
    tok = wspolne / min(len(sa), len(sb))
    seq = difflib.SequenceMatcher(None, ' '.join(ta), ' '.join(tb)).ratio()
    return max(tok * 0.9 + seq * 0.1, seq)

def warianty(nazwa):
    w = [nazwa]
    try:
        from nazwy import pl
        p = pl(nazwa)
        if p and p != nazwa: w.append(p)
    except Exception: pass
    return w

def podobne_w(nasza, ich): return max(podobne(v, ich) for v in warianty(nasza))

# ---------------------------------------------------------------- sieć
def _sesja():
    import requests
    s = requests.Session()
    s.headers.update({'User-Agent': UA, 'Accept-Language': 'pl-PL,pl;q=0.9', 'Accept': 'application/json, text/plain, */*'})
    return s

def _json(ses, url):
    r = ses.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    j = r.json()
    if isinstance(j, dict) and j.get('error'): raise ValueError(f'błąd w odpowiedzi: {str(j.get("error"))[:80]}')
    return j

# ---------------------------------------------------------------- Superbet
def _czas_sb(e):
    """Czas meczu. utcDate, jeśli jest; inaczej matchDate (przy dopasowaniu sprawdzamy odczyt UTC i polski)."""
    for k in ('utcDate', 'matchDate'):
        v = e.get(k)
        if v:
            try: return dt.datetime.fromisoformat(str(v).replace('Z', '').replace('T', ' ')[:19]).replace(tzinfo=dt.timezone.utc)
            except Exception: pass
    ms = e.get('unixDateMillis')
    if ms: return dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc)
    return None

def _strony(e):
    n = str(e.get('matchName') or '')
    cz = re.split(r'\s*·\s*|\s+-\s+|\s+–\s+|\s+vs\.?\s+', n)
    return (cz[0].strip(), cz[1].strip()) if len(cz) >= 2 else (n, '')

def oferta_superbet(ses):
    dzien = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')
    j = _json(ses, f'{SB}/events/by-date?currentStatus=active&offerState=prematch&startDate={dzien}%2000:00:00')
    ev = j.get('data') or []
    for e in ev:
        sp = str(e.get('sportId')); d = DIAG['sporty'].setdefault(sp, dict(n=0, przyklad=[]))
        d['n'] += 1
        if len(d['przyklad']) < 3: d['przyklad'].append(str(e.get('matchName'))[:60])
    if ev: DIAG['pola_zdarzenia'] = sorted(ev[0].keys())[:40]; DIAG['przyklad_glowne'] = (ev[0].get('odds') or [])[:3]
    return ev

def rynki_meczu(ses, event_id):
    j = _json(ses, f'{SB}/events/{event_id}')
    d = j.get('data')
    d = d[0] if isinstance(d, list) and d else d
    return (d or {}).get('odds') or []

# ---------------------------------------------------------------- dopasowanie
def _utc_nasz(start):
    t = dt.datetime.strptime(str(start)[:16], '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
    return t.astimezone(dt.timezone.utc)

def dopasuj(nasz, oferta, tol_min, zamiana):
    """nasz = dict(h, a, start). Zwraca (event, odwrócone, wynik, odczyt_czasu) albo None."""
    try: t0 = _utc_nasz(nasz['start'])
    except Exception: return None
    best = None
    for e in oferta:
        t = _czas_sb(e)
        if t is None: continue
        dts = [abs((t - t0).total_seconds()) / 60,
               abs((t.replace(tzinfo=TZ).astimezone(dt.timezone.utc) - t0).total_seconds()) / 60]
        dmin = min(dts)
        if dmin > tol_min: continue
        h, a = _strony(e)
        s1 = min(podobne_w(nasz['h'], h), podobne_w(nasz['a'], a))
        s2 = min(podobne_w(nasz['h'], a), podobne_w(nasz['a'], h)) if zamiana else 0
        s, odwr = (s1, False) if s1 >= s2 else (s2, True)
        if s < 0.55: continue
        wynik = s - dmin / (tol_min * 20)
        if best is None or wynik > best[2]: best = (e, odwr, wynik, dts.index(dmin))
    return best

# ---------------------------------------------------------------- rynki -> nasze klucze
def _linia(o):
    for v in (o.get('specialBetValue'), o.get('name'), o.get('marketName')):
        m = re.search(r'(\d+[.,]5)', str(v or ''))
        if m: return m.group(1).replace(',', '.')
    return None

def _ou(nazwa):
    n = _bez_ogonkow(nazwa).lower().strip()
    if n.startswith('+') or 'powyzej' in n or 'over' in n or n.startswith('wiecej'): return 'Over'
    if n.startswith('-') or 'ponizej' in n or 'under' in n or n.startswith('mniej'): return 'Under'
    return None

def _cena(o):
    try: c = float(o.get('price') or 0)
    except Exception: return None
    return c if c > 1.0 and str(o.get('status', 'active')).lower() in ('active', '', 'none', '1') else None

def klucze_pilka(odds, glowne):
    """Kursy Superbetu w naszym zapisie kluczy (piłka). glowne = kursy 1/X/2 z oferty dnia."""
    k = {}
    for o in glowne or []:
        n = str(o.get('name') or o.get('code') or '').upper(); c = _cena(o)
        if n in ('1', 'X', '2') and c: k.setdefault(n, c)
    for o in odds:
        c = _cena(o)
        if not c: continue
        if ';' in str(o.get('marketName') or ''): continue          # kombinacje (bet builder) – pomijamy
        rn = _bez_ogonkow(o.get('marketName')).lower().strip(); nz = str(o.get('name') or o.get('code') or '').strip()
        nzl = _bez_ogonkow(nz).lower()
        if any(x in rn for x in ('polow', 'pol.', 'rzut', 'kartk', 'korner', 'rozn', 'faul', 'spalon', 'minut', 'strzal',
                                 'zawodnik', 'gracz', 'dogrywk', 'karn', '15 min', '10 min', 'przedzial')): continue
        if rn in ('mecz', '1x2', 'wynik meczu', 'koncowy wynik', 'zwyciezca meczu', 'wynik', 'rezultat meczu') and nz.upper() in ('1', 'X', '2'):
            k.setdefault(nz.upper(), c)
        elif 'podwojna szansa' in rn and nz.upper().replace(' ', '') in ('1X', 'X2', '12'):
            k.setdefault(nz.upper().replace(' ', ''), c)
        elif ('obie' in rn and 'strzel' in rn and '&' not in rn and ' i ' not in rn) or rn in ('gg/ng', 'btts'):
            if nzl in ('tak', 'gg', 'yes'): k.setdefault('BTTS Tak', c)
            elif nzl in ('nie', 'ng', 'no'): k.setdefault('BTTS Nie', c)
        elif ('gol' in rn or 'bramk' in rn) and any(x in rn for x in ('liczba', 'suma', 'lacznie', 'gole', 'powyzej/ponizej')) \
                and not any(x in rn for x in ('gospodar', 'gosci', 'gosc', 'druzyn', 'zespol', 'dokladn', 'nieparzys', 'parzyst', '&', ' i ')):
            ou, ln = _ou(nz), _linia(o)
            if ou and ln: k.setdefault(f'{ou} {ln}', c)
    return k

def klucze_duel(glowne, odwr):
    """Tenis / walki: zwycięzca. '1' = pierwszy w nazwie meczu u Superbetu."""
    k = {}
    for o in glowne or []:
        n = str(o.get('name') or o.get('code') or '').upper(); c = _cena(o)
        if not c: continue
        if n == '1': k.setdefault('B' if odwr else 'A', c)
        elif n == '2': k.setdefault('A' if odwr else 'B', c)
        elif n == 'X': k.setdefault('D', c)
    return k

def klucze_tenis(odds, glowne, odwr, bo, A_B=('', '')):
    """Tenis: zwycięzca, dokładny wynik w setach, liczba setów. Wynik u Superbetu liczony od pierwszego zawodnika w nazwie."""
    k = klucze_duel(glowne, odwr)
    for o in odds:
        c = _cena(o)
        if not c: continue
        if ';' in str(o.get('marketName') or ''): continue          # kombinacje – pomijamy
        rn = _bez_ogonkow(o.get('marketName')).lower(); nz = str(o.get('name') or '').strip()
        mw = re.fullmatch(r'(.+?) wygra seta', str(o.get('marketName') or '').strip())
        if mw and _bez_ogonkow(nz).lower() == 'tak':                  # „X wygra seta – Tak” = min. 1 set
            kto = mw.group(1); pa, pb = podobne(kto, A_B[0]), podobne(kto, A_B[1])
            if max(pa, pb) >= 0.6: k.setdefault(('A' if pa >= pb else 'B') + ' min. 1 set', c)
            continue
        if 'gem' in rn or 'tie' in rn or re.search(r'\b[1-5]\. set|set [1-5]\b|[1-5] set\b', rn): continue
        m = re.fullmatch(r'(\d)\s*[:\-]\s*(\d)', nz)
        if m and 'set' in rn and ('wynik' in rn or 'dokladn' in rn):
            x, y = int(m.group(1)), int(m.group(2))
            gp, gd = ('B', 'A') if odwr else ('A', 'B')      # gp = pierwszy u Superbetu
            kl = f'{gp} {x}:{y}' if x > y else f'{gd} {y}:{x}'
            k.setdefault(kl, c)
            if int(bo or 3) == 3 and {x, y} == {2, 0}: k.setdefault(kl.split()[0] + ' -1.5', c)
        elif 'set' in rn and any(x in rn for x in ('liczba', 'suma', 'lacznie', 'powyzej/ponizej')):
            ou, ln = _ou(nz), _linia(o)
            if ou and ln: k.setdefault(f"{'Ponad' if ou == 'Over' else 'Poniżej'} {ln} seta", c)
    return k

def _zapisz_przyklad(event, odds):
    if len(DIAG['rynki_przyklad']) >= 5: return
    rynki = {}
    for o in odds:
        r = str(o.get('marketName'))
        if ';' in r: continue
        if r not in rynki and len(rynki) < 90: rynki[r] = []
        if r in rynki and len(rynki[r]) < 4: rynki[r].append(f"{o.get('name')}|{o.get('specialBetValue', '')}|{o.get('price')}")
    DIAG['rynki_przyklad'][str(event.get('matchName'))[:60]] = rynki

# ---------------------------------------------------------------- nasze mecze
def nasze_mecze():
    """[(sport, event_id, h, a, start)] z dzis.json (piłka) i inne.json (tenis, walki)."""
    wyn = {}
    try:
        d = json.load(open(os.path.join(OUT, 'dzis.json')))
        for m in (d.get('pewne') or []) + (d.get('mecze') or []):
            if m.get('event_id') and m.get('gospodarz'):
                wyn[m['event_id']] = ('pilka', m['event_id'], m['gospodarz'], m['gosc'], m['start'], 0)
    except Exception as e: DIAG['bledy'].append(f'dzis.json: {e}')
    try:
        d = json.load(open(os.path.join(OUT, 'inne.json')))
        for sp in ('tenis', 'walki'):
            for m in ((d.get(sp) or {}).get('mecze') or []):
                if m.get('event_id') and m.get('a'):
                    wyn[m['event_id']] = (sp, m['event_id'], m['a'], m['b'], m['start'], m.get('bo') or 3)
    except Exception as e: DIAG['bledy'].append(f'inne.json: {e}')
    return list(wyn.values())

def dopasuj_wszystko(ses, oferta):
    kursy = {}
    przyklady = {}
    for sp, eid, h, a, start, bo in nasze_mecze():
        if time.time() - START > LIMIT_CZASU: DIAG['bledy'].append('limit czasu'); break
        tol, zam = {'pilka': (35, False), 'tenis': (360, True), 'walki': (720, True)}[sp]
        b = dopasuj(dict(h=h, a=a, start=start), oferta, tol, zam)
        if not b:
            DIAG['niedopasowane'].append(f'{sp}: {h} – {a} ({start})'); continue
        e, odwr, s, jak = b
        DIAG['czas_offset'].append(jak)
        glowne = e.get('odds') or []
        odds = []
        if sp in ('pilka', 'tenis'):
            try:
                odds = rynki_meczu(ses, e.get('eventId'))
                if przyklady.get(sp, 0) < (3 if sp == 'pilka' else 2): _zapisz_przyklad(e, odds); przyklady[sp] = przyklady.get(sp, 0) + 1
            except Exception as ex: DIAG['bledy'].append(f'rynki {e.get("eventId")}: {str(ex)[:80]}')
        k = klucze_pilka(odds, glowne) if sp == 'pilka' else (klucze_tenis(odds, glowne, odwr, bo, (h, a)) if sp == 'tenis' else klucze_duel(glowne, odwr))
        if k:
            kursy[eid] = dict(superbet=dict(id=e.get('eventId'), nazwa=e.get('matchName'), zgodnosc=round(s, 2), kursy=k))
        else:
            DIAG['niedopasowane'].append(f'{sp}: {h} – {a}: dopasowany ({e.get("matchName")}), ale bez kursów')
    return kursy

# ---------------------------------------------------------------- dopisanie do typów
def _typy_w(obj):
    """Wszystkie słowniki-typy (mają 'klucz' i 'szansa') w meczu."""
    if isinstance(obj, dict):
        if 'klucz' in obj and 'szansa' in obj: yield obj
        for v in obj.values():
            if isinstance(v, dict) and 'klucz' in v and 'szansa' in v: yield v

NAZWY_BUK = {'fortuna': 'Fortuna', 'sts': 'STS', 'betclic': 'Betclic PL'}

def _kursy_vps():
    """Kursy z polskiego serwera (Fortuna, później STS i Betclic) – docs/data/kursy_vps.json, jeśli świeże (do 6 h)."""
    try:
        d = json.load(open(os.path.join(OUT, 'kursy_vps.json')))
        t = dt.datetime.strptime(d['czas'], '%Y-%m-%d %H:%M UTC').replace(tzinfo=dt.timezone.utc)
        if (dt.datetime.now(dt.timezone.utc) - t).total_seconds() > 6 * 3600: DIAG['vps'] = 'nieaktualne'; return {}
        DIAG['vps'] = dict(czas=d['czas'], mecze=len(d.get('mecze') or {}))
        return d.get('mecze') or {}
    except Exception as e:
        DIAG['vps'] = f'brak: {str(e)[:60]}'; return {}

def dopisz(kursy):
    ile = 0
    vps = _kursy_vps()
    def nadaj(m, eid):
        nonlocal ile
        zrodla = {'Superbet': ((kursy.get(eid) or {}).get('superbet') or {}).get('kursy') or {}}
        for buk, dane in ((vps.get(eid) or {}).items()):
            zrodla[NAZWY_BUK.get(buk, buk)] = (dane or {}).get('kursy') or {}
        for t in _typy_w(m):
            kp = {b: k[t['klucz']] for b, k in zrodla.items() if k.get(t['klucz'])}
            if kp: t['kursy_pl'] = kp; ile += 1
            else: t.pop('kursy_pl', None)
    p = os.path.join(OUT, 'dzis.json')
    try:
        d = json.load(open(p))
        for m in (d.get('pewne') or []) + (d.get('mecze') or []) + (d.get('value') or []):
            if isinstance(m, dict) and m.get('event_id'): nadaj(m, m['event_id'])
        _zapisz_bezpiecznie(p, d)
    except Exception as e: DIAG['bledy'].append(f'zapis dzis.json: {e}')
    p = os.path.join(OUT, 'inne.json')
    try:
        d = json.load(open(p))
        for sp in ('tenis', 'walki'):
            s = d.get(sp) or {}
            for m in (s.get('mecze') or []) + (s.get('value') or []):
                if isinstance(m, dict) and m.get('event_id'): nadaj(m, m['event_id'])
        _zapisz_bezpiecznie(p, d)
    except Exception as e: DIAG['bledy'].append(f'zapis inne.json: {e}')
    return ile

def _zapisz_bezpiecznie(p, d):
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: json.dump(d, f, ensure_ascii=False)
    json.load(open(tmp))
    os.replace(tmp, p)

# ---------------------------------------------------------------- start
def czy_teraz(st):
    if os.environ.get('GITHUB_EVENT_NAME', 'push') != 'schedule': return True
    ost = (st.get('kursy_pl') or {}).get('utc')
    if not ost: return True
    try: ost_t = dt.datetime.fromisoformat(ost)
    except Exception: return True
    try:   # nowe pełne liczenie (12:00) nadpisało dzis.json – dopisz kursy od razu
        wyg = json.load(open(os.path.join(OUT, 'dzis.json'))).get('wygenerowano')
        if wyg and dt.datetime.strptime(wyg, '%Y-%m-%d %H:%M').replace(tzinfo=TZ) > ost_t: return True
    except Exception: pass
    try:   # nowe kursy z polskiego serwera
        c = json.load(open(os.path.join(OUT, 'kursy_vps.json'))).get('czas')
        if c and dt.datetime.strptime(c, '%Y-%m-%d %H:%M UTC').replace(tzinfo=dt.timezone.utc) > ost_t: return True
    except Exception: pass
    return (dt.datetime.now(dt.timezone.utc) - ost_t).total_seconds() >= CO_ILE_MIN * 60

def main():
    try: st = json.load(open(os.path.join(OUT, 'status.json')))
    except Exception: st = {}
    if not czy_teraz(st): print('Kursy PL: za wcześnie (co ~2 h)'); return
    ses = _sesja(); stan = dict(ok=False, zdarzen=0, dopasowane=0, typow=0)
    kursy = {}
    try:
        oferta = oferta_superbet(ses); stan['zdarzen'] = len(oferta)
        kursy = dopasuj_wszystko(ses, oferta); stan['dopasowane'] = len(kursy); stan['ok'] = True
    except Exception as e: DIAG['bledy'].append(f'Superbet: {type(e).__name__}: {str(e)[:150]}')
    stan['typow'] = dopisz(kursy)   # także gdy Superbet nie odpowie – wtedy tylko kursy z serwera
    teraz = dt.datetime.now(TZ).strftime('%Y-%m-%d %H:%M')
    nasze = len(nasze_mecze())
    pelny = dict(czas=teraz, wersja=3, bukmacherzy=dict(superbet=stan), mecze=kursy,
                 niedostepni=dict(betclic='blokada 403 dla serwerów spoza Polski', sts='Cloudflare – blokada', fortuna='Geoblock – tylko Polska'),
                 diag=dict(DIAG, nasze_mecze=nasze, sekund=round(time.time() - START)))
    try: _zapisz_bezpiecznie(os.path.join(OUT, 'kursy_pl.json'), pelny)
    except Exception as e: print('kursy_pl.json:', e)
    try: st = json.load(open(os.path.join(OUT, 'status.json')))
    except Exception: st = {}
    st['kursy_pl'] = dict(czas=teraz, utc=dt.datetime.now(dt.timezone.utc).isoformat(), superbet=stan, nasze_mecze=nasze,
                          niedopasowane=len(DIAG['niedopasowane']), vps=DIAG.get('vps'), bledy=DIAG['bledy'][:4], sekund=round(time.time() - START))
    try: _zapisz_bezpiecznie(os.path.join(OUT, 'status.json'), st)
    except Exception as e: print('status.json:', e)
    print('Kursy PL:', json.dumps(st['kursy_pl'], ensure_ascii=False))

if __name__ == '__main__':
    import sys; sys.path.insert(0, os.path.dirname(__file__))
    try: main()
    except Exception as e: print('Kursy PL – błąd (reszta programu działa):', e)
