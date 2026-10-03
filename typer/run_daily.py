"""Codzienne uruchomienie: dane -> modele -> typy na dziś -> dziennik -> pliki JSON dla aplikacji."""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from core import *
import copy, hashlib, requests, re
import core, raport, powiadomienia as tg, zrodla, ai_raport, sporty, wspolne, analityk, analityk_ai, archiwum, sekcja_zwlok
from nazwy import pl, pl_txt, pl_mecz

NAZWY_LIG = {'soccer_uefa_champs_league': 'Liga Mistrzów', 'soccer_fifa_world_cup': 'Mistrzostwa świata',
 'soccer_uefa_european_championship': 'Mistrzostwa Europy', 'soccer_uefa_nations_league': 'Liga Narodów',
 'soccer_fifa_world_cup_qualifiers_europe': 'El. mistrzostw świata', 'soccer_uefa_euro_qualification': 'El. mistrzostw Europy',
 'soccer_epl': 'Premier League', 'soccer_spain_la_liga': 'La Liga', 'soccer_poland_ekstraklasa': 'Ekstraklasa',
 'soccer_italy_serie_a': 'Serie A', 'soccer_germany_bundesliga': 'Bundesliga', 'soccer_france_ligue_one': 'Ligue 1',
 'soccer_uefa_europa_league': 'Liga Europy', 'soccer_uefa_europa_conference_league': 'Liga Konferencji',
 'soccer_international_friendlies': 'Mecz towarzyski', 'soccer_portugal_primeira_liga': 'Liga Portugal',
 'soccer_netherlands_eredivisie': 'Eredivisie', 'soccer_efl_champ': 'Championship', 'soccer_germany_bundesliga2': '2. Bundesliga',
 'soccer_turkey_super_league': 'Süper Lig', 'soccer_belgium_first_div': 'Jupiler Pro League', 'soccer_spl': 'Premiership (SCO)',
 'soccer_usa_mls': 'MLS (USA)', 'soccer_brazil_campeonato': 'Brasileirão', 'soccer_argentina_primera_division': 'Liga Profesional (ARG)',
 'soccer_mexico_ligamx': 'Liga MX', 'soccer_japan_j_league': 'J1 League', 'soccer_china_superleague': 'Super League (CHN)'}

RAPORT_ILE_MECZOW = 10   # ile meczów sprawdzać w API-Football (darmowy plan: 100 zapytań dziennie)

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
    # (szansa, nazwa, opis, maska wyników); liczby po polsku: 2,5 zamiast 2.5
    przec = lambda t: re.sub(r'(\d)\.(\d)', r'\1,\2', t)
    return {k: (v[0][0], przec(v[1]), przec(v[2]), v[0][1]) for k, v in r.items()}

# korekty z testów: ligi – '12' przeceniane ~3,5 pkt; puchary – 'X2' przeceniane ~5 pkt; skrajne gole i BTTS przeceniane
NAJPEWNIEJSZE = ['1', '2', '1X', 'X2', '12', 'Over 1.5', 'Over 2.5', 'Under 3.5']
# test 30.09 (21 556 meczów 2024–2026): „Obie strzelą – nie” jako ⚖️ 61%→55%, handicap -2,5 jako 🎯 32%→27% – wyłączone z tych poziomów
LEPSZY_KURS = ['1', '2', '1X', 'X2', '12', 'Over 1.5', 'Over 2.5', 'Under 2.5', 'Under 3.5', 'BTTS Tak',
               'H -1.5', 'A -1.5', 'H -2.5', 'A -2.5', 'H -3.5', 'A -3.5', 'Over 3.5', 'Over 4.5', 'H o1.5', 'A o1.5', 'H o2.5', 'A o2.5', 'H o0.5', 'A o0.5']
RYZYKOWNE = ['1', 'X', '2', 'Over 2.5', 'Over 3.5', 'Under 1.5', 'BTTS Tak', 'H -1.5', 'A -1.5',
             'H -3.5', 'A -3.5', 'H -4.5', 'A -4.5', 'Over 4.5', 'Over 5.5', 'H o2.5', 'A o2.5', 'H o1.5', 'A o1.5', '1 & o1.5', '2 & o1.5', '1 & o2.5', '2 & o2.5', 'X & u2.5', 'BTTS & o2.5']

ODRADZANE = []     # typy, które AI odradza (nie trafiają do Pewnych)
ANALITYK_PILKA = 3  # wersja 36 (wariant A): 3 mecze piłki + 2 tenisa/walk dziennie Gemini Pro; wersja 35: ile meczów piłki dziennie analizuje Gemini Pro (w ramach budżetu 150 zł/mies.)
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
    r = rynki_rozszerzone(x['M'], pl(x['home']), pl(x['away'])); najlepszy = None
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
                event_id=x.get('event_id'), sport_key=x.get('sport_key'),
                start=x['start'].strftime('%Y-%m-%d %H:%M'), godzina=x['start'].strftime('%H:%M'), zrodlo=x['tryb'],
                szanse={z: round(float(mk[z]), 4) for z in ['1', 'X', '2', 'Over 2.5', 'BTTS Tak']},
                wyniki=wyniki_top(x['M']), uwaga=x['uwaga'], najczestsze=najczestsze(x['M']),
                analiza=dict(model=x.get('model_key'), h=x.get('model_h'), a=x.get('model_a'),
                             lam=[round(float(v), 4) for v in x['lam_mkt']] if x.get('lam_mkt') is not None else None),
                raport=x.get('raport'), analityk=x.get('analityk'), **tablica(x['M']))

def typy_na_dzis():
    mecze = dzisiejsze_mecze()
    analizy = []
    for key, model, ev in mecze:
        try: x = macierz_meczu(ev, model)
        except Exception as e: print("pominięto", ev.get('home_team'), e); x = None
        if x:                                  # wersja 34 – Analityk: braki w kadrze (FotMob) → korekta szans
            try: analityk.pilka(x, core.score_matrix_rynek, pl)
            except Exception as e: analityk._blad(f"piłka {x.get('home')}: {e}")
        if x: analizy.append((list(LIGI_DO_SKANU).index(key), key, x))
    # --- VALUE: liczona po pobraniu polskich kursów (value_pl.py, z kursy_pl.main – przed Telegramem i przy każdym odświeżeniu) ---
    value, value_x = [], []
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
    naj_meczu = {}                      # najpewniejszy typ każdego meczu (AI ocenia właśnie jego)
    for t in wszystkie: naj_meczu.setdefault(id(t['x']), t)
    for _, key, x in analizy:           # mecze spoza 15 najpopularniejszych też dostają typ do oceny przez AI
        if id(x) in naj_meczu: continue
        r = rynki_rozszerzone(x['M'], x['home'], x['away'])
        lst = [(szansa(z, r[z][0], x), z) for z in NAJPEWNIEJSZE]; lst = [v for v in lst if 1 / v[0] >= PEWNE_MIN_KURS]
        if lst: p, z = max(lst); naj_meczu[id(x)] = dict(p=p, z=z, x=x, key=key, liga=LIGI_DO_SKANU.get(key))
    # raport (nieobecni, nagłówki) + analiza AI: najpierw kandydaci do Pewnych, potem Value, potem pozostałe mecze z listy
    kandydaci = []
    for t in wszystkie:
        if not any(t['x'] is k for k in kandydaci): kandydaci.append(t['x'])
    for v in value_x:
        if not any(v is k for k in kandydaci): kandydaci.append(v)
    for _, _, x in sorted(analizy, key=lambda t: (t[0], t[2]['start'])):
        if not any(x is k for k in kandydaci): kandydaci.append(x)
    limit_ai = min(ai_raport.AI_PILKA, ai_raport.zostalo_analiz())
    for i, x in enumerate(kandydaci[:max(RAPORT_ILE_MECZOW, limit_ai)]):
        polski = x['sport_key'] == 'soccer_poland_ekstraklasa' or 'Poland' in (x['home'], x['away'])
        t = naj_meczu.get(id(x)); rr = rynki_rozszerzone(x['M'], pl(x['home']), pl(x['away'])) if t else None
        mk = markets(x['M'])
        try: x['raport'] = raport.raport(x['home'], x['away'], x['start'], polski=polski, sport_key=x['sport_key'],
                                         rozgrywki=NAZWY_LIG.get(x['sport_key'], ''), ai=i < limit_ai,
                                         typ=((rr[t['z']][1] + (f" ({rr[t['z']][2]})" if rr[t['z']][2] else '')), t['p']) if t else None, szanse={k: float(mk[k]) for k in ('1', 'X', '2')})
        except Exception as e: print('raport:', x['home'], e)
    # wersja 35 – Analityk AI (Gemini Pro: na ślepo → adwokat diabła → sędzia) dla najważniejszych kandydatów; jego werdykt decyduje
    for x in kandydaci:                              # analizy z pamięci (wcześniejsze uruchomienie tego dnia) – bez kosztu
        a = analityk_ai.z_pamieci('pilka', x['event_id'])
        if a:
            r_ = x.get('raport') or {}; x['raport'] = r_
            r_['pro'] = a; r_['werdykt'] = 'zgoda' if a['werdykt'] == 'mocna_zgoda' else a['werdykt']
    for x in kandydaci[:8]:
        if (x.get('raport') or {}).get('pro'): continue
        if analityk_ai.STAN['analiz'] >= ANALITYK_PILKA or not analityk_ai.mozna(): break
        try:
            t = naj_meczu.get(id(x)); rr = rynki_rozszerzone(x['M'], pl(x['home']), pl(x['away'])); mk = markets(x['M'])
            lista = {k: (v[1] + (f' ({v[2]})' if v[2] else ''), round(float(v[0]), 4)) for k, v in rr.items() if k in MASKI and 0.04 <= v[0] <= 0.96}
            typ = ((rr[t['z']][1] + (f" ({rr[t['z']][2]})" if rr[t['z']][2] else '')), t['p']) if t else None
            fm = analityk._fm_mecz.get((x.get('analityk') or {}).get('fotmob_id'))
            rynek = {k: float(mk[k]) for k in ('1', 'X', '2')}
            a = analityk_ai.analiza_pilka(x['home'], x['away'], pl(x['home']), pl(x['away']), NAZWY_LIG.get(x['sport_key'], ''), x['start'], fm, rynek, typ, lista)
            if not a: continue
            r_ = x.setdefault('raport', {}) or {}; x['raport'] = r_
            r_['pro'] = a; r_['werdykt'] = 'zgoda' if a['werdykt'] == 'mocna_zgoda' else a['werdykt']
            analityk_ai.zapisz('pilka', x['event_id'], f"{x['home']} – {x['away']}", x['start'], typ[0] if typ else '', rynek, a, x['sport_key'])
            analityk_ai.do_pamieci('pilka', x['event_id'], a)
        except Exception as e: analityk_ai._blad(f"{x.get('home')}: {type(e).__name__}: {e}")
    for v in value:  # dołącz raporty do kart Value
        for x in value_x:
            if v['mecz'] == f"{x['home']} – {x['away']}": v['raport'] = x.get('raport')
    werd = lambda x: (x.get('raport') or {}).get('werdykt')
    # Pewne: nigdy typy, które AI odradza; najpierw „zgoda” (lub brak oceny), potem „ryzyko”; po jednym typie na mecz
    wybrane, uzyte, odradzane = [], set(), []
    for t in wszystkie:
        mid = (t['x']['home'], t['x']['away'])
        if werd(t['x']) == 'odradza':
            if mid not in uzyte and t['p'] >= PEWNE_MIN_SZANSA and len(odradzane) < 5: odradzane.append(t); uzyte.add(mid)
    for dopuszczalne in (('zgoda', None), ('ryzyko',)):
        for t in wszystkie:
            mid = (t['x']['home'], t['x']['away'])
            if werd(t['x']) not in dopuszczalne: continue
            if t['p'] >= PEWNE_MIN_SZANSA and mid not in uzyte and len(wybrane) < PEWNE_ILE_TYPOW: wybrane.append(t); uzyte.add(mid)
    for t in wszystkie:   # dopełnienie do 5 typami poniżej progu (oznaczone, liczone w dzienniku osobno)
        if len(wybrane) >= PEWNE_ILE_TYPOW: break
        mid = (t['x']['home'], t['x']['away'])
        if t['p'] >= 0.55 and mid not in uzyte and werd(t['x']) != 'odradza': wybrane.append(t); uzyte.add(mid)
    pewne, do_dziennika = [], []
    def wiersz(x, poziom, typ, lista, nizsza):
        return dict(data_zapisu=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'),
                event_id=x['event_id'], liga=x['sport_key'], kraj=x.get('model_key') or '', start=x['start'].strftime('%Y-%m-%d %H:%M'),
                mecz=f"{x['home']} – {x['away']}", gospodarz=x['home'], gosc=x['away'], poziom=poziom, klucz=typ['klucz'],
                zaklad=typ['zaklad'], szansa=typ['szansa'], kurs_uczciwy=typ['kurs_uczciwy'], kurs_betclic=typ['kurs_betclic'],
                zrodlo=x['tryb'], ostrzezenie=bool((x.get('raport') or {}).get('powazne')), wynik='', trafiony=np.nan, zysk_na_1zl=np.nan,
                ai=werd(x) or '', lista=lista, nizsza=bool(nizsza))
    for t in sorted(wybrane, key=lambda t: t['x']['start']):
        x, liga = t['x'], t['liga']
        glowny = wybierz(x, liga, [t['z']], 1.0, 99)
        lepszy = wybierz(x, liga, LEPSZY_KURS, 1.55, 2.30, pmin=0.40, wyklucz=(t['z'],))
        ryzyk = wybierz(x, liga, RYZYKOWNE, 2.50, 5.00, pmin=0.18, wyklucz=(t['z'], lepszy['klucz'] if lepszy else None))
        niz = bool(t['p'] < PEWNE_MIN_SZANSA)
        pewne.append(dict(opis_meczu(x, t['key']), klucz=glowny['klucz'], zaklad=glowny['zaklad'], opis=glowny['opis'], szansa=glowny['szansa'],
                          kurs_uczciwy=glowny['kurs_uczciwy'], kurs_min=glowny['kurs_min'], kurs_betclic=glowny['kurs_betclic'],
                          nizsza_pewnosc=niz, werdykt=werd(x), lepszy_kurs=lepszy, ryzykowny=ryzyk))
        for poziom, typ in (('najpewniejszy', glowny), ('lepszy_kurs', lepszy), ('ryzykowny', ryzyk)):
            if typ: do_dziennika.append(wiersz(x, poziom, typ, 'pewne', niz and poziom == 'najpewniejszy'))
    odr = []
    for t in odradzane:   # nie gramy, ale zapisujemy – dziennik pokaże, czy AI miało rację
        x = t['x']; glowny = wybierz(x, t['liga'], [t['z']], 1.0, 99)
        odr.append(dict(opis_meczu(x, t['key']), klucz=glowny['klucz'], zaklad=glowny['zaklad'], opis=glowny['opis'], szansa=glowny['szansa'],
                        kurs_uczciwy=glowny['kurs_uczciwy'], kurs_min=glowny['kurs_min'], kurs_betclic=glowny['kurs_betclic'], werdykt='odradza'))
        do_dziennika.append(wiersz(x, 'najpewniejszy', glowny, 'odradzane', False))
    ODRADZANE[:] = odr
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
    """Jak w tenisie i walkach: typ meczu na danym poziomie zastępujemy nowym tylko tego samego dnia programu, gdy nie jest
    rozliczony i nowe typy pójdą na Telegram (poza nocą) – dziennik rozlicza to, co dostałeś."""
    d = wczytaj_pewne(); n = pd.DataFrame(nowe)
    if len(d) and len(n):
        dzien_nowych = wspolne.dzien_str()
        stare = {(str(a), b): (wspolne.dzien_str(pd.Timestamp(t).tz_localize('Europe/Warsaw')) if str(t) not in ('', 'nan') else '',
                               str(k), (pd.isna(w) or str(w) == '') and pd.isna(tr))
                 for a, b, t, k, w, tr in zip(d.event_id, d.poziom, d.data_zapisu, d.klucz, d.wynik, d.trafiony)}
        wolno = wspolne.mozna_podmienic_typy(); zastap, zostaw = set(), []
        for i, r in n.iterrows():
            k = (str(r.event_id), r.poziom)
            if k not in stare: zostaw.append(i); continue
            dz, klucz, otwarty = stare[k]
            if klucz != str(r.klucz) and wolno and otwarty and dz == dzien_nowych: zastap.add(k); zostaw.append(i)
        n = n.loc[zostaw]
        if zastap: d = d[[(str(a), b) not in zastap for a, b in zip(d.event_id, d.poziom)]]
    if len(n): pd.concat([d, n], ignore_index=True).to_csv(PLIK_PEWNE, index=False); print(f'Dziennik Pewne: +{len(n)} typów')

