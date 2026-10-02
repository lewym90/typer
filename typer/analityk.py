"""Analityk – korekty szans z czynników, których rynek nie wycenia w pełni (wersja 34).
Wielkości z testów na archiwum (sekcja 37 podsumowania), przycięte o ok. 30% (ostrożnie – próby po 1–5 tys.):
  ⚽ piłka (FotMob – braki w kadrze z wartością zawodników): 2 ważnych poza kadrą −0,8 pkt szansy wygranej,
     3 → −1,2, 4+ → −1,7, najlepszy zawodnik poza kadrą dodatkowo −0,8 (razem maks. −2,5);
  🎾 tenis (ESPN – ostatnie mecze): zawodnik po przerwie ≥30 dni przeciw rywalowi, który grał <14 dni temu: 37,1% → 35,0%;
  🥊 MMA (ufc-master – wiek, ostatnia walka): młodszy o ≥6 lat 59,7 → 63,4%; ≥35 lat przeciw <30: 38,1 → 34,6%;
     przerwa ≥400 dni 46,5 → 43,8%.
Każda korekta zapisuje powód (widoczny w aplikacji), a STAN trafia do status.json (czy źródła działają)."""
import os, io, json, time, datetime as dt
import numpy as np, pandas as pd, requests

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
STAN = dict(pilka=dict(fotmob=None, mecze=0, dopasowane=0, z_korekta=0), tenis=dict(baza=None, z_korekta=0),
            walki=dict(baza=None, z_korekta=0), bledy=[])
SILA = 0.7                                            # część efektu z testu, którą stosujemy
_lg = lambda p: float(np.log(p / (1 - p)))
_sg = lambda z: float(1 / (1 + np.exp(-z)))


def _blad(t):
    if len(STAN['bledy']) < 8: STAN['bledy'].append(str(t)[:160])


def stan():
    return STAN


# =============================================================== PIŁKA (FotMob)
FM = 'https://www.fotmob.com/api/data'
_fm_lista, _fm_mecz = {}, {}
BRAKI_DP = {2: 0.008, 3: 0.012}                       # liczba ważnych poza kadrą → spadek szansy wygranej
BRAKI_4 = 0.017; NAJLEPSZY_DP = 0.008; MAKS_DP = 0.025


def _fm_get(url):
    r = requests.get(url, timeout=15, headers={'User-Agent': UA, 'Referer': 'https://www.fotmob.com/', 'Accept': 'application/json'})
    if r.status_code != 200: raise RuntimeError(f'FotMob {r.status_code}')
    return r.json()


def _fm_mecze_z(o, out):
    if isinstance(o, dict):
        h, a = o.get('home'), o.get('away')
        if o.get('id') and isinstance(h, dict) and isinstance(a, dict) and (h.get('name') or h.get('longName')):
            st = o.get('status') or {}
            t = st.get('utcTime') or o.get('time')
            try: t = pd.Timestamp(t).tz_convert('UTC') if pd.Timestamp(t).tzinfo else pd.Timestamp(t).tz_localize('UTC')
            except Exception: t = None
            out[str(o['id'])] = (str(o['id']), h.get('longName') or h.get('name'), a.get('longName') or a.get('name'), t)
        for v in o.values(): _fm_mecze_z(v, out)
    elif isinstance(o, list):
        for v in o: _fm_mecze_z(v, out)
    return out


def fotmob_dzien(data):
    """Mecze FotMob danego dnia (data w Warszawie, 'YYYYMMDD')."""
    if data in _fm_lista: return _fm_lista[data]
    try:
        j = _fm_get(f'{FM}/matches?date={data}&timezone=Europe%2FWarsaw&ccode3=POL')
        _fm_lista[data] = list(_fm_mecze_z(j, {}).values()); STAN['pilka']['fotmob'] = 'działa'
    except Exception as e:
        _fm_lista[data] = []; STAN['pilka']['fotmob'] = f'błąd: {str(e)[:80]}'; _blad(f'FotMob lista {data}: {e}')
    return _fm_lista[data]


def _podobne(a, b):
    try:
        import kursy_pl as KP
        return KP.podobne_w(a, b)
    except Exception:
        import difflib
        return difflib.SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()


