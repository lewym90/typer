"""Tenis (🎾) i sporty walki (🥊 MMA, boks): kursy z The Odds API, szanse z Pinnacle/Betfair, typy na 3 poziomach,
osobne listy Pewne, Value w Betclic, dziennik z rozliczeniem (ESPN, zapasowo Odds API), Telegram i strażnik na żywo.
Mecze bez kursów Pinnacle/Betfair są pomijane (decyzja użytkownika 29.09)."""
import os, re, json, time, hashlib, unicodedata, requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
import numpy as np, pandas as pd
import core, tenis, walki, ai_raport, powiadomienia as tg, wspolne

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
PLIK_TYPOW = os.path.join(OUT, 'typy_inne.csv')
PLIK_JSON = 'inne.json'
GRUPY = {'Tennis': 'tenis', 'Mixed Martial Arts': 'walki', 'Boxing': 'walki'}
LIMIT_KREDYTOW = 16      # maks. na jedno pełne liczenie (tenis + walki); 1 kredyt = 1 turniej/gala (rynek h2h, region eu)
REZERWA_KREDYTOW = 40    # poniżej tego zostawiamy kredyty dla piłki
PEWNE_ILE, PEWNE_Z_ILU = 5, 15
POLACY = {'rebecki', 'tybura', 'swiatek', 'hurkacz', 'linette', 'frech', 'majchrzak', 'zuk', 'chwalinska', 'kawa', 'michalski', 'pawlikowski', 'fracz',
          'blachowicz', 'oleksiejczuk', 'jedrzejczyk', 'kowalkiewicz', 'kochman', 'rakoczy', 'bartosinski', 'gamrot', 'pudzianowski',
          'khalidov', 'soldic', 'szpilka', 'glowacki', 'wach', 'balski', 'rozanski', 'adamek', 'mamed'}
STAN = dict(tenis={}, walki={}, bledy=[], kredyty=0, pominiete=[], rundy={})
teraz = lambda: pd.Timestamp.now(tz='Europe/Warsaw')

def _blad(t):
    t = str(t)[:200]; print('Sporty:', t)
    if t not in STAN['bledy']: STAN['bledy'].append(t)

def nrm(s):
    s = unicodedata.normalize('NFKD', str(s).replace('ł', 'l').replace('Ł', 'L').replace('ø', 'o')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z ]', ' ', s)).strip()

def nazwisko(s):
    t = nrm(s).split(); return t[-1] if t else ''

def ta_sama_osoba(a, b):
    """'Iga Swiatek' ~ 'I. Swiatek' ~ 'Swiatek I.' – zgodne nazwisko i (jeśli są) inicjały."""
    A, B = nrm(a).split(), nrm(b).split()
    if not A or not B: return False
    if A == B: return True
    wsp = set(x for x in A if len(x) > 2) & set(x for x in B if len(x) > 2)
    if not wsp: return False
    ia, ib = {x[0] for x in A if x not in wsp}, {x[0] for x in B if x not in wsp}
    return not ia or not ib or bool(ia & ib)

PL_OSOBY = {'iga swiatek': 'Iga Świątek', 'magdalena frech': 'Magdalena Fręch', 'kamil majchrzak': 'Kamil Majchrzak',
            'maja chwalinska': 'Maja Chwalińska', 'jan blachowicz': 'Jan Błachowicz', 'joanna jedrzejczyk': 'Joanna Jędrzejczyk',
            'mateusz gamrot': 'Mateusz Gamrot', 'karolina kowalkiewicz': 'Karolina Kowalkiewicz', 'mateusz rebecki': 'Mateusz Rębecki',
            'marcin tybura': 'Marcin Tybura', 'lukasz rozanski': 'Łukasz Różański', 'mariusz pudzianowski': 'Mariusz Pudzianowski',
            'daniel michalski': 'Daniel Michalski', 'kacper zuk': 'Kacper Żuk', 'katarzyna kawa': 'Katarzyna Kawa'}
TURNIEJ_PL = {'Boxing': 'Boks'}
# nazwy turniejów tenisowych po polsku (miasto), oryginalna nazwa w nawiasie; Wielkie Szlemy i nieznane – bez zmian
MIASTA = [('china open', 'Pekin'), ('beijing', 'Pekin'), ('japan open', 'Tokio'), ('pan pacific', 'Tokio'), ('toray', 'Tokio'),
          ('shanghai', 'Szanghaj'), ('wuhan', 'Wuhan'), ('ningbo', 'Ningbo'), ('paris masters', 'Paryż'), ('rolex paris', 'Paryż'),
          ('italian open', 'Rzym'), ('internazionali', 'Rzym'), ('rome', 'Rzym'), ('madrid', 'Madryt'), ('mutua', 'Madryt'),
          ('monte carlo', 'Monte Carlo'), ('indian wells', 'Indian Wells'), ('bnp paribas open', 'Indian Wells'), ('miami', 'Miami'),
          ('canadian open', 'Kanada'), ('national bank open', 'Kanada'), ('cincinnati', 'Cincinnati'), ('dubai', 'Dubaj'),
          ('qatar', 'Doha'), ('doha', 'Doha'), ('korea open', 'Seul'), ('seoul', 'Seul'), ('swiss indoors', 'Bazylea'), ('basel', 'Bazylea'),
          ('erste bank', 'Wiedeń'), ('vienna', 'Wiedeń'), ('stockholm', 'Sztokholm'), ('brisbane', 'Brisbane'), ('adelaide', 'Adelaide'),
          ('auckland', 'Auckland'), ('rotterdam', 'Rotterdam'), ('barcelona', 'Barcelona'), ('stuttgart', 'Stuttgart'), ('halle', 'Halle'),
          ("queen's", 'Londyn (Queen’s)'), ('queens', 'Londyn (Queen’s)'), ('eastbourne', 'Eastbourne'), ('berlin', 'Berlin'),
          ('washington', 'Waszyngton'), ('citi open', 'Waszyngton'), ('linz', 'Linz'), ('charleston', 'Charleston'), ('guadalajara', 'Guadalajara'),
          ('chengdu', 'Chengdu'), ('hangzhou', 'Hangzhou'), ('astana', 'Astana'), ('almaty', 'Ałmaty'), ('antwerp', 'Antwerpia'),
          ('european open', 'Antwerpia'), ('metz', 'Metz'), ('moselle', 'Metz'), ('tokyo', 'Tokio'), ('osaka', 'Osaka'), ('hong kong', 'Hongkong'),
          ('warsaw', 'Warszawa'), ('poland open', 'Warszawa'), ('mexican open', 'Acapulco'), ('acapulco', 'Acapulco'), ('rio', 'Rio de Janeiro'),
          ('buenos aires', 'Buenos Aires'), ('marseille', 'Marsylia'), ('montpellier', 'Montpellier'), ('lyon', 'Lyon'), ('geneva', 'Genewa'),
          ('munich', 'Monachium'), ('bmw open', 'Monachium'), ('hamburg', 'Hamburg'), ('umag', 'Umag'), ('kitzbuhel', 'Kitzbühel'),
          ('gstaad', 'Gstaad'), ('bastad', 'Båstad'), ('winston', 'Winston-Salem'), ('atp finals', 'Turyn (Finały ATP)'),
          ('wta finals', 'Finały WTA'), ('french open', 'Roland Garros'), ('roland garros', 'Roland Garros')]

def turniej_pl(tytul):
    """'ATP China Open' -> 'ATP Pekin (China Open)'; Wimbledon, US Open, Australian Open i nieznane – bez zmian."""
    t = str(tytul or '')
    if t in TURNIEJ_PL: return TURNIEJ_PL[t]
    k = t.lower()
    for klucz, miasto in MIASTA:
        if klucz in k:
            if klucz in ('french open', 'roland garros'):
                return re.sub(r'(?i)french open|roland garros', 'Roland Garros', t)
            m = re.match(r'(?i)(atp|wta)\s+(.*)', t)
            if m:
                reszta = m.group(2).strip()
                return f"{m.group(1).upper()} {miasto}" + (f" ({reszta})" if miasto.lower() not in reszta.lower() else '')
            return f"{miasto} ({t})" if miasto.lower() not in k else t
    return t
def pl_osoba(n): return PL_OSOBY.get(nrm(n), n)

def polski(*osoby): return any(t in POLACY for o in osoby for t in nrm(o).split())

# ---------------- kursy ----------------
def _okno(sport):
    """Od teraz do końca doby programu: 6:00 (tenis), 9:00 (walki – gale w USA kończą się rano)."""
    t = teraz(); do = wspolne.koniec_doby(sport, t)
    f = lambda x: x.tz_convert('UTC').strftime('%Y-%m-%dT%H:%M:%SZ')
    return f(wspolne.poczatek_listy(t)), f(do)   # najwcześniej od 8:00

def _ranga(key, tytul, evs):
    """Kolejność pobierania (gdy brakuje kredytów): mecze Polaków, Wielki Szlem, turnieje 1000, reszta."""
    if any(polski(e.get('home_team'), e.get('away_team')) for e in evs): return 0
    k = key + ' ' + (tytul or '').lower()
    if any(s in k for s in tenis.WIELKIE_SZLEMY) or 'open' in k and ('us' in k or 'french' in k or 'australian' in k): return 1
    if 'mma' in k or 'ufc' in k: return 1
    if re.search(r'masters|1000|indian wells|miami|madrid|rome|italian|canadian|cincinnati|shanghai|paris|china|wuhan|beijing|dubai|doha', k): return 2
    return 3

def pobierz():
    """Lista turniejów i meczów jest DARMOWA; kursy (1 kredyt na turniej/galę) tylko, gdy coś gra w najbliższej dobie."""
    wynik = {'tenis': [], 'walki': []}
    try: lista = core.api('sports')
    except Exception as e: _blad(f'lista sportów: {e}'); return wynik
    klucze = []
    for s in lista:
        sp = GRUPY.get(s.get('group'))
        if not sp or 'winner' in s.get('key', ''): continue   # zakłady długoterminowe (zwycięzca turnieju) pomijamy
        od, do = _okno(sp)
        try: evs = core.api(f"sports/{s['key']}/events", commenceTimeFrom=od, commenceTimeTo=do)
        except Exception as e: _blad(f"{s['key']}: {e}"); continue
        if evs: klucze.append((_ranga(s['key'], s.get('title'), evs), s['key'], s.get('title', ''), s.get('group'), sp, len(evs)))
    start_kr = core.KREDYTY['wydane_teraz']
    for _, key, tytul, grupa, sp, n in sorted(klucze):
        wydane = core.KREDYTY['wydane_teraz'] - start_kr
        poz = core.KREDYTY['pozostalo']
        if wydane + 1 > LIMIT_KREDYTOW or (poz is not None and poz < REZERWA_KREDYTOW):
            STAN['pominiete'].append(f'{tytul} ({n}) – brak kredytów'); continue
        od, do = _okno(sp)
        try: odds = core.api(f'sports/{key}/odds', regions='eu', markets='h2h', oddsFormat='decimal', commenceTimeFrom=od, commenceTimeTo=do)
        except Exception as e: _blad(f'{key}: {e}'); continue
        for ev in odds: wynik[sp].append((key, tytul, grupa, ev))
    STAN['kredyty'] = core.KREDYTY['wydane_teraz'] - start_kr
    return wynik