def rozlicz_pewne(wyniki_api):
    d = wczytaj_pewne()
    if not len(d): return d
    teraz = pd.Timestamp.now(tz='Europe/Warsaw').tz_localize(None)
    for i, r in d[(d.wynik.isna() | (d.wynik == '')) & (pd.to_datetime(d.start) < teraz - pd.Timedelta(hours=2.5))].iterrows():
        w = wyniki_api.get(str(r.event_id)) or (wynik_z_danych(r.gospodarz, r.gosc, r.start) if DANE else None)
        if not w or None in w or r.klucz not in MASKI: continue
        hg, ag = min(int(w[0]), MAXG), min(int(w[1]), MAXG); traf = bool(MASKI[r.klucz][hg, ag])
        d.loc[i, 'wynik'] = f"{w[0]}:{w[1]}"; d.loc[i, 'trafiony'] = float(traf)
        kurs = r.get('kurs_pl_rano') if pd.notna(r.get('kurs_pl_rano')) and r.get('kurs_pl_rano') else r.kurs_betclic   # od wersji 33: najlepszy polski kurs z rana
        if pd.notna(kurs) and kurs: d.loc[i, 'zysk_na_1zl'] = (float(kurs) - 1) if traf else -1.0
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

def rozlicz_wszystko():
    """Rozlicza oba dzienniki. Wyniki: najpierw ESPN (za darmo), potem The Odds API (2 kredyty na ligę), na końcu dane historyczne."""
    teraz = pd.Timestamp.now(tz='Europe/Warsaw').tz_localize(None)
    V, P_ = wczytaj_dziennik(), wczytaj_pewne()
    def czeka(d):
        if not len(d): return d
        return d[(d.wynik.isna() | (d.wynik == '')) & (pd.to_datetime(d.start) < teraz - pd.Timedelta(hours=2.2))]
    wyniki, braki = {}, set()
    for d in (czeka(V), czeka(P_)):
        for r in d.itertuples():
            if str(r.event_id) in wyniki: continue
            w = tg.wynik(r.liga, r.gospodarz, r.gosc, r.start)
            if w and w[2] == 'post': wyniki[str(r.event_id)] = (w[0], w[1])
            else: braki.add(r.liga)
    if braki and ODDS_API_KEY:
        try: wyniki.update({k: v for k, v in pobierz_wyniki(list(braki)).items() if k not in wyniki})
        except Exception as e: print('wyniki API:', e)
    def wynik_dla(r):
        w = wyniki.get(str(r.event_id))
        if not w and DANE: w = wynik_z_danych(r.gospodarz, r.gosc, r.start)
        return w if w and None not in w else None
    for i, r in czeka(V).iterrows():
        w = wynik_dla(r)
        if w:
            V.loc[i, 'wynik'] = f"{w[0]}:{w[1]}"; V.loc[i, 'zysk_na_1zl'] = round(zysk_zakladu(r.rynek, r.strona, r.linia, r.kurs_betclic, *w), 4)
    if len(V): V.to_csv(PLIK_DZIENNIKA, index=False)
    rozlicz_pewne(wyniki)
    def _wynik_ai(eid, g, a, s, liga):
        if eid in wyniki: return wyniki[eid]
        try:
            w = tg.wynik(liga, g, a, s) if liga else None
            if w and w[2] == 'post': return (w[0], w[1])
        except Exception: pass
        return wynik_z_danych(g, a, s) if DANE else None
    try: analityk_ai.rozlicz_inne(sporty.PLIK_TYPOW)
    except Exception as e: print('Analityk AI – rozliczenie tenis/walki:', e)
    try: analityk_ai.rozlicz(_wynik_ai, MASKI, MAXG)
    except Exception as e: print('Analityk AI – rozliczenie:', e)
    try: analityk_ai.rozlicz(_wynik_ai, MASKI, MAXG, plik=analityk_ai.PLIK_FLASH)      # wersja 44: dziennik Flash
    except Exception as e: print('Flash – rozliczenie:', e)
    return wyniki

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

def _grupa(g):
    return dict(n=int(len(g)), przewidywane=float(g.szansa.mean()), weszlo=float(g.trafiony.mean()), trafione=int(g.trafiony.sum())) if len(g) else None

def stat_pewne(d):
    if not len(d) or 'trafiony' not in d: return None
    d = d.copy()
    d['lista'] = d['lista'].fillna('pewne') if 'lista' in d else 'pewne'
    d['nizsza'] = d['nizsza'].fillna(False).astype(str).str.lower().isin(['true', '1', '1.0']) if 'nizsza' in d else False
    d['ai'] = d['ai'].fillna('').astype(str) if 'ai' in d else ''
    R_all = d[d.trafiony.notna()]
    R = R_all[R_all.lista == 'pewne']
    if not len(R): return dict(rozliczonych=0, czeka=int((d.trafiony.isna() & (d.lista == 'pewne')).sum()))
    poziomy = {p: dict(n=int(len(g)), przewidywane=float(g.szansa.mean()), weszlo=float(g.trafiony.mean()),
                       zysk_betclic_10zl=float(g.zysk_na_1zl.dropna().sum() * 10) if g.zysk_na_1zl.notna().any() else None,
                       z_kursem=int(g.zysk_na_1zl.notna().sum()))
               for p, g in R.groupby('poziom')}
    # główna skuteczność = typ dnia (🔒) z listy Pewne, bez dopełnień poniżej progu
    G = R[(R.poziom == 'najpewniejszy') & ~R.nizsza]
    teraz = pd.Timestamp.now(tz='Europe/Warsaw').tz_localize(None)
    glowne = dict(wszystko=_grupa(G), d30=_grupa(G[pd.to_datetime(G.start) >= teraz - pd.Timedelta(days=30)]),
                  d90=_grupa(G[pd.to_datetime(G.start) >= teraz - pd.Timedelta(days=90)]),
                  nizsza=_grupa(R[(R.poziom == 'najpewniejszy') & R.nizsza]))
    N = R_all[R_all.poziom == 'najpewniejszy']
    ai = dict(zgoda=_grupa(N[(N.ai == 'zgoda') & (N.lista == 'pewne')]), ryzyko=_grupa(N[(N.ai == 'ryzyko') & (N.lista == 'pewne')]),
              odradza=_grupa(N[N.lista == 'odradzane']), bez_oceny=_grupa(N[(N.ai == '') & (N.lista == 'pewne')]))
    ligi = R.groupby('kraj').agg(n=('trafiony', 'size'), przewidywane=('szansa', 'mean'), weszlo=('trafiony', 'mean'))
    ligi = ligi[ligi.n >= 10].round(3).reset_index().to_dict('records')
    ostrz = R.groupby('ostrzezenie').agg(n=('trafiony', 'size'), przewidywane=('szansa', 'mean'), weszlo=('trafiony', 'mean')).round(3)
    ruch = float(R.ruch.dropna().mean()) if 'ruch' in R and R.ruch.notna().sum() >= 5 else None
    return dict(rozliczonych=int(len(R)), czeka=int(((d.trafiony.isna()) & (d.lista == 'pewne')).sum()), poziomy=poziomy, glowne=glowne, ai=ai,
                ligi=ligi, ruch_rynku=ruch, z_ostrzezeniem=ostrz.reset_index().to_dict('records'),
                ostatnie=[dict(r_, zaklad=pl_txt(r_['zaklad'], *str(r_['mecz']).split(' – '))) for r_ in
                          R_all.sort_values('start', ascending=False).head(60).replace({np.nan: None})[
                    ['start', 'mecz', 'poziom', 'zaklad', 'szansa', 'wynik', 'trafiony', 'kurs_betclic', 'ai', 'lista', 'nizsza']].to_dict('records')])

