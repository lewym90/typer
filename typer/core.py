import os, sys
import numpy as np, pandas as pd
ODDS_API_KEY = os.environ.get('ODDS_API_KEY', '')
BANKROLL = 1000
SEZONY_WSTECZ = 3
WAGA_MODELU = 0.0   # test 2022-2026 (25 tys. meczów): dokładanie modelu do kursów Pinnacle pogarsza trafność
MIN_EV_Z_RYNKIEM = 0.04
MIN_EV_SAM_MODEL = 0.10
KURS_MIN, KURS_MAX = 1.30, 4.00
REGIONY_ODDS_API = "eu"
POBIERZ_BTTS = False
PLATNY_PLAN = os.environ.get('PLATNY_PLAN', '') == '1'

# ===== SILNIK =====
import numpy as np, pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

MAXG = 10
KALIBRACJA_GOLI = 0.7   # dobrane w backteście na ~8 600 meczach

def fit_model(df, ref_date, half_life_days=365, reg=1.0, min_matches=6, weight_col=None):
    """Ważona regresja Poissona (siła ataku/obrony + przewaga własnego boiska) + korekta Dixona-Colesa.
    df: date, home, away, hg, ag, [neutral], [w]"""
    d = df[df['date'] < ref_date].dropna(subset=['hg', 'ag']).copy()
    age = (pd.Timestamp(ref_date) - d['date']).dt.days.values
    w = 0.5 ** (age / half_life_days)
    if weight_col and weight_col in d:
        w = w * d[weight_col].values
    keep = w > 0.01
    d, w = d[keep], w[keep]
    teams = sorted(set(d['home']) | set(d['away']))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = d['home'].map(idx).values; ai = d['away'].map(idx).values
    hg = d['hg'].values.astype(float); ag = d['ag'].values.astype(float)
    neu = d['neutral'].values.astype(float) if 'neutral' in d else np.zeros(len(d))

    def nll(p):
        att, dfn, mu, home = p[:n], p[n:2*n], p[2*n], p[2*n+1]
        lh = mu + home * (1 - neu) + att[hi] + dfn[ai]
        la = mu + att[ai] + dfn[hi]
        eh, ea = np.exp(lh), np.exp(la)
        f = -np.sum(w * (hg * lh - eh + ag * la - ea)) + reg * (att @ att + dfn @ dfn)
        rh, ra = w * (hg - eh), w * (ag - ea)
        g = np.zeros_like(p)
        g[:n] = -(np.bincount(hi, rh, n) + np.bincount(ai, ra, n)) + 2 * reg * att
        g[n:2*n] = -(np.bincount(ai, rh, n) + np.bincount(hi, ra, n)) + 2 * reg * dfn
        g[2*n] = -(rh.sum() + ra.sum())
        g[2*n+1] = -np.sum(rh * (1 - neu))
        return f, g

    p0 = np.zeros(2 * n + 2); p0[2*n] = np.log(max(np.average(np.r_[hg, ag]), 0.1))
    res = minimize(nll, p0, jac=True, method='L-BFGS-B')
    p = res.x
    att, dfn, mu, home = p[:n], p[n:2*n], p[2*n], p[2*n+1]
    lh = np.exp(mu + home * (1 - neu) + att[hi] + dfn[ai]); la = np.exp(mu + att[ai] + dfn[hi])

    def rho_nll(r):
        t = np.ones(len(d))
        m = (hg == 0) & (ag == 0); t[m] = 1 - lh[m] * la[m] * r
        m = (hg == 0) & (ag == 1); t[m] = 1 + lh[m] * r
        m = (hg == 1) & (ag == 0); t[m] = 1 + la[m] * r
        m = (hg == 1) & (ag == 1); t[m] = 1 - r
        return -np.sum(w * np.log(np.clip(t, 1e-9, None)))
    rho = minimize_scalar(rho_nll, bounds=(-0.2, 0.2), method='bounded').x
    cnt = pd.concat([d['home'], d['away']]).value_counts()
    T = np.average(hg + ag, weights=w)   # średnia liczba goli w meczu (do kalibracji)
    return dict(teams=idx, att=att, dfn=dfn, mu=mu, home=home, rho=rho, T=T,
                n_matches={t: int(cnt.get(t, 0)) for t in teams}, min_matches=min_matches)

def expected_goals(m, home, away, neutral=False):
    i, j = m['teams'][home], m['teams'][away]
    lh = np.exp(m['mu'] + (0 if neutral else m['home']) + m['att'][i] + m['dfn'][j])
    la = np.exp(m['mu'] + m['att'][j] + m['dfn'][i])
    # KALIBRACJA GOLI: backtest 2023-26 pokazał, że model przesadza przy skrajnych prognozach goli
    # (np. Under 2.5 z szansą 71% wchodził w 61%). Ściągamy sumę goli o 30% w stronę średniej.
    tot = lh + la; f = (m['T'] + KALIBRACJA_GOLI * (tot - m['T'])) / tot
    return lh * f, la * f

# Wersja 42 – kara za dużą różnicę bramek w macierzy z RYNKU: M(i,j) · exp(-KAPPA_RYNEK·(i-j)²).
# Test 03.10 (Matches.csv, 156 549 meczów z kursami 1X2 i 2,5; ocena 2020–2026): zwykły Poisson z kursów zawyżał gole
# i handicapy faworyta, a zaniżał gole outsidera i „obie strzelą” (faworyt ≥75%: „-2,5” 40,2% → weszło 35,3%,
# „faworyt powyżej 3,5” 31,3 → 27,3, „outsider strzeli” 47,4 → 51,4, BTTS 44,7 → 49,0). Gole łącznie były trafne.
# Z karą 0,025: średni błąd kalibracji 13 rynków × 5 przedziałów siły faworyta 1,63 → 1,00 pkt, log-loss lepszy.
KAPPA_RYNEK = 0.025
WERSJA = 62          # numer wersji programu (Ustawienia w aplikacji); zmieniać przy każdej nowej wersji

def score_matrix(lh, la, rho, kappa=0.0):
    M = np.outer(poisson.pmf(np.arange(MAXG + 1), lh), poisson.pmf(np.arange(MAXG + 1), la))
    M[0, 0] *= 1 - lh * la * rho; M[0, 1] *= 1 + lh * rho
    M[1, 0] *= 1 + la * rho; M[1, 1] *= 1 - rho
    if kappa: M = M * np.exp(-kappa * np.subtract.outer(np.arange(MAXG + 1), np.arange(MAXG + 1)) ** 2)
    return M / M.sum()

def score_matrix_rynek(lh, la, rho=-0.05):
    """Macierz wyników z rynku (λ z market_lambdas) – z karą za dużą różnicę bramek (wersja 42)."""
    return score_matrix(lh, la, rho, KAPPA_RYNEK)

def _ah_outcome(M, line):
    """Handicap azjatycki dla gospodarzy (line np. -0.5, -1, -0.75). Zwraca (p_wygranej, p_zwrotu, p_przegranej) dla pół/całych linii."""
    diff = np.subtract.outer(np.arange(MAXG + 1), np.arange(MAXG + 1)) + line
    return M[diff > 1e-9].sum(), M[np.abs(diff) < 1e-9].sum(), M[diff < -1e-9].sum()

def ev_asian(M, line, odds, side='home'):
    """Wartość oczekiwana zakładu AH (obsługuje linie ćwiartkowe) na 1 jednostkę stawki."""
    if side == 'away':
        M = M.T
    frac = line * 4 % 2
    lines = [line - 0.25, line + 0.25] if abs(frac - 1) < 1e-9 else [line]
    ev = 0
    for l in lines:
        pw, pp, pl = _ah_outcome(M, l)
        ev += (pw * (odds - 1) - pl) / len(lines)
    return ev