def uczciwe(ev):
    """Szanse bez marży z Pinnacle i giełdy Betfair (średnia, gdy są oba). Zwraca ({nazwa: p}, źródło, kursy Betclic)."""
    A, B = ev['home_team'], ev['away_team']
    bm = {b['key']: {mk['key']: mk['outcomes'] for mk in b['markets']} for b in ev.get('bookmakers', [])}
    lst, zr = [], []
    pin = (bm.get('pinnacle') or {}).get('h2h')
    if pin:
        d = {o['name']: o['price'] for o in pin}
        nazwy = [A, B] + (['Draw'] if 'Draw' in d else [])
        if all(n in d for n in nazwy): lst.append(dict(zip(nazwy, core.devig([d[n] for n in nazwy])))); zr.append('Pinnacle')
    bf = bm.get('betfair_ex_eu') or bm.get('betfair_ex_uk')
    if bf and bf.get('h2h'):
        back = {o['name']: o['price'] for o in bf['h2h']}; lay = {o['name']: o['price'] for o in bf.get('h2h_lay', [])}
        nazwy = [A, B] + (['Draw'] if 'Draw' in back else [])
        f = core._fair_z_gieldy(back, lay, nazwy)
        if f is not None: lst.append(dict(zip(nazwy, f))); zr.append('Betfair')
    if not lst: return None, None, None
    klucze = set().union(*lst)
    p = {k: float(np.mean([x.get(k, 0.0) for x in lst])) for k in klucze}; s = sum(p.values()); p = {k: v / s for k, v in p.items()}
    bc = next((v.get('h2h') for k, v in bm.items() if 'betclic' in k and v.get('h2h')), None)
    return p, '+'.join(zr), ({o['name']: o['price'] for o in bc} if bc else None)

# ---------------- typy ----------------
def _typ(nazwa, sz, opis_fn, a, b, kb=None):
    return dict(klucz=nazwa, zaklad=opis_fn(nazwa, a, b), szansa=round(float(sz), 4), kurs_uczciwy=round(1 / sz, 3),
                kurs_min=round(0.95 / sz, 3), kurs_betclic=kb)

def _betclic_dla(nazwa, bc, a, b):
    if not bc: return None
    return bc.get(a) if nazwa == 'A' else (bc.get(b) if nazwa == 'B' else None)

def przelicz(sp, key, tytul, grupa, ev):
    p, zr, bc = uczciwe(ev)
    if p is None: return None   # bez Pinnacle/Betfair – pomijamy
    A0, B0 = ev['home_team'], ev['away_team']; pd_ = p.get('Draw', 0.0)
    p = {pl_osoba(k): v for k, v in p.items()}; bc = {pl_osoba(k): v for k, v in bc.items()} if bc else None
    A, B = pl_osoba(A0), pl_osoba(B0)   # polskie znaki w nazwiskach Polaków (dopasowanie wyników i tak je pomija)
    start = pd.Timestamp(ev['commence_time']).tz_convert('Europe/Warsaw')
    e = dict(sport=sp, sport_key=key, turniej=turniej_pl(tytul), turniej_oryg=tytul, event_id=ev['id'], a=A, b=B, mecz=f'{A} – {B}',
             start=start.strftime('%Y-%m-%d %H:%M'), godzina=start.strftime('%H:%M'), dzien=start.strftime('%d.%m'), zrodlo=zr,
             polski=polski(A, B), betclic=bc)
    if sp == 'tenis':
        bo = tenis.do_ilu_setow(key); pa = tenis.kalibruj(p[A] / (p[A] + p[B])); wta = tenis.kobiety(key)
        R = tenis.rozklad(pa, bo, wta); T, rk = tenis.typy(R, bo); op = lambda n, a, b: tenis.opis(n, a, b, bo)
        e.update(dyscyplina='Tenis', bo=bo, wta=wta, szansa_a=round(pa, 4), szansa_b=round(1 - pa, 4),
                 wyniki=[dict(a=w[0], b=w[1], szansa=round(float(v), 4)) for w, v in sorted(R.items(), key=lambda x: -x[1])])
    else:
        mma = grupa == 'Mixed Martial Arts'
        if mma:
            pa = walki.kalibruj_mma(p[A] / (p[A] + p[B])); kat = walki.kategoria(A, B)
            r5, rundy_zr, kat_espn = rundy_walki(dict(sport='walki', dyscyplina='MMA', start=e['start'], a=A, b=B))
            kat = kat or kat_espn
            R = walki.rozklad_mma(pa, kat, r5)
            e.update(dyscyplina='MMA', kategoria=walki.KATEGORIE_PL.get(kat), rundy=5 if r5 else 3, rundy_zrodlo=rundy_zr,
                     szansa_a=round(pa, 4), szansa_b=round(1 - pa, 4),
                     przed_czasem=round(float(R[('A', 'KO')] + R[('B', 'KO')]), 4),
                     metody=dict(a_ko=round(float(R[('A', 'KO')]), 4), a_pkt=round(float(R[('A', 'PKT')]), 4),
                                 b_ko=round(float(R[('B', 'KO')]), 4), b_pkt=round(float(R[('B', 'PKT')]), 4)))
        else:
            R = walki.rozklad_boks(p[A], p[B], pd_)
            e.update(dyscyplina='Boks', szansa_a=round(p[A], 4), szansa_b=round(p[B], 4), szansa_remis=round(pd_, 4) if pd_ else None)
        T, rk = walki.typy(R); op = walki.opis
    for poz, (k, sz) in T.items(): e[poz] = _typ(k, sz, op, A, B, _betclic_dla(k, bc, A, B))
    # value: Betclic vs uczciwy kurs (tylko zwycięzca – inne rynki nie są w darmowym planie)
    e['value'] = []
    for strona, n in (('A', A), ('B', B)):
        k = (bc or {}).get(n); sz = e['szansa_a'] if strona == 'A' else e['szansa_b']
        if not k or not sz: continue
        ev_ = sz * k - 1
        if ev_ >= core.MIN_EV_VALUE and 1.30 <= k <= 4.00:
            e['value'].append(dict(klucz=strona, zaklad=f'wygra {n}', kurs=k, szansa=sz, ev=round(ev_, 4), kurs_uczciwy=round(1 / sz, 3),
                                   kurs_szukaj=round(1.02 / sz, 2), stawka_proc=round(core.kelly(sz, k), 4)))
    return e

def werdykt(m): return ((m.get('raport') or {}).get('ai') or {}).get('werdykt')

KSW_DO_GLOWNYCH = 100   # KSW wchodzi do 5 głównych Pewnych dopiero po tylu rozliczonych walkach w dzienniku

def lista_pewnych(mecze):
    """5 najpewniejszych typów z 15 najpopularniejszych meczów (Polacy, ważne turnieje, później na gali = ważniejsza walka).
    Nigdy typy, które AI odradza; najpierw „zgoda” (lub brak oceny), potem „ryzyko”; dopełnienie poniżej 70% – oznaczone.
    Zwraca (pewne, odradzane)."""
    def popularnosc(m):
        if m['sport'] == 'tenis': return (not m['polski'], _ranga(m['sport_key'], m.get('turniej_oryg') or m['turniej'], []), m['start'])
        return (not m['polski'], m['dyscyplina'] != 'MMA', tuple(-ord(c) for c in m['start']))   # później na gali = ważniejsza walka
    kol = sorted(mecze, key=popularnosc)
    for m in mecze: m.pop('nizsza_pewnosc', None)
    kand = [m for m in kol[:PEWNE_Z_ILU] if m.get('najpewniejszy')]
    odradzane = [m for m in kand if werdykt(m) == 'odradza' and m['najpewniejszy']['szansa'] >= core.PEWNE_MIN_SZANSA]
    kand = [m for m in kand if werdykt(m) != 'odradza']
    mocne = sorted([m for m in kand if m['najpewniejszy']['szansa'] >= core.PEWNE_MIN_SZANSA],
                   key=lambda m: (werdykt(m) == 'ryzyko', -m['najpewniejszy']['szansa']))
    wyb = mocne[:PEWNE_ILE]
    if len(wyb) < PEWNE_ILE:
        slabsze = sorted([m for m in kand if 0.55 <= m['najpewniejszy']['szansa'] < core.PEWNE_MIN_SZANSA], key=lambda m: -m['najpewniejszy']['szansa'])
        for m in slabsze[:PEWNE_ILE - len(wyb)]: m['nizsza_pewnosc'] = True; wyb.append(m)
    return wyb, odradzane[:3]

# ---------------- KSW: kursy polskich bukmacherów (Pinnacle nie wystawia) ----------------
def _ksw_z_serwera():
    """Walki KSW z polskiego serwera (Fortuna + STS) – docs/data/kursy_vps.json, jeśli świeże (do 30 h)."""
    try:
        d = json.load(open(os.path.join(OUT, 'kursy_vps.json')))
        t = pd.Timestamp(d['czas'].replace(' UTC', ''), tz='UTC')
        if (pd.Timestamp.now(tz='UTC') - t).total_seconds() > 30 * 3600: STAN['ksw'] = 'kursy z serwera nieaktualne'; return []
        return d.get('ksw') or []
    except Exception as e: STAN['ksw'] = f'brak kursów z serwera: {str(e)[:60]}'; return []

def _ksw_superbet(walki_):
    """Dopisuje kursy Superbetu (zwycięzca) do walk KSW – dopasowanie po nazwiskach i czasie."""
    try:
        import kursy_pl as KP
        oferta = KP.oferta_superbet(KP._sesja())
    except Exception as e: _blad(f'KSW Superbet: {e}'); return
    for w in walki_:
        start = pd.Timestamp(w['t']).tz_convert('Europe/Warsaw').strftime('%Y-%m-%d %H:%M')
        b = KP.dopasuj(dict(h=w['a'], a=w['b'], start=start), oferta, 720, True)
        if not b: continue
        k = KP.klucze_duel(b[0].get('odds') or [], b[1])
        if k.get('A') and k.get('B'): w['kursy']['superbet'] = dict(A=k['A'], B=k['B'])

