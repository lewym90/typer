"""Archiwum kursów (wersja 37; wersja 41 – rozliczanie mecz po meczu, z ponawianiem; wersja 50 – Superbet jako drugi bukmacher, wyniki zapasowe z Flashscore) – rozliczanie odczytów Zbieracza i nauka „gdzie bukmacher się myli”.
Wejście: docs/data/archiwum/kursy/<data>_{rano,popoludnie,przed}.json.gz (z polskiego serwera, Fortuna, wszystkie rynki).
Piłka: wynik z FotMob (lista meczów dnia ze stanem i wynikiem), dopasowanie po czasie (±20 min) i nazwach (polskie ↔ angielskie),
każdy kurs rozliczany maską wyniku (te same klucze co w programie). Wynik: docs/data/archiwum/rozliczone/<data>.csv.gz
(mecz, rynek, kurs rano, kurs przed meczem, trafiony) i docs/data/archiwum/statystyki.json (trafność wobec kursu, zysk przy
stawianiu wszystkiego, ruch kursu – w podziale na rodzaj rynku, przedział kursu i ligę). Tenis i walki: zbierane, rozliczanie w kolejnej wersji."""
import os, re, json, gzip, glob, datetime as dt
import numpy as np, pandas as pd

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
KAT_K = os.path.join(OUT, 'archiwum', 'kursy')
KAT_R = os.path.join(OUT, 'archiwum', 'rozliczone')
PLIK_STAT = os.path.join(OUT, 'archiwum', 'statystyki.json')
STAN = dict(rozliczone_dni=[], meczow=0, dopasowanych=0, kursow=0, czeka=0, bez_wyniku=0, bledy=[])
PRZEDZIALY = [(1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 10.0), (10.0, 1000.0)]


def _blad(t):
    if len(STAN['bledy']) < 6: STAN['bledy'].append(str(t)[:160])


def kategoria(k):
    if k in ('1', 'X', '2'): return '1X2'
    if k in ('1X', 'X2', '12'): return 'podwójna szansa'
    if k.startswith(('Over', 'Under')): return 'gole w meczu'
    if k.startswith('BTTS &') or '&' in k: return 'wynik + gole'
    if k.startswith('BTTS'): return 'obie strzelą'
    if re.match(r'^[HA] -', k): return 'handicap'
    if re.match(r'^[HA] o', k): return 'gole drużyny'
    return 'inne'


def _wczytaj(sciezka):
    try:
        with gzip.open(sciezka, 'rt', encoding='utf-8') as f: return json.load(f)
    except Exception as e: _blad(f'{os.path.basename(sciezka)}: {e}'); return None