def ev_total(M, line, odds, side='over'):
    tot = np.add.outer(np.arange(MAXG + 1), np.arange(MAXG + 1)).astype(float)
    frac = line * 4 % 2
    lines = [line - 0.25, line + 0.25] if abs(frac - 1) < 1e-9 else [line]
    ev = 0
    for l in lines:
        d = (tot - l) if side == 'over' else (l - tot)
        pw, pl = M[d > 1e-9].sum(), M[d < -1e-9].sum()
        ev += (pw * (odds - 1) - pl) / len(lines)
    return ev

def markets(M):
    g = np.arange(MAXG + 1)
    tot = np.add.outer(g, g)
    out = {'1': np.tril(M, -1).sum(), 'X': np.trace(M), '2': np.triu(M, 1).sum()}
    out['1X'] = out['1'] + out['X']; out['X2'] = out['X'] + out['2']; out['12'] = out['1'] + out['2']
    for l in [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]:
        out[f'Over {l}'] = M[tot > l].sum(); out[f'Under {l}'] = 1 - out[f'Over {l}']
    out['BTTS Tak'] = M[1:, 1:].sum(); out['BTTS Nie'] = 1 - out['BTTS Tak']
    for l in [0.5, 1.5, 2.5]:
        out[f'Gosp. Over {l}'] = M[g > l, :].sum(); out[f'Gości Over {l}'] = M[:, g > l].sum()
    return out

def top_scores(M, k=5):
    flat = [((i, j), M[i, j]) for i in range(MAXG + 1) for j in range(MAXG + 1)]
    return sorted(flat, key=lambda x: -x[1])[:k]

def devig(odds_list):
    """Usuwa marżę bukmachera metodą potęgową (p_i = (1/kurs_i)^k, suma = 1) -> uczciwe prawdopodobieństwa.
    Wersja 33: test 02.10 – piłka 69 168 meczów Pinnacle (zamknięcie): log-loss 1X2 0,99820 → 0,99796, gole 2,5 0,67473 → 0,67464;
    faworyci 80%+: przewidywane 84,7%, weszło 84,2% (proporcjonalna 83,9% → 85,7% – zaniżała faworytów).
    Marża potęgowa spada głównie na outsiderów (tak jak naprawdę rozkłada ją bukmacher). Zapas: metoda proporcjonalna."""
    inv = np.array([1 / o for o in odds_list], dtype=float)
    s = inv.sum()
    if s <= 1.0 + 1e-9 or not np.all(np.isfinite(inv)) or np.any(inv <= 0): return inv / s
    try:
        lo, hi = 1.0, 8.0                       # (1/kurs)^k maleje z k – szukamy k z sumą = 1 (bisekcja)
        for _ in range(60):
            k = (lo + hi) / 2
            if (inv ** k).sum() > 1: lo = k
            else: hi = k
        p = inv ** ((lo + hi) / 2); return p / p.sum()
    except Exception: return inv / s

def market_lambdas(p1, px, p2, p_over=None, line=2.5, rho=-0.05):
    """Odtwarza oczekiwane gole z uczciwych kursów rynku (np. Pinnacle) -> pozwala liczyć BTTS/handicapy/gole."""
    tot = np.add.outer(np.arange(MAXG + 1), np.arange(MAXG + 1))
    def loss(x):
        M = score_matrix(np.exp(x[0]), np.exp(x[1]), rho, KAPPA_RYNEK)
        e = (np.tril(M, -1).sum() - p1) ** 2 + (np.trace(M) - px) ** 2 + (np.triu(M, 1).sum() - p2) ** 2
        if p_over is not None:
            e += (M[tot > line].sum() - p_over) ** 2
        return e
    r = minimize(loss, [np.log(1.4), np.log(1.1)], method='Nelder-Mead', options={'xatol': 1e-4, 'fatol': 1e-8})
    return np.exp(r.x[0]), np.exp(r.x[1])


import requests, io, unicodedata, difflib, re, warnings
warnings.filterwarnings('ignore')

