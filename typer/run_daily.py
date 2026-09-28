"""Codzienne uruchomienie: dane -> modele -> typy na dziś -> dziennik -> pliki JSON dla aplikacji."""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from core import *
import core

NAZWY_LIG = {'soccer_uefa_champs_league': 'Liga Mistrzów', 'soccer_fifa_world_cup': 'Mistrzostwa świata',
 'soccer_uefa_european_championship': 'Mistrzostwa Europy', 'soccer_uefa_nations_league': 'Liga Narodów',
 'soccer_fifa_world_cup_qualifiers_europe': 'El. mistrzostw świata', 'soccer_uefa_euro_qualification': 'El. mistrzostw Europy',
 'soccer_epl': 'Premier League', 'soccer_spain_la_liga': 'La Liga', 'soccer_poland_ekstraklasa': 'Ekstraklasa',
 'soccer_italy_serie_a': 'Serie A', 'soccer_germany_bundesliga': 'Bundesliga', 'soccer_france_ligue_one': 'Ligue 1',
 'soccer_uefa_europa_league': 'Liga Europy', 'soccer_uefa_europa_conference_league': 'Liga Konferencji',
 'soccer_international_friendlies': 'Mecz towarzyski', 'soccer_portugal_primeira_liga': 'Liga Portugal',
 'soccer_netherlands_eredivisie': 'Eredivisie', 'soccer_efl_champ': 'Championship', 'soccer_germany_bundesliga2': '2. Bundesliga',
 'soccer_turkey_super_league': 'Süper Lig', 'soccer_belgium_first_div': 'Jupiler Pro League', 'soccer_spl': 'Premiership (SCO)'}

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

def korekta(z, x, liga):
    w = 1 if x['tryb'] == 'tylko model' else WAGA_MODELU
    if liga == 'Puchary europejskie': return -0.05 * w if z == 'X2' else 0
    return -0.035 * w if z == '12' else 0

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
        p = r[z][0] + korekta(z, x, liga)
        if p <= pmin or not (kmin <= 1 / p <= kmax): continue
        if najlepszy is None or p > najlepszy[1]: najlepszy = (z, p)
    if not najlepszy: return None
    z, p = najlepszy; kb = kurs_betclic_dla(x, z)
    return dict(klucz=z, zaklad=r[z][1], opis=r[z][2], szansa=round(p, 4), kurs_uczciwy=round(1 / p, 2), kurs_min=round(0.95 / p, 2),
                kurs_betclic=kb, ev=round(p * kb - 1, 4) if kb else None)

def tablica(M):
    g = np.arange(MAXG + 1)
    return dict(xg_gosp=round(float((M.sum(1) * g).sum()), 2), xg_gosc=round(float((M.sum(0) * g).sum()), 2))

def opis_meczu(x, liga):
    mk = markets(x['M'])
    return dict(mecz=f"{x['home']} – {x['away']}", gospodarz=x['home'], gosc=x['away'], liga=NAZWY_LIG.get(liga, liga),
                start=x['start'].strftime('%Y-%m-%d %H:%M'), godzina=x['start'].strftime('%H:%M'), zrodlo=x['tryb'],
                szanse={z: round(float(mk[z]), 4) for z in ['1', 'X', '2', 'Over 2.5', 'BTTS Tak']},
                wyniki=wyniki_top(x['M']), uwaga=x['uwaga'], **tablica(x['M']))