def fotmob_szukaj(home, away, start):
    """(id FotMob, odwrócone) dla naszego meczu (start: Timestamp z czasem Warszawy)."""
    t = pd.Timestamp(start); t_utc = t.tz_convert('UTC') if t.tzinfo else t.tz_localize('Europe/Warsaw').tz_convert('UTC')
    best = None
    for d in {t.strftime('%Y%m%d'), (t - pd.Timedelta(days=1)).strftime('%Y%m%d')}:
        for mid, h, a, tt in fotmob_dzien(d):
            if tt is None or abs((tt - t_utc).total_seconds()) > 40 * 60: continue
            s1 = min(_podobne(home, h), _podobne(away, a)); s2 = min(_podobne(home, a), _podobne(away, h))
            s, odw = (s1, False) if s1 >= s2 else (s2, True)
            if s >= 0.55 and (best is None or s > best[2]): best = (mid, odw, s)
    return (best[0], best[1]) if best else (None, False)


def fotmob_szczegoly(mid):
    if mid in _fm_mecz: return _fm_mecz[mid]
    try: _fm_mecz[mid] = _fm_get(f'{FM}/matchDetails?matchId={mid}')
    except Exception as e: _fm_mecz[mid] = None; _blad(f'FotMob mecz {mid}: {e}')
    return _fm_mecz[mid]


def braki_druzyny(t):
    """Ważni zawodnicy poza kadrą (kontuzja/kara; bez „niepewnych”): ważny = wartość ≥ mediany jedenastki."""
    if not isinstance(t, dict): return None
    wart = [float(s.get('marketValue') or 0) for s in (t.get('starters') or []) if isinstance(s, dict)]
    wart = [w for w in wart if w > 0]
    if len(wart) < 7: return None                          # bez wartości zawodników nie oceniamy
    med, maks = float(np.median(wart)), max(wart)
    U = [u for u in (t.get('unavailable') or []) if isinstance(u, dict)
         and str((u.get('unavailability') or {}).get('expectedReturn') or '').lower() != 'doubtful']
    wazni = sorted([u for u in U if float(u.get('marketValue') or 0) >= med], key=lambda u: -float(u.get('marketValue') or 0))
    najl = wazni[0] if wazni and float(wazni[0].get('marketValue') or 0) >= 0.9 * maks else None
    n = len(wazni)
    dp = (BRAKI_4 if n >= 4 else BRAKI_DP.get(n, 0.0)) + (NAJLEPSZY_DP if najl else 0.0)
    return dict(wazni=[dict(nazwa=u.get('name'), powod=(u.get('unavailability') or {}).get('type'),
                            powrot=(u.get('unavailability') or {}).get('expectedReturn'), wartosc=u.get('marketValue')) for u in wazni[:6]],
                ile=n, najlepszy=(najl or {}).get('name'), niedostepnych=len(U), dp=round(min(dp, MAKS_DP), 4))


def _wygrana(lh, la, kto, score_matrix):
    M = score_matrix(lh, la, -0.05)
    return float(np.tril(M, -1).sum()) if kto == 'h' else float(np.triu(M, 1).sum())


def oslab(lh, la, kto, dp, score_matrix):
    """Mnożnik λ osłabionej drużyny (rywal +połowa różnicy), tak by jej szansa wygranej spadła o dp."""
    if dp <= 0: return 1.0
    p0 = _wygrana(lh, la, kto, score_matrix); cel = p0 - dp; lo, hi = 0.6, 1.0
    for _ in range(30):
        f = (lo + hi) / 2; g = 1 + (1 - f) / 2
        p = _wygrana(lh * f, la * g, kto, score_matrix) if kto == 'h' else _wygrana(lh * g, la * f, kto, score_matrix)
        if p > cel: hi = f
        else: lo = f
    return round((lo + hi) / 2, 4)


def mnozniki(f_h, f_a):
    """Mnożniki λ (gospodarz, gość) z osłabień obu drużyn."""
    return f_h * (1 + (1 - f_a) / 2), f_a * (1 + (1 - f_h) / 2)


