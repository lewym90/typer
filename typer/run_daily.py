"""Codzienne uruchomienie: dane -> modele -> typy na dziś -> dziennik -> pliki JSON dla aplikacji."""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from core import *
import core, raport

NAZWY_LIG = {'soccer_uefa_champs_league': 'Liga Mistrzów', 'soccer_fifa_world_cup': 'Mistrzostwa świata',
 'soccer_uefa_european_championship': 'Mistrzostwa Europy', 'soccer_uefa_nations_league': 'Liga Narodów',
 'soccer_fifa_world_cup_qualifiers_europe': 'El. mistrzostw świata', 'soccer_uefa_euro_qualification': 'El. mistrzostw Europy',
 'soccer_epl': 'Premier League', 'soccer_spain_la_liga': 'La Liga', 'soccer_poland_ekstraklasa': 'Ekstraklasa',
 'soccer_italy_serie_a': 'Serie A', 'soccer_germany_bundesliga': 'Bundesliga', 'soccer_france_ligue_one': 'Ligue 1',
 'soccer_uefa_europa_league': 'Liga Europy', 'soccer_uefa_europa_conference_league': 'Liga Konferencji',
 'soccer_international_friendlies': 'Mecz towarzyski', 'soccer_portugal_primeira_liga': 'Liga Portugal',
 'soccer_netherlands_eredivisie': 'Eredivisie', 'soccer_efl_champ': 'Championship', 'soccer_germany_bundesliga2': '2. Bundesliga',
 'soccer_turkey_super_league': 'Süper Lig', 'soccer_belgium_first_div': 'Jupiler Pro League', 'soccer_spl': 'Premiership (SCO)'}

RAPORT_ILE_MECZOW = 8   # ile meczów sprawdzać w API-Football (darmowy plan: 100 zapytań dziennie)

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')

def wyniki_top(M, k=3):
    return [dict(wynik=f"{i}:{j}", szansa=round(float(p), 4), kurs_uczciwy=round(1 / float(p), 2)) for (i, j), p in top_scores(M, k)]