NAZWY_BUK_PL = {'fortuna': 'Fortuna', 'sts': 'STS', 'superbet': 'Superbet', 'betclic': 'Betclic PL'}

def przelicz_ksw(w):
    """Walka KSW → karta jak z The Odds API. Szansa = średnia z kursów polskich bukmacherów bez marży (bez kalibracji UFC –
    na 42 walkach KSW pogarszała wynik)."""
    kursy = {NAZWY_BUK_PL.get(b, b): v for b, v in (w.get('kursy') or {}).items() if v.get('A', 0) > 1 and v.get('B', 0) > 1}
    if not kursy: return None
    pa = float(np.mean([(1 / v['A']) / (1 / v['A'] + 1 / v['B']) for v in kursy.values()]))
    A, B = pl_osoba(w['a']), pl_osoba(w['b'])
    start = pd.Timestamp(w['t']).tz_convert('Europe/Warsaw')
    eid = 'ksw-' + hashlib.md5(f"{nrm(A)}|{nrm(B)}|{start.strftime('%Y-%m-%d')}".encode()).hexdigest()[:12]
    r5 = bool(w.get('pas'))
    R = walki.rozklad_mma(pa, None, r5)
    e = dict(sport='walki', sport_key='ksw', turniej=w.get('gala') or 'KSW', turniej_oryg=w.get('gala') or 'KSW', event_id=eid, a=A, b=B, mecz=f'{A} – {B}',
             start=start.strftime('%Y-%m-%d %H:%M'), godzina=start.strftime('%H:%M'), dzien=start.strftime('%d.%m'),
             zrodlo='rynek PL (' + ', '.join(sorted(kursy)) + ')', rynek_pl=True, polski=True, betclic=None, dyscyplina='MMA',
             kategoria=None, rundy=5 if r5 else 3, rundy_zrodlo='5 rund (walka o pas)' if r5 else '3 rundy (przyjęto)',
             szansa_a=round(pa, 4), szansa_b=round(1 - pa, 4), kursy_walki=kursy)
    _uzupelnij_mma(e, R, A, B)
    return e

def _uzupelnij_mma(e, R, A, B):
    e.update(przed_czasem=round(float(R[('A', 'KO')] + R[('B', 'KO')]), 4),
             metody=dict(a_ko=round(float(R[('A', 'KO')]), 4), a_pkt=round(float(R[('A', 'PKT')]), 4),
                         b_ko=round(float(R[('B', 'KO')]), 4), b_pkt=round(float(R[('B', 'PKT')]), 4)))
    T, rk = walki.typy(R)
    for poz in ('najpewniejszy', 'lepszy_kurs', 'ryzykowny'): e.pop(poz, None)
    for poz, (k, sz) in T.items():
        e[poz] = _typ(k, sz, walki.opis, A, B, None)
        if e.get('kursy_walki') and k in ('A', 'B'):
            e[poz]['kursy_pl'] = {b: v[k] for b, v in e['kursy_walki'].items() if v.get(k)}
    e['value'] = []
    if e.get('kursy_walki'):   # value: najlepszy polski kurs vs uczciwy kurs ze średniej rynku PL
        for strona, n in (('A', A), ('B', B)):
            sz = e['szansa_a'] if strona == 'A' else e['szansa_b']
            buk, k = max(((b, v[strona]) for b, v in e['kursy_walki'].items()), key=lambda x: x[1])
            ev_ = sz * k - 1
            if ev_ >= 0.03 and 1.30 <= k <= 4.00 and len(e['kursy_walki']) >= 2:
                e['value'].append(dict(klucz=strona, zaklad=f'wygra {n}', kurs=k, bukmacher=buk, szansa=sz, ev=round(ev_, 4), kurs_uczciwy=round(1 / sz, 3),
                                       kurs_szukaj=round(1.02 / sz, 2), stawka_proc=round(core.kelly(sz, k), 4), rynek_pl=True,
                                       kursy_pl={b: v[strona] for b, v in e['kursy_walki'].items()}))

def przelicz_rundy(m, r5, zrodlo):
    kat = {v: k for k, v in walki.KATEGORIE_PL.items()}.get(m.get('kategoria'))
    R = walki.rozklad_mma(m['szansa_a'], kat, r5)
    m.update(rundy=5 if r5 else 3, rundy_zrodlo=f"{'5 rund' if r5 else '3 rundy'} ({zrodlo})")
    _uzupelnij_mma(m, R, m['a'], m['b'])

def ksw_mecze():
    od, do = _okno('walki'); od, do = pd.Timestamp(od), pd.Timestamp(do)
    lista = [w for w in _ksw_z_serwera() if od - pd.Timedelta(hours=3) <= pd.Timestamp(w['t']) <= do]
    if not lista: return []
    _ksw_superbet(lista)
    out = []
    for w in lista:
        try:
            e = przelicz_ksw(w)
            if e: out.append(e)
        except Exception as ex: _blad(f"KSW {w.get('a')} – {w.get('b')}: {ex}")
    STAN['ksw'] = f'{len(out)} walk z kursami'
    return out

def ksw_rozliczonych():
    d = wczytaj_typy()
    if not len(d): return 0
    return int(((d.sport_key == 'ksw') & (d.poziom == 'najpewniejszy') & d.trafiony.notna()).sum())

# ---------------- raport (nagłówki + AI) ----------------
def naglowki(osoba, ile=3, polskie=False):
    n = nazwisko(osoba)
    if len(n) < 3: return []
    jez = 'hl=pl&gl=PL&ceid=PL:pl' if polskie else 'hl=en-US&gl=US&ceid=US:en'
    try:
        r = requests.get(f"https://news.google.com/rss/search?q={quote(chr(34) + osoba + chr(34))}+when:7d&{jez}", timeout=15)
        out = []
        for it in ET.fromstring(r.content).iter('item'):
            t = it.findtext('title') or ''
            if n not in nrm(t) or re.search(r'odds|prediction|pick|betting|tips|live ?stream|how to watch', t, re.I): continue
            out.append(dict(tytul=t[:160], link=it.findtext('link') or '', data=(it.findtext('pubDate') or '')[5:16]))
            if len(out) >= ile: break
        return out
    except Exception as e: _blad(f'nagłówki {osoba}: {e}'); return []

POLECENIE = """Jesteś profesjonalnym analitykiem {dziedzina} i typerem. Przygotuj po polsku analizę przed {co}: {a} – {b} ({turniej}),
{kiedy} czasu polskiego.
{szukaj}
{rynek}
Sprawdź wszystko, co wpływa na wynik: {tematy}
{zasady}
{ocena}
{kontekst}
Odpowiedz WYŁĄCZNIE obiektem JSON (bez ```), dokładnie w tej postaci:
{{"werdykt": "zgoda" | "ryzyko" | "odradza",
  "powod": "jedno zdanie – najważniejszy powód werdyktu",
  "podsumowanie": "analiza 3–5 zdań, maks. 600 znaków",
  "forma": "jedno zdanie o formie obu {kogo} (tylko fakty ze źródeł)",
  "styl": "jedno zdanie – jak style do siebie pasują",
  "lepszy_zaklad": "inny zakład w {czym}, który uważasz za rozsądniejszy, albo pusty tekst",
  "problemy_a": ["krótko", ...], "problemy_b": ["krótko", ...],
  "ostrzezenie": true/false, "ostrzezenie_dla": "a" | "b" | "oba" | "brak", "uzasadnienie": "jedno zdanie"{dodatki}}}
"ostrzezenie" = true tylko przy poważnej sprawie: {powazne}."""
DODATKI_WALKI = ''',
  "oceny": {"a": {"stojka": 1-10, "zapasy": 1-10, "parter": 1-10, "kondycja": 1-10}, "b": {...tak samo}}  – tylko gdy źródła opisują styl obu
           zawodników (inaczej null); 10 = światowa czołówka w tym elemencie,
  "rundy": 3 | 5 | null  – 5 tylko, gdy źródło potwierdza walkę o pas lub walkę wieczoru na 5 rund,
  "bilans_a": "np. 18-1-0 albo pusty", "bilans_b": "np. 12-3-0 albo pusty"'''
TEMATY = {'tenis': ('meczem tenisowym', 'tenisa', 'zawodników', 'tym meczu',
                    'kontuzje i urazy, krecz lub wycofanie w ostatnich turniejach, zmęczenie (długi mecz dzień wcześniej, podróż, dużo meczów '
                    'z rzędu), forma i wyniki na tej nawierzchni, choroba, motywacja (ranking, obrona punktów), styl gry obu zawodników '
                    '(serwis, return, gra z głębi kortu) i to, jak do siebie pasują, wcześniejsze mecze między nimi.',
                    'uraz, niedawny krecz, choroba albo skrajne zmęczenie'),
          'walki': ('walką', 'MMA i sportów walki', 'zawodników', 'tej walce',
                    'zastępstwo w ostatniej chwili (krótki termin przygotowań), ważenie (nie zrobił limitu, ciężkie zbijanie), kontuzje, długa '
                    'przerwa od ostatniej walki, zmiana obozu lub trenera, bilans i forma z ostatnich walk, styl obu zawodników (stójka, '
                    'zapasy, parter, kondycja na dystansie) i to, jak do siebie pasują (np. zapaśnik przeciw zawodnikowi bez obrony obaleń).',
                    'zastępstwo na krótki termin, nieudane ważenie, kontuzja')}

def _typ_ai(m):
    t = m.get('najpewniejszy') or m.get('lepszy_kurs')
    return (t['zaklad'], t['szansa']) if t else None

