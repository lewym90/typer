import os, sys
import numpy as np, pandas as pd
ODDS_API_KEY = os.environ.get('ODDS_API_KEY', '')
BANKROLL = 1000
SEZONY_WSTECZ = 3
WAGA_MODELU = 0.35
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

def score_matrix(lh, la, rho):
    M = np.outer(poisson.pmf(np.arange(MAXG + 1), lh), poisson.pmf(np.arange(MAXG + 1), la))
    M[0, 0] *= 1 - lh * la * rho; M[0, 1] *= 1 + lh * rho
    M[1, 0] *= 1 + la * rho; M[1, 1] *= 1 - rho
    return M / M.sum()

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
    """Usuwa marżę bukmachera (metoda proporcjonalna) -> uczciwe prawdopodobieństwa."""
    inv = np.array([1 / o for o in odds_list]); return inv / inv.sum()

def market_lambdas(p1, px, p2, p_over=None, line=2.5, rho=-0.05):
    """Odtwarza oczekiwane gole z uczciwych kursów rynku (np. Pinnacle) -> pozwala liczyć BTTS/handicapy/gole."""
    tot = np.add.outer(np.arange(MAXG + 1), np.arange(MAXG + 1))
    def loss(x):
        M = score_matrix(np.exp(x[0]), np.exp(x[1]), rho)
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
 'soccer_uefa_champs_league':None, 'soccer_fifa_world_cup':'Reprezentacje', 'soccer_uefa_european_championship':'Reprezentacje',
 'soccer_uefa_nations_league':'Reprezentacje', 'soccer_fifa_world_cup_qualifiers_europe':'Reprezentacje',
 'soccer_uefa_euro_qualification':'Reprezentacje', 'soccer_epl':'Anglia', 'soccer_spain_la_liga':'Hiszpania',
 'soccer_poland_ekstraklasa':'Polska', 'soccer_italy_serie_a':'Włochy', 'soccer_germany_bundesliga':'Niemcy',
 'soccer_france_ligue_one':'Francja', 'soccer_uefa_europa_league':None, 'soccer_uefa_europa_conference_league':None,
 'soccer_international_friendlies':'Reprezentacje', 'soccer_portugal_primeira_liga':'Portugalia',
 'soccer_netherlands_eredivisie':'Holandia', 'soccer_efl_champ':'Anglia', 'soccer_germany_bundesliga2':'Niemcy',
 'soccer_turkey_super_league':'Turcja', 'soccer_belgium_first_div':'Belgia', 'soccer_spl':'Szkocja',
}
MIN_EV_VALUE = 0.03       # Betclic musi dawać min. 3% więcej niż uczciwy kurs Pinnacle/Betfair
PEWNE_MIN_SZANSA = 0.68   # "bezpieczne" typy: minimalna szansa wejścia
PEWNE_MIN_KURS = 1.25     # niższe kursy nie mają sensu (za mały zysk)
PEWNE_ILE_MECZOW = 15     # z ilu najpopularniejszych meczów wybierać
PEWNE_ILE_TYPOW = 5       # ile najpewniejszych typów pokazać
# Chcesz więcej lig? Dopisz klucz (lista: uruchom pokaz_ligi()) i model: 'Szkocja','Belgia','Turcja','Grecja',
# 'Austria','Dania','Norwegia','Szwecja','Szwajcaria','Rumunia','Finlandia','Irlandia','Rosja','Szkocja'.

API = "https://api.the-odds-api.com/v4"
def api(sciezka, **p):
    r = requests.get(f"{API}/{sciezka}", params={'apiKey': ODDS_API_KEY, **p}, timeout=30)
    if r.status_code != 200: raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
    print(f"   (kredyty pozostałe: {r.headers.get('x-requests-remaining')})"); return r.json()

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
    M_mkt = score_matrix(*market_lambdas(*p_mkt, p_over=p_ov), -0.05) if p_mkt is not None else None
    if M_mod is not None and M_mkt is not None: M, tryb, prog = WAGA_MODELU * M_mod + (1 - WAGA_MODELU) * M_mkt, f'model+{zrodlo}', MIN_EV_Z_RYNKIEM
    elif M_mkt is not None: M, tryb, prog = M_mkt, f'rynek ({zrodlo})', MIN_EV_Z_RYNKIEM
    elif M_mod is not None: M, tryb, prog = M_mod, 'tylko model', MIN_EV_SAM_MODEL
    else: return None
    uwaga = ''
    if k and min(MODELE[k]['n_matches'][h], MODELE[k]['n_matches'][a]) < 10: uwaga = '⚠ mało danych o drużynie'
    return dict(M=M, M_mod=M_mod, M_mkt=M_mkt, p_mkt=p_mkt, ostry=zrodlo in ('Pinnacle', 'Betfair', 'Pinnacle+Betfair'), betclic=betclic, tryb=tryb, prog=prog, uwaga=uwaga, home=home, away=away,
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
    teraz = pd.Timestamp.now(tz='Europe/Warsaw'); koniec = teraz.normalize() + pd.Timedelta(days=1)
    f = lambda t: t.tz_convert('UTC').strftime('%Y-%m-%dT%H:%M:%SZ')
    aktywne = {s['key'] for s in api('sports')}
    wynik = []
    for key, model in LIGI_DO_SKANU.items():
        if key not in aktywne: continue
        # lista meczów jest DARMOWA – kursy pobieramy tylko, gdy liga gra dzisiaj
        try: evs = api(f'sports/{key}/events', commenceTimeFrom=f(teraz), commenceTimeTo=f(koniec))
        except Exception: continue
        if not evs: continue
        print(f"→ {key}: {len(evs)} mecz(e) dziś")
        try: odds = api(f'sports/{key}/odds', regions=REGIONY_ODDS_API, markets='h2h,totals,spreads', oddsFormat='decimal',
                        commenceTimeFrom=f(teraz), commenceTimeTo=f(koniec))
        except Exception as e: print("   błąd:", e); continue
        for ev in odds:
            if POBIERZ_BTTS:
                try:
                    extra = api(f"sports/{key}/events/{ev['id']}/odds", regions=REGIONY_ODDS_API, markets='btts', oddsFormat='decimal')
                    for b in ev['bookmakers']:
                        for eb in extra.get('bookmakers', []):
                            if eb['key'] == b['key']: b['markets'] += eb['markets']
                except Exception: pass
            wynik.append((key, model, ev))
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

def ev_zakladu(M, rynek, strona, linia, kurs):
    """Wartość oczekiwana zakładu wg macierzy wyników M."""
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
    M = score_matrix(*market_lambdas(*p1, p_over=pov), -0.05)
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
         'Rumunia':'ROU','Rosja':'RUS','Szwecja':'SWE','Szwajcaria':'SWZ'}

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

# ===== MODELE =====
MODELE = {}
def trenuj():
    DZIS = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
    MODELE.clear()
    for k, d in DANE.items():
        if k == 'Reprezentacje': MODELE[k] = fit_model(d, DZIS, half_life_days=1095, reg=0.1, weight_col='w')
        else: MODELE[k] = fit_model(d, DZIS, half_life_days=365, reg=0.3)