# ---------- kandydaci na typy (z macierzy wyników) ----------
def rynki_rozszerzone(M, H, A):
    """Szanse wielu zakładów liczone z macierzy dokładnych wyników. Zwraca {klucz: (szansa, nazwa, opis)}."""
    g = np.arange(MAXG + 1); I, J = np.meshgrid(g, g, indexing='ij'); T = I + J; D = I - J
    P = lambda maska: (float(M[maska].sum()), maska)
    r = {
     '1': (P(D > 0), '1', 'wygra ' + H), 'X': (P(D == 0), 'X', 'remis'), '2': (P(D < 0), '2', 'wygra ' + A),
     '1X': (P(D >= 0), '1X', H + ' lub remis'), 'X2': (P(D <= 0), 'X2', A + ' lub remis'), '12': (P(D != 0), '12', 'bez remisu'),
     'BTTS Tak': (P((I > 0) & (J > 0)), 'Obie strzelą – tak', ''), 'BTTS Nie': (P((I == 0) | (J == 0)), 'Obie strzelą – nie', ''),
     'H -1.5': (P(D >= 2), f'Handicap {H} -1.5', f'{H} wygra różnicą 2+ goli'),
     'A -1.5': (P(D <= -2), f'Handicap {A} -1.5', f'{A} wygra różnicą 2+ goli'),
     'H -2.5': (P(D >= 3), f'Handicap {H} -2.5', f'{H} wygra różnicą 3+ goli'),
     'A -2.5': (P(D <= -3), f'Handicap {A} -2.5', f'{A} wygra różnicą 3+ goli'),
     'H -3.5': (P(D >= 4), f'Handicap {H} -3.5', f'{H} wygra różnicą 4+ goli'),
     'A -3.5': (P(D <= -4), f'Handicap {A} -3.5', f'{A} wygra różnicą 4+ goli'),
     'H -4.5': (P(D >= 5), f'Handicap {H} -4.5', f'{H} wygra różnicą 5+ goli'),
     'A -4.5': (P(D <= -5), f'Handicap {A} -4.5', f'{A} wygra różnicą 5+ goli'),
     'H o2.5': (P(I >= 3), f'{H} powyżej 2.5 gola', f'{H} strzeli 3+ gole'),
     'A o2.5': (P(J >= 3), f'{A} powyżej 2.5 gola', f'{A} strzeli 3+ gole'),
     'H o1.5': (P(I >= 2), f'{H} powyżej 1.5 gola', f'{H} strzeli 2+ gole'),
     'A o1.5': (P(J >= 2), f'{A} powyżej 1.5 gola', f'{A} strzeli 2+ gole'),
     'H o0.5': (P(I >= 1), f'{H} powyżej 0.5 gola', f'{H} strzeli gola'),
     'A o0.5': (P(J >= 1), f'{A} powyżej 0.5 gola', f'{A} strzeli gola'),
     '1 & o1.5': (P((D > 0) & (T >= 2)), f'1 i powyżej 1.5 gola', f'{H} wygra, w meczu 2+ gole'),
     '2 & o1.5': (P((D < 0) & (T >= 2)), f'2 i powyżej 1.5 gola', f'{A} wygra, w meczu 2+ gole'),
     '1 & o2.5': (P((D > 0) & (T >= 3)), f'1 i powyżej 2.5 gola', f'{H} wygra, w meczu 3+ gole'),
     '2 & o2.5': (P((D < 0) & (T >= 3)), f'2 i powyżej 2.5 gola', f'{A} wygra, w meczu 3+ gole'),
     'X & u2.5': (P((D == 0) & (T <= 2)), 'X i poniżej 2.5 gola', 'remis 0:0 lub 1:1'),
     'BTTS & o2.5': (P((I > 0) & (J > 0) & (T >= 3)), 'Obie strzelą i powyżej 2.5', ''),
    }
    for l in (1.5, 2.5, 3.5, 4.5, 5.5):
        r[f'Over {l}'] = (P(T > l), f'Powyżej {l} gola', ''); r[f'Under {l}'] = (P(T < l), f'Poniżej {l} gola', '')
    # (szansa, nazwa, opis, maska wyników)
    return {k: (v[0][0], v[1], v[2], v[0][1]) for k, v in r.items()}

# korekty z testów: ligi – '12' przeceniane ~3,5 pkt; puchary – 'X2' przeceniane ~5 pkt; skrajne gole i BTTS przeceniane
NAJPEWNIEJSZE = ['1', '2', '1X', 'X2', '12', 'Over 1.5', 'Over 2.5', 'Under 3.5']
LEPSZY_KURS = ['1', '2', '1X', 'X2', '12', 'Over 1.5', 'Over 2.5', 'Under 2.5', 'Under 3.5', 'BTTS Tak', 'BTTS Nie',
               'H -1.5', 'A -1.5', 'H -2.5', 'A -2.5', 'H -3.5', 'A -3.5', 'Over 3.5', 'Over 4.5', 'H o1.5', 'A o1.5', 'H o2.5', 'A o2.5', 'H o0.5', 'A o0.5']
RYZYKOWNE = ['1', 'X', '2', 'Over 2.5', 'Over 3.5', 'Under 1.5', 'BTTS Tak', 'H -1.5', 'A -1.5', 'H -2.5', 'A -2.5',
             'H -3.5', 'A -3.5', 'H -4.5', 'A -4.5', 'Over 4.5', 'Over 5.5', 'H o2.5', 'A o2.5', 'H o1.5', 'A o1.5', '1 & o1.5', '2 & o1.5', '1 & o2.5', '2 & o2.5', 'X & u2.5', 'BTTS & o2.5']

SAMOKOREKTA = {}   # z dziennika typów "Pewne" (min. 100 rozliczonych typów danego rodzaju)

def szansa(z, p, x):
    """Szansa po kalibracji: model -> ogólna kalibracja; rynek (Pinnacle/Betfair) zostaje bez zmian. Potem samokorekta z dziennika."""
    if x['tryb'] == 'tylko model': p = kalibruj(z, p, x.get('model_key'))
    return float(min(0.99, max(0.01, p + SAMOKOREKTA.get(z, 0.0))))

