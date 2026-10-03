"""Wersja 49 (wersja 50: + wyniki Flashscore, surowe rynki wszystkich dyscyplin – rynki_surowe.py) – ROZLICZANIE KURSÓW POZOSTAŁYCH SPORTÓW (tenis, walki, hokej, koszykówka, baseball, siatkówka…).
Kursy: odczyty Zbieracza (Fortuna – klucze A/B, sety w tenisie). Wyniki: własna baza archiwum/wyniki (ESPN).
Dopasowanie: tenis po nazwiskach (Fortuna „Rakhimova K.” ↔ ESPN „Kamilla Rakhimova”), drużyny po nazwach; czas ±3 dni
dla tenisa (ESPN podaje czasem dzień turnieju), ±4 h dla pozostałych; kolejność stron może być odwrócona.
Wynik: docs/data/archiwum/rozliczone_inne/<data>.csv.gz (data = dzień startu, czas polski) – te same kolumny co piłka
+ sp, a w status.json → archiwum.inne: liczby i trafność vs szansa z kursu per sport."""
import os, re, json, gzip, glob, unicodedata
import numpy as np, pandas as pd

BAZA = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data', 'archiwum')
SP_WYNIKI = {'tenis': 'tenis', 'sporty walki': 'mma', 'mma': 'mma', 'hokej': 'hokej', 'koszykowka': 'koszykowka',
             'baseball': 'baseball', 'siatkowka': 'siatkowka', 'pilka_reczna': 'pilka_reczna', 'zuzel': 'zuzel', 'boks': 'boks'}
# wersja 50: klucze A/B (zwycięzca) tylko tam, gdzie znaczą „zwycięzca meczu”; w hokeju/ręcznej A/B pochodziły z rynku
# 3-drogowego w czasie regulaminowym – tam liczymy surowe rynki (rynki_surowe.py) z poprawnym czasem gry
SP_KLUCZE = ('tenis', 'mma', 'boks')
STAN = dict(meczow=0, dopasowanych=0, kursow=0, sporty={}, bledy=[])


def _ascii(t):
    return unicodedata.normalize('NFKD', str(t or '').lower().replace('ł', 'l')).encode('ascii', 'ignore').decode()


def _tokeny(n, fortuna=False):
    t = re.findall(r"[a-z][a-z'\-]+\.?", _ascii(n))
    if fortuna: t = [x for x in t if not x.endswith('.') or len(x) > 3]       # inicjały („K.”, „L.A.”) pomijamy
    return {x.strip('.') for x in t if len(x.strip('.')) >= 3}


def _zgodne(f, e, sp):
    """Czy zawodnik/drużyna z Fortuny (f) to ten sam co w ESPN (e)."""
    if sp == 'tenis':
        tf, te = _tokeny(f, True), _tokeny(e)
        return bool(tf) and tf <= te
    tf, te = _tokeny(f), _tokeny(e)
    if not tf or not te: return False
    wsp = tf & te
    return len(wsp) >= 1 and (len(wsp) >= min(len(tf), len(te)) or any(len(x) >= 6 for x in wsp))


def _wyniki(dni=12):
    out = {}
    for p in sorted(glob.glob(os.path.join(BAZA, 'wyniki', '*.json.gz')))[-dni:]:
        try:
            with gzip.open(p, 'rt', encoding='utf-8') as f:
                for w in json.load(f).get('wyniki') or []:
                    if w.get('koniec') and w.get('zr') in ('espn', 'flash'): out[(w['zr'], w['sp'], w['id'])] = w
        except Exception as e: STAN['bledy'].append(f'{os.path.basename(p)}: {e}'[:120])
    return list(out.values())


def _odczyty(dni=10):
    dzis = pd.Timestamp.now(tz='Europe/Warsaw').normalize(); od = {}
    for i in range(dni, -1, -1):
        d = (dzis - pd.Timedelta(days=i)).strftime('%Y-%m-%d')
        for p in sorted(glob.glob(os.path.join(BAZA, 'kursy', f'{d}_*.json.gz'))):
            if '_superbet_' in p: continue
            try:
                with gzip.open(p, 'rt', encoding='utf-8') as f: z = json.load(f)
            except Exception: continue
            tryb = z.get('tryb') or os.path.basename(p).split('_', 1)[1].split('.')[0]
            for m in z.get('mecze') or []:
                if m.get('sp') == 'pilka' or not (m.get('k') or m.get('r')) or '/' in str(m.get('h')): continue      # debel – później
                o = od.setdefault(m['id'], dict(sp=m['sp'], h=m['h'], a=m['a'], t=m['t'], tur=m.get('tur', ''), rano={}, popoludnie={}, przed={}, zamk={}, r={}))
                o.setdefault(tryb, {}).update(m.get('k') or {})
                for rn, wy in (m.get('r') or []):                 # wersja 50: surowe rynki (nowe dyscypliny)
                    for nz, c in wy:
                        o['r'].setdefault(tryb, {}).setdefault(f'{rn}|{nz}', c)
    return od


