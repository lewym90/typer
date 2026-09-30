"""Tenis: szanse z rynku (Pinnacle/Betfair) -> rozkład wyników w setach -> typy na trzech poziomach.
Parametry dopasowane na 14 625 meczach ATP 2020–2026 (tennis-data.co.uk, kursy zamknięcia Pinnacle/Betfair);
test 30.09 na 79 408 meczach ATP i WTA 2010–2026. Kobiety (WTA) częściej kończą mecz 2:0 – mają osobne parametry setów.
Prosty model „każdy set niezależnie” mylił się o 7–10 pkt (za rzadko 2:0) – dlatego rozkład setów jest liczony
z regresji: P(wygra bez straty seta | wygra) zależy od szansy zwycięzcy."""
import numpy as np

# Platt: rynek lekko nie docenia faworytów (90–95% → wchodzi 95%); p' = sigmoid(PLATT * logit(p))
PLATT = 1.0551
# P(wynik bez straty seta | wygrał) = sigmoid(a + b*logit(p_zwycięzcy)); dla 5 setów także P(3:1 | wygrał i stracił seta)
SETY = {3: {'g': (0.4244, 0.3665)}, 5: {'g': (-0.5918, 0.4521), 'h': (0.3065, 0.3307)}}
SETY_WTA = {'g': (0.5106, 0.396)}   # dopasowane na 38 390 meczach WTA 2010–2026 (więcej 2:0 niż u mężczyzn)
WIELKIE_SZLEMY = ('aus_open', 'french_open', 'wimbledon', 'us_open')

_sig = lambda z: 1 / (1 + np.exp(-z))
_lg = lambda p: np.log(p / (1 - p))

def do_ilu_setow(sport_key):
    """Mężczyźni w Wielkim Szlemie grają do 3 wygranych setów, reszta do 2."""
    k = sport_key or ''
    return 5 if k.startswith('tennis_atp') and any(s in k for s in WIELKIE_SZLEMY) else 3

def kalibruj(p):
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return float(_sig(PLATT * _lg(p)))

def kobiety(sport_key):
    return 'tennis_wta' in (sport_key or '')

def rozklad(p, bo=3, wta=False):
    """Szanse wyników w setach dla zawodnika A (p = skalibrowana szansa A na wygranie meczu)."""
    p = min(max(p, 1e-4), 1 - 1e-4); q = 1 - p
    ga, gb = SETY_WTA['g'] if (wta and bo == 3) else SETY[bo]['g']
    g = lambda x: _sig(ga + gb * _lg(x))
    if bo == 3:
        return {(2, 0): p * g(p), (2, 1): p * (1 - g(p)), (1, 2): q * (1 - g(q)), (0, 2): q * g(q)}
    h = lambda x: _sig(SETY[5]['h'][0] + SETY[5]['h'][1] * _lg(x))
    return {(3, 0): p * g(p), (3, 1): p * (1 - g(p)) * h(p), (3, 2): p * (1 - g(p)) * (1 - h(p)),
            (0, 3): q * g(q), (1, 3): q * (1 - g(q)) * h(q), (2, 3): q * (1 - g(q)) * (1 - h(q))}

def rynki(R, bo=3):
    """Zakłady: nazwa -> zbiór wyników (w setach), przy których wchodzi. 'A'/'B' = pierwszy/drugi zawodnik."""
    n = bo // 2 + 1; W = list(R)
    r = {'A': {w for w in W if w[0] == n}, 'B': {w for w in W if w[1] == n},
         'A +1.5': {w for w in W if w[0] >= 1} if bo == 3 else {w for w in W if w[0] >= 2},   # handicap setowy
         'B +1.5': {w for w in W if w[1] >= 1} if bo == 3 else {w for w in W if w[1] >= 2},
         'A min. 1 set': {w for w in W if w[0] >= 1}, 'B min. 1 set': {w for w in W if w[1] >= 1},
         'A -1.5': {w for w in W if w[0] == n and w[1] <= n - 2}, 'B -1.5': {w for w in W if w[1] == n and w[0] <= n - 2}}
    if bo == 3:
        r.update({'Ponad 2.5 seta': {(2, 1), (1, 2)}, 'Poniżej 2.5 seta': {(2, 0), (0, 2)},
                  'A 2:0': {(2, 0)}, 'A 2:1': {(2, 1)}, 'B 2:0': {(0, 2)}, 'B 2:1': {(1, 2)}})
        for k in ('A +1.5', 'B +1.5'): r.pop(k)   # przy 2 setach „+1.5” = „min. 1 set”
    else:
        r.update({'Ponad 3.5 seta': {w for w in W if sum(w) >= 4}, 'Poniżej 3.5 seta': {(3, 0), (0, 3)},
                  'Ponad 4.5 seta': {(3, 2), (2, 3)}, 'Poniżej 4.5 seta': {w for w in W if sum(w) <= 4},
                  'A 3:0': {(3, 0)}, 'A 3:1': {(3, 1)}, 'A 3:2': {(3, 2)}, 'B 3:0': {(0, 3)}, 'B 3:1': {(1, 3)}, 'B 3:2': {(2, 3)}})
    return r

