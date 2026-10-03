"""Wersja 46 – ZBIORNIK WYNIKÓW (GitHub, przy pełnym liczeniu): wyniki wszystkich dyscyplin z internetu, zapisywane jako
własna baza do późniejszego rozliczenia kursów z Archiwum (Zbieracz na polskim serwerze zapisuje kursy Fortuny wszystkich
11 sportów programu). Zasada: kursów z przeszłości nie da się odtworzyć – dlatego zbieramy je od razu; wyniki zapisujemy
równolegle w prostej, jednolitej postaci, żeby dopasowanie mecz ↔ wynik dało się zrobić (i poprawić) w dowolnym momencie.

Źródła: ESPN (koszykówka, hokej, baseball, F1, MMA, boks, tenis, siatkówka akademicka) i FotMob (piłka nożna – wszystkie ligi).
Siatkówka zawodowa, piłka ręczna i żużel nie mają darmowego źródła w tej formie – ich wyniki uzupełnimy później
(kursy i tak są zbierane). Plik dnia: docs/data/archiwum/wyniki/<data>.json.gz
  {czas, zrodla: {źródło: liczba}, bledy: [...], wyniki: [{sp, liga, zr, id, t (UTC), h, a, gh, ga, zw ('h'|'a'|'r'|None), stan, wynik}]}
Plik dnia jest uzupełniany przez 3 kolejne dni (mecze późne, dogrywki, opóźnione wyniki)."""
import os, json, gzip, time
import pandas as pd, requests

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data', 'archiwum', 'wyniki')
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/{s}/scoreboard'
LIGI_ESPN = {
    'koszykowka': ['basketball/nba', 'basketball/wnba', 'basketball/mens-college-basketball', 'basketball/womens-college-basketball',
                   'basketball/nbl', 'basketball/fiba'],
    'hokej': ['hockey/nhl', 'hockey/mens-college-hockey'],
    'baseball': ['baseball/mlb', 'baseball/college-baseball'],
    'f1': ['racing/f1'],
    'mma': ['mma/ufc', 'mma/pfl', 'mma/bellator'],
    'boks': ['boxing'],
    'tenis': ['tennis/atp', 'tennis/wta'],
    'siatkowka': ['volleyball/womens-college-volleyball', 'volleyball/mens-college-volleyball'],
}
STAN = dict(zrodla={}, bledy=[], dni=[])
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36'}


def _blad(t):
    t = str(t)[:160]
    if t not in STAN['bledy'] and len(STAN['bledy']) < 30: STAN['bledy'].append(t)


def _int(x):
    try: return int(float(str(x).split()[0]))
    except Exception: return None


def _nazwa(c):
    for k in ('team', 'athlete'):
        o = c.get(k) or {}
        n = o.get('displayName') or o.get('shortDisplayName') or o.get('name') or o.get('fullName')
        if n: return n
    r = c.get('roster') or {}
    return r.get('displayName') or c.get('displayName') or c.get('name')


def _zawody(o, out, kontekst):
    """Rekurencyjnie: każdy obiekt z listą 'competitors' (2 strony) = jeden mecz/walka/pojedynek; wyścig (F1) – zwycięzca."""
    if isinstance(o, dict):
        cs = o.get('competitors')
        if isinstance(cs, list) and len(cs) >= 2 and all(isinstance(c, dict) for c in cs):
            st = ((o.get('status') or kontekst.get('status') or {}).get('type') or {})
            t = o.get('date') or o.get('startDate') or kontekst.get('date')
            if len(cs) == 2:
                h = next((c for c in cs if c.get('homeAway') == 'home'), cs[0]); a = next((c for c in cs if c is not h), cs[1])
                gh, ga = _int(h.get('score')), _int(a.get('score'))
                zw = 'h' if h.get('winner') else ('a' if a.get('winner') else ('r' if st.get('completed') and gh is not None and gh == ga else None))
                ls = [[_int(x.get('value')) for x in (c.get('linescores') or []) if isinstance(x, dict)] for c in (h, a)]
                out.append(dict(id=str(o.get('id') or ''), t=t, h=_nazwa(h), a=_nazwa(a), gh=gh, ga=ga, zw=zw,
                                stan=st.get('name') or st.get('description'), koniec=bool(st.get('completed')),
                                wynik=st.get('detail') or st.get('shortDetail'), czesci=ls if any(ls) else None,
                                metoda=(o.get('details') or [{}])[0].get('type', {}).get('text') if isinstance(o.get('details'), list) and o.get('details') else None))
            else:   # wyścig: kolejność
                kol = sorted(cs, key=lambda c: _int(c.get('order')) or 999)
                out.append(dict(id=str(o.get('id') or ''), t=t, h=_nazwa(kol[0]), a=None, gh=None, ga=None, zw='h',
                                stan=st.get('name'), koniec=bool(st.get('completed')), wynik='wyścig',
                                kolejnosc=[_nazwa(c) for c in kol[:20]]))
            return
        k2 = dict(kontekst)
        if o.get('date'): k2['date'] = o['date']
        if o.get('status'): k2['status'] = o['status']
        for v in o.values(): _zawody(v, out, k2)
    elif isinstance(o, list):
        for v in o: _zawody(v, out, kontekst)