# ---------- SPRAWDZENIE PRZED MECZEM (co 30 min między 12:15 a 00:45) ----------
POZIOMY = (('najpewniejszy', '🔒', None), ('lepszy_kurs', '⚖️', 'lepszy_kurs'), ('ryzykowny', '🎯', 'ryzykowny'))

def _typy_meczu(m):
    """Lista (poziom, ikona, klucz, nazwa, szansa) z karty meczu Pewne."""
    out = []
    for poz, ik, pole in POZIOMY:
        t = m if pole is None else m.get(pole)
        if t and t.get('klucz'): out.append((poz, ik, t['klucz'], t['zaklad'], t['szansa']))
    return out

def _mecze_dnia(d):
    """Unikalne mecze z zakładek Pewne i Value (słowniki z pliku dzis.json)."""
    out, ids = [], set()
    for m in d.get('pewne', []) + d.get('value', []):
        if m.get('event_id') and m['event_id'] not in ids: ids.add(m['event_id']); out.append(m)
    return out

STRAZNIK = []
DIAG = []   # co zrobiło sprawdzenie przed meczem (zapisywane w status.json – zmiana A)

def sprawdz_przed_meczem(d):
    teraz = pd.Timestamp.now(tz='Europe/Warsaw')
    P_, V = wczytaj_pewne(), wczytaj_dziennik(); zmiana = False
    for m in _mecze_dnia(d):
        start = pd.Timestamp(m['start']).tz_localize('Europe/Warsaw'); minut = (start - teraz).total_seconds() / 60
        diag = dict(mecz=pl_mecz(m['mecz']), minut=round(minut))
        # 0) raport AI odświeżany 35–150 min przed meczem (tylko mecze z Pewnych) – trafia do zapowiedzi ok. godzinę przed meczem
        r = m.get('raport')
        if r is not None and 'klucz' in m and 35 <= minut <= 150 and not r.get('ai_odswiezony') and ai_raport.KLUCZ:
            try:
                polski = m.get('sport_key') == 'soccer_poland_ekstraklasa' or 'Poland' in (m['gospodarz'], m['gosc'])
                istotna = raport.odswiez_ai(r, m, polski=polski); r['ai_odswiezony'] = True; zmiana = True
                diag['ai'] = 'odświeżony' + (' – zmiana' if istotna else '')
            except Exception as e: diag['ai'] = f'błąd: {e}'
        if minut < 10 or minut > 100:
            if 'ai' in diag: DIAG.append(diag)
            continue
        stare = copy.deepcopy(m.get('przedmeczowe') or {})
        pm = copy.deepcopy(stare); pierwsze = not stare
        # 1) kursy tuż przed meczem (2 kredyty) – raz na mecz, w oknie 20–100 min
        if not pm.get('kursy') and minut >= 20 and ODDS_API_KEY and (core.KREDYTY['pozostalo'] or 99) > 25:
            try:
                ev = api(f"sports/{m['sport_key']}/events/{m['event_id']}/odds", regions=REGIONY_ODDS_API, markets='h2h,totals', oddsFormat='decimal')
                bm = {b['key']: {mk['key']: mk['outcomes'] for mk in b['markets']} for b in ev.get('bookmakers', [])}
                p1, pov, zr = ostre_prawdopodobienstwa(bm, ev['home_team'], ev['away_team'])
                if p1 is not None:
                    M = core.score_matrix_rynek(*analityk.lambdy_przed_meczem(market_lambdas(*p1, p_over=pov), m))
                    ruch = {poz: [sz, round(float((M * MASKI[k]).sum()), 4)] for poz, ik, k, n, sz in _typy_meczu(m) if k in MASKI}
                    pm['kursy'] = dict(czas=teraz.strftime('%H:%M'), zrodlo=zr, ruch=ruch, szanse={z: round(float((M * MASKI[z]).sum()), 4) for z in '1X2'})
                    for poz, (a, b) in ruch.items():   # zapis do dziennika: szansa tuż przed meczem
                        sel = (P_.event_id.astype(str) == str(m['event_id'])) & (P_.poziom == poz) if len(P_) else []
                        if len(P_) and sel.any(): P_.loc[sel, 'szansa_przed'] = b; P_.loc[sel, 'ruch'] = round(b - a, 4)
                    if 'rynek' in m and len(V):         # Value: CLV = wartość Twojego kursu wobec uczciwego kursu tuż przed meczem
                        sel = (V.event_id.astype(str) == str(m['event_id'])) & (V.zaklad == m['zaklad'])
                        if sel.any():
                            clv = ev_zakladu(M, m['rynek'], m['strona'], m['linia'], m['kurs']); V.loc[sel, 'clv'] = round(float(clv), 4); pm['clv'] = round(float(clv), 4)
                diag['kursy'] = 'tak' if pm.get('kursy') else 'brak ostrych kursów'
            except Exception as e: print('kursy przed meczem:', m['mecz'], e); diag['kursy'] = f'błąd: {str(e)[:80]}'
        # 2) składy – ESPN (za darmo, z liczbą zmian względem poprzedniego meczu); zapas: BSD, potem API-Football (plan płatny)
        if not pm.get('sklady') and minut <= 80:
            try:
                slug, em = tg.znajdz_espn(m.get('sport_key'), m['gospodarz'], m['gosc'], m['start'])
                diag['espn_mecz'] = bool(em)
                s_ = tg.sklady_espn(m.get('sport_key'), m['gospodarz'], m['gosc'], m['start']) if em else None
                if not s_: s_ = zrodla.sklad_bsd(m['gospodarz'], m['gosc'], m['start'])
                if not s_ and (m.get('raport') or {}).get('api'): s_ = raport.sklady(m['raport']['api'])
                if s_: pm['sklady'] = s_
                diag['sklady'] = s_.get('zrodlo', 'API-Football') if s_ else 'jeszcze nie ma'
            except Exception as e: print('składy:', m['mecz'], e); diag['sklady'] = f'błąd: {str(e)[:80]}'
        elif pm.get('sklady'): diag['sklady'] = 'już są'
        # 3) ostrzeżenia
        ost = []
        for poz, (a, b) in (pm.get('kursy') or {}).get('ruch', {}).items():
            if b - a <= -0.05: ost.append(f"rynek odwraca się od typu ({poz.replace('_', ' ')}): {round(a*100)}% → {round(b*100)}%")
        for p in (pm.get('sklady') or {}).get('poza', []):
            kto = pl(m['gospodarz']) if p['strona'] == 'gosp' else pl(m['gosc'])
            ost.append(f"{kto}: {p['zawodnik']} ({p['gole']} goli) {p['gdzie']}")
        for strona, n in ((pm.get('sklady') or {}).get('zmiany') or {}).items():
            if n >= 5: ost.append(f"{pl(m['gospodarz']) if strona == 'gosp' else pl(m['gosc'])}: mocna rotacja – {n} zmian w pierwszym składzie względem poprzedniego meczu")
        pm['ostrzezenia'] = ost
        if pm != stare or pierwsze:
            m['przedmeczowe'] = pm; zmiana = True
        diag['wyslano_tg'] = bool(pm.get('wyslano'))
        DIAG.append(diag)
    if zmiana:
        # to samo sprawdzenie dopisujemy do wszystkich kopii meczu (Pewne i Value mają osobne karty)
        mapa = {m['event_id']: (m.get('przedmeczowe'), m.get('raport')) for m in _mecze_dnia(d)}
        for m in d.get('pewne', []) + d.get('value', []) + d.get('mecze', []):
            if m.get('event_id') in mapa:
                pm_, r_ = mapa[m['event_id']]
                if pm_: m['przedmeczowe'] = pm_
                if r_ and m.get('raport') is not None: m['raport'] = r_
        if len(P_): P_.to_csv(PLIK_PEWNE, index=False)
        if len(V): V.to_csv(PLIK_DZIENNIKA, index=False)
    return zmiana

# ---------------- AI przy każdym meczu z Pewnych i Value (cały dzień, wszystkie dyscypliny) ----------------
def _flash_dziennik(m):
    """Wersja 44: szanse Flash z karty do dziennika typy_flash.csv (ocena AI na dużej próbie)."""
    try:
        ai = (m.get('raport') or {}).get('ai')
        if ai: analityk_ai.zapisz_flash(m.get('event_id') or '', f"{m['gospodarz']} – {m['gosc']}", m['start'], m.get('sport_key', ''), m.get('szanse') or {}, ai)
    except Exception as e: print('Flash – dziennik:', e)

def _ai_pilka(m, typ):
    ok = _ai_pilka_(m, typ)
    if ok: _flash_dziennik(m)
    return ok

def _ai_pilka_(m, typ):
    """Raport AI meczu piłkarskiego do karty (Pewne lub Value). Zwraca True, gdy karta dostała analizę."""
    r = m.get('raport')
    if r is None:   # karta bez raportu (np. tylko Value) – pełny raport: nieobecni, nagłówki i AI
        polski = m.get('sport_key') == 'soccer_poland_ekstraklasa' or 'Poland' in (m['gospodarz'], m['gosc'])
        m['raport'] = raport.raport(m['gospodarz'], m['gosc'], pd.Timestamp(m['start']), polski=polski, sport_key=m.get('sport_key'),
                                    rozgrywki=m.get('liga', ''), ai=True, typ=typ, szanse=m.get('szanse'))
        return bool(m['raport'].get('ai'))
    polski = m.get('sport_key') == 'soccer_poland_ekstraklasa' or 'Poland' in (m['gospodarz'], m['gosc'])
    ai = ai_raport.raport_ai(m['gospodarz'], m['gosc'], pl(m['gospodarz']), pl(m['gosc']), m.get('liga', ''), pd.Timestamp(m['start']),
                             braki=r.get('braki'), zapowiedz=r.get('zapowiedz'), naglowki=[x['tytul'] for v in (r.get('naglowki') or {}).values() for x in v],
                             polski=polski, typ=typ, szanse=m.get('szanse'))
    if not ai: return False
    r['ai'] = ai; r['werdykt'] = ai.get('werdykt')
    try: raport._ostrzezenia_z_brakow(r, m['gospodarz'], m['gosc'])
    except Exception: pass
    return True

def _ai_inne(m):
    if not m.get('naglowki'):
        try: m['naglowki'] = {'a': sporty.naglowki(m['a'], polskie=bool(m.get('rynek_pl'))), 'b': sporty.naglowki(m['b'], polskie=bool(m.get('rynek_pl')))}
        except Exception: pass
    ai = sporty.raport_ai(m, m.get('polski'))
    if not ai: return False
    r = m.setdefault('raport', {}); r['ai'] = ai; r['werdykt'] = ai.get('werdykt')
    if ai.get('ostrzezenie'):
        kto = {'a': m['a'], 'b': m['b'], 'oba': 'obu zawodników'}.get(ai.get('ostrzezenie_dla'), '')
        r['ostrzezenie'] = f"Uwaga ({kto}): {ai['uzasadnienie']}" if kto else ai['uzasadnienie']
    return True