def kurs_betclic_dla(x, z):
    """Kurs Betclic dla naszego zakładu, jeśli jest w API."""
    nazwy = {'1': '1', 'X': 'X', '2': '2', 'Over 1.5': 'Powyżej 1.5 gola', 'Over 2.5': 'Powyżej 2.5 gola', 'Over 3.5': 'Powyżej 3.5 gola',
             'Under 1.5': 'Poniżej 1.5 gola', 'Under 2.5': 'Poniżej 2.5 gola', 'Under 3.5': 'Poniżej 3.5 gola',
             'H -1.5': 'Handicap gosp. -1.5', 'A -1.5': 'Handicap gościa -1.5', 'H -2.5': 'Handicap gosp. -2.5', 'A -2.5': 'Handicap gościa -2.5',
             'BTTS Tak': 'BTTS Tak', 'BTTS Nie': 'BTTS Nie'}
    if z not in nazwy or not x.get('betclic'): return None
    for nz, kurs, p, e, meta in oferty_betclic(x):
        if nz == nazwy[z]: return kurs
    return None

PRZECIWNE = {'BTTS Tak': 'BTTS Nie', '1X': '2', 'X2': '1', '12': 'X', 'Over 1.5': 'Under 1.5', 'Over 2.5': 'Under 2.5',
             'Over 3.5': 'Under 3.5', 'Over 4.5': 'Under 4.5'}
PRZECIWNE.update({v: k for k, v in list(PRZECIWNE.items())})

def wybierz(x, liga, lista, kmin, kmax, pmin=0.0, wyklucz=()):
    wyklucz = [z for z in wyklucz if z]
    r = rynki_rozszerzone(x['M'], x['home'], x['away']); najlepszy = None
    for z in lista:
        if z in wyklucz: continue
        # bez zakładów sprzecznych z już wybranymi (nie mogą wejść razem)
        if any(float(x['M'][r[z][3] & r[w][3]].sum()) < 0.03 for w in wyklucz): continue
        p = szansa(z, r[z][0], x)
        if p <= pmin or not (kmin <= 1 / p <= kmax): continue
        if najlepszy is None or p > najlepszy[1]: najlepszy = (z, p)
    if not najlepszy: return None
    z, p = najlepszy; kb = kurs_betclic_dla(x, z)
    return dict(klucz=z, zaklad=r[z][1], opis=r[z][2], szansa=round(p, 4), kurs_uczciwy=round(1 / p, 2), kurs_min=round(0.95 / p, 2),
                kurs_betclic=kb, ev=round(p * kb - 1, 4) if kb else None)

def tablica(M):
    g = np.arange(MAXG + 1)
    return dict(xg_gosp=round(float((M.sum(1) * g).sum()), 2), xg_gosc=round(float((M.sum(0) * g).sum()), 2))

def najczestsze(M):
    """Najczęstszy wynik osobno dla wygranej gospodarza, remisu i wygranej gościa."""
    out = {}
    for k, war in (('1', lambda i, j: i > j), ('X', lambda i, j: i == j), ('2', lambda i, j: i < j)):
        best = max(((i, j) for i in range(MAXG + 1) for j in range(MAXG + 1) if war(i, j)), key=lambda t: M[t])
        out[k] = dict(wynik=f"{best[0]}:{best[1]}", szansa=round(float(M[best]), 4))
    return out

def opis_meczu(x, liga):
    mk = markets(x['M'])
    return dict(mecz=f"{x['home']} – {x['away']}", gospodarz=x['home'], gosc=x['away'], liga=NAZWY_LIG.get(liga, liga),
                start=x['start'].strftime('%Y-%m-%d %H:%M'), godzina=x['start'].strftime('%H:%M'), zrodlo=x['tryb'],
                szanse={z: round(float(mk[z]), 4) for z in ['1', 'X', '2', 'Over 2.5', 'BTTS Tak']},
                wyniki=wyniki_top(x['M']), uwaga=x['uwaga'], najczestsze=najczestsze(x['M']),
                analiza=dict(model=x.get('model_key'), h=x.get('model_h'), a=x.get('model_a'),
                             lam=[round(float(v), 4) for v in x['lam_mkt']] if x.get('lam_mkt') is not None else None),
                raport=x.get('raport'), **tablica(x['M']))

