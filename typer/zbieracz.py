"""Zbieracz kursów (wersja 37) – uruchamiany na polskim serwerze przez cron (k.py --zbieracz <tryb>).
Cała oferta Fortuny (piłka, tenis, MMA, boks; mecze startujące w najbliższych 24 h), WSZYSTKIE rynki meczu:
  tryb 'rano'       – ok. 7:30 (po porannym odczycie kursów),
  tryb 'popoludnie' – ok. 15:00,
  tryb 'przed'      – co kilka minut (wersja 43 – SKANER SKŁADÓW, piłka):
                        • 120–240 min przed startem: skład FotMob „przewidywany” (ostatnia jedenastka + niedostępni) – punkt odniesienia,
                        • 45–75 min: kursy Fortuny (wszystkie rynki) + skład FotMob (często już potwierdzony),
                        • 3–20 min: kursy Fortuny („zamknięcie”) + potwierdzony skład FotMob,
                      inne sporty: kursy 45–75 min i 3–20 min. Wysyłane wieczorem i powtórnie rano (mecze po północy),
  tryb 'wyslij'     – ok. 23:30: wysłanie odczytów „przed meczem”, „zamknięcia” i składów z całego dnia.
Na serwerze zostaje pełny zapis (wszystkie rynki, surowe nazwy) w /opt/typer/zbieracz/<data>/ (90 dni),
do repozytorium idzie wersja znormalizowana (nasze klucze rynków) jako docs/data/archiwum/kursy/<data>_<tryb>.json.gz –
GitHub następnego dnia rozlicza każdy kurs wynikiem (archiwum.py) i liczy, gdzie bukmacher się myli."""
import os, io, re, json, gzip, time, base64, shutil, datetime as dt

KAT = '/opt/typer/zbieracz'
GLOWNE = ('pilka', 'tenis', 'mma', 'boks', 'sporty walki')
LIMIT_S = {'rano': 1080, 'popoludnie': 1080, 'przed': 240, 'wyslij': 180, 'superbet': 1080}
START = time.time()


def _tz():
    try:
        from zoneinfo import ZoneInfo; return ZoneInfo('Europe/Warsaw')
    except Exception: return dt.timezone(dt.timedelta(hours=2))


def _dzien(): return dt.datetime.now(_tz()).strftime('%Y-%m-%d')


def _katalog(d=None):
    k = os.path.join(KAT, d or _dzien()); os.makedirs(k, exist_ok=True); return k


def _surowe(rynki):
    """Wszystkie rynki meczu w zwięzłej postaci: [[nazwa rynku, [[wynik, kurs], ...]], ...]."""
    out = []
    for m in rynki or []:
        n = re.sub(r'\s+', ' ', str(m.get('marketTypeName') or m.get('name') or '')).strip()
        oc = []
        for o in m.get('outcomes') or []:
            try: c = float(o.get('odds') or 0)
            except Exception: continue
            if c > 1: oc.append([str(o.get('name') or '').replace('\xa0', ' ')[:60], round(c, 2)])
        if n and oc: out.append([n[:90], oc])
    return out