def _ai_inne_value(m, v):
    """Ocena AI pozycji Value tenisa / walki – oceniany jest zakład Value (np. „wygra X”), kontekst z meczu."""
    if not m.get('naglowki'):
        try: m['naglowki'] = {'a': sporty.naglowki(m['a'], polskie=bool(m.get('rynek_pl'))), 'b': sporty.naglowki(m['b'], polskie=bool(m.get('rynek_pl')))}
        except Exception: pass
    ai = sporty.raport_ai(m, m.get('polski'), typ=(v['zaklad'], v['szansa']))
    if not ai: return False
    v['raport'] = dict(v.get('raport') or {}, ai=ai, werdykt=ai.get('werdykt'))
    return True

def uzupelnij_ai(d, inne, limit=12):
    """Każda karta z zakładek Pewne i Value (główne i w każdej dyscyplinie), której mecz się jeszcze nie zaczął, ma mieć analizę AI.
    Pewne: jedna analiza na mecz (ocena typu z Pewnych). Value: każda pozycja ma WŁASNĄ ocenę swojego zakładu (inny typ niż w Pewnych),
    ta sama pozycja w kilku kartach (np. lista dyscypliny i zagnieżdżona w meczu) dostaje tę samą analizę. Zwraca (zrobione, brakuje)."""
    teraz = pd.Timestamp.now(tz='Europe/Warsaw').tz_localize(None)
    zrobione = brak = 0
    grupy = {}   # klucz -> (sport, mecz-kontekst, lista kart)
    def dodaj(k, sp, ctx, karta):
        g = grupy.setdefault(k, (sp, ctx, [])); g[2].append(karta)
    for m in (d or {}).get('pewne', []):
        dodaj(('pilka', str(m.get('event_id') or m['mecz']), 'pewne'), 'pilka', m, m)
    for v in (d or {}).get('value', []):
        dodaj(('pilka', str(v.get('event_id') or v['mecz']), 'value', v.get('zaklad')), 'pilka', v, v)
    for sp in ('tenis', 'walki'):
        s = (inne or {}).get(sp) or {}
        pew = set(str(x) for x in s.get('pewne', []))
        mm = {str(m['event_id']): m for m in s.get('mecze', [])}
        for eid, m in mm.items():
            if eid in pew: dodaj((sp, eid, 'pewne'), sp, m, m)
            for v in m.get('value') or []: dodaj((sp, eid, 'value', v.get('klucz') or v.get('zaklad')), sp, m, v)
        for v in s.get('value', []):
            eid = str(v.get('event_id'))
            if eid in mm: dodaj((sp, eid, 'value', v.get('klucz') or v.get('zaklad')), sp, mm[eid], v)
    for k, (sp, ctx, karty) in grupy.items():
        rodzaj = k[2]
        try:
            if pd.Timestamp(karty[0]['start'] if karty[0].get('start') else ctx['start']) <= teraz: continue   # mecz już trwa / zakończony
        except Exception: continue
        if rodzaj == 'value':   # stara ocena skopiowana z Pewnych (przed v32) nie liczy się – Value ma mieć ocenę swojego zakładu
            for x in karty:
                if (x.get('raport') or {}).get('ai') and not x['raport'].get('dla_value'):
                    x['raport'] = {kk: vv for kk, vv in x['raport'].items() if kk not in ('ai', 'werdykt')}
        ma = next((x['raport']['ai'] for x in karty if (x.get('raport') or {}).get('ai')), None)
        if ma:   # analiza jest w jednej karcie – kopiujemy do pozostałych z tej samej grupy
            for x in karty:
                if not (x.get('raport') or {}).get('ai'):
                    x['raport'] = dict(x.get('raport') or {}, ai=ma, werdykt=ma.get('werdykt'), **({'dla_value': True} if rodzaj == 'value' else {}))
            continue
        if zrobione >= limit or ai_raport.zostalo_analiz() <= 0: brak += 1; continue
        k0 = karty[0]
        try:
            if sp == 'pilka':
                t = k0 if k0.get('zaklad') else None
                typ = (pl_txt(t['zaklad'], k0['gospodarz'], k0['gosc']) + (f" ({pl_txt(t['opis'], k0['gospodarz'], k0['gosc'])})" if t.get('opis') and len(t['zaklad']) <= 3 else ''), t['szansa']) if t else None
                ok = _ai_pilka(k0, typ)
            elif rodzaj == 'value':
                ok = _ai_inne_value(ctx, k0)
            else:
                ok = _ai_inne(k0)
        except Exception as e: print('AI uzupełnienie:', k, e); ok = False
        if ok:
            zrobione += 1
            if rodzaj == 'value': k0['raport']['dla_value'] = True
            for x in karty[1:]:
                x['raport'] = dict(x.get('raport') or {}, ai=k0['raport']['ai'], werdykt=k0['raport']['ai'].get('werdykt'),
                                   **({'dla_value': True} if rodzaj == 'value' else {}))
        else: brak += 1
    STAN_AI.update(zrobione=STAN_AI.get('zrobione', 0) + zrobione, brakuje=brak)
    return zrobione, brak

STAN_AI = {}

# ---------------- zapowiedź ok. godzinę przed meczem (wszystkie dyscypliny, tylko mecze z głównych Pewnych i Value) ----------------
OKNO_ZAPOWIEDZI = (35, 75)   # minut przed startem; sprawdzenia co 30 min – zawsze trafi jedno

def _szansa_klucza(sp, e, k):
    """Szansa typu o kluczu k z przeliczonego meczu tenisa / walki (nowe kursy)."""
    try:
        if sp == 'tenis':
            R = {(w['a'], w['b']): w['szansa'] for w in e.get('wyniki', [])}
            rk = sporty.tenis.rynki(R, int(e.get('bo') or 3))
        elif e.get('metody'):
            me = e['metody']; R = {('A', 'KO'): me['a_ko'], ('A', 'PKT'): me['a_pkt'], ('B', 'KO'): me['b_ko'], ('B', 'PKT'): me['b_pkt']}
            rk = sporty.walki.rynki(R)
        else:
            return {'A': e.get('szansa_a'), 'B': e.get('szansa_b')}.get(k)
        return round(float(sum(R[x] for x in rk[k])), 4) if k in rk else None
    except Exception: return None