def _sety(w, odwr):
    """(sety A, sety B) z wyników gemów ESPN; A = pierwszy z Fortuny."""
    cz = w.get('czesci')
    if not cz or len(cz) != 2: return None
    h, a = cz
    if len(h) != len(a) or not h: return None
    sh = sum(1 for x, y in zip(h, a) if x is not None and y is not None and x > y)
    sa = sum(1 for x, y in zip(h, a) if x is not None and y is not None and y > x)
    return (sa, sh) if odwr else (sh, sa)


def rozlicz(teraz=None):
    import tenis
    wyn = _wyniki(); od = _odczyty()
    teraz = teraz or pd.Timestamp.now(tz='UTC')
    po_sp = {}
    for w in wyn: po_sp.setdefault(w['sp'], []).append(w)
    gotowe = set()
    for p in glob.glob(os.path.join(BAZA, 'rozliczone_inne', '*.csv.gz')):
        try: gotowe |= set(pd.read_csv(p, usecols=['mecz', 'start']).astype(str).itertuples(index=False, name=None))
        except Exception: pass
    nowe = {}
    for fid, o in od.items():
        sp = SP_WYNIKI.get(o['sp'])
        if not sp or sp not in po_sp: continue
        mecz = f"{o['h']} – {o['a']}"
        if (mecz, str(o['t'])) in gotowe: continue
        t = pd.Timestamp(o['t']).tz_localize('UTC')
        if t > teraz - pd.Timedelta(hours=3): continue
        STAN['meczow'] += 1
        okno = pd.Timedelta(days=3) if sp == 'tenis' else pd.Timedelta(hours=4)
        if sp == 'tenis' and any(w.get('zr') == 'flash' for w in po_sp[sp][:50]): okno = pd.Timedelta(days=3)
        best = None
        for w in po_sp[sp]:
            try: tw = pd.Timestamp(w['t']); tw = tw.tz_convert('UTC') if tw.tzinfo else tw.tz_localize('UTC')
            except Exception: continue
            dt_ = abs(tw - t)
            if dt_ > okno: continue
            for odwr in (False, True):
                eh, ea = (w['a'], w['h']) if odwr else (w['h'], w['a'])
                if _zgodne(o['h'], eh, sp) and _zgodne(o['a'], ea, sp) and (best is None or dt_ < best[0]): best = (dt_, w, odwr)
        if not best: continue
        _, w, odwr = best
        zw = w.get('zw')
        if sp not in SP_KLUCZE:                 # wersja 50: surowe rynki z poprawnym czasem gry
            STAN['dopasowanych'] += 1; STAN['sporty'][o['sp']] = STAN['sporty'].get(o['sp'], 0) + 1
            _surowe(o, w, odwr, mecz, t, nowe); continue
        if zw not in ('h', 'a'): continue
        a_wygral = (zw == 'h') != odwr
        STAN['dopasowanych'] += 1; STAN['sporty'][o['sp']] = STAN['sporty'].get(o['sp'], 0) + 1
        sety = _sety(w, odwr) if sp == 'tenis' else None
        rk = None
        if sety and max(sety) in (2, 3):
            bo = 3 if max(sety) == 2 else 5
            rk = tenis.rynki(tenis.rozklad(0.5, bo), bo)
        kr = o['rano'] or o['popoludnie']
        dzien = t.tz_convert('Europe/Warsaw').strftime('%Y-%m-%d')
        for k in set(kr) | set(o['przed']) | set(o['zamk']):
            if k in ('A', 'B'): traf = int(a_wygral if k == 'A' else not a_wygral)
            elif rk and k in rk: traf = int(tuple(sety) in rk[k])
            else: continue
            nowe.setdefault(dzien, []).append(dict(data=dzien, sp=o['sp'], liga=o['tur'], mecz=mecz, start=o['t'], rynek=k,
                                                   kurs_rano=kr.get(k), kurs_przed=o['przed'].get(k) or o['popoludnie'].get(k),
                                                   kurs_zamk=o['zamk'].get(k), wynik=(f'{sety[0]}:{sety[1]}' if sety else ('A' if a_wygral else 'B')),
                                                   trafiony=traf))
    kat = os.path.join(BAZA, 'rozliczone_inne'); os.makedirs(kat, exist_ok=True)
    for dzien, w in nowe.items():
        p = os.path.join(kat, f'{dzien}.csv.gz'); d = pd.DataFrame(w)
        if os.path.exists(p):
            try: d = pd.concat([pd.read_csv(p), d], ignore_index=True)
            except Exception: pass
        d.drop_duplicates(['mecz', 'start', 'rynek']).to_csv(p, index=False, compression='gzip')
        STAN['kursow'] += len(w)
    return STAN


