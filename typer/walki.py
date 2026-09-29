"""Sporty walki (MMA, boks): szanse z rynku (Pinnacle/Betfair) -> rozkład (kto wygra i jak) -> typy na trzech poziomach.
MMA: dopasowane na 6 916 walkach UFC 2010–2026 (kursy z ufc-master, GitHub shortlikeafox).
 - Rynek nie docenia faworytów (75–80% → wygrywają 83%) – kalibracja Platta, test krokowy 2022–2026:
   faworyci ≥68%: przewidywane 77%, weszło 78% (893 walki).
 - Szansa skończenia przed czasem zależy od kategorii wagowej (ciężka 62%, kobiety słomkowa 32%) i przewagi faworyta;
   test krokowy 1 899 walk: „przed czasem” 50,3% → 50,0%, „faworyt przed czasem” 35,3% → 35,3%.
Boks: brak danych historycznych – tylko zwycięzca (i remis, gdy jest w kursach), bez kalibracji."""
import re, unicodedata, io
import numpy as np, pandas as pd, requests

PLATT_MMA = 1.1151
KONCZENIE = {"a0": -0.1313, "b": 0.1469, "r5": 0.3389, "wc": {
    "Bantamweight": -0.1078, "Catch Weight": 0.1707, "Featherweight": -0.097, "Flyweight": -0.1924, "Heavyweight": 0.6592,
    "Light Heavyweight": 0.5495, "Lightweight": 0.0923, "Middleweight": 0.3367, "Welterweight": 0.0546,
    "Women's Bantamweight": -0.3712, "Women's Featherweight": -0.1817, "Women's Flyweight": -0.4468, "Women's Strawweight": -0.5971}}
KATEGORIE_PL = {"Bantamweight": "kogucia", "Catch Weight": "umowna", "Featherweight": "piórkowa", "Flyweight": "musza", "Heavyweight": "ciężka",
                "Light Heavyweight": "półciężka", "Lightweight": "lekka", "Middleweight": "średnia", "Welterweight": "półśrednia",
                "Women's Bantamweight": "kogucia kobiet", "Women's Featherweight": "piórkowa kobiet", "Women's Flyweight": "musza kobiet",
                "Women's Strawweight": "słomkowa kobiet"}
DANE_UFC = 'https://raw.githubusercontent.com/shortlikeafox/ultimate_ufc_dataset/master/ufc-master.csv'

_sig = lambda z: 1 / (1 + np.exp(-z))
_lg = lambda p: np.log(p / (1 - p))

def nrm(s):
    s = unicodedata.normalize('NFKD', str(s).replace('ł', 'l').replace('Ł', 'L').replace('ø', 'o')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z ]', ' ', s)).strip()

_kat = {}
def kategorie():
    """Ostatnia kategoria wagowa każdego zawodnika UFC (z publicznego zbioru danych; brak = model ogólny)."""
    if 'd' in _kat: return _kat['d']
    out = {}
    try:
        d = pd.read_csv(io.StringIO(requests.get(DANE_UFC, timeout=60).text), usecols=['R_fighter', 'B_fighter', 'date', 'weight_class'])
        d = d.sort_values('date')
        for kol in ('R_fighter', 'B_fighter'):
            for n, w in zip(d[kol], d.weight_class): out[nrm(n)] = w
    except Exception as e: print('Kategorie UFC niepobrane:', e)
    _kat['d'] = out; return out

def kategoria(a, b):
    k = kategorie(); ka, kb = k.get(nrm(a)), k.get(nrm(b))
    return ka or kb

def kalibruj_mma(p):
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return float(_sig(PLATT_MMA * _lg(p)))

def rozklad_mma(p, kat=None, rund5=False):
    """Wyniki: ('A','KO') przed czasem, ('A','PKT') na punkty, to samo dla B."""
    q = 1 - p; K = KONCZENIE
    f = lambda x: _sig(K['a0'] + K['b'] * _lg(min(max(x, 1e-4), 1 - 1e-4)) + K['r5'] * rund5 + K['wc'].get(kat, 0.0))
    return {('A', 'KO'): p * f(p), ('A', 'PKT'): p * (1 - f(p)), ('B', 'KO'): q * f(q), ('B', 'PKT'): q * (1 - f(q))}

def rozklad_boks(pa, pb, pd_=0.0):
    R = {('A', ''): pa, ('B', ''): pb}
    if pd_: R[('D', '')] = pd_
    return R

def rynki(R):
    W = list(R)
    r = {'A': {w for w in W if w[0] == 'A'}, 'B': {w for w in W if w[0] == 'B'}}
    if ('A', 'KO') in R:
        r.update({'A przed czasem': {('A', 'KO')}, 'A na punkty': {('A', 'PKT')}, 'B przed czasem': {('B', 'KO')}, 'B na punkty': {('B', 'PKT')},
                  'Przed czasem': {('A', 'KO'), ('B', 'KO')}, 'Pełny dystans': {('A', 'PKT'), ('B', 'PKT')}})
    if ('D', '') in R: r['Remis'] = {('D', '')}
    return r

NAJPEWNIEJSZE = ['A', 'B', 'Przed czasem', 'Pełny dystans']
LEPSZY_KURS = ['A', 'B', 'Przed czasem', 'Pełny dystans', 'A przed czasem', 'B przed czasem', 'A na punkty', 'B na punkty']
RYZYKOWNE = ['A', 'B', 'A przed czasem', 'B przed czasem', 'A na punkty', 'B na punkty']

def typy(R):
    from tenis import _wybierz
    rk = rynki(R); out = {}; wyb = []
    for poz, lista, kmin, kmax, pmin in (('najpewniejszy', NAJPEWNIEJSZE, 1.25, 99, 0.55), ('lepszy_kurs', LEPSZY_KURS, 1.55, 2.30, 0.40),
                                         ('ryzykowny', RYZYKOWNE, 2.50, 5.00, 0.18)):
        t = _wybierz(R, rk, lista, kmin, kmax, pmin, wyb)
        if t: out[poz] = t; wyb.append(t[0])
    return out, rk

def opis(nazwa, a, b):
    kto = lambda s: a if s == 'A' else b
    if nazwa in ('A', 'B'): return f'wygra {kto(nazwa)}'
    if nazwa == 'Przed czasem': return 'walka skończy się przed czasem (KO/TKO/poddanie)'
    if nazwa == 'Pełny dystans': return 'walka potrwa pełny dystans (decyzja sędziów)'
    if nazwa == 'Remis': return 'remis'
    s, co = nazwa.split(' ', 1)
    return f"{kto(s)} wygra {'przed czasem' if co == 'przed czasem' else 'na punkty'}"