def raport_ai(m, polski_=False):
    if not ai_raport.KLUCZ or ai_raport._licznik() >= ai_raport.MAKS_DZIENNIE or ai_raport.zostalo_analiz() <= 0: return None
    co, dziedzina, kogo, czym, tematy, powazne = TEMATY[m['sport']]
    ng = m.get('naglowki') or {}
    kont = [f"Nagłówki o {x}: " + ' | '.join(h['tytul'] for h in ng.get(k, [])) for k, x in (('a', m['a']), ('b', m['b'])) if ng.get(k)]
    kontekst = ('DANE ZEBRANE PRZEZ PROGRAM (traktuj jako wskazówki):\n' + '\n'.join(kont)) if kont else ''
    szukaj = ('Wyszukaj w Google najnowsze wiadomości o obu zawodnikach' + (' (koniecznie także w polskich mediach: WP SportoweFakty, '
              'Przegląd Sportowy, MMA Rocks, InTheCage, Lowking, Sport.pl)' if polski_ or m.get('rynek_pl') else '') + '.')
    rynek = f"Szanse z kursów bukmacherów: wygra {m['a']} {m['szansa_a']*100:.0f}%, wygra {m['b']} {m['szansa_b']*100:.0f}%." if m.get('szansa_a') else ''
    typ = _typ_ai(m)
    t = lambda sz: POLECENIE.format(co=co, dziedzina=dziedzina, kogo=kogo, czym=czym, a=m['a'], b=m['b'], turniej=m['turniej'],
                                    kiedy=f"{m['dzien']}, {m['godzina']}", szukaj=sz, rynek=rynek, tematy=tematy, powazne=powazne,
                                    zasady=ai_raport.ZASADY, ocena=ai_raport.ocena_txt(typ), kontekst=kontekst,
                                    dodatki=DODATKI_WALKI if m['sport'] == 'walki' else '')
    if not kont and not ai_raport._szukanie['ok']: return None   # bez wyszukiwania i bez nagłówków AI nie ma z czego pisać
    txt, zr, szukal = ai_raport._zapytaj(t(szukaj), t(ai_raport.BEZ_SZUKANIA))
    if not txt: return None
    try: d = ai_raport._wyciagnij_json(txt)
    except Exception: d = None
    if not d or not d.get('podsumowanie'): return None
    ai_raport.STAN['udane'] += 1; ai_raport.analiz_dzis(1)
    w = ai_raport.pilnuj_werdyktu(ai_raport.werdykt_z(d) if typ else None, szukal, zr, d)
    if w: ai_raport.STAN['werdykty'][w] = ai_raport.STAN['werdykty'].get(w, 0) + 1
    L = lambda k: [str(x)[:120] for x in (d.get(k) or []) if x][:6]
    out = dict(tekst=str(d['podsumowanie'])[:700], problemy_a=L('problemy_a'), problemy_b=L('problemy_b'),
               ostrzezenie=bool(d.get('ostrzezenie')), ostrzezenie_dla=str(d.get('ostrzezenie_dla') or 'brak'),
               uzasadnienie=str(d.get('uzasadnienie') or '')[:200], zrodla=zr[:5], szukal=bool(szukal), werdykt=w,
               powod=str(d.get('powod') or '')[:220], forma=str(d.get('forma') or '')[:260], styl=str(d.get('styl') or '')[:260],
               lepszy_zaklad=str(d.get('lepszy_zaklad') or '')[:160], typ=typ[0] if typ else None, czas=teraz().strftime('%H:%M'))
    if m['sport'] == 'walki' and zr:   # oceny stylu i bilans tylko, gdy AI miało źródła
        oc = d.get('oceny') or {}
        def ok(x):
            try: return {k: max(1, min(10, int(x[k]))) for k in ('stojka', 'zapasy', 'parter', 'kondycja')}
            except Exception: return None
        if isinstance(oc, dict) and ok(oc.get('a') or {}) and ok(oc.get('b') or {}): out['oceny'] = dict(a=ok(oc['a']), b=ok(oc['b']))
        if d.get('rundy') in (3, 5, '3', '5'): out['rundy'] = int(d['rundy'])
        for k in ('bilans_a', 'bilans_b'):
            v = str(d.get(k) or '').strip()
            if re.fullmatch(r'\d{1,2}-\d{1,2}(-\d{1,2})?', v): out[k] = v
    return out

def dodaj_raporty(mecze, kolejnosc):
    """Nagłówki + analiza AI: najpierw kandydaci do Pewnych i Value, potem pozostałe mecze/walki z listy (limit kosztu)."""
    limit = min(ai_raport.AI_INNE, ai_raport.zostalo_analiz())
    for i, m in enumerate(kolejnosc):
        if i >= max(limit, 6): break
        m['naglowki'] = {'a': naglowki(m['a'], polskie=bool(m.get('rynek_pl'))), 'b': naglowki(m['b'], polskie=bool(m.get('rynek_pl')))}
        ai = raport_ai(m, m['polski']) if i < limit else None
        ost = None
        if ai and ai['ostrzezenie']:
            kto = {'a': m['a'], 'b': m['b'], 'oba': 'obu zawodników'}.get(ai['ostrzezenie_dla'], '')
            ost = f"Uwaga ({kto}): {ai['uzasadnienie']}" if kto else ai['uzasadnienie']
        m['raport'] = dict(ai=ai, ostrzezenie=ost, werdykt=(ai or {}).get('werdykt'))
        if ai and m['sport'] == 'walki' and m.get('rynek_pl') and ai.get('rundy') and ai['rundy'] != m.get('rundy'):
            przelicz_rundy(m, ai['rundy'] == 5, 'wg analizy AI')

# ---------------- dziennik ----------------
KOLUMNY = ['data', 'sport', 'dyscyplina', 'sport_key', 'turniej', 'event_id', 'start', 'a', 'b', 'rodzaj', 'poziom', 'klucz', 'zaklad',
           'szansa', 'kurs', 'bo', 'wynik', 'trafiony', 'zysk_na_1zl', 'status', 'ai', 'nizsza']

def wczytaj_typy():
    try: return pd.read_csv(PLIK_TYPOW, dtype={'event_id': str, 'wynik': str, 'status': str, 'klucz': str}, keep_default_na=False, na_values=[''])
    except FileNotFoundError: return pd.DataFrame(columns=KOLUMNY)

def zapisz_typy(nowe):
    """Dopisuje typy do dziennika. Typ tego samego meczu i poziomu, który już jest w dzienniku, zostaje zastąpiony nowym TYLKO
    tego samego dnia programu, gdy stary nie jest rozliczony i nowe typy pójdą na Telegram (poza nocą) – żeby dziennik
    rozliczał dokładnie to, co dostałeś."""
    d = wczytaj_typy(); n = pd.DataFrame(nowe, columns=KOLUMNY)
    if not len(n): return
    if len(d):
        bylo = set(zip(d.event_id.astype(str), d.rodzaj, d.poziom.astype(str), d.klucz.astype(str)))
        n = n[[(str(a), b, str(c), str(k)) not in bylo for a, b, c, k in zip(n.event_id, n.rodzaj, n.poziom, n.klucz)]]
        stare = {(str(a), b, str(c)): (str(dz), pd.isna(t) and pd.isna(z) and pd.isna(st))
                 for a, b, c, dz, t, z, st in zip(d.event_id, d.rodzaj, d.poziom, d.data, d.trafiony, d.zysk_na_1zl, d.status)}
        wolno = wspolne.mozna_podmienic_typy()
        zastap, zostaw = set(), []
        for i, r in n.iterrows():
            k = (str(r.event_id), r.rodzaj, str(r.poziom))
            if k not in stare: zostaw.append(i); continue
            dz, otwarty = stare[k]
            if wolno and otwarty and dz == str(r.data): zastap.add(k); zostaw.append(i)
        n = n.loc[zostaw]
        if zastap:
            d = d[[(str(a), b, str(c)) not in zastap for a, b, c in zip(d.event_id, d.rodzaj, d.poziom)]]
    if len(n): pd.concat([d, n], ignore_index=True).to_csv(PLIK_TYPOW, index=False)

def wiersze_do_dziennika(sp, pewne, mecze, odradzane=()):
    out, dz = [], wspolne.dzien_str()
    base = lambda m: dict(data=dz, sport=sp, dyscyplina=m['dyscyplina'], sport_key=m['sport_key'], turniej=m['turniej'], event_id=m['event_id'],
                          start=m['start'], a=m['a'], b=m['b'], bo=m.get('bo'), ai=werdykt(m) or '')
    for m in pewne:
        for poz in ('najpewniejszy', 'lepszy_kurs', 'ryzykowny'):
            t = m.get(poz)
            if t: out.append(dict(base(m), rodzaj='pewne', poziom=poz, klucz=t['klucz'], zaklad=t['zaklad'], szansa=t['szansa'],
                                  nizsza=bool(m.get('nizsza_pewnosc')) and poz == 'najpewniejszy'))
    for m in odradzane:   # nie gramy – zapis pokaże, czy AI miało rację
        t = m.get('najpewniejszy')
        if t: out.append(dict(base(m), rodzaj='odradzane', poziom='najpewniejszy', klucz=t['klucz'], zaklad=t['zaklad'], szansa=t['szansa'], nizsza=False))
    for m in mecze:
        for v in m.get('value', []): out.append(dict(base(m), rodzaj='value', poziom='value', klucz=v['klucz'], zaklad=v['zaklad'], szansa=v['szansa'], kurs=v['kurs'], nizsza=False))
    return out

# ---------------- wyniki (ESPN, zapasowo The Odds API) ----------------
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/{s}/scoreboard'
_espn = {}
def _pojedynki(j):
    """Wszystkie pojedynki (competitions z 2 zawodnikami) w odpowiedzi ESPN – tenis i MMA mają zagnieżdżoną strukturę."""
    out = []
    def idz(x):
        if isinstance(x, dict):
            c = x.get('competitors')
            if isinstance(c, list) and len(c) == 2 and all(isinstance(z, dict) for z in c): out.append(x)
            for v in x.values(): idz(v)
        elif isinstance(x, list):
            for v in x: idz(v)
    idz(j); return out

def _osoba(c):
    a = c.get('athlete') or c.get('team') or {}
    return a.get('displayName') or a.get('fullName') or a.get('shortName') or ''

def _teksty(x, acc):
    if isinstance(x, dict):
        for k, v in x.items():
            if k in ('competitors', 'links', 'logo', 'headshot', 'flag'): continue
            _teksty(v, acc)
    elif isinstance(x, list):
        for v in x: _teksty(v, acc)
    elif isinstance(x, str): acc.append(x)
    return acc

WAGI_ESPN = sorted(walki.KONCZENIE['wc'], key=len, reverse=True)   # kategorie wagowe (najpierw „Women's …”, „Light Heavyweight”)