def norm(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()
    s = s.replace('&', ' and ').replace('utd', 'united').replace("'", '')
    s = re.sub(r'\b(fc|afc|cf|sc|ac|fk|sk|bk|if|cd|ud|sv|vfb|vfl|tsg|as|ssc|rc|rcd|ogc|osc|sporting clube de|club)\b', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

ALIASY = {  # nazwa u bukmachera -> nazwa w danych (dopisuj, jeśli coś się nie dopasuje)
 'manchester united': 'man united', 'manchester city': 'man city', 'nottingham forest': 'nottm forest',
 'wolverhampton wanderers': 'wolves', 'tottenham hotspur': 'tottenham', 'newcastle united': 'newcastle',
 'brighton and hove albion': 'brighton', 'west ham united': 'west ham', 'leeds united': 'leeds',
 'sheffield united': 'sheffield united', 'paris saint germain': 'paris sg', 'bayern munich': 'bayern munich',
 'borussia monchengladbach': 'mgladbach', 'eintracht frankfurt': 'ein frankfurt', 'bayer leverkusen': 'leverkusen',
 'athletic bilbao': 'ath bilbao', 'atletico madrid': 'ath madrid', 'real sociedad': 'sociedad', 'celta vigo': 'celta',
 'inter milan': 'inter', 'internazionale': 'inter', 'as roma': 'roma', 'hellas verona': 'verona',
 'psv eindhoven': 'psv eindhoven', 'sporting lisbon': 'sp lisbon', 'sporting cp': 'sp lisbon', 'fc porto': 'porto',
 'usa': 'united states', 'korea republic': 'south korea', 'turkiye': 'turkey', 'czechia': 'czech republic',
 'ir iran': 'iran', 'polska': 'poland', 'niemcy': 'germany', 'hiszpania': 'spain', 'francja': 'france',
 'anglia': 'england', 'wlochy': 'italy', 'holandia': 'netherlands', 'belgia': 'belgium', 'portugalia': 'portugal',
 'chorwacja': 'croatia', 'czechy': 'czech republic', 'slowacja': 'slovakia', 'ukraina': 'ukraine', 'austria': 'austria',
 'szwajcaria': 'switzerland', 'dania': 'denmark', 'szwecja': 'sweden', 'norwegia': 'norway', 'finlandia': 'finland',
 'szkocja': 'scotland', 'walia': 'wales', 'irlandia': 'republic of ireland', 'irlandia polnocna': 'northern ireland',
 'wegry': 'hungary', 'rumunia': 'romania', 'serbia': 'serbia', 'grecja': 'greece', 'turcja': 'turkey', 'albania': 'albania',
 'slowenia': 'slovenia', 'bosnia': 'bosnia and herzegovina', 'islandia': 'iceland', 'litwa': 'lithuania', 'lotwa': 'latvia',
 'estonia': 'estonia', 'gruzja': 'georgia', 'armenia': 'armenia', 'bulgaria': 'bulgaria', 'macedonia': 'north macedonia',
 'czarnogora': 'montenegro', 'mołdawia': 'moldova', 'moldawia': 'moldova', 'bialorus': 'belarus', 'kazachstan': 'kazakhstan',
 'brazylia': 'brazil', 'argentyna': 'argentina', 'meksyk': 'mexico', 'stany zjednoczone': 'united states', 'japonia': 'japan',
 'korea poludniowa': 'south korea', 'maroko': 'morocco', 'kolumbia': 'colombia', 'urugwaj': 'uruguay', 'cote divoire': 'ivory coast', 'bosnia herzegovina': 'bosnia and herzegovina',
}

def dopasuj(nazwa, druzyny):
    """Zwraca nazwę drużyny z danych najbliższą nazwie u bukmachera (albo None)."""
    n = norm(nazwa); n = ALIASY.get(n, n)
    mapa = {norm(t): t for t in druzyny}
    if n in mapa: return mapa[n]
    m = difflib.get_close_matches(n, list(mapa), n=1, cutoff=0.72)
    if m: return mapa[m[0]]
    for k, t in mapa.items():   # np. "legia warszawa" vs "legia"
        if len(k) >= 4 and (k in n.split() or n.startswith(k) or k.startswith(n)):
            return t
    return None

def kelly(p, kurs, frakcja=0.25, maks=0.02):
    f = (p * kurs - 1) / (kurs - 1)
    return max(0, min(f * frakcja, maks))


# ===== SKANER =====
LIGI_DO_SKANU = {  # klucz The Odds API -> model; kolejność = popularność (najpopularniejsze pierwsze)
 'soccer_uefa_champs_league':'Puchary europejskie', 'soccer_fifa_world_cup':'Reprezentacje', 'soccer_uefa_european_championship':'Reprezentacje',
 'soccer_uefa_nations_league':'Reprezentacje', 'soccer_fifa_world_cup_qualifiers_europe':'Reprezentacje',
 'soccer_uefa_euro_qualification':'Reprezentacje', 'soccer_epl':'Anglia', 'soccer_spain_la_liga':'Hiszpania',
 'soccer_poland_ekstraklasa':'Polska', 'soccer_italy_serie_a':'Włochy', 'soccer_germany_bundesliga':'Niemcy',
 'soccer_france_ligue_one':'Francja', 'soccer_uefa_europa_league':'Puchary europejskie', 'soccer_uefa_europa_conference_league':'Puchary europejskie',
 'soccer_international_friendlies':'Reprezentacje', 'soccer_portugal_primeira_liga':'Portugalia',
 'soccer_netherlands_eredivisie':'Holandia', 'soccer_efl_champ':'Anglia', 'soccer_germany_bundesliga2':'Niemcy',
 'soccer_turkey_super_league':'Turcja', 'soccer_belgium_first_div':'Belgia', 'soccer_spl':'Szkocja',
 'soccer_usa_mls':'USA', 'soccer_brazil_campeonato':'Brazylia', 'soccer_argentina_primera_division':'Argentyna',
 'soccer_mexico_ligamx':'Meksyk', 'soccer_japan_j_league':'Japonia', 'soccer_china_superleague':'Chiny',
}
MIN_EV_VALUE = 0.03       # najlepszy polski kurs musi dawać min. 3% więcej niż uczciwy kurs Pinnacle/Betfair
PEWNE_MIN_SZANSA = 0.70   # typ dnia: minimalna szansa wejścia (test: piłka 78,7%, tenis 77,3%, MMA 75,3% przy tym progu)
PEWNE_MIN_KURS = 1.25     # niższe kursy nie mają sensu (za mały zysk)
PEWNE_ILE_MECZOW = 15     # z ilu najpopularniejszych meczów wybierać
PEWNE_ILE_TYPOW = 5       # ile najpewniejszych typów pokazać
# Chcesz więcej lig? Dopisz klucz (lista: uruchom pokaz_ligi()) i model: 'Szkocja','Belgia','Turcja','Grecja',
# 'Austria','Dania','Norwegia','Szwecja','Szwajcaria','Rumunia','Finlandia','Irlandia','Rosja','Szkocja'.

API = "https://api.the-odds-api.com/v4"
KREDYTY = {'pozostalo': None, 'zuzyto': None, 'na_dzis': None, 'wydane_teraz': 0, 'start_dnia': None, 'dzien': None, 'zablokowane': 0}
def _limit_dnia():
    """Wersja 50: ile kredytów wolno wydać dziś łącznie (piłka, tenis/walki, kursy przed meczem, wyniki), żeby pula
    starczyła do końca miesiąca (darmowy plan zerował się po 3 dniach). Pula na początek dnia: KREDYTY['start_dnia']."""
    st = KREDYTY.get('start_dnia')
    if st is None: return None
    t = pd.Timestamp.now(tz='Europe/Warsaw'); dni = (t + pd.offsets.MonthEnd(0)).day - t.day + 1
    return max(4, int(st / dni))

def _platne(sciezka):
    return '/odds' in sciezka or '/scores' in sciezka or sciezka.startswith('historical')

def api(sciezka, **p):
    lim = _limit_dnia()
    if lim is not None and _platne(sciezka) and KREDYTY['pozostalo'] is not None and KREDYTY['start_dnia'] - KREDYTY['pozostalo'] >= lim:
        KREDYTY['zablokowane'] = KREDYTY.get('zablokowane', 0) + 1
        raise RuntimeError(f'dzienny limit kredytów ({lim}) wyczerpany – reszta jutro')
    r = requests.get(f"{API}/{sciezka}", params={'apiKey': ODDS_API_KEY, **p}, timeout=30)
    if r.status_code != 200: raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
    try:
        poz = int(float(r.headers.get('x-requests-remaining')))
        if KREDYTY['pozostalo'] is not None: KREDYTY['wydane_teraz'] += max(0, KREDYTY['pozostalo'] - poz)
        KREDYTY['pozostalo'] = poz; KREDYTY['zuzyto'] = int(float(r.headers.get('x-requests-used', 0)))
        if KREDYTY.get('start_dnia') is None or poz > KREDYTY['start_dnia']: KREDYTY['start_dnia'] = poz   # nowy miesiąc / doładowanie
    except Exception: pass
    print(f"   (kredyty pozostałe: {r.headers.get('x-requests-remaining')})"); return r.json()

def budzet_dzienny(rezerwa=0.2):
    """Ile kredytów można dziś wydać, żeby starczyło do końca miesiąca (część zostaje na sprawdzenia przed meczami)."""
    if KREDYTY['pozostalo'] is None: return 999
    t = pd.Timestamp.now(tz='Europe/Warsaw'); dni = (t + pd.offsets.MonthEnd(0)).day - t.day + 1
    b = max(4, int(KREDYTY['pozostalo'] / dni * (1 - rezerwa)))
    lim = _limit_dnia()          # wersja 50: piłka rano dostaje większość dziennego limitu, reszta na tenis/walki i przed meczem
    return min(b, max(4, int(lim * 0.6))) if lim else b

def pokaz_ligi():
    s = pd.DataFrame(api('sports')); print(s[s.group == 'Soccer'][['key','title']].to_string())

def znajdz_model(home, away, preferowany):
    kolejnosc = [preferowany] if preferowany else []
    kolejnosc += [k for k in MODELE if k not in kolejnosc]
    for k in kolejnosc:
        m = MODELE[k]; h, a = dopasuj(home, m['teams']), dopasuj(away, m['teams'])
        if h and a and h != a: return k, h, a
    return None, None, None

NAZWY_ZAKL = {'1': 'wygra gospodarz', 'X': 'remis', '2': 'wygra gość', '1X': 'gospodarz lub remis', 'X2': 'gość lub remis',
              '12': 'bez remisu', 'BTTS Tak': 'obie drużyny strzelą', 'BTTS Nie': 'co najmniej jedna nie strzeli'}

def _fair_z_gieldy(back, lay, nazwy):
    """Uczciwe szanse z giełdy Betfair: środek między kursem 'back' i 'lay'. Pomija rynki z małą płynnością."""
    p = []
    for n in nazwy:
        b = back.get(n); l = lay.get(n)
        if b is None: return None
        if l is not None:
            if l / b > 1.10: return None      # za duży rozrzut = mała płynność, niewiarygodne
            p.append((1 / b + 1 / l) / 2)
        else: p.append(1 / b)
    p = np.array(p); return p / p.sum()

def ostre_prawdopodobienstwa(bm, home, away):
    """Uczciwe szanse z 'ostrych' źródeł: Pinnacle i giełda Betfair (średnia, gdy są oba)."""
    z1, zo, zr = [], [], []
    pin = bm.get('pinnacle')
    if pin:
        try:
            d = {o['name']: o['price'] for o in pin['h2h']}; z1.append(devig([d[home], d['Draw'], d[away]])); zr.append('Pinnacle')
        except Exception: pass
        try:
            t = {(o['name'], o.get('point')): o['price'] for o in pin['totals']}
            zo.append(devig([t[('Over', 2.5)], t[('Under', 2.5)]])[0])
        except Exception: pass
    bf = bm.get('betfair_ex_eu') or bm.get('betfair_ex_uk')
    if bf:
        try:
            back = {o['name']: o['price'] for o in bf.get('h2h', [])}; lay = {o['name']: o['price'] for o in bf.get('h2h_lay', [])}
            f = _fair_z_gieldy(back, lay, [home, 'Draw', away])
            if f is not None: z1.append(f); zr.append('Betfair')
        except Exception: pass
        try:
            back = {o['name']: o['price'] for o in bf.get('totals', []) if o.get('point') == 2.5}
            lay = {o['name']: o['price'] for o in bf.get('totals_lay', []) if o.get('point') == 2.5}
            f = _fair_z_gieldy(back, lay, ['Over', 'Under'])
            if f is not None: zo.append(f[0])
        except Exception: pass
    if not z1: return None, (np.mean(zo) if zo else None), None
    return np.mean(z1, axis=0), (np.mean(zo) if zo else None), '+'.join(zr)

def macierz_meczu(ev, preferowany):
    """Łączy model statystyczny z rynkiem (Pinnacle / średnia bukmacherów). Zwraca macierz wyników i info."""
    home, away = ev['home_team'], ev['away_team']
    bm = {b['key']: {mk['key']: mk['outcomes'] for mk in b['markets']} for b in ev.get('bookmakers', [])}
    betclic = next((v for k, v in bm.items() if 'betclic' in k), None)
    p_mkt, p_ov, zrodlo = ostre_prawdopodobienstwa(bm, home, away)
    if p_mkt is None:   # brak ostrych kursów – średnia wszystkich bukmacherów bez marży (słabsze)
        try:
            lst = []
            for v in bm.values():
                if 'h2h' in v:
                    d = {o['name']: o['price'] for o in v['h2h']}; lst.append(devig([d[home], d['Draw'], d[away]]))
            if len(lst) >= 3: p_mkt, zrodlo = np.mean(lst, axis=0), f'średnia {len(lst)} buk.'
        except Exception: pass
    k, h, a = znajdz_model(home, away, preferowany)
    neutral = preferowany == 'Reprezentacje' and (ev['sport_key'].endswith('world_cup') or 'championship' in ev['sport_key'])
    M_mod = score_matrix(*expected_goals(MODELE[k], h, a, neutral), MODELE[k]['rho']) if k else None
    lam_mkt = market_lambdas(*p_mkt, p_over=p_ov) if p_mkt is not None else None
    M_mkt = score_matrix_rynek(*lam_mkt) if lam_mkt is not None else None
    if M_mkt is not None: M, tryb, prog = M_mkt, f'rynek ({zrodlo})', MIN_EV_Z_RYNKIEM
    elif M_mod is not None: M, tryb, prog = M_mod, 'tylko model', MIN_EV_SAM_MODEL
    else: return None
    uwaga = ''
    if k and min(MODELE[k]['n_matches'][h], MODELE[k]['n_matches'][a]) < 10 and M_mkt is None: uwaga = '⚠ mało danych o drużynie'
    # (usunięte ostrzeżenie „rynek i model mocno się różnią” – test na 64 374 meczach: typy z nim i bez niego wchodzą tak samo, 76,1%)
    return dict(M=M, M_mod=M_mod, M_mkt=M_mkt, lam_mkt=lam_mkt, model_key=k, model_h=h, model_a=a, p_mkt=p_mkt, ostry=zrodlo in ('Pinnacle', 'Betfair', 'Pinnacle+Betfair'), betclic=betclic, tryb=tryb, prog=prog, uwaga=uwaga, home=home, away=away,
                start=pd.Timestamp(ev['commence_time']).tz_convert('Europe/Warsaw'), event_id=ev['id'], sport_key=ev['sport_key'])

def oferty_betclic(x):
    """Wszystkie zakłady Betclic z API z oceną: (nazwa, kurs, szansa, EV, dane_do_rozliczenia)."""
    M, b, home, away = x['M'], x['betclic'] or {}, x['home'], x['away']; mk = markets(M); out = []
    for o in b.get('h2h', []):
        z = '1' if o['name'] == home else ('2' if o['name'] == away else 'X')
        out.append((z, o['price'], mk[z], mk[z] * o['price'] - 1, dict(rynek='1X2', strona=z, linia=0)))
    for o in b.get('totals', []):
        l, s = o.get('point'), o['name'].lower(); e = ev_total(M, l, o['price'], s)
        out.append((f"{'Powyżej' if s=='over' else 'Poniżej'} {l} gola", o['price'], (e + 1) / o['price'], e, dict(rynek='gole', strona=s, linia=l)))
    for o in b.get('spreads', []):
        l = o.get('point'); s = 'home' if o['name'] == home else 'away'; e = ev_asian(M, l, o['price'], s)
        out.append((f"Handicap {'gosp.' if s=='home' else 'gościa'} {l:+}", o['price'], (e + 1) / o['price'], e, dict(rynek='handicap', strona=s, linia=l)))
    for o in b.get('btts', []):
        z = 'BTTS Tak' if o['name'].lower() == 'yes' else 'BTTS Nie'
        out.append((z, o['price'], mk[z], mk[z] * o['price'] - 1, dict(rynek='btts', strona=z, linia=0)))
    return out

def dzisiejsze_mecze():
    """Mecze od teraz do końca doby programu (6:00 – nocne mecze w Ameryce należą do tego samego dnia). Kursy pobierane
    w kolejności popularności lig, dopóki nie wyczerpie się dzienny budżet kredytów (darmowy plan: 500/mies.)."""
    import wspolne
    teraz = pd.Timestamp.now(tz='Europe/Warsaw'); koniec = wspolne.koniec_doby('pilka', teraz)
    od = wspolne.poczatek_listy(teraz)   # najwcześniej mecze od 8:00
    f = lambda t: t.tz_convert('UTC').strftime('%Y-%m-%dT%H:%M:%SZ')
    aktywne = {s['key'] for s in api('sports')}
    budzet = budzet_dzienny(); KREDYTY['na_dzis'] = budzet; start_kr = KREDYTY['wydane_teraz']
    wynik = []
    for key, model in LIGI_DO_SKANU.items():
        if key not in aktywne: continue
        # lista meczów jest DARMOWA – kursy pobieramy tylko, gdy liga gra dzisiaj
        try: evs = api(f'sports/{key}/events', commenceTimeFrom=f(od), commenceTimeTo=f(koniec))
        except Exception: continue
        if not evs: continue
        odds = None
        if KREDYTY['wydane_teraz'] - start_kr + 2 > budzet:
            print(f"→ {key}: dzienny budżet kredytów wyczerpany ({budzet}) – kursy z Pinnacle (za darmo)")
        else:
            print(f"→ {key}: {len(evs)} mecz(e) dziś")
            try: odds = api(f'sports/{key}/odds', regions=REGIONY_ODDS_API, markets='h2h,totals', oddsFormat='decimal',
                            commenceTimeFrom=f(od), commenceTimeTo=f(koniec))
            except Exception as e: print("   błąd:", e)
        if odds is None:      # wersja 55: brak kredytów / błąd → te same mecze z kursami Pinnacle guest (darmowe API strony)
            try:
                import pinnacle; odds = pinnacle.jako_odds_api(evs, 'pilka'); print(f"   Pinnacle: {len(odds)} z {len(evs)}")
            except Exception as e: print("   Pinnacle błąd:", e); odds = []
        for ev in odds: wynik.append((key, model, ev))
    return wynik

PLIK_DZIENNIKA = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data', 'typy_value.csv')

def wczytaj_dziennik():
    try: return pd.read_csv(PLIK_DZIENNIKA, dtype={'wynik': str, 'strona': str, 'zaklad': str, 'event_id': str},
                            keep_default_na=False, na_values=[''])
    except FileNotFoundError: return pd.DataFrame()

def zapisz_value(nowe):
    d = wczytaj_dziennik(); n = pd.DataFrame(nowe)
    if len(d):   # ten sam zakład na ten sam mecz zapisujemy tylko raz (pierwszy kurs)
        klucz = set(zip(d.event_id.astype(str), d.zaklad))
        n = n[[(str(a), b) not in klucz for a, b in zip(n.event_id, n.zaklad)]]
    if len(n):
        pd.concat([d, n], ignore_index=True).to_csv(PLIK_DZIENNIKA, index=False)
        print(f"📒 Zapisano {len(n)} nowych typów value do dziennika.")



# ===== DZIENNIK =====
def zysk_zakladu(rynek, strona, linia, kurs, hg, ag):
    """Zysk na 1 zł stawki (obsługuje linie ćwiartkowe i zwroty)."""
    if rynek == 'klucz':                       # Value z polskich kursów: zakład zapisany naszym kluczem
        return kurs - 1 if bool(maska_klucza(strona)[min(int(hg), MAXG), min(int(ag), MAXG)]) else -1.0
    if rynek == '1X2':
        w = {'1': hg > ag, 'X': hg == ag, '2': hg < ag}[strona]; return kurs - 1 if w else -1.0
    if rynek == 'btts':
        w = (hg > 0 and ag > 0) == (strona == 'BTTS Tak'); return kurs - 1 if w else -1.0
    linia = float(linia)
    linie = [linia - 0.25, linia + 0.25] if abs((linia * 4) % 2 - 1) < 1e-9 else [linia]
    wynik = 0
    for l in linie:
        if rynek == 'gole': r = (hg + ag - l) if strona == 'over' else (l - hg - ag)
        else: r = (hg - ag + l) if strona == 'home' else (ag - hg + l)
        wynik += (kurs - 1 if r > 1e-9 else (0 if abs(r) < 1e-9 else -1)) / len(linie)
    return wynik

def maska_klucza(z):
    """Maska wyników (gole gospodarza × gole gościa), przy których wchodzi zakład o naszym kluczu (Value z polskich kursów)."""
    g = np.arange(MAXG + 1); I, J = np.meshgrid(g, g, indexing='ij'); T = I + J; D = I - J
    stale = {'1': D > 0, 'X': D == 0, '2': D < 0, '1X': D >= 0, 'X2': D <= 0, '12': D != 0,
             'BTTS Tak': (I > 0) & (J > 0), 'BTTS Nie': (I == 0) | (J == 0), 'BTTS & o2.5': (I > 0) & (J > 0) & (T >= 3)}
    if z in stale: return stale[z]
    m = re.fullmatch(r'(Over|Under) (\d+)\.5', z)
    if m: n = int(m.group(2)); return T > n if m.group(1) == 'Over' else T <= n
    m = re.fullmatch(r'([HA]) -(\d+)\.5', z)
    if m: n = int(m.group(2)) + 1; return D >= n if m.group(1) == 'H' else D <= -n
    m = re.fullmatch(r'([HA]) o(\d+)\.5', z)
    if m: n = int(m.group(2)); return I > n if m.group(1) == 'H' else J > n
    m = re.fullmatch(r'([12X]) & ([ou])(\d+)\.5', z)
    if m:
        w = {'1': D > 0, 'X': D == 0, '2': D < 0}[m.group(1)]; n = int(m.group(3))
        return w & (T > n if m.group(2) == 'o' else T <= n)
    raise ValueError(f'nieznany klucz zakładu: {z}')

def ev_zakladu(M, rynek, strona, linia, kurs):
    """Wartość oczekiwana zakładu wg macierzy wyników M."""
    if rynek == 'klucz': return float(M[maska_klucza(strona)].sum()) * kurs - 1
    mk = markets(M)
    if rynek == '1X2': return mk[strona] * kurs - 1
    if rynek == 'btts': return mk[strona] * kurs - 1
    if rynek == 'gole': return ev_total(M, float(linia), kurs, strona)
    return ev_asian(M, float(linia), kurs, strona)

def clv_zakladu(r):
    """💎 CLV: czy Twój kurs Betclic był lepszy niż uczciwy kurs Pinnacle/Betfair tuż przed meczem (plan płatny)."""
    t = (pd.Timestamp(r.start).tz_localize('Europe/Warsaw') - pd.Timedelta(minutes=5)).tz_convert('UTC')
    h = api(f"historical/sports/{r.liga}/events/{r.event_id}/odds", regions='eu', markets='h2h,totals',
            oddsFormat='decimal', date=t.strftime('%Y-%m-%dT%H:%M:%SZ'))
    ev = (h.get('data') if isinstance(h, dict) else None) or {}
    bm = {b['key']: {mk['key']: mk['outcomes'] for mk in b['markets']} for b in ev.get('bookmakers', [])}
    p1, pov, zr = ostre_prawdopodobienstwa(bm, ev.get('home_team'), ev.get('away_team'))
    if p1 is None: return None
    M = score_matrix_rynek(*market_lambdas(*p1, p_over=pov))
    return ev_zakladu(M, r.rynek, r.strona, r.linia, r.kurs_betclic)

def wynik_z_danych(gosp, gosc, start):
    """Zapasowo: szuka wyniku w pobranych danych historycznych (gdy API już go nie ma)."""
    for k, d in DANE.items():
        h, a = dopasuj(gosp, MODELE[k]['teams']), dopasuj(gosc, MODELE[k]['teams'])
        if not (h and a): continue
        m = d[(d.home == h) & (d.away == a) & ((d.date - pd.Timestamp(start[:10])).abs() <= pd.Timedelta(days=1))].dropna(subset=['hg'])
        if len(m): return int(m.hg.iloc[0]), int(m.ag.iloc[0])
    return None

def rozlicz():
    d = wczytaj_dziennik()
    if not len(d): print("Dziennik jest pusty – typy value zapiszą się po pierwszym dniu, w którym się pojawią."); return d
    teraz = pd.Timestamp.now(tz='Europe/Warsaw').tz_localize(None)
    do = d[(d.wynik.isna() | (d.wynik == '')) & (pd.to_datetime(d.start) < teraz - pd.Timedelta(hours=2.5))]
    wyniki = {}
    for liga in do.liga.unique():   # wyniki z ostatnich 3 dni z The Odds API (koszt: 2 kredyty na ligę)
        try:
            for s in api(f'sports/{liga}/scores', daysFrom=3):
                if s.get('completed') and s.get('scores'):
                    sc = {x['name']: int(x['score']) for x in s['scores']}
                    wyniki[s['id']] = (sc.get(s['home_team']), sc.get(s['away_team']))
        except Exception as e: print("Nie pobrano wyników", liga, e)
    for i, r in do.iterrows():
        w = wyniki.get(str(r.event_id)) or wynik_z_danych(r.gospodarz, r.gosc, r.start)
        if w and None not in w:
            d.loc[i, 'wynik'] = f"{w[0]}:{w[1]}"
            d.loc[i, 'zysk_na_1zl'] = round(zysk_zakladu(r.rynek, r.strona, r.linia, r.kurs_betclic, *w), 4)
    if PLATNY_PLAN:   # 💎 CLV (koszt ok. 20 kredytów na typ, liczony raz)
        if 'clv' not in d: d['clv'] = np.nan
        for i, r in d[d.clv.isna() & (pd.to_datetime(d.start) < teraz)].iterrows():
            try: d.loc[i, 'clv'] = clv_zakladu(r)
            except Exception as e: print("CLV niepobrane:", r.mecz, e)
    d.to_csv(PLIK_DZIENNIKA, index=False)
    return d



# ===== DANE =====
FD = "https://www.football-data.co.uk"
KRAJE = {  # jeden model na kraj (awanse/spadki łączą ligi)
 'Anglia': ['E0','E1','E2','E3','EC'], 'Szkocja': ['SC0','SC1','SC2','SC3'], 'Niemcy': ['D1','D2'],
 'Włochy': ['I1','I2'], 'Hiszpania': ['SP1','SP2'], 'Francja': ['F1','F2'], 'Holandia': ['N1'],
 'Belgia': ['B1'], 'Portugalia': ['P1'], 'Turcja': ['T1'], 'Grecja': ['G1'],
}
EXTRA = {'Polska':'POL','Austria':'AUT','Dania':'DNK','Finlandia':'FIN','Irlandia':'IRL','Norwegia':'NOR',
         'Rumunia':'ROU','Rosja':'RUS','Szwecja':'SWE','Szwajcaria':'SWZ',
         'USA':'USA','Brazylia':'BRA','Argentyna':'ARG','Meksyk':'MEX','Japonia':'JPN','Chiny':'CHN'}

def sezony(n):
    t = pd.Timestamp.today(); y = t.year if t.month >= 7 else t.year - 1
    return [f"{(y-i)%100:02d}{(y-i+1)%100:02d}" for i in range(n)]

def czytaj(url):
    r = requests.get(url, timeout=30); r.raise_for_status()
    return pd.read_csv(io.StringIO(r.content.decode('latin1')), on_bad_lines='skip')

def std(df, h, a, hg, ag, liga):
    out = df.rename(columns={h:'home', a:'away', hg:'hg', ag:'ag'}).copy()
    out['date'] = pd.to_datetime(out['Date'], dayfirst=True, errors='coerce')
    out['liga'] = liga; out['neutral'] = False
    return out.dropna(subset=['date','home','away'])


DANE = {}
def pobierz_dane():
    DANE.clear()
    global r
    for kraj, kody in KRAJE.items():
        czesci = []
        for kod in kody:
            for s in sezony(SEZONY_WSTECZ):
                try: czesci.append(std(czytaj(f"{FD}/mmz4281/{s}/{kod}.csv"), 'HomeTeam','AwayTeam','FTHG','FTAG', kod))
                except Exception: pass
        if czesci: DANE[kraj] = pd.concat(czesci, ignore_index=True)
    for kraj, kod in EXTRA.items():
        try:
            d = std(czytaj(f"{FD}/new/{kod}.csv"), 'Home','Away','HG','AG', kod)
            DANE[kraj] = d[d.date >= pd.Timestamp.today() - pd.DateOffset(years=SEZONY_WSTECZ)]
        except Exception as e: print("Nie udało się:", kraj, e)
    
    r = czytaj("https://raw.githubusercontent.com/martj42/international_results/master/results.csv")
    r = r.rename(columns={'home_team':'home','away_team':'away','home_score':'hg','away_score':'ag'})
    r['date'] = pd.to_datetime(r['date']); r['neutral'] = r['neutral'].astype(str).str.upper().eq('TRUE')
    r = r[r.date >= '2014-01-01']
    r['w'] = np.where(r.tournament.eq('Friendly'), 0.6, 1.0)   # towarzyskie mniej wiarygodne
    r['liga'] = 'INT'
    DANE['Reprezentacje'] = r
    
    for k, d in DANE.items(): print(f"{k:14s} {len(d):6d} meczów")

# ===== DOPASOWANIE NAZW Z PUCHARÓW =====
STOP = set('fc cf ac afc sc sv ssc ss as acf bc rc rcd cd ud sd club de del 1909 1907 1846 1899 1904 1900 1913 1910 04 05 29 osc losc bsc fk sk nk gnk kv rsc pae sfp cp sl tsg vfb vfl rb ogc balompie calcio 1 hotspur football the'.split())
def nrm(s):
    s = str(s).translate(str.maketrans({'ø':'o','Ø':'O','æ':'ae','Æ':'AE','ß':'ss','ł':'l','Ł':'L','ı':'i','đ':'d','Đ':'D'}))
    s = unicodedata.normalize('NFKD', s).encode('ascii','ignore').decode().lower()
    s = s.replace('&',' and ').replace("'",'').replace('-',' ').replace('.',' ')
    return ' '.join(t for t in s.split() if t not in STOP)
ALIAS = {'sporting braga':'sp braga', 'sporting clube braga':'sp braga', 'braga':'sp braga', 'sporting clube portugal':'sp lisbon', 'sporting':'sp lisbon',
 'aek athen':'aek', 'aek athens':'aek', 'istanbul basaksehir':'buyuksehyr', 'basaksehir':'buyuksehyr', 'kobenhavn':'fc copenhagen', 'copenhagen':'fc copenhagen',
 'heart midlothian':'hearts', 'heart of midlothian':'hearts', 'union saint gilloise':'st gilloise', 'royale union saint gilloise':'st gilloise', 'hjk helsinki':'hjk',
 'olympiakos piraeus':'olympiakos', 'olympiacos':'olympiakos', 'fcsb':'fcsb', 'steaua bucuresti':'fcsb', 'rapid wien':'sk rapid', 'rapid bucuresti':'fc rapid bucuresti',
 'bodo glimt':'bodo/glimt', 'malmo':'malmo ff', 'psv':'psv eindhoven', 'az':'az alkmaar',
 'manchester city':'man city','manchester united':'man united','brighton and hove albion':'brighton','newcastle united':'newcastle',
 'west ham united':'west ham','nottingham forest':'nottm forest','wolverhampton wanderers':'wolves','leicester city':'leicester',
 'internazionale milano':'inter','atletico madrid':'ath madrid','atletico madrid':'ath madrid','athletic':'ath bilbao','athletic bilbao':'ath bilbao',
 'real sociedad':'sociedad','real betis':'betis','paris saint germain':'paris sg','olympique lyonnais':'lyon','olympique marseille':'marseille',
 'stade rennais':'rennes','stade brestois':'brest','bayern munchen':'bayern munich','borussia monchengladbach':'mgladbach',
 'eintracht frankfurt':'ein frankfurt','bayer leverkusen':'leverkusen','borussia dortmund':'dortmund','koln':'fc koln','celta vigo':'celta',
 'rayo vallecano':'vallecano','espanyol':'espanol','hellas verona':'verona','union berlin':'union berlin','leipzig':'rb leipzig',
 'sporting lisbon':'sp lisbon','sporting portugal':'sp lisbon','nice':'nice','fiorentina':'fiorentina','granada':'granada',
 'atletico':'ath madrid', 'bor monchengladbach':'mgladbach', 'lazio roma':'lazio','villarreal':'villarreal','sevilla':'sevilla','napoli':'napoli','lazio':'lazio','roma':'roma'}
def dopasuj_puchar(nazwa, domowe):
    """Nazwa z danych pucharowych -> nazwa drużyny w danych ligowych jej kraju (albo None)."""
    n = nrm(nazwa); n = ALIAS.get(n, n)
    mapa = {nrm(t): t for t in domowe}
    if n in mapa: return mapa[n]
    tn = set(n.split())
    for k, t in mapa.items():
        tk = set(k.split())
        if tk and (tk <= tn or tn <= tk) and len(k) >= 4: return t
    m = difflib.get_close_matches(n, list(mapa), n=1, cutoff=0.8)
    return mapa[m[0]] if m else None

# ===== WSPÓLNY MODEL =====
def fit_joint(df, ref_date, half_life_days=365, reg_team=0.3, reg_league=0.01, kal=0.7):
    """Wspólny model wszystkich lig: siła drużyny = poziom ligi + odchylenie drużyny.
    df: date, home, away, hg, ag, neutral, lh (liga gosp.), la (liga gościa)"""
    d = df[(df.date < ref_date)].dropna(subset=['hg','ag']).copy()
    age = (pd.Timestamp(ref_date) - d.date).dt.days.values
    w = 0.5 ** (age / half_life_days); keep = w > 0.02; d, w = d[keep], w[keep]
    liga_druz = {}
    for t, l in zip(pd.concat([d.home, d.away]), pd.concat([d.lh, d.la])): liga_druz.setdefault(t, l)
    teams = sorted(liga_druz); ti = {t:i for i,t in enumerate(teams)}
    ligi = sorted(set(liga_druz.values())); li = {l:i for i,l in enumerate(ligi)}
    n, L = len(teams), len(ligi); tl = np.array([li[liga_druz[t]] for t in teams])
    hi, ai = d.home.map(ti).values, d.away.map(ti).values
    hg, ag = d.hg.values.astype(float), d.ag.values.astype(float); neu = d.neutral.values.astype(float)
    cup = (d.lh != d.la).values.astype(float) if 'cup' not in d else d.cup.values.astype(float)
    def f(p):
        a, b, A, B, mu, home, hc = p[:n], p[n:2*n], p[2*n:2*n+L], p[2*n+L:2*n+2*L], p[-3], p[-2], p[-1]
        att, dfn = a + A[tl], b + B[tl]
        lh_ = mu + (home + hc*cup)*(1-neu) + att[hi] + dfn[ai]; la_ = mu + att[ai] + dfn[hi]
        eh, ea = np.exp(lh_), np.exp(la_)
        v = -np.sum(w*(hg*lh_ - eh + ag*la_ - ea)) + reg_team*(a@a + b@b) + reg_league*(A@A + B@B)
        rh, ra = w*(hg-eh), w*(ag-ea)
        gatt = -(np.bincount(hi, rh, n) + np.bincount(ai, ra, n)); gdfn = -(np.bincount(ai, rh, n) + np.bincount(hi, ra, n))
        g = np.zeros_like(p)
        g[:n] = gatt + 2*reg_team*a; g[n:2*n] = gdfn + 2*reg_team*b
        g[2*n:2*n+L] = np.bincount(tl, gatt, L) + 2*reg_league*A; g[2*n+L:2*n+2*L] = np.bincount(tl, gdfn, L) + 2*reg_league*B
        g[-3] = -(rh.sum()+ra.sum()); g[-2] = -np.sum(rh*(1-neu)); g[-1] = -np.sum(rh*(1-neu)*cup) + 2*0.5*hc; v += 0.5*hc*hc; return v, g
    p0 = np.zeros(2*n+2*L+3); p0[-3] = np.log(1.35)
    p = minimize(f, p0, jac=True, method='L-BFGS-B').x
    a, b, A, B, mu, home, hc = p[:n], p[n:2*n], p[2*n:2*n+L], p[2*n+L:2*n+2*L], p[-3], p[-2], p[-1]
    att, dfn = a + A[tl], b + B[tl]
    lh_ = np.exp(mu + (home + hc*cup)*(1-neu) + att[hi] + dfn[ai]); la_ = np.exp(mu + att[ai] + dfn[hi])
    def rn(r):
        t = np.ones(len(d)); m=(hg==0)&(ag==0); t[m]=1-lh_[m]*la_[m]*r; m=(hg==0)&(ag==1); t[m]=1+lh_[m]*r
        m=(hg==1)&(ag==0); t[m]=1+la_[m]*r; m=(hg==1)&(ag==1); t[m]=1-r; return -np.sum(w*np.log(np.clip(t,1e-9,None)))
    rho = minimize_scalar(rn, bounds=(-.2,.2), method='bounded').x
    cnt = pd.concat([d.home, d.away]).value_counts()
    T = np.average(hg+ag, weights=w)
    return dict(teams=ti, att=att, dfn=dfn, mu=mu, home=home, home_cup=hc, rho=rho, T=T, n_matches=cnt.to_dict(),
                liga=liga_druz, ligi={l:(A[li[l]], B[li[l]]) for l in ligi}, kal=kal)
def xg(m, h, a, neutral=False, puchar=True):
    i, j = m['teams'][h], m['teams'][a]
    lh = np.exp(m['mu'] + (0 if neutral else m['home'] + (m['home_cup'] if puchar else 0)) + m['att'][i] + m['dfn'][j]); la = np.exp(m['mu'] + m['att'][j] + m['dfn'][i])
    t = lh + la; f = (m['T'] + m['kal']*(t - m['T']))/t; return lh*f, la*f

# ===== PUCHARY EUROPEJSKIE: wspólny model wszystkich lig =====
import re as _re
KRAJ_KODY = {'ENG':'Anglia','SCO':'Szkocja','GER':'Niemcy','ITA':'Włochy','ESP':'Hiszpania','FRA':'Francja','NED':'Holandia',
 'BEL':'Belgia','POR':'Portugalia','TUR':'Turcja','GRE':'Grecja','POL':'Polska','AUT':'Austria','DEN':'Dania','FIN':'Finlandia',
 'IRL':'Irlandia','NOR':'Norwegia','ROU':'Rumunia','RUS':'Rosja','SWE':'Szwecja','SUI':'Szwajcaria'}
PIERWSZE_LIGI = {'USA','BRA','ARG','MEX','JPN','CHN','E0','SC0','D1','I1','SP1','F1','N1','B1','P1','T1','G1','POL','AUT','DNK','FIN','IRL','NOR','ROU','RUS','SWE','SWZ'}
_MIES = {m:i+1 for i,m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())}

def parsuj_puchary(txt, comp):
    rows, year, date, final = [], None, None, False
    for line in txt.replace('\r','').split('\n'):
        if line.startswith('▪'): final = line.strip() == '▪ Final'
        m = _re.search(r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2})(?: (\d{4}))?', line)
        if m and ' v ' not in line:
            if m.group(4): year = int(m.group(4))
            mo = _MIES[m.group(2)]
            if date is not None and not m.group(4) and mo < date.month - 6: year += 1
            if year: date = pd.Timestamp(year, mo, int(m.group(3)))
            continue
        mm = _re.search(r'^\s*(?:\d{1,2}[.:]\d{2}\s+)?(.+?) \(([A-Z]{3})\)\s+v\s+(.+?) \(([A-Z]{3})\)\s+(.*)$', line)
        if not mm or date is None: continue
        rest = mm.group(5)
        s = _re.search(r'\((\d+)-(\d+)', rest) if ('a.e.t' in rest or 'pen' in rest) else _re.match(r'(\d+)-(\d+)', rest)
        if not s: continue
        rows.append(dict(date=date, home=mm.group(1).strip(), hc=mm.group(2), away=mm.group(3).strip(), ac=mm.group(4),
                         hg=int(s.group(1)), ag=int(s.group(2)), comp=comp, neutral=final))
    return rows

