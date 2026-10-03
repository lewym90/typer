"""Wersja 50 – PINNACLE ZA DARMO (publiczne API strony pinnacle.com, „guest”, bez konta i bez limitu kredytów).
Cel: ostre kursy (najlepszy punkt odniesienia rynku) dla WSZYSTKICH sportów i lig, które Pinnacle wystawia – także tam, gdzie
The Odds API tego nie daje albo kosztuje kredyty – oraz kursy zamknięcia (CLV) do archiwum. Na razie TYLKO ZBIERANIE
(do sprawdzenia, czy API odpowiada z serwerów GitHuba); typy dalej liczone jak dotąd. Gdy działa → kolejna wersja może
zastąpić The Odds API (piłka, tenis, walki) i dać Pinnacle nowym dyscyplinom.

Tryby: 'pelne' (rano, pełne liczenie) – mecze startujące w ciągu 30 h; 'zamk' (co 30 min) – mecze 5–50 min przed startem
(kurs zamknięcia). Zapis: docs/data/archiwum/pinnacle/<data>_rano.json.gz i <data>_zamk.json.gz (zamknięcie nadpisywane
świeższym odczytem do startu). Rynki (okres 0 = cały mecz, 1 = 1. połowa/tercja/set…): klucze
  'ml|<okres>' {home, away, draw}, 'tot|<okres>|<linia>' {over, under}, 'spr|<okres>|<linia gosp.>' {home, away},
  'tt|<okres>|home|<linia>' / 'tt|<okres>|away|<linia>' {over, under}; kursy dziesiętne (z amerykańskich)."""
import os, json, gzip, time, datetime as dt
import requests

BASE = 'https://guest.api.arcadia.pinnacle.com/0.1'
KLUCZ = 'CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R'          # publiczny klucz strony pinnacle.com (ten sam w każdej przeglądarce)
OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data', 'archiwum', 'pinnacle')
SUROWE = os.path.join(os.path.dirname(__file__), '..', 'surowe', 'pinnacle_probka.json')
SPORTY = {'soccer': 'pilka', 'tennis': 'tenis', 'basketball': 'koszykowka', 'hockey': 'hokej', 'baseball': 'baseball',
          'handball': 'pilka_reczna', 'volleyball': 'siatkowka', 'mixed martial arts': 'mma', 'mma': 'mma', 'boxing': 'boks',
          'formula 1': 'f1', 'auto racing': 'f1', 'motorsport': 'f1'}
STAN = dict(czas=None, tryb=None, http=None, sporty={}, mecze=0, rynki=0, bledy=[], sekund=0, plik=None)
NAGL = {'X-API-Key': KLUCZ, 'Referer': 'https://www.pinnacle.com/', 'Origin': 'https://www.pinnacle.com', 'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36'}


def _blad(t):
    t = str(t)[:160]
    if t not in STAN['bledy'] and len(STAN['bledy']) < 10: STAN['bledy'].append(t)


def _get(sciezka, get=None):
    if get: return get(sciezka)
    r = requests.get(BASE + sciezka, headers=NAGL, timeout=25)
    STAN['http'] = r.status_code
    if r.status_code != 200: raise RuntimeError(f'HTTP {r.status_code}: {r.text[:80]}')
    return r.json()


def dziesietny(p):
    try: p = float(p)
    except Exception: return None
    if p >= 100: return round(1 + p / 100, 3)
    if p <= -100: return round(1 + 100 / abs(p), 3)
    return round(p, 3) if 1.0 < p < 100 else None


def _pkt(x):
    try: return f'{float(x):g}'
    except Exception: return None


def rynki(markety):
    """Lista rynków Pinnacle (markets/straight) → {matchupId: {klucz: {strona: kurs}}}."""
    out = {}
    for m in markety or []:
        if not isinstance(m, dict) or str(m.get('status', 'open')) != 'open': continue
        mid, typ, okres = m.get('matchupId'), m.get('type'), m.get('period', 0)
        ceny = m.get('prices') or []
        d = out.setdefault(mid, {})
        if typ == 'moneyline':
            k = f'ml|{okres}'
            for c in ceny: d.setdefault(k, {})[c.get('designation')] = dziesietny(c.get('price'))
        elif typ == 'total':
            for c in ceny:
                l = _pkt(c.get('points'))
                if l: d.setdefault(f'tot|{okres}|{l}', {})[c.get('designation')] = dziesietny(c.get('price'))
        elif typ == 'spread':
            home = next((c for c in ceny if c.get('designation') == 'home'), None)
            l = _pkt(home.get('points')) if home else None
            if l:
                for c in ceny: d.setdefault(f'spr|{okres}|{l}', {})[c.get('designation')] = dziesietny(c.get('price'))
        elif typ == 'team_total':
            strona = m.get('side')
            for c in ceny:
                l = _pkt(c.get('points'))
                if l and strona: d.setdefault(f'tt|{okres}|{strona}|{l}', {})[c.get('designation')] = dziesietny(c.get('price'))
    return out