def _rundy_espn(c):
    """Liczba rund walki z ESPN (pole format.regulation.periods – różne warianty), None gdy brak."""
    for f in (c.get('format'), (c.get('type') or {}).get('format') if isinstance(c.get('type'), dict) else None):
        if isinstance(f, dict):
            for k in ('regulation', 'overtime'):
                v = (f.get(k) or {}).get('periods') if isinstance(f.get(k), dict) else None
                if isinstance(v, (int, float)) and int(v) in (3, 5): return int(v)
            v = f.get('periods') or f.get('rounds')
            if isinstance(v, (int, float)) and int(v) in (3, 5): return int(v)
    for k in ('rounds', 'scheduledRounds', 'numberOfRounds'):
        v = c.get(k)
        if isinstance(v, (int, float)) and int(v) in (3, 5): return int(v)
    return None

def espn_dzien(sciezka, data_ny):
    k = (sciezka, data_ny)
    if k in _espn and time.time() - _espn[k][0] < 50: return _espn[k][1]
    try: j = requests.get(ESPN.format(s=sciezka), params={'dates': data_ny}, timeout=20).json()
    except Exception as e: _blad(f'ESPN {sciezka}: {e}'); j = {}
    out = []
    pary = [(c, e.get('name') or e.get('shortName') or '', str(e.get('id') or '')) for e in (j.get('events') or []) for c in _pojedynki(e)] \
        or [(c, '', '') for c in _pojedynki(j)]
    ostatnie = {}   # najpóźniejsza walka każdej gali = walka wieczoru
    for c, _, eid in pary:
        t = str(c.get('date') or c.get('startDate') or '')
        if t and t > ostatnie.get(eid, ''): ostatnie[eid] = t
    for c, turniej, eid in pary:
        z = c['competitors']; st = (c.get('status') or {}); ty = st.get('type') or {}
        txt = ' '.join(_teksty(st, [])).lower() + ' ' + ' '.join(_teksty(c.get('notes') or [], [])).lower()
        opis_walki = ' '.join(_teksty({k: v for k, v in c.items() if k not in ('status', 'competitors')}, [])).lower()
        gemy = [[s.get('value') for s in (x.get('linescores') or [])] for x in z]
        start = c.get('date') or c.get('startDate')
        waga = next((w for w in WAGI_ESPN if w.lower() in opis_walki), None)
        out.append(dict(a=_osoba(z[0]), b=_osoba(z[1]), wygral=[bool(x.get('winner')) for x in z], gemy=gemy, stan=ty.get('state', 'pre'),
                        koniec=bool(ty.get('completed')) or ty.get('state') == 'post', opis=txt, start=start,
                        id=str(c.get('id') or ''), turniej=turniej, sciezka=sciezka, rundy=_rundy_espn(c),
                        tytul=bool(re.search(r'title|championship|\bbelt\b', opis_walki)) and 'contender' not in opis_walki,
                        ostatnia=bool(start) and str(start) == ostatnie.get(eid) and sum(1 for x in pary if x[2] == eid) >= 3, waga=waga))
    _espn[k] = (time.time(), out)
    return out

def rundy_walki(m):
    """(czy 5 rund, skąd wiadomo, kategoria z ESPN). Kolejno: liczba rund z ESPN; walka o pas; walka wieczoru gali UFC/PFL
    (ostatnia na karcie, bez Contender Series); w pozostałych przypadkach 3 rundy."""
    r5, zr, waga = _rundy_walki(m)
    klucz = zr.split('(')[-1].rstrip(')') if '(' in zr else zr   # do status.json: skąd program wziął liczbę rund
    STAN['rundy'][klucz] = STAN['rundy'].get(klucz, 0) + 1
    return r5, zr, waga

def _rundy_walki(m):
    try: x, _ = znajdz_espn(m)
    except Exception as e: _blad(f'ESPN rundy: {e}'); x = None
    if not x: return False, '3 rundy (brak walki w ESPN – przyjęto)', None
    gala = (x.get('turniej') or '').lower()
    if x.get('rundy') in (3, 5): return x['rundy'] == 5, f"{x['rundy']} rund (ESPN)" if x['rundy'] == 5 else '3 rundy (ESPN)', x.get('waga')
    if x.get('tytul'): return True, '5 rund (walka o pas)', x.get('waga')
    if x.get('ostatnia') and x.get('sciezka') in ('mma/ufc', 'mma/pfl') and 'contender' not in gala:
        return True, '5 rund (walka wieczoru)', x.get('waga')
    return False, '3 rundy', x.get('waga')

def _sciezki(m):
    if m['sport'] == 'tenis': return ['tennis/atp', 'tennis/wta']
    return ['mma/ufc', 'mma/pfl', 'mma/bellator'] if m.get('dyscyplina') == 'MMA' else ['mma/ufc']   # boks: zapasowo Odds API

def znajdz_espn(m):
    t = pd.Timestamp(m['start']).tz_localize('Europe/Warsaw').tz_convert('America/New_York')
    for s in _sciezki(m):
        for dd in (0, -1, 1):
            for x in espn_dzien(s, (t + pd.Timedelta(days=dd)).strftime('%Y%m%d')):
                if ta_sama_osoba(x['a'], m['a']) and ta_sama_osoba(x['b'], m['b']): return x, False
                if ta_sama_osoba(x['a'], m['b']) and ta_sama_osoba(x['b'], m['a']): return x, True
    return None, False

def _set_skonczony(a, b):
    a, b = int(a), int(b)
    return (max(a, b) >= 6 and abs(a - b) >= 2) or max(a, b) == 7

def sety(x, odwr, krecz=False):
    """Wygrane sety (A, B) z gemów ESPN; tylko zakończone sety (w trakcie meczu bez ostatniego; przy kreczu bez niedokończonego)."""
    ga, gb = (x['gemy'][1], x['gemy'][0]) if odwr else (x['gemy'][0], x['gemy'][1])
    n = min(len(ga), len(gb)); sa = sb = 0; wyn = []
    for i in range(n):
        a, b = ga[i], gb[i]
        if a is None or b is None: continue
        if not x['koniec'] and i == n - 1: break
        if krecz and not _set_skonczony(a, b): wyn.append(f'{int(a)}:{int(b)}'); continue
        if a > b: sa += 1
        elif b > a: sb += 1
        wyn.append(f'{int(a)}:{int(b)}')
    return sa, sb, wyn

def wynik_meczu(m, x, odwr):
    """(status, wynik_do_rozliczenia, opis). status: 'ok' | 'krecz' | 'walkower' | 'remis' | None (nieznane)."""
    wa, wb = (x['wygral'][1], x['wygral'][0]) if odwr else (x['wygral'][0], x['wygral'][1])
    o = x['opis']
    if not (wa or wb):   # bez zwycięzcy: odwołany / przełożony (ESPN oznacza go jako „zakończony”)
        if re.search(r'cancel', o): return 'odwolany', None, 'mecz odwołany'
        if re.search(r'postpon|suspend|delay', o): return 'przelozony', None, 'mecz przełożony'
    if m['sport'] == 'tenis':
        if re.search(r'walkover|w/o|\bwo\b', o): return 'walkower', None, 'walkower'
        if re.search(r'retire|\bret\b|abandon|default', o):
            sa, sb, wyn = sety(x, odwr, krecz=True)
            return 'krecz', ('A' if wa else 'B' if wb else None, sa, sb), f"krecz – {sa}:{sb} w setach ({' '.join(wyn)})"
        sa, sb, wyn = sety(x, odwr)
        if not (wa or wb): return None, None, ''
        return 'ok', ('A' if wa else 'B', sa, sb), f"{sa}:{sb} ({' '.join(wyn)})"
    if re.search(r'\bdraw\b|no contest|\bnc\b', o): return 'remis', None, 'remis / no contest'
    if not (wa or wb): return None, None, ''
    kto = 'A' if wa else 'B'
    if re.search(r'decision|\bdec\b|\bu-?dec\b|\bs-?dec\b|\bm-?dec\b|points', o): met = 'PKT'
    elif re.search(r'\bko\b|tko|knockout|submission|\bsub\b|\bdq\b|disqualif|doctor|stoppage|\brtd\b|retire', o): met = 'KO'
    else: met = None
    return 'ok', (kto, met), f"wygrał {m['a'] if kto == 'A' else m['b']}" + (f" ({'przed czasem' if met == 'KO' else 'na punkty'})" if met else '')

def ocen(klucz, sport, bo, w):
    """1.0 / 0.0 albo None (nie da się rozstrzygnąć, np. nieznany sposób zwycięstwa)."""
    if sport == 'tenis':
        kto, sa, sb = w
        n = int(bo or 3) // 2 + 1
        if (sa, sb) not in [(n, i) for i in range(n)] + [(i, n) for i in range(n)]:   # sety niepełne – tylko zwycięzca
            return (1.0 if klucz == kto else 0.0) if klucz in ('A', 'B') else None
        rk = tenis.rynki({(n, i): 0 for i in range(n)} | {(i, n): 0 for i in range(n)}, int(bo or 3))
        return 1.0 if (sa, sb) in rk.get(klucz, set()) else 0.0
    kto, met = w
    if klucz in ('A', 'B'): return 1.0 if klucz == kto else 0.0
    if met is None: return None
    rk = walki.rynki({('A', 'KO'): 0, ('A', 'PKT'): 0, ('B', 'KO'): 0, ('B', 'PKT'): 0})
    return 1.0 if (kto, met) in rk.get(klucz, set()) else 0.0

def _odds_api_wyniki(keys):
    """Zapasowo (2 kredyty na turniej/galę): zwycięzca z The Odds API – gdy ESPN nie ma meczu (np. boks)."""
    out = {}
    for k in keys:
        if (core.KREDYTY['pozostalo'] or 0) < 60: break
        try:
            for s in core.api(f'sports/{k}/scores', daysFrom=3):
                if s.get('completed') and s.get('scores'):
                    sc = {x['name']: float(x['score']) for x in s['scores'] if x.get('score') not in (None, '')}
                    a, b = sc.get(s['home_team']), sc.get(s['away_team'])
                    if a is not None and b is not None and a != b: out[str(s['id'])] = 'A' if a > b else 'B'
        except Exception as e: _blad(f'wyniki {k}: {e}')
    return out

# ---------------- KSW: wyniki z Wikipedii (ESPN nie ma KSW) ----------------
_wiki = {}
def _wiki_ksw(rok):
    """Walki z tabel wyników na stronie „<rok> in Konfrontacja Sztuk Walki” (szablon MMAevent bout)."""
    if rok in _wiki: return _wiki[rok]
    out = []
    try:
        r = requests.get('https://en.wikipedia.org/w/index.php', params={'title': f'{rok}_in_Konfrontacja_Sztuk_Walki', 'action': 'raw'},
                         headers={'User-Agent': 'typer/1.0 (prywatny program; github.com/lewym90/typer)'}, timeout=30)
        if r.status_code == 200: out = parsuj_wiki_ksw(r.text)
    except Exception as e: _blad(f'Wikipedia KSW {rok}: {e}')
    _wiki[rok] = out
    return out