def pilka(x, score_matrix, nazwy_pl=lambda n: n):
    """Korekta meczu piłki (x z core.macierz_meczu): braki z FotMob → nowa macierz wyników. Zapis w x['analityk']."""
    lam = x.get('lam_mkt')
    if lam is None: return None
    STAN['pilka']['mecze'] += 1
    mid, odw = fotmob_szukaj(x['home'], x['away'], x['start'])
    if not mid: return None
    STAN['pilka']['dopasowane'] += 1
    d = fotmob_szczegoly(mid)
    if not d: return None
    lu = ((d.get('content') or {}).get('lineup') or {})
    bh, ba = braki_druzyny(lu.get('awayTeam' if odw else 'homeTeam')), braki_druzyny(lu.get('homeTeam' if odw else 'awayTeam'))
    info = dict(zrodlo='FotMob', fotmob_id=mid, sklad=lu.get('lineupType'), gosp=bh, gosc=ba, powody=[])
    lh, la = float(lam[0]), float(lam[1])
    fh = oslab(lh, la, 'h', (bh or {}).get('dp', 0), score_matrix)
    fa = oslab(lh, la, 'a', (ba or {}).get('dp', 0), score_matrix)
    for b, nazwa in ((bh, x['home']), (ba, x['away'])):
        if b and b['dp'] > 0:
            imiona = ', '.join((w['nazwa'] + (' – najlepszy w drużynie' if w['nazwa'] == b.get('najlepszy') else '')) for w in b['wazni'][:4] if w.get('nazwa'))
            if b['ile'] > 4: imiona += f" i {b['ile'] - 4} inn."
            info['powody'].append(f"{nazwy_pl(nazwa)}: poza kadrą {imiona} → szansa wygranej −{b['dp'] * 100:.1f} pkt".replace('.', ',', 0)
                                  .replace(f"{b['dp'] * 100:.1f}", f"{b['dp'] * 100:.1f}".replace('.', ',')))
    mh, ma = mnozniki(fh, fa); info['f'] = [round(mh, 4), round(ma, 4)]
    x['analityk'] = info
    if mh == 1 and ma == 1: return info
    x['M_przed_analitykiem'] = x['M']
    x['M'] = score_matrix(lh * mh, la * ma, -0.05)
    x['lam_mkt'] = (lh * mh, la * ma)
    STAN['pilka']['z_korekta'] += 1
    return info


def lambdy_przed_meczem(lam, m, sila=0.35):
    """Kursy tuż przed meczem już częściowo uwzględniają braki – korekta słabsza (test: efekt wobec zamknięcia ~1/3)."""
    f = ((m or {}).get('analityk') or {}).get('f')
    if not f: return lam
    return (lam[0] * (1 - (1 - f[0]) * sila), lam[1] * (1 - (1 - f[1]) * sila))


# =============================================================== TENIS (ESPN – ostatnie mecze)
PLIK_TENIS = 'tenis_ostatnie.json'
TENIS_DNI = 62                                         # przerwa liczona tylko, gdy znamy ostatni mecz (30–62 dni temu)
TENIS_DL = SILA * (_lg(0.350) - _lg(0.371))            # ≈ −0,064 logitu dla wracającego po przerwie
_tb = {}


def tenis_baza():
    """{zawodnik: [daty meczów]} z wyników ESPN (ATP+WTA) z ostatnich 62 dni; uzupełniana przy każdym liczeniu (tylko brakujące dni)."""
    if 'b' in _tb: return _tb['b']
    p = os.path.join(OUT, PLIK_TENIS)
    try: b = json.load(open(p))
    except Exception: b = {}
    b.setdefault('dni', {}); b.setdefault('gracze', {})
    try:
        import sporty
        dzis = pd.Timestamp.now(tz='America/New_York').normalize()
        pobrane = 0
        for i in range(1, TENIS_DNI + 1):
            d = (dzis - pd.Timedelta(days=i)).strftime('%Y%m%d')
            if b['dni'].get(d) == 'gotowe' or pobrane >= 130: continue
            ok = True
            for s in ('tennis/atp', 'tennis/wta'):
                try:
                    j = requests.get(sporty.ESPN.format(s=s), params={'dates': d}, timeout=20).json(); pobrane += 1
                except Exception as e: _blad(f'ESPN tenis {d}: {e}'); ok = False; continue
                for c in sporty._pojedynki(j):
                    st = ((c.get('status') or {}).get('type') or {})
                    if not (st.get('completed') or st.get('state') == 'post'): continue
                    data = str(c.get('date') or c.get('startDate') or '')[:10] or f'{d[:4]}-{d[4:6]}-{d[6:]}'
                    for z in c['competitors']:
                        n = sporty._osoba(z)
                        if n:
                            L = b['gracze'].setdefault(n, [])
                            if data not in L: L.append(data); L.sort(); del L[:-6]
            if ok: b['dni'][d] = 'gotowe' if i >= 2 else 'częściowo'
        granica = (dzis - pd.Timedelta(days=TENIS_DNI + 10)).strftime('%Y%m%d')
        b['dni'] = {k: v for k, v in b['dni'].items() if k >= granica}
        g2 = f'{granica[:4]}-{granica[4:6]}-{granica[6:]}'
        b['gracze'] = {n: [x for x in L if x >= g2] for n, L in b['gracze'].items() if any(x >= g2 for x in L)}
        b['od'] = min(b['dni']) if b['dni'] else None
        b['czas'] = pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M')
        with open(p, 'w', encoding='utf-8') as f: json.dump({k: v for k, v in b.items() if k != '_idx'}, f, ensure_ascii=False)
        STAN['tenis']['baza'] = dict(dni=sum(1 for v in b['dni'].values() if v == 'gotowe'), graczy=len(b['gracze']), pobrane=pobrane)
    except Exception as e: _blad(f'tenis baza: {e}'); STAN['tenis']['baza'] = f'błąd: {str(e)[:80]}'
    _tb['b'] = b; return b