def pobierz_puchary(sezony_wstecz=4):
    t = pd.Timestamp.today(); y = t.year if t.month >= 7 else t.year - 1
    rows = []
    for i in range(sezony_wstecz):
        s = f"{y-i}-{(y-i+1)%100:02d}"
        for comp in ('cl', 'el', 'conf'):
            try:
                r = requests.get(f"https://raw.githubusercontent.com/openfootball/champions-league/master/{s}/{comp}.txt", timeout=30)
                if r.status_code == 200: rows += parsuj_puchary(r.content.decode('utf-8'), comp)
            except Exception as e: print('puchary', s, comp, e)
    return pd.DataFrame(rows)

def trenuj_puchary():
    C = pobierz_puchary()
    if not len(C): print('Brak danych pucharowych'); return None
    # drużyny krajowe: grupa = liga (dywizja), w której grały ostatnio
    dom, dywizja, kraj_druzyn = [], {}, {}
    for k, d in DANE.items():
        if k == 'Reprezentacje': continue
        d = d.sort_values('date')
        for t, l in zip(pd.concat([d.home, d.away]), pd.concat([d.liga, d.liga])): dywizja[t] = l
        kraj_druzyn[k] = sorted(set(d.home) | set(d.away))
        dom.append(d[['date','home','away','hg','ag']].assign(neutral=False))
    dom = pd.concat(dom, ignore_index=True)
    dom['lh'] = dom.home.map(dywizja); dom['la'] = dom.away.map(dywizja); dom['cup'] = 0.0
    def mapuj(n, c):
        k = KRAJ_KODY.get(c)
        if k in kraj_druzyn:
            t = dopasuj_puchar(n, kraj_druzyn[k])
            if t: return t, dywizja[t]
        return f"{n} ({c})", c
    C[['home', 'lh']] = [mapuj(n, c) for n, c in zip(C.home, C.hc)]
    C[['away', 'la']] = [mapuj(n, c) for n, c in zip(C.away, C.ac)]
    C['cup'] = 1.0
    ALL = pd.concat([dom, C[['date','home','away','hg','ag','neutral','lh','la','cup']]], ignore_index=True)
    DZIS = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
    m = fit_joint(ALL, DZIS, kal=KALIBRACJA_GOLI)
    druzyny_pucharowe = set(C.home) | set(C.away)
    m['eksport'] = [t for t in m['teams'] if m['liga'][t] in PIERWSZE_LIGI or t in druzyny_pucharowe]
    m['home'] = m['home'] + m['home_cup']          # w pucharach przewaga własnego boiska jest większa
    m['n_matches'] = {t: int(m['n_matches'].get(t, 0)) for t in m['teams']}
    print(f"Puchary: {len(C)} meczów, {len(m['eksport'])} drużyn w rankingu")
    return m