def _odwroc(x, odwr):
    return None if x is None else ([x[1], x[0]] if odwr else [x[0], x[1]])


def _surowe(o, w, odwr, mecz, t, nowe):
    """Rozliczenie surowych rynków Fortuny (rynki_surowe) jednego meczu; wynik w kolejności stron Fortuny."""
    import rynki_surowe as RS
    fin = _odwroc([w.get('gh'), w.get('ga')], odwr)
    if None in fin: return
    punkty = None
    cz = w.get('czesci')
    if cz and len(cz) == 2 and all(x is not None for x in cz[0] + cz[1]): punkty = _odwroc([sum(cz[0]), sum(cz[1])], odwr)
    wyn = dict(final=fin, reg=_odwroc(w.get('reg'), odwr), punkty=punkty)
    r = o.get('r') or {}
    kr = r.get('rano') or r.get('popoludnie') or {}
    kp = {**(r.get('popoludnie') or {}), **(r.get('przed') or {})}
    kz = r.get('zamk') or {}
    dzien = t.tz_convert('Europe/Warsaw').strftime('%Y-%m-%d')
    for k in set(kr) | set(kp) | set(kz):
        rn, _, nz = k.partition('|')
        x = RS.rozlicz(o['sp'], rn, nz, wyn, o['h'], o['a'])
        if x is None: continue
        traf, kat = x
        nowe.setdefault(dzien, []).append(dict(data=dzien, sp=o['sp'], liga=o['tur'], mecz=mecz, start=o['t'], rynek=k[:120], kategoria=kat,
                                               kurs_rano=kr.get(k), kurs_przed=kp.get(k), kurs_zamk=kz.get(k),
                                               wynik=f"{fin[0]}:{fin[1]}" + (f" (reg. {wyn['reg'][0]}:{wyn['reg'][1]})" if wyn['reg'] and wyn['reg'] != fin else ''),
                                               trafiony=traf, zr=w.get('zr')))


def statystyki():
    """Per sport: rozliczone kursy, trafność vs szansa z kursu (1/kurs bez marży ~ /1,06), zysk na wszystkich kursach."""
    ps = glob.glob(os.path.join(BAZA, 'rozliczone_inne', '*.csv.gz'))
    if not ps: return {}
    d = pd.concat([pd.read_csv(p) for p in ps], ignore_index=True)
    d['kurs'] = pd.to_numeric(d.kurs_rano, errors='coerce').fillna(pd.to_numeric(d.kurs_przed, errors='coerce'))
    d = d[d.kurs > 1]
    out = {}
    agr = lambda g: dict(meczow=int(g[['mecz', 'start']].drop_duplicates().shape[0]), kursow=int(len(g)), trafione=round(float(g.trafiony.mean()), 4),
                         z_kursu=round(float((1 / g.kurs).mean() / 1.06), 4), roi=round(float(np.where(g.trafiony > 0, g.kurs - 1, -1).mean()), 4))
    if 'kategoria' not in d: d['kategoria'] = None
    for sp, g in d.groupby('sp'):
        out[sp] = agr(g)
        rk = {str(k): agr(x) for k, x in g.groupby(g.kategoria.fillna('zwycięzca/sety')) if len(x) >= 20}   # wersja 50: rodzaje zakładów
        if rk: out[sp]['rynki'] = rk
    return out