def typy_na_dzis():
    mecze = dzisiejsze_mecze()
    analizy = []
    for key, model, ev in mecze:
        try: x = macierz_meczu(ev, model)
        except Exception as e: print("pominięto", ev.get('home_team'), e); x = None
        if x: analizy.append((list(LIGI_DO_SKANU).index(key), key, x))
    # --- VALUE (Betclic vs Pinnacle/Betfair) ---
    value, do_zapisu, value_x = [], [], []
    for _, key, x in sorted(analizy, key=lambda t: t[2]['start']):
        if x['M_mkt'] is None or not x['ostry']: continue
        for z, kurs, p, e, meta in oferty_betclic(dict(x, M=x['M_mkt'])):
            if KURS_MIN <= kurs <= KURS_MAX and e >= MIN_EV_VALUE:
                zr = x['tryb'].split('+', 1)[-1] if x['M_mod'] is not None else x['tryb']
                if not any(x is v for v in value_x): value_x.append(x)
                value.append(dict(opis_meczu(x, key), zaklad=z, opis=NAZWY_ZAKL.get(z, ''), kurs=kurs, szansa=round(p, 4),
                                  kurs_uczciwy=round(1 / p, 2), kurs_szukaj=round(1.02 / p, 2), ev=round(e, 4), zrodlo=zr, stawka_proc=round(kelly(p, kurs), 4), **meta))
                do_zapisu.append(dict(data_zapisu=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'),
                    event_id=x['event_id'], liga=x['sport_key'], start=x['start'].strftime('%Y-%m-%d %H:%M'),
                    mecz=f"{x['home']} – {x['away']}", gospodarz=x['home'], gosc=x['away'], zaklad=z, **meta,
                    kurs_betclic=kurs, kurs_uczciwy=round(1 / p, 3), szansa=round(p, 3), EV=round(e, 4),
                    stawka_sugerowana=round(BANKROLL * kelly(p, kurs), 0), wynik='', zysk_na_1zl=np.nan))
    if do_zapisu: zapisz_value(do_zapisu)
    # --- 5 NAJPEWNIEJSZYCH (+ lepszy kurs i ryzykowny z tego samego meczu) ---
    wszystkie = []
    for poz, key, x in sorted(analizy, key=lambda t: (t[0], t[2]['start']))[:PEWNE_ILE_MECZOW]:
        liga = LIGI_DO_SKANU.get(key)
        r = rynki_rozszerzone(x['M'], x['home'], x['away'])
        for z in NAJPEWNIEJSZE:
            p = szansa(z, r[z][0], x)
            if 1 / p < PEWNE_MIN_KURS: continue
            wszystkie.append(dict(p=p, z=z, x=x, key=key, liga=liga))
    wszystkie.sort(key=lambda t: -t['p'])
    # raport przedmeczowy (kontuzje, rotacje, nagłówki) dla meczów-kandydatów i meczów z Value
    kandydaci = []
    for t in wszystkie:
        if not any(t['x'] is k for k in kandydaci): kandydaci.append(t['x'])
        if len(kandydaci) >= RAPORT_ILE_MECZOW: break
    for v in value_x:
        if not any(v is k for k in kandydaci): kandydaci.append(v)
    for x in kandydaci:
        try: x['raport'] = raport.raport(x['home'], x['away'], x['start'], polski=x['sport_key'] == 'soccer_poland_ekstraklasa')
        except Exception as e: print('raport:', x['home'], e)
    for v in value:  # dołącz raporty do kart Value
        for x in value_x:
            if v['mecz'] == f"{x['home']} – {x['away']}": v['raport'] = x.get('raport')
    # najpierw mecze bez poważnych ostrzeżeń, po jednym typie na mecz
    wybrane, uzyte = [], set()
    for bez_ostrzezen in (True, False):
        for t in wszystkie:
            mid = (t['x']['home'], t['x']['away']); ost = bool((t['x'].get('raport') or {}).get('powazne'))
            if bez_ostrzezen and ost: continue
            if t['p'] >= PEWNE_MIN_SZANSA and mid not in uzyte and len(wybrane) < PEWNE_ILE_TYPOW: wybrane.append(t); uzyte.add(mid)
    for t in wszystkie:
        if len(wybrane) >= PEWNE_ILE_TYPOW: break
        mid = (t['x']['home'], t['x']['away'])
        if t['p'] >= 0.55 and mid not in uzyte: wybrane.append(t); uzyte.add(mid)
    pewne, do_dziennika = [], []
    for t in sorted(wybrane, key=lambda t: t['x']['start']):
        x, liga = t['x'], t['liga']
        glowny = wybierz(x, liga, [t['z']], 1.0, 99)
        lepszy = wybierz(x, liga, LEPSZY_KURS, 1.55, 2.30, pmin=0.40, wyklucz=(t['z'],))
        ryzyk = wybierz(x, liga, RYZYKOWNE, 2.50, 5.00, pmin=0.18, wyklucz=(t['z'], lepszy['klucz'] if lepszy else None))
        pewne.append(dict(opis_meczu(x, t['key']), klucz=glowny['klucz'], zaklad=glowny['zaklad'], opis=glowny['opis'], szansa=glowny['szansa'],
                          kurs_uczciwy=glowny['kurs_uczciwy'], kurs_min=glowny['kurs_min'], kurs_betclic=glowny['kurs_betclic'],
                          nizsza_pewnosc=bool(t['p'] < PEWNE_MIN_SZANSA), lepszy_kurs=lepszy, ryzykowny=ryzyk))
        for poziom, typ in (('najpewniejszy', glowny), ('lepszy_kurs', lepszy), ('ryzykowny', ryzyk)):
            if typ: do_dziennika.append(dict(data_zapisu=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'),
                event_id=x['event_id'], liga=x['sport_key'], kraj=x.get('model_key') or '', start=x['start'].strftime('%Y-%m-%d %H:%M'),
                mecz=f"{x['home']} – {x['away']}", gospodarz=x['home'], gosc=x['away'], poziom=poziom, klucz=typ['klucz'],
                zaklad=typ['zaklad'], szansa=typ['szansa'], kurs_uczciwy=typ['kurs_uczciwy'], kurs_betclic=typ['kurs_betclic'],
                zrodlo=x['tryb'], ostrzezenie=bool((x.get('raport') or {}).get('powazne')), wynik='', trafiony=np.nan, zysk_na_1zl=np.nan))
    if do_dziennika: zapisz_pewne(do_dziennika)
    wszystkie_mecze = [opis_meczu(x, key) for _, key, x in sorted(analizy, key=lambda t: (t[0], t[2]['start']))]
    return value, pewne, wszystkie_mecze