def fotmob_wyniki(dzien):
    """[(h, a, czas UTC, gole gosp., gole gości)] zakończonych meczów dnia (Warszawa) z FotMob."""
    import analityk
    out = []
    # wersja 48: także dzień wcześniej – FotMob grupuje mecze z Ameryk wg daty lokalnej (Boca 02.10 21:30 = 03.10 02:30 PL)
    for d in ((pd.Timestamp(dzien) - pd.Timedelta(days=1)).strftime('%Y-%m-%d'), dzien, (pd.Timestamp(dzien) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')):
        try: j = analityk._fm_get(f"{analityk.FM}/matches?date={d.replace('-', '')}&timezone=Europe%2FWarsaw&ccode3=POL")
        except Exception as e: _blad(f'FotMob {d}: {e}'); continue
        def chodz(o):
            if isinstance(o, dict):
                h, a, st = o.get('home'), o.get('away'), o.get('status') or {}
                if isinstance(h, dict) and isinstance(a, dict) and st.get('finished') and not st.get('cancelled'):
                    try:
                        gh, ga = h.get('score'), a.get('score')
                        if gh is None and st.get('scoreStr'): gh, ga = [int(x) for x in re.findall(r'\d+', st['scoreStr'])[:2]]
                        t = pd.Timestamp(st.get('utcTime')); t = t.tz_convert('UTC') if t.tzinfo else t.tz_localize('UTC')
                        out.append((h.get('longName') or h.get('name'), a.get('longName') or a.get('name'), t, int(gh), int(ga)))
                    except Exception: pass
                for v in o.values(): chodz(v)
            elif isinstance(o, list):
                for v in o: chodz(v)
        chodz(j)
    return out


_ZNACZNIKI = re.compile(r'\b(u\s?1[5-9]|u\s?2[0-3]|ii|iii|b|reserves?|rezerwy|\(k\)|\(w\)|women|kobiety|youth|juniors?)\b|\((k|w)\)', re.I)


def _znaczniki(n):
    return {re.sub(r'\s', '', x.group(0).lower()).replace('(w)', 'k').replace('(k)', 'k').replace('women', 'k').replace('kobiety', 'k')
            .replace('reserves', 'ii').replace('reserve', 'ii').replace('rezerwy', 'ii').replace('b', 'ii') for x in _ZNACZNIKI.finditer(str(n))}


import functools, bisect


@functools.lru_cache(maxsize=300000)
def _podobne(a, b):
    """Wersja 48: drużyny młodzieżowe/rezerwy/kobiece tylko z takimi samymi (U19 ≠ seniorzy), porównanie bez tych dopisków."""
    if _znaczniki(a) != _znaczniki(b): return 0.0
    a2, b2 = _ZNACZNIKI.sub(' ', str(a)).strip() or a, _ZNACZNIKI.sub(' ', str(b)).strip() or b
    return _podobne_(a2, b2)


def _podobne_(a, b):
    try:
        import kursy_pl as KP
        from nazwy import pl
        return max(KP.podobne_w(a, b), KP.podobne_w(a, pl(b)))
    except Exception:
        import difflib
        return difflib.SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()


def _wczytaj_odczyty(dni_wstecz=9):
    """Wszystkie odczyty piłki z ostatnich dni: id meczu Fortuny → dict(h, a, t, tur, rano, popoludnie, przed)."""
    dzis = pd.Timestamp.now(tz='Europe/Warsaw').normalize()
    odczyty = {}
    for i in range(dni_wstecz, -1, -1):
        d = (dzis - pd.Timedelta(days=i)).strftime('%Y-%m-%d')
        for p in sorted(glob.glob(os.path.join(KAT_K, f'{d}_*.json.gz'))):
            if '_superbet_' in p: continue            # wersja 50: Superbet ma własne rozliczenie (_wczytaj_superbet)
            z = _wczytaj(p)
            if not z or (z.get('buk') or 'fortuna') != 'fortuna': continue
            tryb = z.get('tryb') or os.path.basename(p).split('_', 1)[1].split('.')[0]
            for m in z.get('mecze') or []:
                if m.get('sp') != 'pilka' or not m.get('id') or not m.get('t'): continue
                o = odczyty.setdefault(m['id'], dict(h=m['h'], a=m['a'], t=m['t'], tur=m.get('tur', ''), buk='fortuna', rano={}, przed={}, popoludnie={}, zamk={}))
                o.setdefault(tryb, {}).update(m.get('k') or {})
    return odczyty


def sb_klucze(r, h, a):
    """Wersja 50: surowe rynki Superbetu z archiwum ([rynek, [[wynik, linia, kurs]]]) → nasze klucze (ten sam czytnik co przy typach)."""
    import kursy_pl as KP
    odds = [dict(marketName=rn, name=nz, specialBetValue=ln, price=c) for rn, wy in (r or []) for nz, ln, c in wy]
    try: return KP.klucze_pilka(odds, [], (h, a))
    except Exception as e: _blad(f'Superbet klucze: {e}'); return {}


def _wczytaj_superbet(dni_wstecz=9):
    """Wersja 50: mecze piłki z odczytów Superbetu (2× dziennie). Kurs „rano” = pierwszy odczyt przed startem,
    „przed” = ostatni odczyt przed startem (zwykle wieczorny – najbliżej zamknięcia)."""
    dzis = pd.Timestamp.now(tz='Europe/Warsaw').normalize()
    od = {}
    for i in range(dni_wstecz, -1, -1):
        d = (dzis - pd.Timedelta(days=i)).strftime('%Y-%m-%d')
        for p in sorted(glob.glob(os.path.join(KAT_K, f'{d}_superbet_*.json.gz'))):
            z = _wczytaj(p)
            if not z: continue
            for m in z.get('mecze') or []:
                if m.get('sp') != 'pilka' or not m.get('id') or not m.get('t') or not m.get('r'): continue
                if str(m.get('czas', '')) > str(m['t']): continue           # odczyt po starcie – pomijamy
                o = od.setdefault('sb:' + str(m['id']), dict(h=m['h'], a=m['a'], t=m['t'], tur='Superbet ' + str(m.get('tur', '')), buk='superbet',
                                                             odczyty=[]))
                o['odczyty'].append((str(m.get('czas', '')), m['r']))
    for o in od.values():
        o['odczyty'].sort(key=lambda x: x[0])
        o['rano'] = sb_klucze(o['odczyty'][0][1], o['h'], o['a'])
        o['przed'] = sb_klucze(o['odczyty'][-1][1], o['h'], o['a']) if len(o['odczyty']) > 1 else {}
        o['popoludnie'], o['zamk'] = {}, {}
        del o['odczyty']
    return od


def flash_pilka(dzien):
    """Wersja 50: zakończone mecze piłki z bazy wyników Flashscore (dni d−1…d+1) – zapas, gdy FotMob nie ma ligi.
    Wynik po 90 min (suma połów), gdy dostępny."""
    out = []
    for dd in ((pd.Timestamp(dzien) - pd.Timedelta(days=1)).strftime('%Y-%m-%d'), dzien, (pd.Timestamp(dzien) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')):
        p = os.path.join(OUT, 'archiwum', 'wyniki', f'{dd}.json.gz')
        if not os.path.exists(p): continue
        try:
            with gzip.open(p, 'rt', encoding='utf-8') as f: w = json.load(f).get('wyniki') or []
        except Exception: continue
        for x in w:
            if x.get('zr') != 'flash' or x.get('sp') != 'pilka' or not x.get('koniec') or x.get('gh') is None: continue
            try: t = pd.Timestamp(x['t']); t = t.tz_convert('UTC') if t.tzinfo else t.tz_localize('UTC')
            except Exception: continue
            gh, ga = (x.get('reg') or [x['gh'], x['ga']])[:2]
            out.append((x['h'], x['a'], t, int(gh), int(ga)))
    return out


def wyniki_dnia(dzien):
    """FotMob (główne) + Flashscore (zapas, niższe ligi)."""
    return fotmob_wyniki(dzien) + flash_pilka(dzien)


def wynik_meczu(gosp, gosc, start, _cache={}):
    """Wersja 50: wynik meczu dziennika (nazwy z The Odds API, start – czas polski 'YYYY-MM-DD HH:MM') z FotMob/Flashscore –
    za darmo, zamiast 2 kredytów na ligę. (gole gosp., gole gości) albo None."""
    try: t = pd.Timestamp(str(start)[:16]).tz_localize('Europe/Warsaw').tz_convert('UTC')
    except Exception: return None
    dzien = t.tz_convert('Europe/Warsaw').strftime('%Y-%m-%d')
    if dzien not in _cache:
        try: _cache[dzien] = wyniki_dnia(dzien)
        except Exception as e: _blad(f'wynik_meczu {dzien}: {e}'); _cache[dzien] = []
    best = None
    for h, a, tt, gh, ga in _cache[dzien]:
        dmin = abs((tt - t).total_seconds()) / 60
        if dmin > 150: continue
        sc = min(_podobne(gosp, h), _podobne(gosc, a))
        if ((dmin <= 20 and sc >= 0.6) or sc >= 0.8) and (best is None or sc > best[0]): best = (sc, gh, ga)
    return (best[1], best[2]) if best else None


def _juz_rozliczone():
    """(mecz, start) wszystkich meczów zapisanych już w archiwum/rozliczone (żeby nie liczyć dwa razy)."""
    zb = set()
    for p in glob.glob(os.path.join(KAT_R, '*.csv.gz')):
        try:
            d = pd.read_csv(p)
            buk = d['buk'].fillna('fortuna').astype(str) if 'buk' in d else pd.Series(['fortuna'] * len(d))
            zb |= set(zip(buk, d.mecz.astype(str), d.start.astype(str)))
        except Exception as e: _blad(f'{os.path.basename(p)}: {e}')
    return zb


def rozlicz(teraz=None, wyniki=None):
    """Wersja 41: rozliczanie meczu po meczu, a nie pliku dnia. Każdy mecz z odczytów (ostatnie 5 dni), który zaczął się
    ponad 2,5 h temu i nie ma go jeszcze w archiwum, dostaje wynik z FotMob (lista dnia startu, czas ±20 min i nazwy).
    Bez wyniku – próba przy kolejnym liczeniu, po 48 h od startu pominięty. Wiersze trafiają do pliku dnia startu
    (czas polski): docs/data/archiwum/rozliczone/<data>.csv.gz. wyniki = funkcja dzień → lista (do testów)."""
    from core import MASKI, MAXG
    teraz = teraz or pd.Timestamp.now(tz='UTC')
    wyniki = wyniki or wyniki_dnia
    odczyty = _wczytaj_odczyty()
    try: odczyty.update(_wczytaj_superbet())         # wersja 50: drugi bukmacher w archiwum
    except Exception as e: _blad(f'Superbet odczyty: {type(e).__name__}: {e}')
    gotowe = _juz_rozliczone()
    cache, nowe = {}, {}
    sb = STAN.setdefault('superbet', dict(meczow=0, dopasowanych=0, kursow=0))
    import time as _t; t_start = _t.time()
    for fid, o in odczyty.items():
        if _t.time() - t_start > 360: _blad('rozliczenie przerwane po 6 min (dokończy kolejne liczenie)'); break
        mecz = f"{o['h']} – {o['a']}"
        jest_sb = o.get('buk') == 'superbet'
        if (o.get('buk', 'fortuna'), mecz, str(o['t'])) in gotowe: continue
        if jest_sb and not (o['rano'] or o['przed']): continue
        t = pd.Timestamp(o['t']).tz_localize('UTC')
        if t > teraz - pd.Timedelta(hours=2.5):
            if not jest_sb: STAN['czeka'] = STAN.get('czeka', 0) + 1
            continue
        if t < teraz - pd.Timedelta(days=7):
            if not jest_sb: STAN['bez_wyniku'] = STAN.get('bez_wyniku', 0) + 1
            continue     # v46: 7 dni prób (było 48 h)
        dzien = t.tz_convert('Europe/Warsaw').strftime('%Y-%m-%d')
        if dzien not in cache:
            lst = sorted(wyniki(dzien), key=lambda x: x[2]); cache[dzien] = (lst, [x[2] for x in lst])
        if jest_sb: sb['meczow'] += 1
        else: STAN['meczow'] += 1
        best = None
        lst, czasy = cache[dzien]
        i0, i1 = bisect.bisect_left(czasy, t - pd.Timedelta(minutes=150)), bisect.bisect_right(czasy, t + pd.Timedelta(minutes=150))
        for h, a, tt, gh, ga in lst[i0:i1]:      # wersja 50: tylko mecze ±150 min (lista posortowana) – szybciej przy bazie Flashscore
            dmin = abs((tt - t).total_seconds()) / 60
            s1 = _podobne(o['h'], h)
            if s1 < 0.5 and dmin > 15: continue     # przy s1 < 0,5 dopasowanie możliwe tylko w regule ±15 min
            s2 = _podobne(o['a'], a); sc = min(s1, s2)
            # wersja 48: ±20 min i obie nazwy ≥0,5; do ±150 min przy nazwach ≥0,75 (różne godziny w źródłach);
            # albo jedna nazwa pewna (≥0,9) i druga ≥0,55 (np. „AD Cali” = „Deportivo Cali”)
            ok = (dmin <= 20 and sc >= 0.5) or (sc >= 0.75) or (max(s1, s2) >= 0.9 and sc >= 0.55) \
                or (dmin <= 15 and max(s1, s2) >= 0.98)      # v49: ta sama drużyna o tej samej porze („Boca Juniors – U.Santa Fe” = „Boca Juniors – Unión”)
            if ok and (best is None or sc > best[0]): best = (sc, gh, ga)
        if not best:                       # wersja 46: diagnostyka – co FotMob ma o tej porze (do poprawy dopasowania)
            if not jest_sb and len(STAN.setdefault('niedopasowane', [])) < 15:
                bl = sorted(((min(_podobne(o['h'], h), _podobne(o['a'], a)), h, a, round((tt - t).total_seconds() / 60))
                             for h, a, tt, gh, ga in lst if abs((tt - t).total_seconds()) <= 6 * 3600), reverse=True)[:1]
                STAN['niedopasowane'].append(f"{o['tur']}: {o['h']} – {o['a']} {o['t']}" + (f" | FotMob: {bl[0][1]} – {bl[0][2]} ({bl[0][0]:.2f}, {bl[0][3]:+d} min)" if bl else ' | FotMob: brak w ±6 h')
                                             + f" | lista dnia: {len(lst)}")
            continue
        if jest_sb: sb['dopasowanych'] += 1
        else: STAN['dopasowanych'] += 1
        _, gh, ga = best
        kursy_rano = o['rano'] or o['popoludnie']
        for k in set(kursy_rano) | set(o['przed']) | set(o['popoludnie']) | set(o['zamk']):
            if k not in MASKI: continue
            kr, kp_ = kursy_rano.get(k), o['przed'].get(k) or o['popoludnie'].get(k)
            nowe.setdefault(dzien, []).append(dict(data=dzien, buk=o.get('buk', 'fortuna'), liga=o['tur'], mecz=mecz, start=o['t'], rynek=k, kategoria=kategoria(k),
                                                   kurs_rano=kr, kurs_przed=kp_, kurs_zamk=o['zamk'].get(k), wynik=f'{gh}:{ga}',
                                                   trafiony=int(bool(MASKI[k][min(gh, MAXG), min(ga, MAXG)]))))
    os.makedirs(KAT_R, exist_ok=True)
    for dzien, w in sorted(nowe.items()):
        p = os.path.join(KAT_R, f'{dzien}.csv.gz')
        d = pd.DataFrame(w)
        if os.path.exists(p):
            try: d = pd.concat([pd.read_csv(p), d], ignore_index=True)
            except Exception as e: _blad(f'{dzien}: {e}')
        d['buk'] = d['buk'].fillna('fortuna') if 'buk' in d else 'fortuna'
        d = d.drop_duplicates(['buk', 'mecz', 'start', 'rynek'], keep='first')
        d.to_csv(p, index=False, compression='gzip')
        n_sb = sum(1 for x in w if x['buk'] == 'superbet')
        STAN['kursow'] += len(w) - n_sb; sb['kursow'] += n_sb; STAN['rozliczone_dni'].append(dzien)
    return sum(len(w) for w in nowe.values())


def statystyki():
    """Zbiorcze statystyki z całego archiwum: gdzie kurs bukmachera jest za wysoki (zysk przy stawianiu wszystkiego)."""
    pliki = sorted(glob.glob(os.path.join(KAT_R, '*.csv.gz')))
    if not pliki: return None
    d = pd.concat([pd.read_csv(p) for p in pliki], ignore_index=True)
    d['buk'] = d['buk'].fillna('fortuna') if 'buk' in d else 'fortuna'
    d['kurs'] = d.kurs_rano.fillna(d.kurs_przed)
    sb_ = d[d.buk == 'superbet']; d = d[d.buk == 'fortuna']     # wersja 50: główne liczby = Fortuna, Superbet osobno
    d = d[d.kurs > 1.0]
    d['przedzial'] = pd.cut(d.kurs, [a for a, _ in PRZEDZIALY] + [1000], right=False, labels=[f'{a:g}–{b:g}' if b < 1000 else f'{a:g}+' for a, b in PRZEDZIALY])
    def agr(g):
        z = np.where(g.trafiony == 1, g.kurs - 1, -1.0)
        clv = (g.kurs_rano / g.kurs_przed - 1).dropna()
        return dict(n=int(len(g)), meczow=int(g.mecz.nunique()), trafione=round(float(g.trafiony.mean()), 4),
                    z_kursu=round(float((1 / g.kurs).mean()), 4), roi=round(float(z.mean()), 4),
                    ruch_kursu=round(float(clv.mean()), 4) if len(clv) else None)
    wynik = dict(czas=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'), dni=len(pliki), meczow=int(d.mecz.nunique()), kursow=int(len(d)),
                 bukmacher='Fortuna', wszystko=agr(d))
    wynik['rynki'] = {k: agr(g) for k, g in d.groupby('kategoria')}
    wynik['rynki_kursy'] = [dict(kategoria=k[0], przedzial=str(k[1]), **agr(g)) for k, g in d.groupby(['kategoria', 'przedzial'], observed=True) if len(g) >= 30]
    lig = [dict(liga=k, **agr(g)) for k, g in d.groupby('liga') if g.mecz.nunique() >= 10]
    wynik['ligi_najlepsze'] = sorted(lig, key=lambda x: -x['roi'])[:10]
    wynik['okazje'] = sorted([x for x in wynik['rynki_kursy'] if x['n'] >= 200], key=lambda x: -x['roi'])[:8]
    sb_ = sb_[sb_.kurs > 1.0].copy()
    if len(sb_):
        sb_['przedzial'] = pd.cut(sb_.kurs, [a for a, _ in PRZEDZIALY] + [1000], right=False, labels=[f'{a:g}–{b:g}' if b < 1000 else f'{a:g}+' for a, b in PRZEDZIALY])
        wynik['superbet'] = dict(meczow=int(sb_.mecz.nunique()), kursow=int(len(sb_)), wszystko=agr(sb_),
                                 rynki={k: agr(g) for k, g in sb_.groupby('kategoria')},
                                 okazje=sorted([dict(kategoria=k[0], przedzial=str(k[1]), **agr(g)) for k, g in sb_.groupby(['kategoria', 'przedzial'], observed=True)
                                                if len(g) >= 200], key=lambda x: -x['roi'])[:8])
    try:
        import archiwum_inne; wynik['inne'] = archiwum_inne.statystyki()
    except Exception as e: _blad(f'statystyki inne: {e}')
    os.makedirs(os.path.dirname(PLIK_STAT), exist_ok=True)
    with open(PLIK_STAT, 'w', encoding='utf-8') as f: json.dump(wynik, f, ensure_ascii=False)
    return wynik


def dzienny():
    """Wołane przy pełnym liczeniu: rozlicza wszystkie mecze z odczytów, które już się skończyły (wersja 41), przelicza statystyki."""
    try: rozlicz()
    except Exception as e: _blad(f'rozliczenie: {type(e).__name__}: {e}')
    try:                                   # wersja 46: zbiornik wyników wszystkich dyscyplin (ESPN + FotMob)
        import wyniki_zbior; STAN['wyniki'] = wyniki_zbior.zbierz()
    except Exception as e: _blad(f'zbiornik wyników: {type(e).__name__}: {e}')
    try:                                   # wersja 49: rozliczanie kursów pozostałych sportów (tenis, walki, hokej, kosz…)
        import archiwum_inne; r = archiwum_inne.rozlicz()
        STAN['inne'] = dict(dopasowanych=r['dopasowanych'], meczow=r['meczow'], kursow=r['kursow'], sporty=archiwum_inne.statystyki(), bledy=r['bledy'][:5])
    except Exception as e: _blad(f'archiwum inne sporty: {type(e).__name__}: {e}')
    try:                                   # wersja 43: skaner składów – braki vs kurs i wynik
        import sklady_lab; STAN['sklady'] = sklady_lab.licz()
    except Exception as e: _blad(f'skaner składów: {type(e).__name__}: {e}')
    try: st = statystyki()
    except Exception as e: _blad(f'statystyki: {e}'); st = None
    if st:
        try:
            pd_ = os.path.join(OUT, 'dziennik.json'); dz = json.load(open(pd_)) if os.path.exists(pd_) else {}
            dz['archiwum'] = skrot(st)
            with open(pd_, 'w', encoding='utf-8') as f: json.dump(dz, f, ensure_ascii=False)
        except Exception as e: _blad(f'dziennik.json: {e}')
    return st


def skrot(st=None):
    """Krótka wersja statystyk do aplikacji (Dziennik)."""
    if st is None:
        try: st = json.load(open(PLIK_STAT))
        except Exception: return None
    return {k: st.get(k) for k in ('czas', 'dni', 'meczow', 'kursow', 'bukmacher', 'wszystko', 'rynki', 'okazje', 'ligi_najlepsze', 'superbet', 'inne')}