def _klucz_nazwiska(n):
    import unicodedata, re
    n = unicodedata.normalize('NFKD', str(n)).encode('ascii', 'ignore').decode().lower()
    w = re.sub(r'[^a-z ]', ' ', n).split()
    return w[-1] if w else ''


def _ostatni(nazwa, przed, b):
    try:
        import sporty
        same = sporty.ta_sama_osoba
    except Exception: same = lambda a, c: str(a).lower() == str(c).lower()
    if '_idx' not in b:
        idx = {}
        for n in b['gracze']:
            for k in {_klucz_nazwiska(n), (_klucz_nazwiska(n.split()[0]) if n.split() else '')}: idx.setdefault(k, []).append(n)
        b['_idx'] = idx
    kand = set(b['_idx'].get(_klucz_nazwiska(nazwa), [])) | set(b['_idx'].get(_klucz_nazwiska(str(nazwa).split()[0]) if str(nazwa).split() else '', []))
    daty = []
    for n in kand:
        if same(n, nazwa): daty += [x for x in b['gracze'][n] if x < przed]
    return max(daty) if daty else None


def tenis(A, B, start):
    """(zmiana logitu szansy A, info) – przerwa ≥30 dni przeciw rywalowi grającemu <14 dni temu."""
    b = tenis_baza()
    if not b.get('od'): return 0.0, None
    t = pd.Timestamp(start); dzien = t.strftime('%Y-%m-%d')
    pokrycie = (t.normalize() - pd.Timestamp(f"{b['od'][:4]}-{b['od'][4:6]}-{b['od'][6:]}")).days
    if pokrycie < 31 or sum(1 for v in b['dni'].values() if v == 'gotowe') < 28: return 0.0, None
    la, lb = _ostatni(A, dzien, b), _ostatni(B, dzien, b)
    dni = lambda x: (t.normalize() - pd.Timestamp(x)).days if x else None
    da, db = dni(la), dni(lb)
    info = dict(przerwa_a=da, przerwa_b=db, ostatni_a=la, ostatni_b=lb, powody=[])
    dl = 0.0
    if da is not None and db is not None:          # zawodnik nieznaleziony w wynikach ESPN = brak korekty (ostrożnie)
        if da >= 30 and db < 14:
            dl = TENIS_DL; info['powody'].append(f"{A}: {da} dni bez meczu, rywal grał {db} dni temu – po takiej przerwie zawodnicy wygrywają rzadziej, niż daje rynek")
        elif db >= 30 and da < 14:
            dl = -TENIS_DL; info['powody'].append(f"{B}: {db} dni bez meczu, rywal grał {da} dni temu – po takiej przerwie zawodnicy wygrywają rzadziej, niż daje rynek")
    if dl: STAN['tenis']['z_korekta'] += 1
    info['dlogit'] = round(dl, 4)
    return dl, info


# =============================================================== MMA (ufc-master: wiek, ostatnia walka)
MMA_MLODSZY = SILA * (_lg(0.634) - _lg(0.597))        # ≈ +0,11 dla młodszego o ≥6 lat
MMA_STARY = SILA * (_lg(0.346) - _lg(0.381))          # ≈ −0,11 dla 35+ przeciw <30
MMA_PRZERWA = SILA * (_lg(0.438) - _lg(0.465))        # ≈ −0,08 po ≥400 dniach przerwy
_mb = {}