def _czysc_wiki(t):
    t = re.sub(r'<ref[^>]*/>|<ref[^>]*>.*?</ref>', '', t, flags=re.S)
    t = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', t)
    t = re.sub(r'\{\{[^{}]*\}\}', '', t)
    t = re.sub(r"'{2,}|\((?:c|ic)\)", '', t)
    return re.sub(r'\s+', ' ', t).strip()

def parsuj_wiki_ksw(tekst):
    """[dict(kat, zw, wynik ('def'|'vs'), prz, metoda)] z wierszy {{MMAevent bout|kategoria|A|def.|B|metoda|runda|czas|…}}."""
    out = []
    for m in re.finditer(r'\{\{\s*MMAevent bout\s*\|', tekst, flags=re.I):
        i, gl, j = m.end(), 1, m.end()
        while j < len(tekst) and gl:   # koniec szablonu (z zagnieżdżeniami)
            if tekst.startswith('{{', j): gl += 1; j += 2; continue
            if tekst.startswith('}}', j): gl -= 1; j += 2; continue
            j += 1
        cz, buf, g2 = [], '', 0
        for ch in tekst[i:j - 2]:
            if ch in '{[': g2 += 1
            elif ch in '}]': g2 -= 1
            if ch == '|' and g2 <= 0: cz.append(buf); buf = ''; continue
            buf += ch
        cz.append(buf)
        cz = [_czysc_wiki(c) for c in cz]
        if len(cz) >= 5 and cz[2].lower().rstrip('.') in ('def', 'vs'):
            out.append(dict(kat=cz[0], zw=cz[1], wynik=cz[2].lower().rstrip('.'), prz=cz[3], metoda=cz[4]))
    if not out:   # zapasowo: zwykła tabela wiki („| Waga || A || def. || B || Metoda || …”)
        for linia in tekst.splitlines():
            if '||' not in linia or not re.search(r'\|\|\s*(def|vs)\.?\s*\|\|', linia, re.I): continue
            cz = [_czysc_wiki(c) for c in linia.lstrip('|').split('||')]
            i = next((j for j, c in enumerate(cz) if c.lower().rstrip('.') in ('def', 'vs')), None)
            if i and i >= 1 and len(cz) > i + 2:
                out.append(dict(kat=cz[i - 2] if i >= 2 else '', zw=cz[i - 1], wynik=cz[i].lower().rstrip('.'), prz=cz[i + 1], metoda=cz[i + 2]))
    return out

def wynik_ksw(m):
    """(status, wynik_do_rozliczenia, opis) jak wynik_meczu() – z Wikipedii. Na Wikipedii zwycięzca stoi przed „def.”."""
    rok = pd.Timestamp(m['start']).year
    for w in _wiki_ksw(rok) + (_wiki_ksw(rok - 1) if pd.Timestamp(m['start']).month == 1 else []):
        for pierwszy, drugi, zwyc in ((w['zw'], w['prz'], 'A'), (w['prz'], w['zw'], 'B')):
            if not (ta_sama_osoba(pierwszy, m['a']) and ta_sama_osoba(drugi, m['b'])): continue
            met = w['metoda'].lower()
            if w['wynik'] == 'vs' or re.search(r'draw|no contest|\bnc\b', met): return 'remis', None, 'remis / no contest'
            if 'decision' in met: metoda = 'PKT'
            elif re.search(r'\bko\b|tko|submission|disqualif|\bdq\b|stoppage|retire', met): metoda = 'KO'
            else: metoda = None
            return 'ok', (zwyc, metoda), f"wygrał {m['a'] if zwyc == 'A' else m['b']}" + (f" ({'przed czasem' if metoda == 'KO' else 'na punkty'})" if metoda else '')
    return None, None, ''

def rozlicz(pelne=False):
    d = wczytaj_typy()
    if not len(d): return d
    now = teraz().tz_localize(None)
    do = d[d.trafiony.isna() & d.zysk_na_1zl.isna() & d.status.isna() & (pd.to_datetime(d.start) < now - pd.Timedelta(hours=1))]
    brak = []
    for eid, g in do.groupby('event_id'):
        r0 = g.iloc[0]; m = dict(sport=r0.sport, dyscyplina=r0.dyscyplina, start=r0.start, a=r0.a, b=r0.b)
        if r0.sport_key == 'ksw':
            st, w, op = wynik_ksw(m)
            if st is None: continue
        else:
            x, odwr = znajdz_espn(m)
            if not x or not x['koniec']:
                if pd.Timestamp(r0.start) < now - pd.Timedelta(hours=10): brak.append((eid, r0.sport_key))
                continue
            st, w, op = wynik_meczu(m, x, odwr)
        for i, r in g.iterrows():
            if st == 'przelozony': continue          # rozliczę, gdy zostanie rozegrany (albo po 7 dniach „brak wyniku”)
            if st == 'odwolany':
                d.loc[i, ['status', 'wynik']] = ['odwołany', op]
                if r.rodzaj == 'value': d.loc[i, 'zysk_na_1zl'] = 0.0
                continue
            if st in ('walkower', 'remis'):
                d.loc[i, ['status', 'wynik']] = [st, op]
                if r.rodzaj == 'value': d.loc[i, 'zysk_na_1zl'] = 0.0
                continue
            if st == 'krecz':   # zasady bukmacherów różne (Betclic: sprawdź regulamin) – typ nie wlicza się do skuteczności
                d.loc[i, ['status', 'wynik']] = ['krecz', op]; continue
            if st != 'ok': continue
            o = ocen(r.klucz, r.sport, r.bo, w)
            if o is None:
                if pd.Timestamp(r.start) < now - pd.Timedelta(days=4): d.loc[i, ['status', 'wynik']] = ['brak wyniku', op]
                continue
            d.loc[i, 'wynik'] = op; d.loc[i, 'trafiony'] = o
            if r.rodzaj == 'value': d.loc[i, 'zysk_na_1zl'] = round(float(r.kurs) - 1, 4) if o else -1.0
    if brak and pelne:   # zapasowo zwycięzca z The Odds API
        w = _odds_api_wyniki(sorted({k for _, k in brak}))
        for eid, _ in brak:
            if str(eid) not in w: continue
            for i, r in d[(d.event_id.astype(str) == str(eid)) & d.trafiony.isna() & d.status.isna()].iterrows():
                if r.klucz in ('A', 'B'):
                    o = 1.0 if r.klucz == w[str(eid)] else 0.0
                    d.loc[i, 'trafiony'] = o; d.loc[i, 'wynik'] = f"wygrał {r.a if w[str(eid)] == 'A' else r.b}"
                    if r.rodzaj == 'value': d.loc[i, 'zysk_na_1zl'] = round(float(r.kurs) - 1, 4) if o else -1.0
    for i, r in d[d.trafiony.isna() & d.zysk_na_1zl.isna() & d.status.isna()].iterrows():   # po 7 dniach bez wyniku – zamknij
        if pd.Timestamp(r.start) < now - pd.Timedelta(days=7): d.loc[i, 'status'] = 'brak wyniku'
    d.to_csv(PLIK_TYPOW, index=False)
    return d

def _grupa(g):
    return dict(n=int(len(g)), przewidywane=float(g.szansa.mean()), weszlo=float(g.trafiony.mean()), trafione=int(g.trafiony.sum())) if len(g) else None

def statystyki():
    d = wczytaj_typy(); out = {}
    if len(d):
        d['ai'] = d['ai'].fillna('').astype(str) if 'ai' in d else ''
        d['nizsza'] = d['nizsza'].fillna(False).astype(str).str.lower().isin(['true', '1', '1.0']) if 'nizsza' in d else False
    t30 = teraz().tz_localize(None) - pd.Timedelta(days=30); t90 = t30 - pd.Timedelta(days=60)
    for sp in ('tenis', 'walki'):
        g = d[d.sport == sp] if len(d) else d
        s = {}
        P = g[(g.rodzaj == 'pewne') & g.trafiony.notna()] if len(g) else g
        for poz in ('najpewniejszy', 'lepszy_kurs', 'ryzykowny'):
            x = P[P.poziom == poz] if len(P) else P
            if len(x): s[poz] = dict(n=len(x), traf=float(x.trafiony.mean()), przew=float(x.szansa.mean()))
        if len(P):
            G = P[(P.poziom == 'najpewniejszy') & ~P.nizsza]
            s['glowne'] = dict(wszystko=_grupa(G), d30=_grupa(G[pd.to_datetime(G.start) >= t30]), d90=_grupa(G[pd.to_datetime(G.start) >= t90]),
                               nizsza=_grupa(P[(P.poziom == 'najpewniejszy') & P.nizsza]))
        N = g[(g.poziom == 'najpewniejszy') & g.trafiony.notna()] if len(g) else g
        if len(N):
            s['ai'] = dict(zgoda=_grupa(N[(N.ai == 'zgoda') & (N.rodzaj == 'pewne')]), ryzyko=_grupa(N[(N.ai == 'ryzyko') & (N.rodzaj == 'pewne')]),
                           odradza=_grupa(N[N.rodzaj == 'odradzane']), bez_oceny=_grupa(N[(N.ai == '') & (N.rodzaj == 'pewne')]))
            if sp == 'walki':
                K = N[(N.sport_key == 'ksw') & (N.rodzaj == 'pewne')]
                s['ksw'] = dict(_grupa(K) or {}, potrzeba=KSW_DO_GLOWNYCH)
        V = g[(g.rodzaj == 'value') & g.zysk_na_1zl.notna()] if len(g) else g
        if len(V):
            roi = V.zysk_na_1zl.mean(); se = V.zysk_na_1zl.std() / np.sqrt(len(V)) if len(V) > 1 else None
            s['value'] = dict(n=len(V), trafione=int((V.zysk_na_1zl > 0).sum()), roi=float(roi), roi_dol=float(roi - 2 * se) if se else None,
                              roi_gora=float(roi + 2 * se) if se else None, zysk_10zl=float(V.zysk_na_1zl.sum() * 10))
        s['czeka'] = int((g.trafiony.isna() & g.zysk_na_1zl.isna() & g.status.isna() & (g.rodzaj != 'odradzane')).sum()) if len(g) else 0
        s['ostatnie'] = g.sort_values('start', ascending=False).head(60).replace({np.nan: None}).to_dict('records') if len(g) else []
        out[sp] = s
    return out