def _odswiez_inne(sp, m):
    """Tenis/walki: świeże kursy (1 kredyt) → nowe szanse typów; ponowna analiza AI. Zapis w karcie meczu (inne.json)."""
    nowe = {}
    if m.get('sport_key') != 'ksw' and ODDS_API_KEY and (core.KREDYTY['pozostalo'] or 99) > 25:
        try:
            ev = api(f"sports/{m['sport_key']}/events/{m['event_id']}/odds", regions='eu', markets='h2h', oddsFormat='decimal')
            grupa = 'Tennis' if sp == 'tenis' else ('Mixed Martial Arts' if m.get('dyscyplina') == 'MMA' else 'Boxing')
            e = sporty.przelicz(sp, m['sport_key'], m.get('turniej_oryg') or m.get('turniej', ''), grupa, ev)
            if e:
                for poz in ('najpewniejszy', 'lepszy_kurs', 'ryzykowny'):
                    t = m.get(poz)
                    if t: nowe[t['klucz']] = _szansa_klucza(sp, e, t['klucz'])
                for v in m.get('value', []): nowe[v['klucz']] = _szansa_klucza(sp, e, v['klucz'])
        except Exception as ex: print('zapowiedź – kursy:', m['mecz'], ex)
    try:
        ai = sporty.raport_ai(m, m.get('polski'), wymus=True)
        if ai:
            r = m.setdefault('raport', {}); r['ai'] = ai; r['werdykt'] = ai.get('werdykt')
            if ai.get('ostrzezenie'):
                kto = {'a': m['a'], 'b': m['b'], 'oba': 'obu zawodników'}.get(ai.get('ostrzezenie_dla'), '')
                r['ostrzezenie'] = f"Uwaga ({kto}): {ai['uzasadnienie']}" if kto else ai['uzasadnienie']
    except Exception as ex: print('zapowiedź – AI:', m['mecz'], ex)
    m['przed'] = dict(czas=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%H:%M'), szanse={k: v for k, v in nowe.items() if v is not None})
    return m['przed']['szanse']

def _linia_szansy(ik, nazwa, stara, nowa, t=None):
    txt = f"{ik} {esc_(nazwa)} · {tg.pct(stara)}"
    if nowa is not None:
        txt += f" → <b>{tg.pct(nowa)}</b>" if abs(nowa - stara) >= 0.005 else ' (bez zmian)'
    return txt

def tekst_zapowiedzi(sp, m, wartosci, minut, powody=None):
    """Jedna wiadomość: typy ze świeżą szansą, kursy, składy (piłka), werdykt i analiza AI, braki, ostrzeżenia.
    Od wersji 33 wysyłana tylko jako ALARM – gdy przed meczem zmieniło się coś ważnego (powody na górze)."""
    ik = wspolne.IKONA[sp]; gdzie = (m.get('liga') if sp == 'pilka' else m.get('turniej')) or ''
    if powody:
        lin = [f"🚨 <b>Zmiana przed meczem</b> · {ik} <b>{esc_(_nazwa_meczu(sp, m))}</b> · {m['godzina']} (za ok. {int(round(minut / 5) * 5)} min)"]
    else:
        lin = [f"⏰ <b>Za ok. {int(round(minut / 5) * 5)} min</b> · {ik} <b>{esc_(_nazwa_meczu(sp, m))}</b> · {m['godzina']}"]
    if gdzie: lin.append(f"<i>{esc_(gdzie)}</i>")
    for p_ in powody or []: lin.append(f"⚠️ <b>{esc_(p_)}</b>")
    lin.append('')
    if sp == 'pilka':
        pm = m.get('przedmeczowe') or {}; ruch = (pm.get('kursy') or {}).get('ruch', {})
        for poz, ikp, k, n, sz in _typy_meczu(m):
            if 'klucz' not in m: break
            t = m if poz == 'najpewniejszy' else (m.get(poz) or {})
            z = pl_txt(n, m['gospodarz'], m['gosc'])
            if len(z) <= 3 and t.get('opis'): z = f"{z} ({pl_txt(t['opis'], m['gospodarz'], m['gosc'])})"
            lin.append(_linia_szansy(ikp, z, sz, (ruch.get(poz) or [None, None])[1]))
            if poz == 'najpewniejszy': lin.append('   ' + _kursy_linia(m))
    else:
        nowe = (m.get('przed') or {}).get('szanse') or {}
        for poz, ikp in (('najpewniejszy', '🔒'), ('lepszy_kurs', '⚖️'), ('ryzykowny', '🎯')):
            t = m.get(poz)
            if not t or not wartosci.get('pewne'): continue
            lin.append(_linia_szansy(ikp, t['zaklad'], t['szansa'], nowe.get(t['klucz'])))
            if poz == 'najpewniejszy': lin.append('   ' + _kursy_linia(t))
    for v in wartosci.get('value', []):
        zak = pl_txt(v['zaklad'], v.get('gospodarz'), v.get('gosc')) if sp == 'pilka' else v['zaklad']
        kk = {_nazwa_buk(n): k for n, k in ((v.get('kursy_pl') or {}).items())}
        if v.get('kurs'): kk.setdefault(_nazwa_buk(v.get('bukmacher') or 'Betclic FR'), v['kurs'])
        best = max(((n, k) for n, k in kk.items() if k), key=lambda x: x[1], default=(_nazwa_buk(v.get('bukmacher') or 'Betclic FR'), v['kurs']))
        clv = (v.get('przedmeczowe') or {}).get('clv')
        lin.append(f"💰 Value: {esc_(zak)} @ <b>{tg.kurs(best[1])}</b> {esc_(best[0])}" + (f" · CLV {clv * 100:+.1f}%" if clv is not None else ''))
    if sp == 'pilka':
        pm = m.get('przedmeczowe') or {}
        sk = pm.get('sklady')
        lin.append('')
        lin.append(f"👥 Składy: potwierdzone ({esc_(sk.get('zrodlo', ''))})" if sk else '👥 Składy: jeszcze nie ogłoszone')
        for o in pm.get('ostrzezenia', []):
            if o not in (powody or []): lin.append(f"⚠️ {esc_(o)}")
    raport = _raport_tg(m, None, sp).split('\n')[1:]   # bez nagłówka – jest wyżej
    if raport: lin += [''] + raport
    return '\n'.join(lin)

PROG_SPADKU = 0.05            # alarm, gdy szansa typu dnia spadła przed meczem o ≥5 pkt
OKNO_ALARMU = (10, 75)        # minut przed startem: przeliczenie (tenis/walki raz) i ocena zmian

def powody_alarmu(sp, m, wart, werdykt_przed=None, ostrz_przed=None):
    """Co zmieniło się przed meczem na tyle, żeby wysłać alarm (lista krótkich powodów; pusta = bez wiadomości)."""
    pw = []
    if sp == 'pilka':
        pm = m.get('przedmeczowe') or {}
        if wart.get('pewne') and 'klucz' in m:
            a_b = ((pm.get('kursy') or {}).get('ruch') or {}).get('najpewniejszy')
            if a_b and a_b[1] is not None and a_b[0] - a_b[1] >= PROG_SPADKU:
                pw.append(f"szansa typu dnia spadła: {tg.pct(a_b[0])} → {tg.pct(a_b[1])}")
        for o in pm.get('ostrzezenia', []):
            if not o.startswith('rynek odwraca'): pw.append(o)          # składy: brak ważnego zawodnika, mocna rotacja
        ai = (m.get('raport') or {}).get('ai') or {}
        if wart.get('pewne') and ai.get('werdykt') == 'odradza' and m.get('werdykt') != 'odradza':
            pw.append('AI teraz odradza' + (f": {ai.get('powod')}" if ai.get('powod') else ''))
        for v in wart.get('value', []):
            clv = (v.get('przedmeczowe') or {}).get('clv')
            if clv is not None and clv <= -0.03: pw.append(f"Value straciła przewagę – rynek poszedł przeciw (CLV {clv * 100:+.1f}%)")
    else:
        nowe = (m.get('przed') or {}).get('szanse') or {}
        t = m.get('najpewniejszy')
        if wart.get('pewne') and t and nowe.get(t['klucz']) is not None and t['szansa'] - nowe[t['klucz']] >= PROG_SPADKU:
            pw.append(f"szansa typu dnia spadła: {tg.pct(t['szansa'])} → {tg.pct(nowe[t['klucz']])}")
        r = m.get('raport') or {}
        if r.get('werdykt') == 'odradza' and werdykt_przed != 'odradza':
            pw.append('AI teraz odradza' + (f": {(r.get('ai') or {}).get('powod')}" if (r.get('ai') or {}).get('powod') else ''))
        if r.get('ostrzezenie') and r.get('ostrzezenie') != ostrz_przed: pw.append(str(r['ostrzezenie'])[:200])
        for v in wart.get('value', []):
            nz = nowe.get(v.get('klucz'))
            if nz is not None and v.get('kurs') and nz * float(v['kurs']) - 1 < 0:
                pw.append(f"Value bez przewagi przy nowych kursach ({v['zaklad']}: {tg.pct(nz)} przy kursie {tg.kurs(v['kurs'])})")
    return pw

def _przed_do_dziennika_inne(eid, szanse):
    """Tenis/walki: szansa typu tuż przed meczem do dziennika (porównanie poranny vs przedmeczowy – do nauki)."""
    if not szanse: return
    try:
        d = sporty.wczytaj_typy()
        if not len(d): return
        if 'szansa_przed' not in d: d['szansa_przed'] = np.nan
        sel = d.event_id.astype(str) == str(eid)
        if not sel.any(): return
        for i in d[sel].index:
            k = str(d.at[i, 'klucz'])
            if k in szanse and szanse[k] is not None: d.at[i, 'szansa_przed'] = round(float(szanse[k]), 4)
        d.to_csv(sporty.PLIK_TYPOW, index=False)
    except Exception as e: print('dziennik – szansa przed meczem:', e)

def zapowiedzi(d):
    """Ok. godzinę przed meczem z głównych list (Pewne i Value, wszystkie dyscypliny): przeliczenie szans (tenis/walki – świeże
    kursy i AI; piłka – sprawdzenie przed meczem), zapis do dziennika i ALARM na Telegram tylko przy realnej zmianie
    (spadek szansy ≥5 pkt, ważny zawodnik poza składem, mocna rotacja, AI teraz odradza, Value bez przewagi).
    Wersja 33: bez rutynowych zapowiedzi. Zwraca liczbę wysłanych alarmów."""
    gl = wspolne.wczytaj(); inne = sporty.wczytaj_json(); st = wczytaj_status()
    dz = gl.get('data') or wspolne.dzien_str()
    zap = st.get('zapowiedzi') or {}
    if zap.get('data') != dz: zap = dict(data=dz, wyslane=[], przeliczone={})
    zap.setdefault('przeliczone', {})
    teraz = pd.Timestamp.now(tz='Europe/Warsaw')
    pew, val = _rozwiaz(gl, d, inne)
    mecze = {}
    for sp, m in pew: mecze.setdefault((sp, str(m.get('event_id') or m['mecz'])), [m, dict(pewne=True, value=[])])
    for sp, v in val:
        k = (sp, str(v.get('event_id') or v['mecz']))
        if k not in mecze:
            karta = v if sp == 'pilka' else next((x for x in (inne.get(sp) or {}).get('mecze', []) if str(x['event_id']) == k[1]), None)
            if not karta: continue
            mecze[k] = [karta, dict(pewne=False, value=[])]
        mecze[k][1]['value'].append(v)
    wyslane, inne_zmiana = 0, False
    for (sp, eid), (m, wart) in mecze.items():
        klucz = f'{sp}:{eid}'
        if klucz in zap['wyslane']: continue
        minut = (pd.Timestamp(m['start']).tz_localize('Europe/Warsaw') - teraz).total_seconds() / 60
        if not (OKNO_ALARMU[0] <= minut <= OKNO_ALARMU[1]): continue
        r0 = m.get('raport') or {}; w0, o0 = r0.get('werdykt'), r0.get('ostrzezenie')
        if sp != 'pilka':
            if klucz in zap['przeliczone']: continue                     # tenis/walki: jedno przeliczenie na mecz
            nowe = _odswiez_inne(sp, m); inne_zmiana = True
            _przed_do_dziennika_inne(eid, nowe)
        powody = powody_alarmu(sp, m, wart, w0, o0)
        zap['przeliczone'][klucz] = dict(czas=teraz.strftime('%H:%M'), minut=round(minut), alarm=bool(powody), powody=powody[:4])
        if powody and tg.wyslij_dlugi(tekst_zapowiedzi(sp, m, wart, minut, powody)): zap['wyslane'].append(klucz); wyslane += 1
    if inne_zmiana:
        with open(os.path.join(OUT, sporty.PLIK_JSON), 'w', encoding='utf-8') as f:
            json.dump(inne, f, ensure_ascii=False, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o))
    st['zapowiedzi'] = zap; zapisz('status.json', st)
    return wyslane

def tg_przed_meczem(m, pm):
    if pm.get('wyslano'): return
    lin = [f"🕐 <b>{esc_(pl_mecz(m['mecz']))}</b> – {m['godzina']}"]
    if pm.get('sklady'): lin.append(f"✅ Składy potwierdzone ({esc_(pm['sklady'].get('zrodlo', ''))})")
    for poz, ik, k, n, sz in _typy_meczu(m):
        nowa = (pm.get('kursy') or {}).get('ruch', {}).get(poz, [sz, None])[1]
        lin.append(f"{ik} {esc_(pl_txt(n, m['gospodarz'], m['gosc']))} – {tg.pct(sz)}" + (f" → {tg.pct(nowa)}" if nowa is not None else ''))
    if 'kurs' in m: lin.append(f"💰 {esc_(pl_txt(m['zaklad'], m['gospodarz'], m['gosc']))} @ {m['kurs']}" + (f" (CLV {pm['clv']*100:+.1f}%)" if pm.get('clv') is not None else ''))
    for o in pm.get('ostrzezenia', []): lin.append(f"⚠️ {esc_(o)}")
    if pm.get('sklady') or pm.get('ostrzezenia'):
        if tg.wyslij('\n'.join(lin)): pm['wyslano'] = True

esc_ = lambda s: tg.esc(s)

def _raport_tg(m, nr=None):
    """Blok raportu jednego meczu do wiadomości na Telegramie."""
    r = m.get('raport') or {}; ai = r.get('ai')
    naglowek = f"<b>{str(nr) + '. ' if nr else ''}{esc_(pl_mecz(m['mecz']))}</b> ({m['godzina']})"
    lin = [naglowek]
    if ai:
        lin.append(esc_(ai['tekst']))
        for s, kto in (('braki_gosp', pl(m['gospodarz'])), ('braki_gosc', pl(m['gosc']))):
            if ai.get(s): lin.append(f"❌ {esc_(kto)}: {esc_(', '.join(ai[s][:6]))}")
        if ai.get('niepewni'): lin.append(f"❓ Niepewni: {esc_(', '.join(ai['niepewni'][:5]))}")
        zr = [z['tytul'] for z in ai.get('zrodla', [])][:3]
        if zr: lin.append(f"<i>Źródła: {esc_(', '.join(zr))}</i>")
    else:
        br = r.get('braki') or {}
        for s, kto in (('gosp', pl(m['gospodarz'])), ('gosc', pl(m['gosc']))):
            if br.get(s): lin.append(f"❌ {esc_(kto)}: {esc_(', '.join(p['zawodnik'] + (' (?)' if p.get('niepewny') else '') for p in br[s][:6]))}")
        if len(lin) == 1: lin.append('Raport AI niedostępny dla tego meczu; brak nieobecnych w bazach danych.' if ai_raport.KLUCZ else 'Brak nieobecnych w bazach danych.')
    for o in r.get('ostrzezenia', []): lin.append(f"⚠️ {esc_(o)}")
    return '\n'.join(lin)

def tg_raporty(d):
    """Druga wiadomość: raporty przedmeczowe dla meczów z Pewnych (zmiana J)."""
    if not d.get('pewne'): return
    czesci = [_raport_tg(m, i) for i, m in enumerate(d['pewne'], 1)]
    if not any((m.get('raport') or {}).get('ai') for m in d['pewne']):
        czesci.append('<i>Raport AI niedostępny – pokazuję nieobecnych z baz danych.</i>')
    tg.wyslij_dlugi('\n\n'.join(czesci))

def tg_aktualizacja_raportu(m, r):
    tg.wyslij('🔄 <b>Aktualizacja raportu</b>\n' + _raport_tg(dict(m, raport=r)))

def _podpis_typow(d):
    """Odcisk typów dnia – ta sama lista typów nie jest wysyłana drugi raz (zmiana G)."""
    t = [(m['mecz'], [k for _, _, k, _, _ in _typy_meczu(m)]) for m in d.get('pewne', [])] + [(v['mecz'], v['zaklad']) for v in d.get('value', [])]
    return hashlib.md5(json.dumps(t, ensure_ascii=False).encode()).hexdigest()[:12]

