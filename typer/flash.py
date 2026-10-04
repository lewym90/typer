"""Wersja 50 – WYNIKI Z FLASHSCORE (wszystkie sporty, wszystkie ligi świata) do własnej bazy wyników.
Po co: ESPN ma tylko ligi amerykańskie i tenis (hokej, koszykówka, siatkówka i ręczna z Europy – zero), a FotMob nie ma
niższych lig piłki (2. Kostaryka, Japonia JFL…). Bez wyników zebrane kursy Fortuny i Superbetu tych meczów są bezużyteczne.

Źródło: publiczny „feed” strony (ten sam, z którego czyta przeglądarka): /x/feed/f_<sport>_<dzień>_<strefa>_<język>_1
z nagłówkiem x-fsign. Format tekstowy: rekordy rozdzielone „¬~”, pola „klucz÷wartość” rozdzielone „¬”.
  ZA – nazwa rozgrywek („POLSKA: Ekstraliga”), AA – id meczu, AD – start (unix), AB – stan (3 = zakończony), AC – szczegół,
  AE/AF – gospodarz/gość, AG/AH – wynik (w tenisie i siatkówce: sety), BA/BB, BC/BD, BE/BF, BG/BH, BI/BJ – części
  (połowy, tercje, kwarty, sety – w tenisie gemy). Surowe pola zostają w zapisie (klucz 'f'), żeby interpretację dało się
  poprawić później bez utraty danych.
Sporty: 1 piłka, 2 tenis, 3 koszykówka, 4 hokej, 6 baseball, 7 piłka ręczna, 12 siatkówka – pewne; MMA, boks, żużel, F1 –
rozpoznawane raz dziennie po nazwach rozgrywek (skan id 13–45), wynik w docs/data/archiwum/flash_sporty.json.
Diagnostyka: STAN (host, język, sporty, liczby, błędy, próbka) → status.json → archiwum.wyniki.flash."""
import os, re, json, time, datetime as dt
import requests

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data', 'archiwum')
PLIK_SPORTY = os.path.join(OUT, 'flash_sporty.json')
FSIGN = 'SW9D1eZo'
HOSTY = [('https://www.flashscore.pl/x/feed/', 'pl', 'https://www.flashscore.pl/'),
         ('https://d.flashscore.pl/x/feed/', 'pl', 'https://www.flashscore.pl/'),
         ('https://local-pl.flashscore.ninja/1/x/feed/', 'pl', 'https://www.flashscore.pl/'),
         ('https://www.flashscore.com/x/feed/', 'en', 'https://www.flashscore.com/'),
         ('https://d.flashscore.com/x/feed/', 'en', 'https://www.flashscore.com/'),
         ('https://local-global.flashscore.ninja/2/x/feed/', 'en', 'https://www.flashscore.com/')]
ZNANE = {1: 'pilka', 2: 'tenis', 3: 'koszykowka', 4: 'hokej', 6: 'baseball', 7: 'pilka_reczna', 12: 'siatkowka', 16: 'boks', 28: 'mma'}   # 16/28 potwierdzone 03.10
SZUKANE = [('mma', r'\b(ufc|ksw|pfl|oktagon|mma|bellator|cage warriors|babilon|fen\b|one championship)'),
           ('boks', r'(boks|boxing|wbc|wba|ibf|wbo|bokser)'),
           ('zuzel', r'(żużel|zuzel|speedway|ekstraliga żużl|sgp)'),
           ('f1', r'(formuła 1|formula 1|\bf1\b)')]
CZESCI = [('BA', 'BB'), ('BC', 'BD'), ('BE', 'BF'), ('BG', 'BH'), ('BI', 'BJ'), ('BK', 'BL')]
REG = {'hokej': 3, 'koszykowka': 4, 'pilka_reczna': 2, 'pilka': 2}     # ile części to czas regulaminowy
STAN = dict(host=None, jezyk=None, sporty={}, liczby={}, bledy=[], probka=None, zapytan=0, sekund=0)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36'
_SES = None
_HOST = None


def _blad(t):
    t = str(t)[:160]
    if t not in STAN['bledy'] and len(STAN['bledy']) < 12: STAN['bledy'].append(t)