def _wyslij_gz(V, sciezka, dane):
    """Wysyła plik .json.gz do repozytorium (GitHub API, zawartość binarna)."""
    try: token = open(V.TOKEN_PLIK).read().strip()
    except Exception: print('Brak tokenu'); return False
    import requests
    surowe = gzip.compress(json.dumps(dane, ensure_ascii=False, separators=(',', ':')).encode())
    h = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'typer-vps'}
    api = f'https://api.github.com/repos/{V.REPO}/contents/{sciezka}'
    for _ in range(3):
        r = requests.get(api, headers=h, timeout=20); sha = r.json().get('sha') if r.status_code == 200 else None
        body = dict(message=f'Zbieracz kursów {sciezka.rsplit("/", 1)[-1]}', content=base64.b64encode(surowe).decode())
        if sha: body['sha'] = sha
        r = requests.put(api, headers=h, json=body, timeout=60)
        if r.status_code in (200, 201): print('Zapisano', sciezka, len(surowe) // 1024, 'kB'); return True
        print('GitHub', r.status_code, r.text[:160]); time.sleep(5)
    return False


def _czytaj(V, s, mecze, limit_s, diag):
    """Pełna oferta każdego meczu (Fortuna) → (znormalizowane, surowe)."""
    norm, sur = [], []
    for f in mecze:
        if time.time() - START > limit_s: diag['przerwane_po'] = len(norm); break
        try: rynki = V.fortuna_pelna_oferta(s, f['id'])
        except Exception as e:
            diag['bledy'] = diag.get('bledy', 0) + 1
            if diag['bledy'] > 40: break
            continue
        sp = f['sp']; sport = sp if sp in ('pilka', 'tenis') else 'duel'
        try: k = V._fortuna_klucze(rynki, False, sport, 3, (f['h'], f['a']))
        except Exception: k = {}
        teraz = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M')
        wsp = dict(id=f['id'], sp=sp, tur=f.get('tur', ''), h=f['h'], a=f['a'], t=f['t'].strftime('%Y-%m-%d %H:%M'), czas=teraz)
        if sp not in ('pilka', 'tenis'):    # wersja 46: walki i nowe dyscypliny – do repozytorium także surowe rynki (najważniejsze 40)
            r40 = _surowe(rynki)[:40]
            if r40: norm.append(dict(wsp, k=k or {}, r=r40))
        elif k: norm.append(dict(wsp, k=k))
        sur.append(dict(wsp, r=_surowe(rynki)))
        time.sleep(0.12)
    return norm, sur


def _zapisz_lokalnie(nazwa, dane):
    p = os.path.join(_katalog(), nazwa)
    with gzip.open(p, 'wt', encoding='utf-8') as f: json.dump(dane, f, ensure_ascii=False, separators=(',', ':'))
    return p


def _sprzataj(dni=90):
    try:
        granica = (dt.datetime.now(_tz()) - dt.timedelta(days=dni)).strftime('%Y-%m-%d')
        for d in os.listdir(KAT):
            if d < granica: shutil.rmtree(os.path.join(KAT, d), ignore_errors=True)
    except Exception: pass


def krok(V, KP, s, tryb):
    """V = moduł kursy_vps (Fortuna, zapis), KP = kursy_pl, s = sesja requests."""
    tryb = tryb if tryb in LIMIT_S else 'rano'
    diag = dict(tryb=tryb); dzis = _dzien(); teraz = dt.datetime.now(dt.timezone.utc)
    os.makedirs(KAT, exist_ok=True)
    if tryb == 'wyslij':
        n = _wyslij_dzien(V, dzis); _sprzataj(); print('Zbieracz – wysłano:', n); return
    if tryb == 'przed':
        skaner(V, KP, s, diag); return
    if tryb == 'superbet':
        superbet(V, KP, diag); return
    # pełny odczyt oferty: rano / po południu
    lista_p = os.path.join(_katalog(), 'lista.json')        # wersja 46: przywrócone (w v43–v45 brakowało → błąd trybu rano/po południu)
    if tryb == 'rano':                     # wersja 43: dosyłka wczorajszych odczytów przed meczem (mecze po 23:30)
        try: _wyslij_dzien(V, (dt.datetime.now(_tz()) - dt.timedelta(days=1)).strftime('%Y-%m-%d'))
        except Exception as e: print('dosyłka wczoraj:', e)
    try: oferta = V.fortuna_mecze(s, diag, wszystkie=True)     # wersja 46: rano i po południu wszystkie 11 sportów programu
    except TypeError: oferta = V.fortuna_mecze(s, diag)
    w24 = [f for f in oferta if 0 <= (f['t'] - teraz).total_seconds() / 3600 <= 24]
    mecze = sorted([f for f in w24 if f['sp'] in GLOWNE], key=lambda f: f['t'])[:1500]
    inne = sorted([f for f in w24 if f['sp'] not in GLOWNE], key=lambda f: f['t'])[:900]
    diag['inne_sporty'] = {}
    for f in inne: diag['inne_sporty'][f['sp']] = diag['inne_sporty'].get(f['sp'], 0) + 1
    mecze += inne
    diag['w_ofercie_24h'] = len(mecze)
    json.dump([dict(id=f['id'], sp=f['sp'], tur=f.get('tur', ''), h=f['h'], a=f['a'], t=f['t'].strftime('%Y-%m-%d %H:%M')) for f in mecze],
              open(lista_p, 'w'), ensure_ascii=False)
    norm, sur = _czytaj(V, s, mecze, LIMIT_S[tryb], diag)
    _zapisz_lokalnie(f'fortuna_{tryb}.json.gz', sur)
    diag.update(odczytane=len(norm), rynkow=sum(len(x['r']) for x in sur), sekund=round(time.time() - START))
    _wyslij_gz(V, f'docs/data/archiwum/kursy/{dzis}_{tryb}.json.gz', dict(czas=teraz.strftime('%Y-%m-%d %H:%M UTC'), buk='fortuna', tryb=tryb, mecze=norm))
    try: V.zapisz_github('surowe/zbieracz_stan.json', dict(czas=teraz.strftime('%Y-%m-%d %H:%M UTC'), **diag))
    except Exception: pass
    print('Zbieracz –', tryb, json.dumps(diag, ensure_ascii=False, default=str)[:400])


# =============================================================== wersja 43 – SKANER SKŁADÓW
# Cel: złapać chwilę, w której skład jest już znany (FotMob ok. 60 min przed meczem), a kursy polskich bukmacherów
# jeszcze go nie uwzględniły. Dla każdego meczu z oferty Fortuny trzy migawki (patrz opis na górze), potem GitHub
# rozlicza (sklady_lab.py): braki ważnych zawodników vs ruch kursu i wynik → gdzie jest przewaga i jak duża.
FM = 'https://www.fotmob.com/api/data'
OKNA = {'s0': (120, 240), 'przed': (45, 75), 'zamk': (3, 20)}
PLIKI = {'s0': 'sklady0.json', 'przed': 'przed.json', 'zamk': 'zamk.json'}
_fm_cache = {}


def _wczytaj_json(p, dom):
    try: return json.load(open(p))
    except Exception: return dom


def _fm_get(s, url):
    r = s.get(url, timeout=15, headers={'Referer': 'https://www.fotmob.com/', 'Accept': 'application/json'})
    if r.status_code != 200: raise RuntimeError(f'FotMob {r.status_code}')
    return r.json()


def _utc(t):
    try: return dt.datetime.fromisoformat(str(t).replace('Z', '+00:00')).astimezone(dt.timezone.utc)
    except Exception: return None


def fm_lista(s, dzien):
    """Mecze FotMob dnia (YYYY-MM-DD, czas polski): [(id, gospodarz, gość, czas UTC, liga)]; pamięć pliku na 40 min."""
    if dzien in _fm_cache: return _fm_cache[dzien]
    p = os.path.join(_katalog(), f'fm_{dzien}.json')
    z = _wczytaj_json(p, None)
    if z and time.time() - z.get('czas', 0) < 2400:
        out = [(x[0], x[1], x[2], _utc(x[3]), x[4]) for x in z['mecze']]; _fm_cache[dzien] = out; return out
    out = []
    try: j = _fm_get(s, f"{FM}/matches?date={dzien.replace('-', '')}&timezone=Europe%2FWarsaw&ccode3=POL")
    except Exception as e: print('FotMob lista:', e); _fm_cache[dzien] = []; return []
    def chodz(o, liga=''):
        if isinstance(o, dict):
            liga = o.get('name') if isinstance(o.get('matches'), list) and o.get('name') else liga
            h, a = o.get('home'), o.get('away')
            if o.get('id') and isinstance(h, dict) and isinstance(a, dict):
                t = _utc((o.get('status') or {}).get('utcTime') or o.get('time'))
                if t: out.append((str(o['id']), h.get('longName') or h.get('name'), a.get('longName') or a.get('name'), t, liga))
                return
            for v in o.values(): chodz(v, liga)
        elif isinstance(o, list):
            for v in o: chodz(v, liga)
    chodz(j)
    json.dump(dict(czas=time.time(), mecze=[[x[0], x[1], x[2], x[3].isoformat(), x[4]] for x in out]), open(p, 'w'), ensure_ascii=False)
    _fm_cache[dzien] = out
    return out


def _podobne(KP, a, b):
    try:
        from nazwy import pl
        return max(KP.podobne_w(a, b), KP.podobne_w(a, pl(b)))
    except Exception:
        try: return KP.podobne_w(a, b)
        except Exception:
            import difflib; return difflib.SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()


def dopasuj_fm(s, KP, m):
    """Mecz Fortuny (h, a, t UTC) → id meczu FotMob albo None (czas ±20 min, nazwy ≥ 0,5)."""
    t = m['t']; best = None
    for dz in {t.astimezone(_tz()).strftime('%Y-%m-%d')}:
        for fid, h, a, tt, liga in fm_lista(s, dz):
            if abs((tt - t).total_seconds()) > 1200: continue
            sc = min(_podobne(KP, m['h'], h), _podobne(KP, m['a'], a))
            if sc >= 0.5 and (best is None or sc > best[0]): best = (sc, fid, h, a, liga)
    return best


def _zawodnicy(lst, niedostepni=False):
    out = []
    for p in lst or []:
        if not isinstance(p, dict): continue
        w = [p.get('id'), p.get('name'), p.get('usualPlayingPositionId', p.get('positionId')), p.get('marketValue')]
        if niedostepni:
            u = p.get('unavailability') or {}
            w += [u.get('type'), u.get('expectedReturn')]
        out.append(w)
    return out


def fm_sklad(s, mid):
    """Zwięzła migawka składu z FotMob matchDetails: typ (lastStarting11 = przewidywany / inne = ogłoszony) i obie drużyny."""
    j = _fm_get(s, f'{FM}/matchDetails?matchId={mid}')
    lu = ((j.get('content') or {}).get('lineup') or {})
    out = dict(typ=lu.get('lineupType'))
    for k, kl in (('h', 'homeTeam'), ('a', 'awayTeam')):
        d = lu.get(kl) or {}
        out[k] = dict(n=d.get('name'), f=d.get('formation'), v=d.get('totalStarterMarketValue'), w=d.get('averageStarterAge'),
                      s=_zawodnicy(d.get('starters')), l=_zawodnicy(d.get('subs')), u=_zawodnicy(d.get('unavailable'), True))
    try:
        st = (j.get('header') or {}).get('status') or {}
        out['start'] = st.get('utcTime')
    except Exception: pass
    return out


def _lista_meczow():
    """Lista z porannego/popołudniowego odczytu – dziś i wczoraj (mecze po północy)."""
    out, ids = [], set()
    for d in (_dzien(), (dt.datetime.now(_tz()) - dt.timedelta(days=1)).strftime('%Y-%m-%d')):
        for m in _wczytaj_json(os.path.join(KAT, d, 'lista.json'), []):
            if m['id'] in ids: continue
            ids.add(m['id']); out.append(dict(m, t=dt.datetime.strptime(m['t'], '%Y-%m-%d %H:%M').replace(tzinfo=dt.timezone.utc)))
    return out


def zrobione(etap):
    """Id meczów, które już mają migawkę danego etapu (dziś i wczoraj)."""
    z = set()
    for d in (_dzien(), (dt.datetime.now(_tz()) - dt.timedelta(days=1)).strftime('%Y-%m-%d')):
        z |= {m['id'] for m in _wczytaj_json(os.path.join(KAT, d, PLIKI[etap]), [])}
    return z


def do_zrobienia(teraz=None):
    """{etap: [mecze]} w oknach czasowych (używane też przez cron, żeby nie uruchamiać procesu bez potrzeby)."""
    teraz = teraz or dt.datetime.now(dt.timezone.utc)
    lista = _lista_meczow(); out = {}
    for etap, (a, b) in OKNA.items():
        juz = zrobione(etap)
        out[etap] = [m for m in lista if m['id'] not in juz and a <= (m['t'] - teraz).total_seconds() / 60 <= b
                     and (etap != 's0' or m['sp'] == 'pilka')]
    return out


def _dopisz(etap, rekordy):
    if not rekordy: return
    p = os.path.join(_katalog(), PLIKI[etap])
    json.dump(_wczytaj_json(p, []) + rekordy, open(p, 'w'), ensure_ascii=False)


def skaner(V, KP, s, diag):
    teraz = dt.datetime.now(dt.timezone.utc); zad = do_zrobienia(teraz); wynik = {}
    fm_ids = _wczytaj_json(os.path.join(KAT, 'fm_ids.json'), {})          # id Fortuny → id FotMob (pamięć dopasowań)
    def sklad(m):
        if m['sp'] != 'pilka': return None
        if m['id'] not in fm_ids:
            b = dopasuj_fm(s, KP, m)
            fm_ids[m['id']] = [b[1], round(b[0], 2), b[2], b[3], b[4]] if b else None
        b = fm_ids.get(m['id'])
        if not b: return None
        try: return dict(fm=b[0], zgodnosc=b[1], fm_h=b[2], fm_a=b[3], liga=b[4], **fm_sklad(s, b[0]))
        except Exception as e: diag['bledy_fm'] = diag.get('bledy_fm', 0) + 1; return None
    # 1) przewidywany skład (bez kursów)
    rek = []
    for m in zad.get('s0', [])[:60]:
        if time.time() - START > LIMIT_S['przed'] * 0.4: break
        sk = sklad(m)
        rek.append(dict(id=m['id'], sp=m['sp'], h=m['h'], a=m['a'], t=m['t'].strftime('%Y-%m-%d %H:%M'),
                        czas=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M'), sk=sk))
        time.sleep(0.15)
    _dopisz('s0', rek); wynik['s0'] = len(rek)
    # 2) i 3) kursy + skład
    for etap in ('zamk', 'przed'):
        okno = zad.get(etap, [])[:40]
        if not okno: continue
        norm, sur = _czytaj(V, s, okno, LIMIT_S['przed'], diag)
        ids = {x['id'] for x in norm}
        for x in norm:
            if x['sp'] == 'pilka' and time.time() - START < LIMIT_S['przed'] + 60:
                m = next(mm for mm in okno if mm['id'] == x['id']); x['sk'] = sklad(m)
        # mecze bez kursów też oznaczamy jako zrobione (żeby nie wracać co 3 min)
        norm += [dict(id=m['id'], sp=m['sp'], h=m['h'], a=m['a'], t=m['t'].strftime('%Y-%m-%d %H:%M'), k={}, brak=True)
                 for m in okno if m['id'] not in ids and time.time() - START <= LIMIT_S['przed']]
        _dopisz(etap, norm); wynik[etap] = len(norm)
        sp_ = os.path.join(_katalog(), f'{etap}_surowe.json.gz')
        try:
            with gzip.open(sp_, 'rt', encoding='utf-8') as f: stare = json.load(f)
        except Exception: stare = []
        with gzip.open(sp_, 'wt', encoding='utf-8') as f: json.dump(stare + sur, f, ensure_ascii=False, separators=(',', ':'))
    json.dump(fm_ids, open(os.path.join(KAT, 'fm_ids.json'), 'w'))
    if any(wynik.values()): print('Zbieracz – przed meczem:', json.dumps(wynik), 'skład FotMob:', sum(1 for v in fm_ids.values() if v))


def _wyslij_dzien(V, d):
    """Wysyła odczyty dnia d: przed meczem i zamknięcie (kursy) oraz składy (archiwum/sklady/<d>.json.gz)."""
    k = os.path.join(KAT, d); n = {}
    czas = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    for etap in ('przed', 'zamk'):
        lst = [m for m in _wczytaj_json(os.path.join(k, PLIKI[etap]), []) if m.get('k') or m.get('r')]
        if lst:
            _wyslij_gz(V, f'docs/data/archiwum/kursy/{d}_{etap}.json.gz',
                       dict(czas=czas, buk='fortuna', tryb=etap, mecze=[{x: v for x, v in m.items() if x != 'sk'} for m in lst]))
        n[etap] = len(lst)
    sk = []
    for etap in ('s0', 'przed', 'zamk'):
        for m in _wczytaj_json(os.path.join(k, PLIKI[etap]), []):
            if m.get('sk'): sk.append(dict(id=m['id'], etap=etap, czas=m.get('czas'), t=m['t'], h=m['h'], a=m['a'], sk=m['sk'],
                                           k1x2={z: m.get('k', {}).get(z) for z in ('1', 'X', '2') if m.get('k', {}).get(z)}))
    if sk: _wyslij_gz(V, f'docs/data/archiwum/sklady/{d}.json.gz', dict(czas=czas, mecze=sk))
    n['sklady'] = len(sk)
    return n


# =============================================================== wersja 48 – SUPERBET: cała oferta 11 sportów
# Fortuna to jeden bukmacher – baza „rynek polski” potrzebuje kilku. Superbet ma publiczne API (bez przeglądarki):
# lista zdarzeń dnia + pełna oferta zdarzenia. Odczyt 2× dziennie (ok. 10:00 i 17:00), mecze startujące w 26 h,
# wszystkie rynki (do 60 na zdarzenie) → serwer (pełne) i repozytorium docs/data/archiwum/kursy/<d>_superbet_<n>.json.gz.
# sportId Superbetu (rozpoznane 03.10 z listy zdarzeń): 5 piłka, 190 piłka kobiet, 2 tenis, 4 koszykówka, 3 hokej,
# 20 baseball, 11 piłka ręczna, 1 siatkówka (prawdopodobnie), 94 żużel, 34 boks, 91/93 wyścigi (F1 / inne), 40 i 13 – do
# rozpoznania (mogą być MMA/inne) – zapisujemy z kluczem 'sb<id>', mapowanie po przejrzeniu danych.
SB_SPORTY = {5: 'pilka', 190: 'pilka', 2: 'tenis', 4: 'koszykowka', 3: 'hokej', 20: 'baseball', 11: 'pilka_reczna',
             1: 'siatkowka', 94: 'zuzel', 34: 'boks', 91: 'f1', 93: 'wyscigi', 40: 'sb40', 13: 'sb13', 28: 'mma', 50: 'mma'}


def _sb_rynki(odds):
    """[[rynek, [[wynik, linia, kurs], ...]], ...] – do 60 rynków."""
    r = {}
    for o in odds or []:
        try: c = round(float(o.get('price') or 0), 2)
        except Exception: continue
        if c <= 1: continue
        mn = str(o.get('marketName') or '')[:90]
        if mn not in r and len(r) >= 60: continue
        r.setdefault(mn, []).append([str(o.get('name') or '')[:60], str(o.get('specialBetValue') or ''), c])
    return [[k, v] for k, v in r.items()]


def superbet(V, KP, diag):
    ses = KP._sesja(); teraz = dt.datetime.now(dt.timezone.utc)
    ev = []
    for i in (0, 1):          # dziś i jutro (lista „by-date” od podanego dnia)
        d = (teraz + dt.timedelta(days=i)).strftime('%Y-%m-%d')
        try:
            j = KP._json(ses, f"{KP.SB}/events/by-date?currentStatus=active&offerState=prematch&startDate={d}%2000:00:00")
            ev += j.get('data') or []
        except Exception as e: diag.setdefault('bledy', []).append(f'lista {d}: {e}'[:120])
    widziane, wyb, sporty_wszystkie = set(), [], {}
    for e in ev:
        sid = e.get('sportId'); sporty_wszystkie[str(sid)] = sporty_wszystkie.get(str(sid), 0) + 1
        try: sid = int(sid)
        except Exception: continue
        if sid not in SB_SPORTY or e.get('eventId') in widziane: continue
        try: t = dt.datetime.fromtimestamp(int(e.get('unixDateMillis')) / 1000, dt.timezone.utc)
        except Exception:
            try: t = dt.datetime.fromisoformat(str(e.get('utcDate')).replace('Z', '+00:00'))
            except Exception: continue
        if not (0 <= (t - teraz).total_seconds() / 3600 <= 26): continue
        widziane.add(e.get('eventId')); wyb.append((t, sid, e))
    wyb.sort(key=lambda x: (x[1] != 5, x[0]))
    diag.update(sb_sporty_wszystkie=sporty_wszystkie, sb_wybrane=len(wyb))
    norm, n_sp = [], {}
    for t, sid, e in wyb[:2500]:
        if time.time() - START > LIMIT_S['superbet']: diag['przerwane_po'] = len(norm); break
        try:
            j = KP._json(ses, f"{KP.SB}/events/{e['eventId']}"); d = j.get('data'); d = d[0] if isinstance(d, list) and d else d
            r = _sb_rynki((d or {}).get('odds'))
        except Exception:
            diag['bledy_n'] = diag.get('bledy_n', 0) + 1
            if diag['bledy_n'] > 60: break
            continue
        if not r: continue
        h, a = KP._strony(e)
        sp = SB_SPORTY[sid]; n_sp[sp] = n_sp.get(sp, 0) + 1
        norm.append(dict(id=str(e.get('eventId')), sp=sp, sid=sid, tur=str(e.get('tournamentId') or ''), kat=str(e.get('categoryId') or ''),
                         br=e.get('betradarId'), h=h, a=a, t=t.strftime('%Y-%m-%d %H:%M'), czas=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M'), r=r))
        time.sleep(0.08)
    diag.update(sb_odczytane=len(norm), sb_sporty=n_sp, sekund=round(time.time() - START))
    nr = 1 if dt.datetime.now(_tz()).hour < 14 else 2
    _zapisz_lokalnie(f'superbet_{nr}.json.gz', norm)
    if norm: _wyslij_gz(V, f'docs/data/archiwum/kursy/{_dzien()}_superbet_{nr}.json.gz',
                        dict(czas=teraz.strftime('%Y-%m-%d %H:%M UTC'), buk='superbet', tryb=f'superbet_{nr}', mecze=norm))
    try: V.zapisz_github('surowe/zbieracz_superbet.json', dict(czas=teraz.strftime('%Y-%m-%d %H:%M UTC'), **diag))
    except Exception: pass
    print('Zbieracz – Superbet', json.dumps(diag, ensure_ascii=False, default=str)[:300])
