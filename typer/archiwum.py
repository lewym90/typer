"""Archiwum kursów (wersja 37) – rozliczanie odczytów Zbieracza i nauka „gdzie bukmacher się myli”.
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
STAN = dict(rozliczone_dni=[], meczow=0, dopasowanych=0, kursow=0, bledy=[])
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
    for d in (dzien, (pd.Timestamp(dzien) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')):
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


def _podobne(a, b):
    try:
        import kursy_pl as KP
        from nazwy import pl
        return max(KP.podobne_w(a, b), KP.podobne_w(a, pl(b)))
    except Exception:
        import difflib
        return difflib.SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()


def rozlicz_dzien(dzien):
    """Rozlicza wszystkie odczyty z danego dnia (piłka). Zwraca liczbę wierszy albo None (brak danych)."""
    from core import MASKI, MAXG
    pliki = sorted(glob.glob(os.path.join(KAT_K, f'{dzien}_*.json.gz')))
    if not pliki: return None
    odczyty = {}                                   # id → dict(meta, rano={k:kurs}, przed={k:kurs})
    for p in pliki:
        d = _wczytaj(p)
        if not d: continue
        tryb = d.get('tryb') or os.path.basename(p).split('_', 1)[1].split('.')[0]
        for m in d.get('mecze') or []:
            if m.get('sp') != 'pilka': continue
            o = odczyty.setdefault(m['id'], dict(h=m['h'], a=m['a'], t=m['t'], tur=m.get('tur', ''), rano={}, przed={}, popoludnie={}))
            o.setdefault(tryb, {}).update(m.get('k') or {})
    if not odczyty: return 0
    wyn = fotmob_wyniki(dzien)
    STAN['meczow'] += len(odczyty)
    wiersze = []
    for fid, o in odczyty.items():
        t = pd.Timestamp(o['t']).tz_localize('UTC')
        best = None
        for h, a, tt, gh, ga in wyn:
            if abs((tt - t).total_seconds()) > 20 * 60: continue
            sc = min(_podobne(o['h'], h), _podobne(o['a'], a))
            if sc >= 0.5 and (best is None or sc > best[0]): best = (sc, gh, ga)
        if not best: continue
        STAN['dopasowanych'] += 1
        _, gh, ga = best
        kursy_rano = o['rano'] or o['popoludnie']
        for k in set(kursy_rano) | set(o['przed']):
            if k not in MASKI: continue
            kr, kp_ = kursy_rano.get(k), o['przed'].get(k) or o['popoludnie'].get(k)
            wiersze.append(dict(data=dzien, liga=o['tur'], mecz=f"{o['h']} – {o['a']}", start=o['t'], rynek=k, kategoria=kategoria(k),
                                kurs_rano=kr, kurs_przed=kp_, wynik=f'{gh}:{ga}', trafiony=int(bool(MASKI[k][min(gh, MAXG), min(ga, MAXG)]))))
    os.makedirs(KAT_R, exist_ok=True)
    if wiersze:
        pd.DataFrame(wiersze).to_csv(os.path.join(KAT_R, f'{dzien}.csv.gz'), index=False, compression='gzip')
        STAN['kursow'] += len(wiersze); STAN['rozliczone_dni'].append(dzien)
    return len(wiersze)


def statystyki():
    """Zbiorcze statystyki z całego archiwum: gdzie kurs bukmachera jest za wysoki (zysk przy stawianiu wszystkiego)."""
    pliki = sorted(glob.glob(os.path.join(KAT_R, '*.csv.gz')))
    if not pliki: return None
    d = pd.concat([pd.read_csv(p) for p in pliki], ignore_index=True)
    d['kurs'] = d.kurs_rano.fillna(d.kurs_przed)
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
    os.makedirs(os.path.dirname(PLIK_STAT), exist_ok=True)
    with open(PLIK_STAT, 'w', encoding='utf-8') as f: json.dump(wynik, f, ensure_ascii=False)
    return wynik


def dzienny():
    """Wołane przy pełnym liczeniu: rozlicza wczoraj i przedwczoraj (jeśli jeszcze nie), przelicza statystyki."""
    dzis = pd.Timestamp.now(tz='Europe/Warsaw').normalize()
    for i in (1, 2, 3):
        d = (dzis - pd.Timedelta(days=i)).strftime('%Y-%m-%d')
        if os.path.exists(os.path.join(KAT_R, f'{d}.csv.gz')): continue
        try: rozlicz_dzien(d)
        except Exception as e: _blad(f'rozliczenie {d}: {type(e).__name__}: {e}')
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
    return {k: st.get(k) for k in ('czas', 'dni', 'meczow', 'kursow', 'bukmacher', 'wszystko', 'rynki', 'okazje', 'ligi_najlepsze')}
