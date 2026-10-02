"""Zbieracz kursów (wersja 37) – uruchamiany na polskim serwerze przez cron (k.py --zbieracz <tryb>).
Cała oferta Fortuny (piłka, tenis, MMA, boks; mecze startujące w najbliższych 24 h), WSZYSTKIE rynki meczu:
  tryb 'rano'       – ok. 7:30 (po porannym odczycie kursów),
  tryb 'popoludnie' – ok. 15:00,
  tryb 'przed'      – co kilka minut: mecze startujące za 45–75 min (jeden odczyt na mecz), wysyłane raz wieczorem,
  tryb 'wyslij'     – ok. 23:30: wysłanie odczytów „przed meczem” z całego dnia.
Na serwerze zostaje pełny zapis (wszystkie rynki, surowe nazwy) w /opt/typer/zbieracz/<data>/ (90 dni),
do repozytorium idzie wersja znormalizowana (nasze klucze rynków) jako docs/data/archiwum/kursy/<data>_<tryb>.json.gz –
GitHub następnego dnia rozlicza każdy kurs wynikiem (archiwum.py) i liczy, gdzie bukmacher się myli."""
import os, io, re, json, gzip, time, base64, shutil, datetime as dt

KAT = '/opt/typer/zbieracz'
LIMIT_S = {'rano': 1080, 'popoludnie': 1080, 'przed': 150, 'wyslij': 120}
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
        if k: norm.append(dict(wsp, k=k))
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
        p = os.path.join(_katalog(), 'przed.json')
        try: przed = json.load(open(p))
        except Exception: przed = []
        if przed: _wyslij_gz(V, f'docs/data/archiwum/kursy/{dzis}_przed.json.gz', dict(czas=teraz.strftime('%Y-%m-%d %H:%M UTC'), buk='fortuna', tryb='przed', mecze=przed))
        _sprzataj(); print('Zbieracz – wysłano „przed meczem”:', len(przed)); return
    lista_p = os.path.join(_katalog(), 'lista.json')
    if tryb == 'przed':
        try: lista = json.load(open(lista_p))
        except Exception: print('Zbieracz: brak listy meczów z rana'); return
        p = os.path.join(_katalog(), 'przed.json')
        try: przed = json.load(open(p))
        except Exception: przed = []
        juz = {m['id'] for m in przed}
        okno = []
        for m in lista:
            t = dt.datetime.strptime(m['t'], '%Y-%m-%d %H:%M').replace(tzinfo=dt.timezone.utc)
            if m['id'] not in juz and 45 <= (t - teraz).total_seconds() / 60 <= 75:
                okno.append(dict(m, t=t))
        if not okno: return
        norm, sur = _czytaj(V, s, okno[:40], LIMIT_S['przed'], diag)
        przed += norm; json.dump(przed, open(p, 'w'), ensure_ascii=False)
        stare = []
        sp_ = os.path.join(_katalog(), 'przed_surowe.json.gz')
        try:
            with gzip.open(sp_, 'rt', encoding='utf-8') as f: stare = json.load(f)
        except Exception: pass
        with gzip.open(sp_, 'wt', encoding='utf-8') as f: json.dump(stare + sur, f, ensure_ascii=False, separators=(',', ':'))
        print('Zbieracz – przed meczem:', len(norm)); return
    # pełny odczyt oferty: rano / po południu
    oferta = V.fortuna_mecze(s, diag)
    mecze = sorted([f for f in oferta if 0 <= (f['t'] - teraz).total_seconds() / 3600 <= 24], key=lambda f: f['t'])[:1500]
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