def typy_na_dzis():
    mecze = dzisiejsze_mecze()
    analizy = []
    for key, model, ev in mecze:
        try: x = macierz_meczu(ev, model)
        except Exception as e: print("pominięto", ev.get('home_team'), e); x = None
        if x: analizy.append((list(LIGI_DO_SKANU).index(key), key, x))
    # --- VALUE (Betclic vs Pinnacle/Betfair) ---
    value, do_zapisu = [], []
    for _, key, x in sorted(analizy, key=lambda t: t[2]['start']):
        if x['M_mkt'] is None or not x['ostry']: continue
        for z, kurs, p, e, meta in oferty_betclic(dict(x, M=x['M_mkt'])):
            if KURS_MIN <= kurs <= KURS_MAX and e >= MIN_EV_VALUE:
                zr = x['tryb'].split('+', 1)[-1] if x['M_mod'] is not None else x['tryb']
                value.append(dict(opis_meczu(x, key), zaklad=z, opis=NAZWY_ZAKL.get(z, ''), kurs=kurs, szansa=round(p, 4),
                                  kurs_uczciwy=round(1 / p, 2), ev=round(e, 4), zrodlo=zr, stawka_proc=round(kelly(p, kurs), 4)))
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
            p = r[z][0] + korekta(z, x, liga)
            if 1 / p < PEWNE_MIN_KURS: continue
            wszystkie.append(dict(p=p, z=z, x=x, key=key, liga=liga))
    wszystkie.sort(key=lambda t: -t['p'])
    wybrane, uzyte = [], set()
    for t in wszystkie:
        mid = (t['x']['home'], t['x']['away'])
        if t['p'] >= PEWNE_MIN_SZANSA and mid not in uzyte and len(wybrane) < PEWNE_ILE_TYPOW: wybrane.append(t); uzyte.add(mid)
    for t in wszystkie:
        if len(wybrane) >= PEWNE_ILE_TYPOW: break
        mid = (t['x']['home'], t['x']['away'])
        if t['p'] >= 0.55 and mid not in uzyte: wybrane.append(t); uzyte.add(mid)
    pewne = []
    for t in sorted(wybrane, key=lambda t: t['x']['start']):
        x, liga = t['x'], t['liga']
        glowny = wybierz(x, liga, [t['z']], 1.0, 99)
        lepszy = wybierz(x, liga, LEPSZY_KURS, 1.55, 2.30, pmin=0.40, wyklucz=(t['z'],))
        ryzyk = wybierz(x, liga, RYZYKOWNE, 2.50, 5.00, pmin=0.18, wyklucz=(t['z'], lepszy['klucz'] if lepszy else None))
        pewne.append(dict(opis_meczu(x, t['key']), zaklad=glowny['zaklad'], opis=glowny['opis'], szansa=glowny['szansa'],
                          kurs_uczciwy=glowny['kurs_uczciwy'], kurs_min=glowny['kurs_min'], kurs_betclic=glowny['kurs_betclic'],
                          nizsza_pewnosc=bool(t['p'] < PEWNE_MIN_SZANSA), lepszy_kurs=lepszy, ryzykowny=ryzyk))
    wszystkie_mecze = [opis_meczu(x, key) for _, key, x in sorted(analizy, key=lambda t: (t[0], t[2]['start']))]
    return value, pewne, wszystkie_mecze

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

def zapisz(nazwa, obj):
    with open(os.path.join(OUT, nazwa), 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o))

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    pobierz_dane(); trenuj()
    zapisz('modele.json', eksport_modeli())
    teraz = pd.Timestamp.now(tz='Europe/Warsaw')
    today = dict(wygenerowano=teraz.strftime('%Y-%m-%d %H:%M'), data=teraz.strftime('%Y-%m-%d'), value=[], pewne=[], mecze=[], blad=None)
    if not ODDS_API_KEY:
        today['blad'] = 'Brak klucza API (sekret ODDS_API_KEY w ustawieniach repozytorium).'
    else:
        try: today['value'], today['pewne'], today['mecze'] = typy_na_dzis()
        except Exception as e: today['blad'] = f'Nie udało się pobrać kursów: {e}'
        try: rozlicz()
        except Exception as e: print('Rozliczenie dziennika nie powiodło się:', e)
    zapisz('dzis.json', today)
    zapisz('dziennik.json', eksport_dziennika())
    print('Gotowe:', len(today['value']), 'value,', len(today['pewne']), 'pewnych,', len(today['mecze']), 'meczów')