# ===== KALIBRACJA SZANS MODELU (ogólna metoda, przeliczana co tydzień) =====
# Test 2022-2026: uczona na starszych meczach i sprawdzana na nowszych zmniejszyła średni błąd na kraj z 2,0 do 1,4 pkt proc.
from scipy.stats import poisson as _poi
_G = np.arange(MAXG + 1); _I, _J = np.meshgrid(_G, _G, indexing='ij'); _T, _D = _I + _J, _I - _J
MASKI = {'1': _D > 0, 'X': _D == 0, '2': _D < 0, '1X': _D >= 0, 'X2': _D <= 0, '12': _D != 0,
 'BTTS Tak': (_I > 0) & (_J > 0), 'BTTS Nie': (_I == 0) | (_J == 0),
 'H -1.5': _D >= 2, 'A -1.5': _D <= -2, 'H -2.5': _D >= 3, 'A -2.5': _D <= -3, 'H -3.5': _D >= 4, 'A -3.5': _D <= -4, 'H -4.5': _D >= 5, 'A -4.5': _D <= -5,
 'H o0.5': _I >= 1, 'A o0.5': _J >= 1, 'H o1.5': _I >= 2, 'A o1.5': _J >= 2, 'H o2.5': _I >= 3, 'A o2.5': _J >= 3,
 '1 & o1.5': (_D > 0) & (_T >= 2), '2 & o1.5': (_D < 0) & (_T >= 2), '1 & o2.5': (_D > 0) & (_T >= 3), '2 & o2.5': (_D < 0) & (_T >= 3),
 'X & u2.5': (_D == 0) & (_T <= 2), 'BTTS & o2.5': (_I > 0) & (_J > 0) & (_T >= 3)}