def _tz_godz(teraz=None):
    try:
        from zoneinfo import ZoneInfo
        return int((teraz or dt.datetime.now(ZoneInfo('Europe/Warsaw'))).utcoffset().total_seconds() // 3600)
    except Exception: return 2


def _get(sid, przes, get=None):
    """Tekst feedu sportu `sid` dla dnia `przes` (0 = dziś, −1 = wczoraj; dzień wg czasu polskiego). None = brak."""
    global _SES, _HOST
    get = get or _pobierz
    kolejnosc = ([_HOST] if _HOST else []) + [h for h in HOSTY if h != _HOST]
    for host, jez, ref in kolejnosc:
        url = f'{host}f_{sid}_{przes}_{_tz_godz()}_{jez}_1'
        try:
            STAN['zapytan'] += 1
            kod, txt = get(url, {'x-fsign': FSIGN, 'Referer': ref, 'User-Agent': UA, 'Accept': '*/*'})
        except Exception as e:
            _blad(f'{host[:40]}: {type(e).__name__}'); continue
        if kod == 200 and txt is not None and ('¬' in txt or txt.strip() in ('', '0')):
            if _HOST != (host, jez, ref): _HOST = (host, jez, ref); STAN['host'] = host; STAN['jezyk'] = jez
            return txt
        _blad(f'{host[:40]} f_{sid}: HTTP {kod}, {len(txt or "")} zn.')
        if _HOST == (host, jez, ref): _HOST = None
    return None


def _pobierz(url, naglowki):
    global _SES
    if _SES is None: _SES = requests.Session()
    r = _SES.get(url, headers=naglowki, timeout=15)
    return r.status_code, r.text


def _int(x):
    try: return int(str(x).strip())
    except Exception: return None


def parsuj(txt):
    """Rekordy meczów z tekstu feedu: [{liga, kraj, AA, AD, AB, AC, AE, AF, AG, AH, BA…}] (surowe pola)."""
    out, liga, kraj = [], '', ''
    for rek in (txt or '').split('¬~'):
        pola = {}
        for p in rek.split('¬'):
            if '÷' in p:
                k, v = p.split('÷', 1); pola.setdefault(k.strip('~'), v)
        if 'ZA' in pola: liga, kraj = pola.get('ZA', ''), pola.get('ZY', '')
        if 'AA' in pola and ('AE' in pola or 'AF' in pola):
            pola['liga'], pola['kraj'] = liga, kraj
            out.append(pola)
    return out


def rekord(p, sp):
    """Surowy rekord feedu → zapis bazy wyników (ten sam układ co ESPN/FotMob w wyniki_zbior) + reg i surowe pola."""
    try: t = dt.datetime.fromtimestamp(int(p.get('AD')), dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    except Exception: t = None
    gh, ga = _int(p.get('AG')), _int(p.get('AH'))
    cz = [[], []]
    for kh, ka in CZESCI:
        if kh in p or ka in p: cz[0].append(_int(p.get(kh))); cz[1].append(_int(p.get(ka)))
        else: break
    koniec = str(p.get('AB')) == '3'
    reg = None
    n = REG.get(sp)
    if n and len(cz[0]) >= n and None not in cz[0][:n] + cz[1][:n]:
        reg = [sum(cz[0][:n]), sum(cz[1][:n])]
        if gh is not None and (reg[0] > gh or reg[1] > ga): reg = None      # części to nie gole/punkty – nie ufamy
    zw = None
    if koniec and gh is not None and ga is not None: zw = 'h' if gh > ga else ('a' if ga > gh else 'r')
    if koniec and str(p.get('AS', '')) in ('1', '2') and sp in ('tenis', 'mma', 'boks'): zw = 'h' if str(p['AS']) == '1' else 'a'
    surowe = {k: v for k, v in p.items() if len(k) == 2 and k[0] in 'AB' and k not in ('AE', 'AF', 'AA', 'AD')}
    return dict(sp=sp, liga=f"{p.get('liga', '')}", zr='flash', id=str(p.get('AA')), t=t, h=p.get('AE'), a=p.get('AF'),
                gh=gh, ga=ga, zw=zw, koniec=koniec, stan=p.get('AC'), czesci=cz if cz[0] else None, reg=reg, f=surowe)


def _wczytaj_sporty():
    try: return json.load(open(PLIK_SPORTY))
    except Exception: return {}


def rozpoznaj_sporty(get=None, sila=False):
    """Raz dziennie: id sportów Flashscore dla MMA, boksu, żużla, F1 (po nazwach rozgrywek z dzisiejszego i wczorajszego feedu)."""
    st = _wczytaj_sporty()
    dzis = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')
    if st.get('data') == dzis and not sila and all(str(k) in (st.get('mapa') or {}) for k in ZNANE): return st
    mapa, probki = {str(k): v for k, v in ZNANE.items()}, {}
    for sid in range(13, 46):
        if sid in ZNANE: continue
        txt = _get(sid, 0, get) or ''
        if '¬' not in txt: txt = _get(sid, -1, get) or ''
        ligi = sorted({p.get('liga', '') for p in parsuj(txt)})
        if not ligi: continue
        probki[str(sid)] = ligi[:6]
        for sp, wz in SZUKANE:
            if sp in mapa.values(): continue
            traf = sum(1 for l in ligi if re.search(wz, l.lower()))
            if traf >= max(1, len(ligi) // 3): mapa[str(sid)] = sp; break
        time.sleep(0.15)
    st = dict(data=dzis, mapa=mapa, probki=probki)
    try:
        os.makedirs(OUT, exist_ok=True)
        with open(PLIK_SPORTY, 'w', encoding='utf-8') as f: json.dump(st, f, ensure_ascii=False)
    except Exception as e: _blad(f'zapis sportów: {e}')
    return st


def dzien(d, get=None, sporty=None):
    """Wszystkie mecze (zakończone i nie) dnia `d` (YYYY-MM-DD, czas polski) ze wszystkich sportów programu."""
    t0 = time.time()
    try: from zoneinfo import ZoneInfo; tz = ZoneInfo('Europe/Warsaw')
    except Exception: tz = dt.timezone(dt.timedelta(hours=2))
    dzis = dt.datetime.now(tz).date()
    przes = (dt.date.fromisoformat(d) - dzis).days
    if przes < -7 or przes > 7: return []
    mapa = (sporty or rozpoznaj_sporty(get)).get('mapa') or {str(k): v for k, v in ZNANE.items()}
    out = []
    for sid, sp in sorted(mapa.items(), key=lambda x: int(x[0])):
        txt = _get(int(sid), przes, get)
        if txt is None: continue
        rek = [rekord(p, sp) for p in parsuj(txt)]
        out += rek
        STAN['liczby'][sp] = STAN['liczby'].get(sp, 0) + len(rek)
        STAN['sporty'][sp] = int(sid)
        if rek and not STAN['probka']: STAN['probka'] = {k: v for k, v in rek[0].items() if k != 'f'}
        time.sleep(0.15)
    STAN['sekund'] = round(STAN['sekund'] + time.time() - t0, 1)
    return out


def zgodnosc(flash, inne):
    """Kontrola jakości: mecze obecne w obu źródłach (ten sam sport, start ±3 h, nazwiska/nazwy) – odsetek zgodnych zwycięzców."""
    import archiwum_inne as AI
    n = zg = 0
    po = {}
    for w in inne:
        if w.get('koniec') and w.get('zw') in ('h', 'a'): po.setdefault(w['sp'], []).append(w)
    for f in flash:
        if not f.get('koniec') or f.get('zw') not in ('h', 'a') or f['sp'] not in po: continue
        try: tf = dt.datetime.fromisoformat(f['t'].replace('Z', '+00:00'))
        except Exception: continue
        for w in po[f['sp']]:
            try: tw = dt.datetime.fromisoformat(str(w['t']).replace('Z', '+00:00'))
            except Exception: continue
            if tw.tzinfo is None: tw = tw.replace(tzinfo=dt.timezone.utc)
            if abs((tw - tf).total_seconds()) > 3 * 3600: continue
            for odwr in (False, True):
                eh, ea = (w['a'], w['h']) if odwr else (w['h'], w['a'])
                if AI._zgodne(f['h'], eh, f['sp']) and AI._zgodne(f['a'], ea, f['sp']):
                    n += 1; zg += int((f['zw'] == 'h') == ((w['zw'] == 'h') != odwr)); break
            else: continue
            break
    return dict(wspolne=n, zgodne=zg)