def tg_typy_dnia(d, status):
    """Typy dnia + raporty. Raz dziennie; ponownie tylko przy zmianie typów; nie w nocy (00–08)."""
    if not d.get('pewne') and not d.get('value'): return 'brak typów'
    teraz = pd.Timestamp.now(tz='Europe/Warsaw')
    if teraz.hour < 7: return 'wstrzymane (noc) – wyślę rano (ok. 8:00)'
    wys = status.get('tg_typy') or {}
    podpis = _podpis_typow(d)
    n_ai = sum(1 for m in d.get('pewne', []) if (m.get('raport') or {}).get('ai'))
    if wys.get('data') == d['data']:   # raz dziennie – zmiany tylko w aplikacji, przed meczem przychodzi zapowiedź
        return 'już wysłane dziś (zmiany tylko w aplikacji)'
    zmiana = wys.get('data') == d['data']
    lin = [f"⚽ <b>{'Zaktualizowane typy' if zmiana else 'Typy'} na {pd.Timestamp(d['data']).strftime('%d.%m')}</b>"]
    for i, m in enumerate(d.get('pewne', []), 1):
        lin.append(f"\n<b>{i}. {esc_(pl_mecz(m['mecz']))}</b> ({m['godzina']}, {esc_(m['liga'])})")
        for poz, ik, k, n, sz in _typy_meczu(m): lin.append(f"{ik} {esc_(pl_txt(n, m['gospodarz'], m['gosc']))} – {tg.pct(sz)} (kurs ≥ {tg.kurs(1/sz)})")
        if (m.get('raport') or {}).get('ostrzezenia'): lin.append('⚠️ ' + esc_('; '.join(m['raport']['ostrzezenia'])))
    if d.get('value'):
        lin.append('\n💰 <b>Value</b> <i>(polskie kursy)</i>')
        for v in d['value']: lin.append(f"{esc_(pl_mecz(v['mecz']))}: {esc_(pl_txt(v['zaklad'], v.get('gospodarz'), v.get('gosc')))} @ {tg.kurs(v['kurs'])} {esc_(_nazwa_buk(v.get('bukmacher') or ''))} (szansa {tg.pct(v['szansa'])}, szukaj ≥ {tg.kurs(v.get('kurs_szukaj', ''))})")
    if tg.APLIKACJA: lin.append(f"\n📱 {tg.APLIKACJA}")
    if tg.wyslij_dlugi('\n'.join(lin)):
        status['tg_typy'] = dict(data=d['data'], podpis=podpis, czas=teraz.strftime('%H:%M'), ai=n_ai)
        tg_raporty(d)
        return 'wysłane'
    return 'błąd wysyłki'

def _rozwiaz(gl, d, inne):
    """Pozycje z glowne.json -> pełne karty (piłka z dzis.json, reszta z inne.json)."""
    pew, val = [], []
    for r in gl.get('pewne', []):
        if r['sport'] == 'pilka': m = next((x for x in d.get('pewne', []) if str(x.get('event_id') or x['mecz']) == r['event_id']), None)
        else: m = next((x for x in (inne.get(r['sport']) or {}).get('mecze', []) if str(x['event_id']) == r['event_id']), None)
        if m: pew.append((r['sport'], m))
    for r in gl.get('value', []):
        zr = d.get('value', []) if r['sport'] == 'pilka' else (inne.get(r['sport']) or {}).get('value', [])
        v = next((x for x in zr if str(x.get('event_id') or x['mecz']) == r['event_id'] and x['zaklad'] == r['zaklad']), None)
        if v: val.append((r['sport'], v))
    return pew, val

WERDYKT_TG = {'zgoda': ('✅', 'zgoda z faworytem'), 'ryzyko': ('⚠️', 'ryzyko niespodzianki'), 'odradza': ('⛔', 'AI odradza')}
DNI_PL = ['poniedziałek', 'wtorek', 'środa', 'czwartek', 'piątek', 'sobota', 'niedziela']

BUKMACHERZY_TG = ['STS', 'Fortuna', 'Superbet', 'Betclic']

def _nazwa_buk(n): return 'Betclic' if n == 'Betclic PL' else n

def _kursy_linia(t):
    """„STS 1,30 · Superbet 1,29 · Fortuna 1,28 · Betclic —” – najlepszy pierwszy i pogrubiony (bez gwiazdki); „—” = bukmacher nie ma zakładu,
    „?” = nie odczytano kursu (problem programu). Tylko polscy bukmacherzy (Betclic = Betclic PL)."""
    kk = sorted({_nazwa_buk(n): float(k) for n, k in (t.get('kursy_pl') or {}).items() if k and float(k) > 1}.items(), key=lambda x: -x[1])
    if not kk: return f"kurs uczciwy {tg.kurs(1 / t['szansa'])} – graj od tego kursu"
    odczyt = {_nazwa_buk(n) for n in (t.get('kursy_odczyt') or [])}
    czesci = [f"{esc_(n)} <b>{tg.kurs(k)}</b>" if i == 0 else f"{esc_(n)} {tg.kurs(k)}"
              for i, (n, k) in enumerate(kk)]
    obecni = {n for n, _ in kk}
    czesci += [f"{n} {'—' if n in odczyt else '?'}" for n in BUKMACHERZY_TG if n not in obecni]
    return ' · '.join(czesci)

def _ai_karty(sp, m):
    r = m.get('raport') or {}; ai = r.get('ai') or {}
    return ai.get('werdykt') or r.get('werdykt') or m.get('werdykt'), ai

def _nazwa_meczu(sp, m): return pl_mecz(m['mecz']) if sp == 'pilka' else m['mecz']

def _linie_pewnego(sp, m, i):
    ik = wspolne.IKONA[sp]
    glowny = m if sp == 'pilka' else (m.get('najpewniejszy') or {})
    def zak(t, z=None):
        z = t['zaklad'] if z is None else z
        if sp != 'pilka': return z
        z = pl_txt(z, m['gospodarz'], m['gosc'])
        return f"{z} ({pl_txt(t['opis'], m['gospodarz'], m['gosc'])})" if len(z) <= 3 and t.get('opis') else z
    gdzie = (m.get('liga') if sp == 'pilka' else m.get('turniej')) or ''
    lin = [f"\n<b>{i}. {ik} {esc_(_nazwa_meczu(sp, m))}</b> · {m['godzina']}" + (f" · <i>{esc_(gdzie)}</i>" if gdzie else '')]
    if glowny.get('zaklad'):
        lin.append(f"{esc_(zak(glowny))} · <b>{tg.pct(glowny['szansa'])}</b>" + (' <i>(poniżej 70%)</i>' if m.get('nizsza_pewnosc') else ''))
        lin.append(_kursy_linia(glowny))
    w, ai = _ai_karty(sp, m)
    if w: lin.append(f"{WERDYKT_TG[w][0]} AI: {WERDYKT_TG[w][1]}" + (f" – {esc_(ai['powod'])}" if ai.get('powod') else ''))
    for pole, ikp, nazwa in (('lepszy_kurs', '⚖️', 'Wyższy kurs'), ('ryzykowny', '🎯', 'Ryzykowny')):
        t = m.get(pole)
        if t: lin.append(f"{ikp} {nazwa}: {esc_(zak(t))} · {tg.pct(t['szansa'])} · od {tg.kurs(1 / t['szansa'])}")
    return lin

def _skutecznosc_30():
    """Główna skuteczność (typy dnia 🔒) z 30 dni – piłka + tenis + walki."""
    n = t = 0
    try:
        g = ((stat_pewne(wczytaj_pewne()) or {}).get('glowne') or {}).get('d30') or {}; n += g.get('n', 0); t += g.get('trafione', 0)
    except Exception: pass
    try:
        for sp, s in sporty.statystyki().items():
            g = ((s or {}).get('glowne') or {}).get('d30') or {}; n += g.get('n', 0); t += g.get('trafione', 0)
    except Exception: pass
    return (t, n) if n else None

def _raport_tg(m, nr=None, sp='pilka'):
    """Raport jednego meczu: werdykt AI, analiza w zwijanym cytacie, braki, forma, styl, lepszy zakład, źródła."""
    r = m.get('raport') or {}; ai = r.get('ai')
    lin = [f"📰 <b>{str(nr) + '. ' if nr else ''}{wspolne.IKONA.get(sp, '')} {esc_(_nazwa_meczu(sp, m))}</b> · {m['godzina']}"]
    if ai:
        w = ai.get('werdykt')
        if w: lin.append(f"{WERDYKT_TG[w][0]} <b>{WERDYKT_TG[w][1].capitalize()}</b>" + (f" – {esc_(ai['powod'])}" if ai.get('powod') else ''))
        lin.append(f"<blockquote expandable>{esc_(ai['tekst'])}</blockquote>")
        if ai.get('forma'): lin.append(f"<b>Forma:</b> {esc_(ai['forma'])}")
        if ai.get('styl'): lin.append(f"<b>Styl:</b> {esc_(ai['styl'])}")
        if sp == 'pilka':
            br = [f"{esc_(pl(k))}: {esc_(', '.join(ai[s][:5]))}" for s, k in (('braki_gosp', m['gospodarz']), ('braki_gosc', m['gosc'])) if ai.get(s)]
            if br: lin.append('<b>Nie zagrają:</b> ' + ' · '.join(br))
            if ai.get('niepewni'): lin.append(f"<b>Niepewni:</b> {esc_(', '.join(ai['niepewni'][:5]))}")
        else:
            pr = [f"{esc_(k)}: {esc_(', '.join(ai[s][:4]))}" for s, k in (('problemy_a', m['a']), ('problemy_b', m['b'])) if ai.get(s)]
            if pr: lin.append('<b>Problemy:</b> ' + ' · '.join(pr))
        if ai.get('lepszy_zaklad'): lin.append(f"<b>Lepszy zakład:</b> {esc_(ai['lepszy_zaklad'])}")
        zr = [z['tytul'] for z in ai.get('zrodla', [])][:3]
        if zr: lin.append(f"<i>Źródła: {esc_(', '.join(zr))}</i>")
    elif sp == 'pilka':
        br = r.get('braki') or {}
        for s, kto in (('gosp', pl(m['gospodarz'])), ('gosc', pl(m['gosc']))):
            if br.get(s): lin.append(f"<b>Nie zagrają – {esc_(kto)}:</b> {esc_(', '.join(p['zawodnik'] + (' (?)' if p.get('niepewny') else '') for p in br[s][:6]))}")
        if len(lin) == 1: lin.append('<i>Brak analizy AI dla tego meczu; brak nieobecnych w bazach danych.</i>')
    else:
        ng = [h['tytul'] for k in ('a', 'b') for h in (m.get('naglowki') or {}).get(k, [])][:3]
        lin.append(('<i>Nagłówki:</i> ' + esc_(' | '.join(ng))) if ng else '<i>Brak analizy AI i świeżych wiadomości.</i>')
    for o in (r.get('ostrzezenia') or ([r['ostrzezenie']] if r.get('ostrzezenie') else []))[:2]: lin.append(f"⚠️ {esc_(plTxt_bezp(o, m))}")
    return '\n'.join(lin)

def plTxt_bezp(o, m):
    try: return pl_txt(o, m.get('gospodarz'), m.get('gosc')) if m.get('gospodarz') else o
    except Exception: return o

def _raport_inne_tg(m, nr): return _raport_tg(m, nr, m['sport'])