def espn_dzien(dzien):
    out = []
    for sp, ligi in LIGI_ESPN.items():
        for s in ligi:
            try:
                r = requests.get(ESPN.format(s=s), params={'dates': dzien.replace('-', ''), 'limit': 500}, timeout=20, headers=UA)
                if r.status_code != 200: _blad(f'ESPN {s}: HTTP {r.status_code}'); continue
                j = r.json(); zn = []
                _zawody(j.get('events') or [], zn, {})
                for z in zn: z.update(sp=sp, liga=s.split('/')[-1], zr='espn')
                out += zn; STAN['zrodla'][s] = STAN['zrodla'].get(s, 0) + len(zn)
            except Exception as e: _blad(f'ESPN {s}: {type(e).__name__}: {e}')
            time.sleep(0.2)
    return out


def fotmob_dzien(dzien):
    """Wszystkie zakończone mecze piłki dnia z FotMob (ta sama lista co w archiwum, zapis jednolity)."""
    import analityk
    out = []
    try: j = analityk._fm_get(f"{analityk.FM}/matches?date={dzien.replace('-', '')}&timezone=Europe%2FWarsaw&ccode3=POL")
    except Exception as e: _blad(f'FotMob {dzien}: {e}'); return out
    def chodz(o, liga=''):
        if isinstance(o, dict):
            if isinstance(o.get('matches'), list): liga = o.get('name') or o.get('ccode') or liga
            h, a, st = o.get('home'), o.get('away'), o.get('status') or {}
            if isinstance(h, dict) and isinstance(a, dict) and o.get('id'):
                gh, ga = _int(h.get('score')), _int(a.get('score'))
                out.append(dict(sp='pilka', liga=liga, zr='fotmob', id=str(o['id']), t=st.get('utcTime'), h=h.get('longName') or h.get('name'),
                                a=a.get('longName') or a.get('name'), gh=gh, ga=ga, koniec=bool(st.get('finished')), stan=(st.get('reason') or {}).get('short'),
                                zw=None if gh is None or ga is None or not st.get('finished') else ('h' if gh > ga else ('a' if ga > gh else 'r')),
                                wynik=st.get('scoreStr')))
                return
            for v in o.values(): chodz(v, liga)
        elif isinstance(o, list):
            for v in o: chodz(v, liga)
    chodz(j)
    STAN['zrodla']['fotmob'] = STAN['zrodla'].get('fotmob', 0) + len(out)
    return out


def zbierz(dni=3):
    """Wyniki z ostatnich `dni` dni (czas polski, bez dzisiejszego) – plik dnia nadpisywany pełniejszą wersją."""
    os.makedirs(OUT, exist_ok=True)
    dzis = pd.Timestamp.now(tz='Europe/Warsaw').normalize()
    for i in range(1, dni + 1):
        d = (dzis - pd.Timedelta(days=i)).strftime('%Y-%m-%d')
        w = espn_dzien(d) + fotmob_dzien(d)
        if not w: continue
        p = os.path.join(OUT, f'{d}.json.gz')
        try:
            with gzip.open(p, 'rt', encoding='utf-8') as f: stare = json.load(f).get('wyniki') or []
        except Exception: stare = []
        nowe_id = {(x['zr'], x['id']) for x in w}
        w += [x for x in stare if (x.get('zr'), x.get('id')) not in nowe_id]      # nic nie ginie, nowsze nadpisuje
        with gzip.open(p, 'wt', encoding='utf-8') as f:
            json.dump(dict(czas=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'), wyniki=w), f, ensure_ascii=False, separators=(',', ':'))
        STAN['dni'].append(f'{d}: {len(w)}')
    return dict(dni=STAN['dni'], zrodla=STAN['zrodla'], bledy=STAN['bledy'][:10])