def _czas(s):
    try: return dt.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except Exception: return None


def zbierz(tryb='pelne', get=None, teraz=None):
    """Odczyt wszystkich sportów programu. Zwraca STAN (do status.json → pinnacle)."""
    t0 = time.time(); teraz = teraz or dt.datetime.now(dt.timezone.utc)
    STAN.update(czas=teraz.strftime('%Y-%m-%d %H:%M UTC'), tryb=tryb)
    try: sporty = _get('/sports', get)
    except Exception as e: _blad(f'sporty: {e}'); return STAN
    mecze, probka = {}, None
    for s in sporty or []:
        sp = SPORTY.get(str(s.get('name', '')).lower())
        if not sp or not s.get('matchupCount'): continue
        if time.time() - t0 > (150 if tryb == 'pelne' else 60): _blad('limit czasu'); break
        try:
            mu = _get(f"/sports/{s['id']}/matchups?withSpecials=false&brandId=0", get)
            okno = [m for m in mu or [] if isinstance(m, dict) and m.get('type') == 'matchup' and not m.get('parentId') and not m.get('isLive')]
            wyb = []
            for m in okno:
                t = _czas(m.get('startTime'))
                if not t: continue
                minut = (t - teraz).total_seconds() / 60
                if (tryb == 'pelne' and 0 < minut <= 30 * 60) or (tryb == 'zamk' and 5 <= minut <= 50): wyb.append((m, t))
            if not wyb: continue
            mk = rynki(_get(f"/sports/{s['id']}/markets/straight?primaryOnly=false&withSpecials=false", get))
        except Exception as e: _blad(f"{s.get('name')}: {e}"); continue
        n = 0
        for m, t in wyb:
            uc = {p.get('alignment'): p.get('name') for p in m.get('participants') or [] if isinstance(p, dict)}
            r = mk.get(m.get('id'))
            if not r or not uc.get('home'): continue
            mecze[str(m['id'])] = dict(sp=sp, liga=(m.get('league') or {}).get('name'), h=uc.get('home'), a=uc.get('away'),
                                      t=t.strftime('%Y-%m-%d %H:%M'), czas=teraz.strftime('%Y-%m-%d %H:%M'), r=r)
            n += 1
            if probka is None: probka = dict(matchup=m, rynki=r)
        STAN['sporty'][sp] = STAN['sporty'].get(sp, 0) + n
        time.sleep(0.3)
    STAN['mecze'] = len(mecze); STAN['rynki'] = sum(len(x['r']) for x in mecze.values())
    if mecze: _zapisz(tryb, mecze, teraz)
    if probka and tryb == 'pelne':
        try:
            os.makedirs(os.path.dirname(SUROWE), exist_ok=True)
            with open(SUROWE, 'w', encoding='utf-8') as f: json.dump(dict(czas=STAN['czas'], **probka), f, ensure_ascii=False, default=str)
        except Exception as e: _blad(f'próbka: {e}')
    STAN['sekund'] = round(time.time() - t0, 1)
    return STAN


def _zapisz(tryb, mecze, teraz):
    try: from zoneinfo import ZoneInfo; d = teraz.astimezone(ZoneInfo('Europe/Warsaw')).strftime('%Y-%m-%d')
    except Exception: d = teraz.strftime('%Y-%m-%d')
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, f"{d}_{'rano' if tryb == 'pelne' else 'zamk'}.json.gz")
    stare = {}
    if os.path.exists(p):
        try:
            with gzip.open(p, 'rt', encoding='utf-8') as f: stare = json.load(f).get('mecze') or {}
        except Exception: stare = {}
    if tryb == 'pelne': stare = {**mecze, **stare}            # rano: pierwszy odczyt dnia zostaje
    else: stare.update(mecze)                                   # zamknięcie: najświeższy odczyt przed startem
    with gzip.open(p, 'wt', encoding='utf-8') as f:
        json.dump(dict(czas=STAN['czas'], buk='pinnacle', tryb=tryb, mecze=stare), f, ensure_ascii=False, separators=(',', ':'))
    STAN['plik'] = os.path.basename(p)