# Wyniki testów historycznych (liczone 29.09 na danych z GitHuba, jak w piłce – do pokazania w aplikacji)
TESTY = {'tenis': dict(opis='79 408 meczów ATP i WTA 2010–2026 (tennis-data.co.uk, kursy Pinnacle/Betfair); kobiety mają osobne parametry setów',
                       najpewniejszy=[0.735, 0.734, 77114], lepszy_kurs=[0.603, 0.598, 70882], ryzykowny=[0.354, 0.350, 40360],
                       pewne5=dict(przew=0.774, weszlo=0.773, dni=1515, wszystkie5=0.273, cztery=0.409, trzy=0.232, dwa_lub_mniej=0.085),
                       value='Pinnacle vs najlepszy kurs rynku ≥2%: +5,9% (±3,3) na 4 343 zakładach; vs Bet365 ≥3%: +4,3% (±12,6) na 388 – niepewne',
                       uwaga='Mężczyźni w Wielkim Szlemie: „handicap -1,5” = wygrana 3:0 lub 3:1. Kreczów nie liczymy do skuteczności.'),
         'walki': dict(opis='6 916 walk UFC 2010–2026 (kursy z ufc-master), test krokowy 2022–2026; 633 walki 5-rundowe',
                       faworyt68=[0.772, 0.781, 893], przed_czasem=[0.503, 0.500, 1899], rundy5=[0.595, 0.592, 633],
                       uwaga='Walki 5-rundowe (walka wieczoru, o pas) kończą się przed czasem częściej – program rozpoznaje je z ESPN. '
                             'Sposób zakończenia: model zna tylko kategorię wagową, nie styl zawodników – bukmacher wie tu więcej. '
                             'Boks: brak danych historycznych – szanse wprost z Pinnacle/Betfair, bez testu.')}

# ---------------- główne ----------------
def licz():
    """Pełne liczenie (ok. 7:10). Zwraca słownik do inne.json."""
    for s_ in ('tenis', 'walki'): STAN[s_] = {}
    STAN['rundy'] = {}
    dane = pobierz(); wynik = dict(wygenerowano=teraz().strftime('%Y-%m-%d %H:%M'), data=wspolne.dzien_str())
    nowe, wszystkie = [], {}
    for sp in ('tenis', 'walki'):
        mecze = []
        for key, tytul, grupa, ev in dane[sp]:
            try:
                e = przelicz(sp, key, tytul, grupa, ev)
                if e: mecze.append(e)
            except Exception as ex: _blad(f"{ev.get('home_team')} – {ev.get('away_team')}: {ex}")
        if sp == 'walki':
            try:
                ids = {(nrm(m['a']), nrm(m['b'])) for m in mecze}
                mecze += [k for k in ksw_mecze() if (nrm(k['a']), nrm(k['b'])) not in ids and (nrm(k['b']), nrm(k['a'])) not in ids]
            except Exception as ex: _blad(f'KSW: {ex}')
        mecze.sort(key=lambda m: m['start'])
        wszystkie[sp] = mecze
    # analiza AI: najpierw kandydaci do Pewnych obu dyscyplin, potem Value, potem reszta z listy
    kolejnosc = []
    for sp in ('tenis', 'walki'):
        pew0, _ = lista_pewnych(wszystkie[sp]); kolejnosc += pew0
    for sp in ('tenis', 'walki'): kolejnosc += [m for m in wszystkie[sp] if m['value'] and m not in kolejnosc]
    for sp in ('walki', 'tenis'): kolejnosc += [m for m in wszystkie[sp] if m not in kolejnosc]
    try: dodaj_raporty(wszystkie['tenis'] + wszystkie['walki'], kolejnosc)
    except Exception as ex: _blad(f'raporty: {ex}')
    for sp in ('tenis', 'walki'):
        mecze = wszystkie[sp]
        pewne, odradzane = lista_pewnych(mecze)   # ponownie – po ocenie AI
        value = [dict(v, **{k: m[k] for k in ('mecz', 'a', 'b', 'turniej', 'godzina', 'dzien', 'start', 'event_id', 'dyscyplina', 'sport', 'zrodlo')})
                 for m in mecze for v in m['value']]
        wynik[sp] = dict(pewne=[m['event_id'] for m in pewne], odradzane=odradzane, mecze=mecze, value=value)
        STAN[sp] = dict(turnieje=len({k for k, *_ in dane[sp]}), mecze=len(dane[sp]), z_kursami=len(mecze), pewne=len(pewne), value=len(value),
                        odradzane=len(odradzane), ksw=sum(1 for m in mecze if m.get('rynek_pl')))
        nowe += wiersze_do_dziennika(sp, pewne, mecze, odradzane)
    wynik['ksw_do_glownych'] = ksw_rozliczonych() >= KSW_DO_GLOWNYCH
    zapisz_typy(nowe)
    return wynik

def zapisz_json(wynik=None):
    """inne.json: typy dnia (gdy podane, inaczej zostają stare) + aktualny dziennik i wyniki testów."""
    try: stare = json.load(open(os.path.join(OUT, PLIK_JSON)))
    except Exception: stare = {}
    d = wynik or stare
    d['dziennik'] = statystyki(); d['testy'] = TESTY
    d['stan'] = dict(tenis=STAN['tenis'] or (stare.get('stan') or {}).get('tenis'), walki=STAN['walki'] or (stare.get('stan') or {}).get('walki'),
                     ksw=STAN.get('ksw'),
                     kredyty=STAN['kredyty'], pominiete=STAN['pominiete'][:6], bledy=STAN['bledy'][:6], czas=teraz().strftime('%Y-%m-%d %H:%M'))
    with open(os.path.join(OUT, PLIK_JSON), 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o))
    return d

def wczytaj_json():
    try: return json.load(open(os.path.join(OUT, PLIK_JSON)))
    except Exception: return {}

# ---------------- Telegram ----------------
IKONA = {'tenis': '🎾', 'walki': '🥊'}
NAZWA = {'tenis': 'Tenis', 'walki': 'Walki (MMA, boks)'}
POZ = (('najpewniejszy', '🔒'), ('lepszy_kurs', '⚖️'), ('ryzykowny', '🎯'))

def _pewne(d, sp):
    s = d.get(sp) or {}; byid = {m['event_id']: m for m in s.get('mecze', [])}
    return [byid[i] for i in s.get('pewne', []) if i in byid]

def tg_typy(d, status):
    """Osobna wiadomość dla tenisa i walk – raz dziennie (ponownie tylko przy zmianie typów), nie w nocy."""
    wyniki = []
    if teraz().hour < 7: return 'wstrzymane (noc)'
    for sp in ('tenis', 'walki'):
        P = _pewne(d, sp); V = (d.get(sp) or {}).get('value', [])
        if not P and not V: continue
        podpis = hashlib.md5(json.dumps([(m['event_id'], [(m.get(p) or {}).get('klucz') for p, _ in POZ]) for m in P] + [(v['event_id'], v['klucz']) for v in V]).encode()).hexdigest()[:12]
        wys = status.get(f'tg_{sp}') or {}
        if wys.get('data') == d.get('data') and wys.get('podpis') == podpis: wyniki.append(f'{sp}: bez zmian'); continue
        e = tg.esc
        lin = [f"{IKONA[sp]} <b>{NAZWA[sp]} – {'zaktualizowane typy' if wys.get('data') == d.get('data') else 'typy'} na {pd.Timestamp(d['data']).strftime('%d.%m')}</b>"]
        for i, m in enumerate(P, 1):
            extra = (f", kat. {m['kategoria']}" if m.get('kategoria') else '') + (f", {m['rundy_zrodlo']}" if m.get('rundy') == 5 else '')
            lin.append(f"\n<b>{i}. {e(m['mecz'])}</b> ({m['dzien']} {m['godzina']}, {e(m['turniej'])}{extra})")
            for poz, ik in POZ:
                t = m.get(poz)
                if t: lin.append(f"{ik} {e(t['zaklad'])} – {tg.pct(t['szansa'])} (kurs ≥ {tg.kurs(1 / t['szansa'])})")
            if m.get('nizsza_pewnosc'): lin.append('<i>niższa pewność – dobrany, żeby było 5 typów</i>')
            r = m.get('raport') or {}
            if r.get('ostrzezenie'): lin.append('⚠️ ' + e(r['ostrzezenie']))
            if (r.get('ai') or {}).get('tekst'): lin.append('📰 ' + e(r['ai']['tekst'][:300]))
        if V:
            lin.append('\n💰 <b>Value (Betclic)</b>')
            for v in V: lin.append(f"{e(v['mecz'])}: {e(v['zaklad'])} @ {tg.kurs(v['kurs'])} (szansa {tg.pct(v['szansa'])}, szukaj ≥ {tg.kurs(v['kurs_szukaj'])})")
        if sp == 'tenis': lin.append('\n<i>Krecz: rozliczenie zależy od regulaminu bukmachera.</i>')
        if tg.APLIKACJA: lin.append(f"📱 {tg.APLIKACJA}")
        if tg.wyslij_dlugi('\n'.join(lin)):
            status[f'tg_{sp}'] = dict(data=d.get('data'), podpis=podpis, czas=teraz().strftime('%H:%M')); wyniki.append(f'{sp}: wysłane')
        else: wyniki.append(f'{sp}: błąd wysyłki')
    return '; '.join(wyniki) or 'brak typów'

def starty_dla_straznika(d):
    """Starty wytypowanych meczów/walk (tenis: plan „nie wcześniej niż” – mecz może zacząć się kilka godzin później)."""
    if d.get('data') != wspolne.dzien_str(): return []
    out = []
    for sp in ('tenis', 'walki'):
        ids = set((d.get(sp) or {}).get('pewne', [])) | {v['event_id'] for v in (d.get(sp) or {}).get('value', [])}
        for m in (d.get(sp) or {}).get('mecze', []):
            if m['event_id'] in ids: out.append((sp, m['event_id'], pd.Timestamp(m['start'])))
    return out

# ---------------- na żywo (wywoływane przez strażnika co minutę) ----------------
SCIEZKI_OBS = {'t.atp': 'tennis/atp', 't.wta': 'tennis/wta', 'm.ufc': 'mma/ufc', 'm.pfl': 'mma/pfl', 'm.bellator': 'mma/bellator'}
def obserwowany_slug(slug): return slug in SCIEZKI_OBS