# ---------- dziennik typów "Pewne" ----------
PLIK_PEWNE = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data', 'typy_pewne.csv')
PLIK_KALIBRACJI = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data', 'kalibracja.json')

def wczytaj_pewne():
    try: return pd.read_csv(PLIK_PEWNE, dtype={'wynik': str, 'klucz': str, 'event_id': str, 'zaklad': str}, keep_default_na=False, na_values=[''])
    except FileNotFoundError: return pd.DataFrame()

def zapisz_pewne(nowe):
    d = wczytaj_pewne(); n = pd.DataFrame(nowe)
    if len(d):
        klucz = set(zip(d.event_id.astype(str), d.poziom))
        n = n[[(str(a), b) not in klucz for a, b in zip(n.event_id, n.poziom)]]
    if len(n): pd.concat([d, n], ignore_index=True).to_csv(PLIK_PEWNE, index=False); print(f'Dziennik Pewne: +{len(n)} typów')

def rozlicz_pewne(wyniki_api):
    d = wczytaj_pewne()
    if not len(d): return d
    teraz = pd.Timestamp.now(tz='Europe/Warsaw').tz_localize(None)
    for i, r in d[(d.wynik.isna() | (d.wynik == '')) & (pd.to_datetime(d.start) < teraz - pd.Timedelta(hours=2.5))].iterrows():
        w = wyniki_api.get(str(r.event_id)) or wynik_z_danych(r.gospodarz, r.gosc, r.start)
        if not w or None in w or r.klucz not in MASKI: continue
        hg, ag = min(int(w[0]), MAXG), min(int(w[1]), MAXG); traf = bool(MASKI[r.klucz][hg, ag])
        d.loc[i, 'wynik'] = f"{w[0]}:{w[1]}"; d.loc[i, 'trafiony'] = float(traf)
        if pd.notna(r.kurs_betclic) and r.kurs_betclic: d.loc[i, 'zysk_na_1zl'] = (float(r.kurs_betclic) - 1) if traf else -1.0
    d.to_csv(PLIK_PEWNE, index=False); return d