def tg_typy_wszystkie(d, inne, gl, status):
    """Jedna wiadomość dziennie: 5 Pewnych i Value ze wszystkich dyscyplin (kursy wszystkich bukmacherów, werdykt AI),
    potem zwięźle pozostałe najpewniejsze typy z zakładek każdej dyscypliny (bez powtórzeń); zaraz potem raporty."""
    pew, val = _rozwiaz(gl, d, inne)
    if not pew and not val: return 'brak typów'
    teraz = pd.Timestamp.now(tz='Europe/Warsaw')
    if teraz.hour < 7: return 'wstrzymane (noc) – wyślę rano (ok. 8:00)'
    podpis = hashlib.md5(json.dumps([(sp, str(m.get('event_id')), [(m.get(p) or {}).get('klucz') for p in ('lepszy_kurs', 'ryzykowny')] + [m.get('klucz') or (m.get('najpewniejszy') or {}).get('klucz')]) for sp, m in pew]
                                    + [(sp, str(v.get('event_id')), v['zaklad']) for sp, v in val], ensure_ascii=False).encode()).hexdigest()[:12]
    n_ai = sum(1 for _, m in pew if (m.get('raport') or {}).get('ai'))
    wys = status.get('tg_typy') or {}
    if wys.get('data') == gl.get('data'):   # raz dziennie – zmiany tylko w aplikacji, przed meczem przychodzi zapowiedź
        return 'już wysłane dziś (zmiany tylko w aplikacji)'
    zmiana = wys.get('data') == gl.get('data')
    dzien = pd.Timestamp(gl.get('data') or wspolne.dzien_str())
    lin = [f"📋 <b>{'Zaktualizowane typy' if zmiana else 'Typy dnia'} · {DNI_PL[dzien.weekday()]} {dzien.strftime('%d.%m')}</b>"]
    sk = _skutecznosc_30()
    lin.append(f"{len(pew)} najpewniejszych" + (f" · 30 dni: <b>{round(100 * sk[0] / sk[1])}%</b> ({sk[0]}/{sk[1]})" if sk and sk[1] >= 10 else ''))
    for i, (sp, m) in enumerate(pew, 1): lin += _linie_pewnego(sp, m, i)
    odr = [('pilka', m) for m in (d.get('odradzane') or [])] + [(sp, m) for sp in ('tenis', 'walki') for m in ((inne or {}).get(sp) or {}).get('odradzane', [])]
    if odr:
        lin.append('')
        for sp, m in odr[:3]:
            w, ai = _ai_karty(sp, m); t = m if sp == 'pilka' else (m.get('najpewniejszy') or {})
            zak = pl_txt(t.get('zaklad', ''), m['gospodarz'], m['gosc']) if sp == 'pilka' else t.get('zaklad', '')
            lin.append(f"⛔ <b>AI odradza:</b> {esc_(_nazwa_meczu(sp, m))} ({esc_(zak)}, {tg.pct(t.get('szansa', 0))})" + (f" – {esc_(ai['powod'])}" if ai.get('powod') else ''))
    if val:
        lin.append('\n<b>💰 Value</b>')
        for sp, v in val:
            zak = pl_txt(v['zaklad'], v.get('gospodarz'), v.get('gosc')) if sp == 'pilka' else v['zaklad']
            kk = {_nazwa_buk(n): k for n, k in ((v.get('kursy_pl') or {}).items())}
            if v.get('kurs'): kk.setdefault(_nazwa_buk(v.get('bukmacher') or 'Betclic FR'), v['kurs'])
            best = max(((n, k) for n, k in kk.items() if k), key=lambda x: x[1], default=(_nazwa_buk(v.get('bukmacher') or 'Betclic FR'), v['kurs']))
            lin.append(f"{wspolne.IKONA[sp]} {esc_(_nazwa_meczu(sp, v))} · {esc_(zak)} @ <b>{tg.kurs(best[1])}</b> {esc_(best[0])} · uczciwy {tg.kurs(v['kurs_uczciwy'])} · +{round(v['ev'] * 100)}%"
                       + (' · <i>rynek PL</i>' if v.get('rynek_pl') else ''))
    reszta = _czesc_dyscyplin(d, inne, pew, val)
    lin += reszta
    if any(sp == 'tenis' for sp, _ in pew + val) or any('Tenis' in x for x in reszta):
        lin.append('\n<i>Tenis – krecz: rozliczenie wg regulaminu bukmachera.</i>')
    if tg.APLIKACJA: lin.append(f'\n<a href="{tg.APLIKACJA}">Otwórz aplikację →</a>')
    if tg.wyslij_dlugi('\n'.join(lin)):
        status['tg_typy'] = dict(data=gl.get('data'), podpis=podpis, czas=teraz.strftime('%H:%M'), ai=n_ai)
        tg_raporty_wszystkie(gl, pew)
        return 'wysłane'
    return 'błąd wysyłki'

NAZWA_DYSC_TG = {'pilka': '⚽ Piłka', 'tenis': '🎾 Tenis', 'walki': '🥊 Walki'}

def _kurs_krotko(t):
    """Najlepszy kurs polskiego bukmachera (bez gwiazdki) albo „od <kurs uczciwy>”, gdy kursów jeszcze nie ma."""
    kk = {_nazwa_buk(n): float(k) for n, k in (t.get('kursy_pl') or {}).items() if k and float(k) > 1}
    if not kk: return f"od {tg.kurs(1 / t['szansa'])}"
    n = max(kk, key=kk.get)
    return f"{esc_(n)} {tg.kurs(kk[n])}"

def _czesc_dyscyplin(d, inne, pew, val):
    """Druga część porannej wiadomości: najpewniejsze typy (🔒) z zakładek Pewne każdej dyscypliny, bez meczów z części głównej.
    Jedna linia na mecz: godzina, mecz, ikona AI, 🔒 zakład, szansa, najlepszy kurs (bez ⚖️/🎯 i bez Value – są w aplikacji)."""
    juz_p = {(sp, str(m.get('event_id') or m.get('mecz'))) for sp, m in pew}
    lin = []
    for sp in ('pilka', 'tenis', 'walki'):
        if sp == 'pilka': mecze = list(d.get('pewne') or [])
        else:
            s = (inne or {}).get(sp) or {}
            mm = {str(m['event_id']): m for m in s.get('mecze') or []}
            mecze = [mm[str(i)] for i in s.get('pewne') or [] if str(i) in mm]
        mecze = [m for m in mecze if (sp, str(m.get('event_id') or m.get('mecz'))) not in juz_p]
        wiersze = []
        for m in sorted(mecze, key=lambda x: str(x.get('start'))):
            t = m if sp == 'pilka' else (m.get('najpewniejszy') or {})
            if not t.get('zaklad') or not t.get('szansa'): continue
            zak = pl_txt(t['zaklad'], m['gospodarz'], m['gosc']) if sp == 'pilka' else t['zaklad']
            if sp == 'pilka' and len(zak) <= 3 and t.get('opis'): zak = f"{zak} ({pl_txt(t['opis'], m['gospodarz'], m['gosc'])})"
            w, _ = _ai_karty(sp, m); ik = WERDYKT_TG.get(w, ('',))[0]
            wiersze.append(f"{m.get('godzina', '')} <b>{esc_(_nazwa_meczu(sp, m))}</b>" + (f" {ik}" if ik else '')
                           + f"\n   🔒 {esc_(zak)} · {tg.pct(t['szansa'])} · {_kurs_krotko(t)}")
        if wiersze: lin += [f"\n<b>{NAZWA_DYSC_TG[sp]}</b>"] + wiersze
    if lin: lin.insert(0, '\n━━━━━━━━━━━━\n<b>Pozostałe najpewniejsze wg dyscyplin</b>')
    return lin

def tg_raporty_wszystkie(gl, pew):
    if not pew: return
    czesci = [_raport_tg(m, i, sp) for i, (sp, m) in enumerate(pew, 1)]
    tg.wyslij_dlugi('\n\n'.join(czesci))

def _stan_na_zywo():
    try: return json.load(open(os.path.join(OUT, 'na_zywo.json')))
    except Exception: return {}

def podsumowanie_dnia(d):
    """ZAPAS: podsumowanie wysyła strażnik na żywo; to wysyłamy tylko, gdy go zabrakło (4 h po ostatnim starcie)."""
    if d.get('podsumowanie_wyslane') or not d.get('pewne'): return False
    if _stan_na_zywo().get('podsumowanie') == d.get('data'): d['podsumowanie_wyslane'] = True; return True
    ostatni = max(pd.Timestamp(x['start']) for x in d['pewne'] + d.get('value', []))
    if pd.Timestamp.now(tz='Europe/Warsaw').tz_localize(None) < ostatni + pd.Timedelta(hours=4): return False
    wiersze, traf = [], {'najpewniejszy': [0, 0], 'lepszy_kurs': [0, 0], 'ryzykowny': [0, 0]}
    for m in d['pewne']:
        w = tg.wynik(m.get('sport_key'), m['gospodarz'], m['gosc'], m['start'])
        if not w or w[2] != 'post':
            ostatni = max(pd.Timestamp(x['start']) for x in d['pewne'])
            if pd.Timestamp.now(tz='Europe/Warsaw').tz_localize(None) < ostatni + pd.Timedelta(hours=3): return False   # jeszcze trwają
            wiersze.append(f"{esc_(pl_mecz(m['mecz']))} – brak wyniku w serwisie"); continue
        m['wynik_koncowy'] = f"{w[0]}:{w[1]}"
        opis = []
        for poz, ik, k, n, sz in _typy_meczu(m):
            ok = bool(MASKI[k][min(w[0], MAXG), min(w[1], MAXG)]) if k in MASKI else False
            traf[poz][0] += ok; traf[poz][1] += 1; opis.append(f"{ik}{'✅' if ok else '❌'}")
        wiersze.append(f"{esc_(pl_mecz(m['mecz']))} <b>{w[0]}:{w[1]}</b> {' '.join(opis)}")
    n = lambda p: f"{traf[p][0]}/{traf[p][1]}"
    tg.wyslij('\n'.join([f"🏁 <b>Wyniki {pd.Timestamp(d['data']).strftime('%d.%m')}</b>",
                          f"🔒 najpewniejsze: {n('najpewniejszy')} · ⚖️ lepszy kurs: {n('lepszy_kurs')} · 🎯 ryzykowne: {n('ryzykowny')}", ''] + wiersze))
    d['podsumowanie_wyslane'] = True
    return True

def pilnuj_straznika(d):
    """Uruchamia strażnika na żywo (osobne zadanie GitHub), gdy wytypowany lub obserwowany mecz zaczyna się w ciągu 60 min
    albo trwa, a strażnik nie działa. Zwraca opis do status.json."""
    repo, token = os.environ.get('GITHUB_REPOSITORY'), os.environ.get('GH_TOKEN')
    if not (repo and token and tg.TOKEN): return 'wyłączony (brak tokenu GitHub lub Telegram)'
    teraz = pd.Timestamp.now(tz='Europe/Warsaw').tz_localize(None); nz = _stan_na_zywo(); dzien = wspolne.dzien_str()
    starty = [pd.Timestamp(m['start']) for m in d.get('pewne', []) + d.get('value', [])] if d.get('data') == dzien else []
    if nz.get('podsumowanie') == dzien: starty = []
    starty += [pd.Timestamp(o['start']) for o in nz.get('obserwowane', [])]
    # wieczorem (ostatnie sprawdzenia przed nocą – w nocy harmonogram nie działa) strażnik rusza także dla nocnych meczów:
    # czeka na nie sam, do końca doby programu (6:00, walki 9:00)
    noc = teraz.hour >= 22 or teraz.hour < 7
    horyzont = lambda sp='pilka': (wspolne.koniec_doby(sp).tz_localize(None) if noc else teraz + pd.Timedelta(minutes=60))
    potrzebny = any(teraz - pd.Timedelta(hours=2.5) <= t <= horyzont() for t in starty)
    if not potrzebny:   # tenis i walki (tenis: mecz może zacząć się kilka godzin po planowanej godzinie)
        try:
            ni = nz.get('inne', {})
            potrzebny = any(teraz - pd.Timedelta(hours=7 if sp == 'tenis' else 4) <= t <= horyzont(sp)
                            and (ni.get(eid) or {}).get('stan') != 'post' for sp, eid, t in sporty.starty_dla_straznika(sporty.wczytaj_json()))
        except Exception as e: print('strażnik (tenis/walki):', e)
    if not potrzebny:   # prośby o obserwowanie czekające u bota
        try: potrzebny = any('/start' in ((u.get('message') or {}).get('text') or '') for u in
                             requests.get(f'https://api.telegram.org/bot{tg.TOKEN}/getUpdates', params={'offset': nz.get('tg_offset', 0) + 1}, timeout=20).json().get('result', []))
        except Exception: pass
    if not potrzebny: return 'niepotrzebny'
    h = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json'}
    try:
        for st_ in ('in_progress', 'queued'):
            runs = requests.get(f'https://api.github.com/repos/{repo}/actions/runs', params={'status': st_, 'per_page': 20}, headers=h, timeout=20).json().get('workflow_runs', [])
            if any(r.get('display_title') == 'Na żywo' for r in runs): return 'działa'
        r = requests.post(f'https://api.github.com/repos/{repo}/actions/workflows/typer.yml/dispatches', headers=h, timeout=20,
                          json={'ref': os.environ.get('GITHUB_REF_NAME', 'main'), 'inputs': {'tryb': 'na_zywo'}})
        return 'uruchomiony' if r.status_code == 204 else f'błąd uruchomienia: HTTP {r.status_code} {r.text[:120]}'
    except Exception as e: return f'błąd: {e}'