NAJPEWNIEJSZE = ['A', 'B', 'A min. 1 set', 'B min. 1 set', 'A +1.5', 'B +1.5', 'A -1.5', 'B -1.5', 'Poniżej 2.5 seta', 'Poniżej 4.5 seta']
LEPSZY_KURS = ['A', 'B', 'A -1.5', 'B -1.5', 'A min. 1 set', 'B min. 1 set', 'A +1.5', 'B +1.5',
               'Ponad 2.5 seta', 'Poniżej 2.5 seta', 'Ponad 3.5 seta', 'Poniżej 3.5 seta', 'Ponad 4.5 seta', 'Poniżej 4.5 seta']
RYZYKOWNE = ['A', 'B', 'A -1.5', 'B -1.5', 'A 2:0', 'A 2:1', 'B 2:0', 'B 2:1', 'A 3:0', 'A 3:1', 'A 3:2', 'B 3:0', 'B 3:1', 'B 3:2',
             'Ponad 2.5 seta', 'Ponad 3.5 seta', 'Ponad 4.5 seta']

def _wybierz(R, rk, lista, kmin, kmax, pmin, wybrane):
    best = None
    for k in lista:
        if k not in rk or k in wybrane: continue
        p = sum(R[w] for w in rk[k])
        if not (kmin <= 1 / max(p, 1e-9) <= kmax) or p <= pmin: continue
        if any(sum(R[w] for w in rk[k] & rk[j]) < 0.03 for j in wybrane): continue   # sprzeczny z wcześniejszym typem
        if best is None or p > best[1]: best = (k, p)
    return best

def typy(R, bo=3):
    """Trzy poziomy jak w piłce: 🔒 najpewniejszy (kurs uczciwy ≥ 1,25), ⚖️ lepszy kurs (1,55–2,30), 🎯 ryzykowny (2,50–5,00)."""
    rk = rynki(R, bo); out = {}; wyb = []
    for poz, lista, kmin, kmax, pmin in (('najpewniejszy', NAJPEWNIEJSZE, 1.25, 99, 0.55), ('lepszy_kurs', LEPSZY_KURS, 1.55, 2.30, 0.40),
                                         ('ryzykowny', RYZYKOWNE, 2.50, 5.00, 0.18)):
        t = _wybierz(R, rk, lista, kmin, kmax, pmin, wyb)
        if t: out[poz] = t; wyb.append(t[0])
    return out, rk

def wszedl(nazwa, rk, a_sety, b_sety):
    return (a_sety, b_sety) in rk.get(nazwa, set())

def opis(nazwa, a, b, bo=3):
    """Nazwa zakładu po polsku z nazwiskami."""
    zam = lambda s: s.replace('A ', f'{a} ', 1) if s.startswith('A ') else (s.replace('B ', f'{b} ', 1) if s.startswith('B ') else s)
    if nazwa == 'A': return f'wygra {a}'
    if nazwa == 'B': return f'wygra {b}'
    if nazwa.endswith('min. 1 set'): return f"{a if nazwa[0] == 'A' else b} wygra min. 1 seta"
    if nazwa.endswith('+1.5'): return f"{a if nazwa[0] == 'A' else b} +1,5 seta (handicap)"
    if nazwa.endswith('-1.5'):
        kto = a if nazwa[0] == 'A' else b
        return f"{kto} wygra bez straty seta" if int(bo or 3) == 3 else f"{kto} wygra, tracąc najwyżej 1 seta (handicap -1,5)"
    if ':' in nazwa:
        kto, w = nazwa.split(' '); x, y = w.split(':')
        return f"{a if kto == 'A' else b} wygra {x}:{y} w setach"
    return zam(nazwa).replace('.5', ',5')