def znajdz_po_id(slug, eid):
    """Mecz/walka wskazana dzwonkiem 🔔 w aplikacji (ESPN id) – do listy obserwowanych."""
    sc = SCIEZKI_OBS.get(slug)
    for dni in (0, 1, -1):
        for x in espn_dzien(sc, (teraz() + pd.Timedelta(days=dni)).tz_convert('America/New_York').strftime('%Y%m%d')):
            if x['id'] == str(eid):
                st = pd.Timestamp(x['start']).tz_convert('Europe/Warsaw').strftime('%Y-%m-%d %H:%M') if x.get('start') else teraz().strftime('%Y-%m-%d %H:%M')
                return dict(dom=x['a'], gosc=x['b'], start=st, liga=x['turniej'] or sc)
    return None

def _obserwowane(stan):
    out = {}
    for o in stan.get('obserwowane', []):
        if not obserwowany_slug(o.get('slug', '')): continue
        sp = 'tenis' if o['slug'].startswith('t.') else 'walki'
        out[f"o_{o['slug']}_{o['id']}"] = dict(sport=sp, dyscyplina='Tenis' if sp == 'tenis' else 'MMA', a=o['dom'], b=o['gosc'], mecz=o['mecz'],
                                                start=o['start'], turniej=o.get('liga', ''), typy=[], bo=3, obserwowany=True)
    return out

def _sledzone(d):
    out = {}
    for sp in ('tenis', 'walki'):
        s = d.get(sp) or {}; ids = set(s.get('pewne', []))
        vals = {}
        for v in s.get('value', []): vals.setdefault(v['event_id'], []).append(v)
        for m in s.get('mecze', []):
            if m['event_id'] not in ids and m['event_id'] not in vals: continue
            typy = [(ik, m[p]['klucz'], m[p]['zaklad']) for p, ik in POZ if m['event_id'] in ids and m.get(p)]
            typy += [('💰', v['klucz'], f"{v['zaklad']} @ {tg.kurs(v['kurs'])}") for v in vals.get(m['event_id'], [])]
            out[m['event_id']] = dict(m, typy=typy)
    return out

def _stan_typu(m, klucz, w, koniec):
    """✅/❌ (rozstrzygnięty) albo ⏳ (jeszcze nie)."""
    if m['sport'] == 'tenis':
        kto, sa, sb = w; bo = int(m.get('bo') or 3); n = bo // 2 + 1
        mozliwe = [(x, y) for x in range(n + 1) for y in range(n + 1) if (x == n) != (y == n) and x >= sa and y >= sb]
        rk = tenis.rynki({(n, i): 0 for i in range(n)} | {(i, n): 0 for i in range(n)}, bo); s = rk.get(klucz, set())
        if koniec and (sa, sb) in rk['A'] | rk['B']: return '✅' if (sa, sb) in s else '❌'
        if mozliwe and all(x in s for x in mozliwe): return '✅'
        if not any(x in s for x in mozliwe): return '❌'
        return '⏳'
    if not koniec: return '⏳'
    o = ocen(klucz, 'walki', None, w)
    return '❔' if o is None else ('✅' if o else '❌')

ETYKIETA = {'✅': '✅ weszło', '❌': '❌ nie weszło', '❔': '❔ nie wiadomo, jak wygrał – rozliczę później', '↩️': '↩️ zwrot – nie liczy się', '⏳': '⏳ jeszcze w grze'}
ETYKIETA_W_TRAKCIE = {'✅': '✅ już weszło', '❌': '❌ już przegrany', '⏳': '⏳ w grze'}

def _linie_typow(m, oceny, w_trakcie=False):
    """Każdy typ w osobnej linii: „🔒 Learner Tien wygra min. 1 seta – ✅ weszło”."""
    et = ETYKIETA_W_TRAKCIE if w_trakcie else ETYKIETA
    return [f"{t[0]} {tg.esc(t[2])} – {et.get(o, o)}" for t, o in zip(m['typy'], oceny)]

def _naglowek_meczu(m):
    ik = IKONA[m['sport']] + (' 🔔' if m.get('obserwowany') else '')
    return f"{ik} <b>{tg.esc(m['mecz'])}</b>" + (f" · <i>{tg.esc(m['turniej'])}</i>" if m.get('turniej') else '')

def _linia_wyniku(m, st, w, op, x, odwr):
    e = tg.esc
    if st == 'ok' and m['sport'] == 'tenis':
        kto, sa, sb = w; _, _, wyn = sety(x, odwr)
        return f"Wynik: <b>{sa}:{sb}</b> w setach ({' '.join(wyn)}) · zwycięzca: <b>{e(m['a'] if kto == 'A' else m['b'])}</b>"
    if st == 'ok':
        kto, met = w
        return f"Wygrał(a) <b>{e(m['a'] if kto == 'A' else m['b'])}</b>" + (f" ({'przed czasem' if met == 'KO' else 'na punkty'})" if met else '')
    if st == 'krecz': return f"Krecz – {e(op)}. Rozliczenie wg regulaminu bukmachera (u nas się nie liczy)."
    if st == 'walkower': return 'Walkower – mecz się nie odbył. Zakłady zwykle zwracane (u nas się nie liczy).'
    if st == 'remis': return 'Remis / no contest – zakłady na zwycięzcę zwykle zwracane.'
    if st == 'odwolany': return 'Mecz odwołany – zakłady zwracane (u nas się nie liczy).'
    if st == 'przelozony': return 'Mecz przełożony – rozliczę, gdy zostanie rozegrany.'
    return 'Serwis wyników nie podał zwycięzcy – rozliczę, gdy wynik się pojawi.'

def obieg_na_zywo(stan, d):
    """Start, koniec każdego seta (tenis) i wynik. Zwraca (czy coś trwa, starty meczów jeszcze przed rozpoczęciem)."""
    S = stan.setdefault('inne', {}); trwa, przyszle = False, []
    SL = _sledzone(d); SL.update(_obserwowane(stan))
    for k in [k for k in S if k not in SL]: S.pop(k)
    teraz_ = teraz().tz_localize(None); starty, konce, sety_wiad = [], [], []
    for eid, m in SL.items():
        s = S.setdefault(eid, dict(stan='pre', sety=0))
        if s['stan'] == 'post': continue
        start = pd.Timestamp(m['start'])
        if start > teraz_ + pd.Timedelta(minutes=90): przyszle.append(start); continue
        try: x, odwr = znajdz_espn(m)
        except Exception as e: print('ESPN (inne):', e); x = None
        limit = pd.Timedelta(hours=7 if m['sport'] == 'tenis' else 4)
        if not x or x['stan'] == 'pre':
            if teraz_ < start + limit: przyszle.append(max(start, teraz_))   # tenis: mecz może zacząć się później niż w planie
            continue
        ik = IKONA[m['sport']] + (' 🔔' if m.get('obserwowany') else ''); e = tg.esc
        if x['stan'] == 'in':
            trwa = True
            if s['stan'] == 'pre': starty.append(f"• {ik} {e(m['mecz'])} <i>({e(m['turniej'])})</i>"); s['stan'] = 'in'
            if m['sport'] == 'tenis':
                sa, sb, wyn = sety(x, odwr)
                if sa + sb > s['sety']:
                    s['sety'] = sa + sb; w = (None, sa, sb)
                    lin = [f"🎾 <b>{e(m['mecz'])}</b> · po {sa + sb}. secie", f"<b>{sa}:{sb}</b> w setach ({' '.join(wyn)})"]
                    lin += _linie_typow(m, [_stan_typu(m, t[1], w, False) for t in m['typy']], w_trakcie=True)
                    sety_wiad.append('\n'.join(lin))
            continue
        if x['koniec']:
            st, w, op = wynik_meczu(m, x, odwr)
            if st is None:   # ESPN: koniec, ale bez zwycięzcy – chwilę czekamy, aż poda wynik
                od = s.setdefault('bez_wyniku', teraz_.strftime('%Y-%m-%d %H:%M'))
                if teraz_ < pd.Timestamp(od) + pd.Timedelta(minutes=30): trwa = True; continue
            s['stan'] = 'post'; s['wynik'] = op or {'przelozony': 'przełożony', 'odwolany': 'odwołany'}.get(st, 'brak wyniku')
            oceny = [_stan_typu(m, t[1], w, True) if st == 'ok' else '↩️' for t in m['typy']]
            if st in ('przelozony', None): oceny = ['⏳'] * len(m['typy'])
            blok = [_naglowek_meczu(m), _linia_wyniku(m, st, w, op, x, odwr)]
            if st in ('ok', 'krecz', 'walkower', 'remis', 'odwolany'): blok += _linie_typow(m, oceny)
            konce.append('\n'.join(blok))
            s['ocena'] = [(t[0], o) for t, o in zip(m['typy'], oceny) if o in ('✅', '❌', '↩️')]
    if starty: tg.wyslij('▶️ <b>Rozpoczęły się:</b>\n' + '\n'.join(starty))
    for w_ in sety_wiad: tg.wyslij(w_)
    if konce: tg.wyslij('🏁 <b>Koniec</b>\n\n' + '\n\n'.join(konce))
    # podsumowanie tenisa / walk – gdy wszystkie wytypowane się skończyły
    for sp in ('tenis', 'walki'):
        ids = [eid for eid, m in _sledzone(d).items() if m['sport'] == sp]
        if ids and all(S.get(i, {}).get('stan') == 'post' for i in ids) and stan.get(f'podsumowanie_{sp}') != d.get('data'):
            lin = [f"📊 <b>{IKONA[sp]} {NAZWA[sp]} – podsumowanie {pd.Timestamp(d.get('data') or wspolne.dzien_str()).strftime('%d.%m')}</b>", '']
            licz_ = {}
            for i in ids:
                m = _sledzone(d)[i]; oc = S[i].get('ocena', [])
                lin.append(f"<b>{tg.esc(m['mecz'])}</b> – {tg.esc(S[i].get('wynik', ''))}" + (f"\n   {'  '.join(a + b for a, b in oc)}" if oc else ''))
                for a, b in oc:
                    if b in '✅❌': licz_.setdefault(a, [0, 0]); licz_[a][0] += b == '✅'; licz_[a][1] += 1
            lin.append('')
            for ik, nz in (('🔒', 'najpewniejsze'), ('⚖️', 'lepszy kurs'), ('🎯', 'ryzykowne'), ('💰', 'value')):
                if ik in licz_: lin.append(f"{ik} {nz}: {licz_[ik][0]}/{licz_[ik][1]}")
            if tg.wyslij('\n'.join(lin)): stan[f'podsumowanie_{sp}'] = d.get('data')
    return trwa, przyszle