for _l in (1.5, 2.5, 3.5, 4.5, 5.5): MASKI[f'Over {_l}'] = _T > _l; MASKI[f'Under {_l}'] = _T < _l
KALIBRACJA_PUCHARY = {"1": [0.1869, 0.9074], "X": [0.2576, 1.3499], "2": [-0.1057, 0.9817], "1X": [0.1058, 0.9817], "X2": [-0.1869, 0.9074], "12": [-0.2576, 1.3499], "Over 1.5": [0.7299, 0.5229], "Over 2.5": [0.1729, 0.943], "Under 2.5": [-0.1729, 0.943], "Under 3.5": [-0.0388, 0.8399], "Over 3.5": [0.0388, 0.8399], "BTTS Tak": [0.2075, 0.3284], "BTTS Nie": [-0.2075, 0.3283], "H -1.5": [-0.0018, 0.8572], "A -1.5": [-0.1258, 1.0171], "H o1.5": [0.1756, 0.8932], "A o1.5": [-0.0127, 0.9243], "H o0.5": [0.4844, 0.8207], "A o0.5": [0.0877, 0.8564], "1 & o1.5": [0.131, 0.908], "2 & o1.5": [-0.0905, 0.9421], "1 & o2.5": [0.12, 0.9349], "2 & o2.5": [-0.0738, 0.928], "X & u2.5": [0.9263, 1.739], "BTTS & o2.5": [-0.0263, 0.282], "H -2.5": [-0.1159, 0.8247], "A -2.5": [-0.3921, 0.8342], "Under 1.5": [-0.7299, 0.5228]}
_lg = lambda p: np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
_sg = lambda x: 1 / (1 + np.exp(-x))