def pobierz_wyniki(ligi):
    """Wyniki z The Odds API (ostatnie 3 dni) – koszt 2 kredyty na ligę."""
    out = {}
    for liga in set(ligi):
        try:
            for s in api(f'sports/{liga}/scores', daysFrom=3):
                if s.get('completed') and s.get('scores'):
                    sc = {x['name']: int(x['score']) for x in s['scores']}; out[s['id']] = (sc.get(s['home_team']), sc.get(s['away_team']))
        except Exception as e: print('wyniki', liga, e)
    return out

def policz_samokorekte(d, minimum=100, maks=0.05):
    """Ostrożna korekta z dziennika: tylko rodzaje typów z min. 100 wynikami, ściągana do zera i ograniczona do ±5 pkt."""
    out = {}
    if not len(d) or 'trafiony' not in d: return out
    R = d[d.trafiony.notna()]
    for k, g in R.groupby('klucz'):
        if len(g) >= minimum:
            roz = (g.trafiony.mean() - g.szansa.mean()) * len(g) / (len(g) + 200)
            out[k] = round(float(np.clip(roz, -maks, maks)), 4)
    return out

def stat_pewne(d):
    if not len(d) or 'trafiony' not in d: return None
    R = d[d.trafiony.notna()]
    if not len(R): return dict(rozliczonych=0, czeka=len(d))
    poziomy = {p: dict(n=int(len(g)), przewidywane=float(g.szansa.mean()), weszlo=float(g.trafiony.mean()),
                       zysk_betclic_10zl=float(g.zysk_na_1zl.dropna().sum() * 10) if g.zysk_na_1zl.notna().any() else None,
                       z_kursem=int(g.zysk_na_1zl.notna().sum()))
               for p, g in R.groupby('poziom')}
    ligi = R.groupby('kraj').agg(n=('trafiony', 'size'), przewidywane=('szansa', 'mean'), weszlo=('trafiony', 'mean'))
    ligi = ligi[ligi.n >= 10].round(3).reset_index().to_dict('records')
    ostrz = R.groupby('ostrzezenie').agg(n=('trafiony', 'size'), przewidywane=('szansa', 'mean'), weszlo=('trafiony', 'mean')).round(3)
    return dict(rozliczonych=int(len(R)), czeka=int(len(d) - len(R)), poziomy=poziomy, ligi=ligi,
                z_ostrzezeniem=ostrz.reset_index().to_dict('records'),
                ostatnie=R.sort_values('start', ascending=False).head(60).replace({np.nan: None})[
                    ['start', 'mecz', 'poziom', 'zaklad', 'szansa', 'wynik', 'trafiony', 'kurs_betclic']].to_dict('records'))

def eksport_modeli():
    out = {}
    for k, m in MODELE.items():
        lista = m.get('eksport', list(m['teams']))
        out[k] = dict(mu=m['mu'], home=m['home'], rho=m['rho'], T=m['T'],
                      druzyny={t: [round(float(m['att'][m['teams'][t]]), 5), round(float(m['dfn'][m['teams'][t]]), 5), m['n_matches'][t]] for t in lista})
    return dict(kalibracja=KALIBRACJA_GOLI, maxg=MAXG, modele=out)