def mma_baza():
    """{nrm(zawodnik): (data ostatniej walki, wiek w tej walce)} z ufc-master (ten sam plik co kategorie wagowe)."""
    if 'b' in _mb: return _mb['b']
    out = {}
    try:
        import walki
        d = pd.read_csv(io.StringIO(requests.get(walki.DANE_UFC, timeout=60).text), usecols=['R_fighter', 'B_fighter', 'date', 'R_age', 'B_age'])
        d = d.sort_values('date')
        for kol, wiek in (('R_fighter', 'R_age'), ('B_fighter', 'B_age')):
            for n, data, w in zip(d[kol], d.date, d[wiek]):
                k = walki.nrm(n)
                if k not in out or str(data) >= out[k][0]: out[k] = (str(data)[:10], float(w) if pd.notna(w) else None)
        STAN['walki']['baza'] = dict(zawodnikow=len(out), do=str(d.date.max())[:10])
    except Exception as e: _blad(f'MMA baza: {e}'); STAN['walki']['baza'] = f'błąd: {str(e)[:80]}'
    _mb['b'] = out; return out


def mma(A, B, start):
    """(zmiana logitu szansy A, info) – wiek i przerwa (tylko zawodnicy z walkami w UFC)."""
    import walki
    b = mma_baza(); t = pd.Timestamp(start).tz_localize(None) if pd.Timestamp(start).tzinfo else pd.Timestamp(start)
    za, zb = b.get(walki.nrm(A)), b.get(walki.nrm(B))
    if not za and not zb: return 0.0, None
    def wiek(z):
        if not z or z[1] is None: return None
        return z[1] + (t - pd.Timestamp(z[0])).days / 365.25
    def przerwa(z): return (t - pd.Timestamp(z[0])).days if z else None
    wa, wb, pa_, pb_ = wiek(za), wiek(zb), przerwa(za), przerwa(zb)
    info = dict(wiek_a=round(wa, 1) if wa else None, wiek_b=round(wb, 1) if wb else None, przerwa_a=pa_, przerwa_b=pb_, powody=[])
    dl = 0.0
    if wa and wb:
        if wb - wa >= 5.95: dl += MMA_MLODSZY; info['powody'].append(f'{A} młodszy o {wb - wa:.0f} lat ({wa:.0f} vs {wb:.0f}) – młodszy o 6+ lat wygrywa częściej, niż daje rynek')
        elif wa - wb >= 5.95: dl -= MMA_MLODSZY; info['powody'].append(f'{B} młodszy o {wa - wb:.0f} lat ({wb:.0f} vs {wa:.0f}) – młodszy o 6+ lat wygrywa częściej, niż daje rynek')
        elif wa >= 35 and wb < 30: dl += MMA_STARY; info['powody'].append(f'{A}: {wa:.0f} lat przeciw {wb:.0f}-latkowi')
        elif wb >= 35 and wa < 30: dl -= MMA_STARY; info['powody'].append(f'{B}: {wb:.0f} lat przeciw {wa:.0f}-latkowi')
    do = (STAN['walki'].get('baza') or {}).get('do') if isinstance(STAN['walki'].get('baza'), dict) else None
    if not do or (t - pd.Timestamp(do)).days > 45:     # zbiór nieaktualny – ktoś mógł walczyć po jego ostatniej dacie
        pa_ = pb_ = None; info['przerwa_a'] = info['przerwa_b'] = None; info['przerwa'] = f'pominięta (dane UFC do {do})'
    if pa_ is not None and pa_ >= 400: dl += MMA_PRZERWA; info['powody'].append(f'{A}: {pa_} dni od ostatniej walki w UFC')
    if pb_ is not None and pb_ >= 400: dl -= MMA_PRZERWA; info['powody'].append(f'{B}: {pb_} dni od ostatniej walki w UFC')
    if dl: STAN['walki']['z_korekta'] += 1
    info['dlogit'] = round(dl, 4)
    return dl, info


def zastosuj(pa, dl, info):
    """Nowa szansa A po korekcie; dopisuje do info zmianę w punktach."""
    if not dl: return pa
    nowa = min(0.985, max(0.015, _sg(_lg(pa) + dl)))
    if info is not None: info['zmiana_a'] = round(nowa - pa, 4); info['szansa_a_rynek'] = round(pa, 4)
    return nowa