def wczytaj_status():
    try: return json.load(open(os.path.join(OUT, 'status.json')))
    except Exception: return {}

def zapisz_status(tryb, bledy=None, st=None, tg_info=None):
    st = st if st is not None else wczytaj_status()
    teraz = pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M')
    st['ostatnie_uruchomienie'] = teraz; st[f'ostatnie_{tryb}'] = teraz
    st['wersja'] = core.WERSJA                  # wersja 42: numer wersji widoczny w Ustawieniach aplikacji
    if core.KREDYTY['pozostalo'] is not None:
        st['kredyty_odds'] = dict(pozostalo=core.KREDYTY['pozostalo'], zuzyto=core.KREDYTY['zuzyto'], budzet_dzis=core.KREDYTY['na_dzis'] or st.get('kredyty_odds', {}).get('budzet_dzis'))
    st['api_football'] = dict(klucz=bool(os.environ.get('API_FOOTBALL_KEY')), uzywany=bool(raport.KLUCZ),
                              uwaga=None if raport.KLUCZ else 'wyłączony – darmowy plan nie obejmuje bieżącego sezonu (włączysz zmienną API_FOOTBALL_PRO=1)',
                              zapytania_ostatnio=raport.licznik['zapytania'], bledy=raport.bledy[:5])
    if tryb == 'pelne' or zrodla.STAN['bsd']['zapytania'] or zrodla.STAN['bigballs']['zapytania']:
        st['bsd'] = dict(zrodla.STAN['bsd'], bledy=zrodla.STAN['bsd']['bledy'][:4], czas=teraz)
        st['bigballs'] = dict(zrodla.STAN['bigballs'], bledy=zrodla.STAN['bigballs']['bledy'][:4], czas=teraz)
    if ai_raport.STAN['zapytania'] or tryb == 'pelne' or STAN_AI:
        ai_raport.koszt_miesiac(); ai_raport.analiz_dzis()
        st['gemini'] = dict(ai_raport.STAN, bledy=ai_raport.STAN['bledy'][:4], uzupelnianie=STAN_AI or None, czas=teraz)
    if DIAG: st['przedmeczowe'] = dict(czas=teraz, mecze=DIAG[:12])
    if tg_info: st['telegram_typy'] = dict(wynik=tg_info, czas=teraz)
    if STRAZNIK: st['na_zywo'] = dict(straznik=STRAZNIK[-1], czas=teraz)
    if tryb == 'pelne':
        st['analityk'] = dict(analityk.stan(), czas=teraz); st['analityk_ai'] = dict(analityk_ai.STAN, czas=teraz)
        try: archiwum.dzienny()                       # wersja 37: rozliczenie archiwum kursów z wczoraj + statystyki
        except Exception as e: archiwum._blad(f'{type(e).__name__}: {e}')
        st['archiwum'] = dict(archiwum.STAN, czas=teraz)
        try: sekcja_zwlok.przeprowadz(PLIK_PEWNE, sporty.PLIK_TYPOW)     # wersja 39: sekcja zwłok wpadek typów dnia
        except Exception as e: sekcja_zwlok.STAN['bledy'].append(f'{type(e).__name__}: {e}')
        st['sekcje'] = dict(sekcja_zwlok.STAN, czas=teraz)
    if tryb == 'pelne' or sporty.STAN['bledy']:
        st['sporty'] = dict(tenis=sporty.STAN['tenis'], walki=sporty.STAN['walki'], ksw=sporty.STAN.get('ksw'), kredyty=sporty.STAN['kredyty'], rundy_walk=sporty.STAN['rundy'],
                            pominiete=sporty.STAN['pominiete'][:6], bledy=sporty.STAN['bledy'][:6], czas=teraz)
    st['telegram'] = dict(tg.STAN_TG, bot=tg.nazwa_bota() or (st.get('telegram') or {}).get('bot'))
    st['bledy'] = (bledy or [])[:5]
    zapisz('status.json', st)

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
    try: dz['sekcje'] = sekcja_zwlok.skrot()
    except Exception as e: print('sekcje:', e)
    try: dz['archiwum'] = archiwum.skrot()
    except Exception as e: print('archiwum:', e)
    try: dz['analityk_ai'] = analityk_ai.statystyki()
    except Exception as e: print('statystyki Analityka AI:', e)
    try:
        import dziennik_kursy; dz['kursy_pl'] = dziennik_kursy.statystyki()
    except Exception as e: print('statystyki kursów PL:', e)
    return dz

def zapisz(nazwa, obj):
    with open(os.path.join(OUT, nazwa), 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o))

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    if os.environ.get('TYPER_TRYB') == 'kursy':
        # polski serwer zapisał nowe kursy (Fortuna, STS) – tylko dopisanie kursów do typów w następnym kroku,
        # bez liczenia, bez sprawdzeń i bez wiadomości na Telegram
        print('Nowe kursy z polskiego serwera – dopisuję je do typów (krok „Kursy polskich bukmacherów”).'); sys.exit(0)
    teraz = pd.Timestamp.now(tz='Europe/Warsaw')
    try: stare = json.load(open(os.path.join(OUT, 'dzis.json')))
    except Exception: stare = {}
    try: core.KREDYTY['pozostalo'] = json.load(open(os.path.join(OUT, 'status.json')))['kredyty_odds']['pozostalo']
    except Exception: pass
    dzis_gotowe = stare.get('data') == wspolne.dzien_str() and str(stare.get('wygenerowano', ''))[11:13] >= '07'
    pelne = os.environ.get('GITHUB_EVENT_NAME') != 'schedule' or (teraz.hour >= 7 and not dzis_gotowe and teraz.hour < 23)
    if not pelne:
        # ---- lekkie sprawdzenie: składy, kursy przed meczem, rozliczenie, podsumowanie wieczorne ----
        bledy = []
        try:   # analiza AI przy każdym meczu z Pewnych i Value – także dobranych w ciągu dnia
            inne_ = sporty.wczytaj_json(); z, b = uzupelnij_ai(stare, inne_)
            if z:
                with open(os.path.join(OUT, sporty.PLIK_JSON), 'w', encoding='utf-8') as f:
                    json.dump(inne_, f, ensure_ascii=False, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o))
                zapisz('dzis.json', stare)
        except Exception as e: bledy.append(f'AI uzupełnienie: {e}')
        if stare.get('pewne') or stare.get('value'):
            try: sprawdz_przed_meczem(stare)
            except Exception as e: bledy.append(f'sprawdzenie: {e}')
            try: podsumowanie_dnia(stare)
            except Exception as e: bledy.append(f'podsumowanie: {e}')
            zapisz('dzis.json', stare)
        try: zapowiedzi(stare)   # przed meczem – przeliczenie i alarm tylko przy zmianie (piłka, tenis, walki; główne Pewne i Value)
        except Exception as e: bledy.append(f'zapowiedzi: {e}')
        try: STRAZNIK.append(pilnuj_straznika(stare))
        except Exception as e: bledy.append(f'strażnik: {e}')
        try: rozlicz_wszystko(); SAMOKOREKTA.update(policz_samokorekte(wczytaj_pewne())); zapisz('dziennik.json', eksport_calosci())
        except Exception as e: bledy.append(f'rozliczenie: {e}')
        try: sporty.rozlicz(); sporty.zapisz_json()
        except Exception as e: bledy.append(f'tenis/walki rozliczenie: {e}')
        zapisz_status('sprawdzenie', bledy); print('Sprawdzenie zakończone', bledy); sys.exit(0)
    bledy = []
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
    SAMOKOREKTA.update(policz_samokorekte(wczytaj_pewne()))
    today = dict(wygenerowano=teraz.strftime('%Y-%m-%d %H:%M'), data=wspolne.dzien_str(), value=[], pewne=[], mecze=[], blad=None,
                 raport_dostepny=bool(raport.KLUCZ) or zrodla.dostepne(), raport_ai=bool(ai_raport.KLUCZ))
    if not ODDS_API_KEY:
        today['blad'] = 'Brak klucza API (sekret ODDS_API_KEY w ustawieniach repozytorium).'
    else:
        try: today['value'], today['pewne'], today['mecze'] = typy_na_dzis(); today['odradzane'] = ODRADZANE
        except Exception as e: today['blad'] = f'Nie udało się pobrać kursów: {e}'; bledy.append(today['blad'])
        try: rozlicz_wszystko()
        except Exception as e: print('Rozliczenie dziennika nie powiodło się:', e); bledy.append(f'rozliczenie: {e}')
    today['api_football_zapytania'] = raport.licznik['zapytania']; today['api_football_bledy'] = raport.bledy[:5]
    zapisz('dzis.json', today)
    inne = None
    if ODDS_API_KEY:   # 🎾 tenis i 🥊 walki – po piłce, z osobnym limitem kredytów
        try: w = sporty.licz(); sporty.rozlicz(pelne=True); inne = sporty.zapisz_json(w)
        except Exception as e: print('Tenis/walki:', e); bledy.append(f'tenis/walki: {e}')
    zapisz('dziennik.json', eksport_calosci())
    try: STRAZNIK.append(pilnuj_straznika(today))
    except Exception as e: bledy.append(f'strażnik: {e}')
    try:   # kursy polskich bukmacherów (Superbet + Fortuna/STS z serwera) – przed wiadomością na Telegram
        import kursy_pl; os.environ['KURSY_PL_TERAZ'] = '1'
        try: kursy_pl.DIAG['vps_czekanie'] = kursy_pl.czekaj_na_vps(); print('Serwer kursów:', kursy_pl.DIAG['vps_czekanie'])
        except Exception as e: kursy_pl.DIAG['vps_czekanie'] = f'błąd: {e}'[:120]
        kursy_pl.main()
        today = json.load(open(os.path.join(OUT, 'dzis.json'))); inne = sporty.wczytaj_json() or inne
    except Exception as e: bledy.append(f'kursy PL: {e}')
    st = wczytaj_status(); tg_info = None
    gl = {}
    try: gl = wspolne.wybierz(today, inne or sporty.wczytaj_json()); wspolne.zapisz(gl)   # 5 Pewnych i Value ze wszystkich dyscyplin
    except Exception as e: bledy.append(f'wspólne listy: {e}')
    try:   # analiza AI przy każdym meczu z Pewnych i Value przed wiadomością
        inne = inne or sporty.wczytaj_json(); z, b = uzupelnij_ai(today, inne, limit=25)
        if z:
            zapisz('dzis.json', today)
            with open(os.path.join(OUT, sporty.PLIK_JSON), 'w', encoding='utf-8') as f:
                json.dump(inne, f, ensure_ascii=False, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o))
    except Exception as e: bledy.append(f'AI uzupełnienie: {e}')
    try: tg_info = tg_typy_wszystkie(today, inne or sporty.wczytaj_json(), gl, st) if gl else tg_typy_dnia(today, st)
    except Exception as e: bledy.append(f'telegram: {e}')
    zapisz_status('pelne', bledy, st, tg_info)
    print('Gotowe:', len(today['value']), 'value,', len(today['pewne']), 'pewnych,', len(today['mecze']), 'meczów; API-Football:', raport.licznik['zapytania'])