def eksport_dziennika():
    d = wczytaj_dziennik()
    if not len(d): return dict(statystyki=None, typy=[])
    R = d[d.zysk_na_1zl.notna()]
    st = dict(zapisanych=len(d), rozliczonych=len(R), czeka=len(d) - len(R))
    if len(R):
        roi = R.zysk_na_1zl.mean(); se = R.zysk_na_1zl.std() / np.sqrt(len(R)) if len(R) > 1 else None
        st.update(trafione=int((R.zysk_na_1zl > 0).sum()), roi=roi, roi_dol=(roi - 2 * se) if se else None,
                  roi_gora=(roi + 2 * se) if se else None, zysk_10zl=float(R.zysk_na_1zl.sum() * 10),
                  srednia_szansa=float(R.szansa.mean()),
                  krzywa=[round(float(v), 3) for v in (R.sort_values('start').zysk_na_1zl.cumsum() * 10)])
        if 'clv' in R and R.clv.notna().sum() >= 10: st['clv'] = float(R.clv.mean())
    typy = d.sort_values('start', ascending=False).head(300).replace({np.nan: None}).to_dict('records')
    return dict(statystyki=st, typy=typy)

def eksport_calosci():
    dz = eksport_dziennika() if len(wczytaj_dziennik()) else dict(statystyki=None, typy=[])
    dz['pewne'] = stat_pewne(wczytaj_pewne()); dz['samokorekta'] = SAMOKOREKTA
    return dz

def zapisz(nazwa, obj):
    with open(os.path.join(OUT, nazwa), 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o))

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    teraz = pd.Timestamp.now(tz='Europe/Warsaw')
    # harmonogram działa o 10:00 i 11:00 UTC – liczymy raz dziennie, od 12:00 czasu polskiego (latem i zimą)
    if os.environ.get('GITHUB_EVENT_NAME') == 'schedule':
        try: stare = json.load(open(os.path.join(OUT, 'dzis.json')))
        except Exception: stare = {}
        if teraz.hour < 12 or (stare.get('data') == teraz.strftime('%Y-%m-%d') and str(stare.get('wygenerowano', ''))[11:13] >= '12'):
            print('Nie teraz – typy na dziś już policzone albo jest przed 12:00.'); sys.exit(0)
    pobierz_dane(); trenuj()
    zapisz('modele.json', eksport_modeli())
    # kalibracja: przeliczana raz w tygodniu
    try:
        K = json.load(open(PLIK_KALIBRACJI))
        if (teraz.tz_localize(None) - pd.Timestamp(K['data'])).days >= 7: raise ValueError('stara')
    except Exception:
        print('Przeliczam kalibrację…'); K = policz_kalibracje()
        if K: zapisz('kalibracja.json', K)
    core.KALIBRACJA = K
    # samokorekta z dziennika Pewne
    SAMOKOREKTA.update(policz_samokorekte(wczytaj_pewne()))
    today = dict(wygenerowano=teraz.strftime('%Y-%m-%d %H:%M'), data=teraz.strftime('%Y-%m-%d'), value=[], pewne=[], mecze=[], blad=None,
                 raport_dostepny=bool(raport.KLUCZ))
    if not ODDS_API_KEY:
        today['blad'] = 'Brak klucza API (sekret ODDS_API_KEY w ustawieniach repozytorium).'
    else:
        try: today['value'], today['pewne'], today['mecze'] = typy_na_dzis()
        except Exception as e: today['blad'] = f'Nie udało się pobrać kursów: {e}'
        try:
            P_ = wczytaj_pewne(); teraz_ = teraz.tz_localize(None)
            czeka = P_[(P_.wynik.isna() | (P_.wynik == '')) & (pd.to_datetime(P_.start) < teraz_ - pd.Timedelta(hours=2.5))] if len(P_) else P_
            wyn = pobierz_wyniki([l for l in set(czeka.get('liga', [])) if l])
            rozlicz(); rozlicz_pewne(wyn)
        except Exception as e: print('Rozliczenie dziennika nie powiodło się:', e)
    today['api_football_zapytania'] = raport.licznik['zapytania']; today['api_football_bledy'] = raport.bledy[:5]
    zapisz('dzis.json', today)
    zapisz('dziennik.json', eksport_calosci())
    print('Gotowe:', len(today['value']), 'value,', len(today['pewne']), 'pewnych,', len(today['mecze']), 'meczów; API-Football:', raport.licznik['zapytania'])
