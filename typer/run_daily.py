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

def opis_meczu(x, liga):
    mk = markets(x['M'])
    return dict(mecz=f"{x['home']} – {x['away']}", gospodarz=x['home'], gosc=x['away'], liga=NAZWY_LIG.get(liga, liga),
                start=x['start'].strftime('%Y-%m-%d %H:%M'), godzina=x['start'].strftime('%H:%M'), zrodlo=x['tryb'],
                szanse={z: round(float(mk[z]), 4) for z in ['1', 'X', '2', 'Over 2.5', 'BTTS Tak']},
                wyniki=wyniki_top(x['M']), uwaga=x['uwaga'])

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
    # --- 5 NAJPEWNIEJSZYCH ---
    wszystkie = []
    for poz, key, x in sorted(analizy, key=lambda t: (t[0], t[2]['start']))[:PEWNE_ILE_MECZOW]:
        mk = markets(x['M'])
        kor = {'12': -0.035 * (1 if x['tryb'] == 'tylko model' else WAGA_MODELU)}
        for z in ['1', '2', '1X', 'X2', '12', 'Over 1.5', 'Over 2.5', 'Under 3.5']:
            p = mk[z] + kor.get(z, 0)
            if 1 / p < PEWNE_MIN_KURS: continue
            nazwa = z.replace('Over', 'Powyżej').replace('Under', 'Poniżej') + (' gola' if z[:2] in ('Ov', 'Un') else '')
            wszystkie.append(dict(p=p, z=nazwa, opis=NAZWY_ZAKL.get(z, ''), x=x, key=key))
    wszystkie.sort(key=lambda t: -t['p'])
    wybrane, uzyte = [], set()
    for t in wszystkie:
        mid = (t['x']['home'], t['x']['away'])
        if t['p'] >= PEWNE_MIN_SZANSA and mid not in uzyte and len(wybrane) < PEWNE_ILE_TYPOW: wybrane.append(t); uzyte.add(mid)
    for t in wszystkie:
        if len(wybrane) >= PEWNE_ILE_TYPOW: break
        if t not in wybrane and t['p'] >= 0.55 and sum(w['x'] is t['x'] for w in wybrane) < 2: wybrane.append(t)
    pewne = [dict(opis_meczu(t['x'], t['key']), zaklad=t['z'], opis=t['opis'], szansa=round(t['p'], 4), kurs_uczciwy=round(1 / t['p'], 2),
                  kurs_min=round(0.95 / t['p'], 2), nizsza_pewnosc=bool(t['p'] < PEWNE_MIN_SZANSA))
             for t in sorted(wybrane, key=lambda t: t['x']['start'])]
    wszystkie_mecze = [opis_meczu(x, key) for _, key, x in sorted(analizy, key=lambda t: (t[0], t[2]['start']))]
    return value, pewne, wszystkie_mecze

def eksport_modeli():
    out = {}
    for k, m in MODELE.items():
        out[k] = dict(mu=m['mu'], home=m['home'], rho=m['rho'], T=m['T'],
                      druzyny={t: [round(float(m['att'][i]), 5), round(float(m['dfn'][i]), 5), m['n_matches'][t]] for t, i in m['teams'].items()})
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