def _macierze(lh, la, rho):
    ph = _poi.pmf(_G[None, :], lh[:, None]); pa = _poi.pmf(_G[None, :], la[:, None]); M = ph[:, :, None] * pa[:, None, :]
    M[:, 0, 0] *= 1 - lh * la * rho; M[:, 0, 1] *= 1 + lh * rho; M[:, 1, 0] *= 1 + la * rho; M[:, 1, 1] *= 1 - rho
    return M / M.sum((1, 2))[:, None, None]

def policz_kalibracje(dni=540, krok=14, lam=60.0):
    """Test krokowy na ostatnich ~1,5 roku każdej ligi -> skalowanie Platta dla każdego rynku + ostrożne przesunięcie dla kraju."""
    L, H, A, R_, TT, HG, AG, KR = [], [], [], [], [], [], [], []
    for k, d in DANE.items():
        start = pd.Timestamp.today().normalize() - pd.Timedelta(days=dni)
        test = d[(d.date >= start) & d.hg.notna()]
        intl = k == 'Reprezentacje'
        for _, g in test.groupby((test.date - start).dt.days // krok):
            m = fit_model(d, g.date.min(), half_life_days=1095 if intl else 365, reg=0.1 if intl else 0.3, weight_col='w' if intl else None)
            for x in g.itertuples():
                if x.home not in m['teams'] or x.away not in m['teams'] or min(m['n_matches'][x.home], m['n_matches'][x.away]) < 8: continue
                lh, la = expected_goals(m, x.home, x.away, bool(getattr(x, 'neutral', False)))
                H.append(lh); A.append(la); R_.append(m['rho']); HG.append(int(x.hg)); AG.append(int(x.ag)); KR.append(k)
    if len(H) < 500: return None
    M = _macierze(np.array(H), np.array(A), np.array(R_)); HG, AG, KR = np.clip(HG, 0, MAXG), np.clip(AG, 0, MAXG), np.array(KR)
    out = {}
    for z, mask in MASKI.items():
        p = (M * mask).sum((1, 2)); y = mask[HG, AG].astype(float); ok = (p > 0.03) & (p < 0.97)
        if ok.sum() < 300: continue
        x, yy = _lg(p[ok]), y[ok]
        f = lambda ab: -np.sum(yy * np.log(_sg(ab[0] + ab[1] * x) + 1e-12) + (1 - yy) * np.log(1 - _sg(ab[0] + ab[1] * x) + 1e-12))
        a, b = minimize(f, [0, 1], method='Nelder-Mead').x
        q = _sg(a + b * x); kr = KR[ok]
        off = {k: round(float(np.sum(yy[kr == k] - q[kr == k]) / (np.sum(q[kr == k] * (1 - q[kr == k])) + lam)), 4) for k in np.unique(kr)}
        out[z] = dict(a=round(float(a), 4), b=round(float(b), 4), kraje=off)
    for z, (a, b) in KALIBRACJA_PUCHARY.items():
        out.setdefault(z, dict(a=0.0, b=1.0, kraje={}))['puchary'] = [a, b]
    return dict(data=pd.Timestamp.today().strftime('%Y-%m-%d'), meczow=len(H), rynki=out)

KALIBRACJA = None
def kalibruj(z, p, model_key):
    """Poprawia szansę z MODELU (nie z rynku) według kalibracji; model_key = liga/kraj modelu."""
    if not KALIBRACJA or z not in KALIBRACJA['rynki']: return p
    c = KALIBRACJA['rynki'][z]
    if model_key == 'Puchary europejskie':
        if 'puchary' not in c: return p
        a, b = c['puchary']; return float(_sg(a + b * _lg(p)))
    return float(_sg(c['a'] + c['b'] * _lg(p) + c['kraje'].get(model_key, 0.0)))

# ===== MODELE =====
MODELE = {}
def trenuj():
    DZIS = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
    MODELE.clear()
    for k, d in DANE.items():
        if k == 'Reprezentacje': MODELE[k] = fit_model(d, DZIS, half_life_days=1095, reg=0.1, weight_col='w')
        else: MODELE[k] = fit_model(d, DZIS, half_life_days=365, reg=0.3)
    try:
        m = trenuj_puchary()
        if m: MODELE['Puchary europejskie'] = m
    except Exception as e: print('Model pucharowy nie powstał:', e)
