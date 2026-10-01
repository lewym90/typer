"""Kursy z polskiego serwera (VPS) – STS, Fortuna, Betclic PL.
Serwer pobiera ten plik z repozytorium przy każdym uruchomieniu (cron co 2 h), więc zmiany wprowadza się tylko w repozytorium.
Wynik trafia do repozytorium przez GitHub API (token w /opt/typer/token).

Czytniki: Fortuna (REST), STS (websocket wss://www.sts.pl/sbk/api/sbk przez przeglądarkę Playwright – python z /opt/typer/pw).
Tryby rozpoznania (--test, --zrzut, --siec, --siec2, --sts) zostają do dalszej pracy nad Betclic PL."""
import os, re, sys, json, time, base64, datetime as dt

REPO = 'lewym90/typer'
TOKEN_PLIK = '/opt/typer/token'
PLIK_WYNIKU = 'docs/data/kursy_vps_test.json'
LIMIT = 240
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/128.0.0.0 Safari/537.36')
START = time.time()

STRONY = {
    'fortuna': ['https://www.efortuna.pl/', 'https://www.efortuna.pl/zaklady-bukmacherskie/pilka-nozna',
                'https://www.efortuna.pl/zaklady-bukmacherskie/tenis'],
    'sts': ['https://www.sts.pl/', 'https://www.sts.pl/pilka-nozna', 'https://www.sts.pl/zaklady-bukmacherskie/pilka-nozna'],
    'betclic': ['https://www.betclic.pl/', 'https://www.betclic.pl/pilka-nozna-s1', 'https://www.betclic.pl/tenis-s2'],
}
URL_ABS = re.compile(r'''["'`](https?://[a-z0-9.\-]+(?:/[^"'`\s<>\\]*)?)["'`]''', re.I)
URL_WZG = re.compile(r'''["'`](/(?:api|rest|offer|oferta|sb-|sportsbook|feed|odds|web/v|v\d/|graphql|ngw|fo-api|live)[^"'`\s<>\\]{1,140})["'`]''', re.I)
CIEKAWE = re.compile(r'api|offer|odds|sport|feed|market|event|prematch|graphql|bet|fixture|match', re.I)
OBRAZ = re.compile(r'\.(png|jpe?g|svg|webp|gif|woff2?|ttf|css|ico|mp4)(\?|$)', re.I)
BLOBY = [r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', r'<script[^>]*id="ng-state"[^>]*>(.*?)</script>',
         r'<script[^>]*id="serverApp-state"[^>]*>(.*?)</script>', r'window\.__([A-Z_]{3,40})__\s*=\s*(\{.*?\});?\s*</script>',
         r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>']
KURS = re.compile(r'(?<![\d.,])(?:1[.,]\d{2}|[2-9][.,]\d{2}|1\d[.,]\d{2})(?![\d])')

def ses():
    import requests
    s = requests.Session()
    s.headers.update({'User-Agent': UA, 'Accept-Language': 'pl-PL,pl;q=0.9,en;q=0.5',
                      'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8'})
    return s

def pobierz(s, url, **kw):
    t0 = time.time()
    try:
        r = s.get(url, timeout=20, **kw)
        return dict(kod=r.status_code, url=r.url, typ=r.headers.get('content-type', '')[:50], rozmiar=len(r.content),
                    ms=int((time.time() - t0) * 1000)), r.text
    except Exception as e:
        return dict(kod=None, blad=f'{type(e).__name__}: {str(e)[:150]}'), ''

def ksztalt(o, g=0):
    if g > 3: return type(o).__name__
    if isinstance(o, dict): return {k: ksztalt(o[k], g + 1) for k in list(o)[:15]}
    if isinstance(o, list): return [len(o), ksztalt(o[0], g + 1) if o else None]
    return type(o).__name__

def rozpoznaj(nazwa, s):
    w = dict(strony=[], bloby=[], adresy=set(), sciezki=set(), skrypty=[], skrypty_przejrzane=0, probki_json=[])
    skr = []
    for url in STRONY[nazwa]:
        meta, txt = pobierz(s, url)
        if txt:
            meta['tytul'] = (re.search(r'<title[^>]*>(.*?)</title>', txt, re.S | re.I) or [None, None])[1]
            meta['liczb_jak_kursy'] = len(KURS.findall(txt))
            meta['poczatek_body'] = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', txt))[:300]
            for wz in BLOBY:
                for m in re.finditer(wz, txt, re.S | re.I):
                    b = m.group(m.lastindex); nazwa_b = m.group(1) if m.lastindex == 2 else wz[:30]
                    item = dict(strona=url, rodzaj=nazwa_b, dlugosc=len(b), poczatek=b[:1500])
                    try: item['ksztalt'] = ksztalt(json.loads(b))
                    except Exception: pass
                    if len(w['bloby']) < 12: w['bloby'].append(item)
            w['adresy'] |= {u for u in URL_ABS.findall(txt) if CIEKAWE.search(u) and not OBRAZ.search(u)}
            w['sciezki'] |= set(URL_WZG.findall(txt))
            baza = re.match(r'https?://[^/]+', meta.get('url') or url).group(0)
            for x in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', txt, re.I):
                x = x if x.startswith('http') else ('https:' + x if x.startswith('//') else baza + '/' + x.lstrip('/'))
                if x not in skr: skr.append(x)
        w['strony'].append(dict(meta, strona=url))
    w['skrypty'] = skr[:40]
    for x in skr[:14]:
        if time.time() - START > LIMIT - 60: break
        meta, txt = pobierz(s, x)
        w['skrypty_przejrzane'] += 1
        if txt:
            w['adresy'] |= {u for u in URL_ABS.findall(txt) if CIEKAWE.search(u) and not OBRAZ.search(u)}
            w['sciezki'] |= set(URL_WZG.findall(txt))
    w['adresy'] = sorted(w['adresy'])[:150]; w['sciezki'] = sorted(w['sciezki'])[:120]
    # próba: adresy wyglądające na API z kursami (bez parametrów wymagających identyfikatorów)
    kand = [u for u in w['adresy'] if re.search(r'api|offer|odds|sportsbook|feed|graphql', u, re.I) and '{' not in u and '$' not in u][:12]
    for u in kand:
        if time.time() - START > LIMIT - 20: break
        meta, txt = pobierz(s, u, headers={'Accept': 'application/json, text/plain, */*'})
        item = dict(meta, adres=u, poczatek=txt[:600])
        try: item['ksztalt'] = ksztalt(json.loads(txt))
        except Exception: pass
        w['probki_json'].append(item)
    return w

def zapisz_github(sciezka, dane, surowy=False):
    try: token = open(TOKEN_PLIK).read().strip()
    except Exception: print('Brak tokenu w', TOKEN_PLIK); return False
    import requests
    h = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'typer-vps'}
    api = f'https://api.github.com/repos/{REPO}/contents/{sciezka}'
    tresc = dane.encode() if surowy else json.dumps(dane, ensure_ascii=False, indent=1).encode()
    for proba in range(3):
        r = requests.get(api, headers=h, timeout=20)
        sha = r.json().get('sha') if r.status_code == 200 else None
        body = dict(message=f'Kursy VPS {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M}', content=base64.b64encode(tresc).decode())
        if sha: body['sha'] = sha
        r = requests.put(api, headers=h, json=body, timeout=30)
        if r.status_code in (200, 201): print('Zapisano w repozytorium:', sciezka); return True
        print('GitHub odpowiedział', r.status_code, r.text[:200]); time.sleep(5)
    return False

SLOWA_JS = re.compile(r'prematch|odds|outcome|selection|market|offer|fixture|betoffer|graphql', re.I)

def zrzut(s, spis):
    """WERSJA 2: surowe strony i skrypty do analizy (katalog surowe/ w repozytorium)."""
    lp = 0
    for nazwa, strony in STRONY.items():
        js, js_widz = [], set()
        for i, url in enumerate(strony[:2]):
            meta, txt = pobierz(s, url)
            if not txt: continue
            plik = f'surowe/{nazwa}_strona{i}.html'
            if zapisz_github(plik, txt, surowy=True): spis.append(dict(plik=plik, url=url, rozmiar=len(txt)))
            baza = re.match(r'https?://[^/]+', meta.get('url') or url).group(0)
            for x in re.findall(r'<(?:script|link)[^>]+(?:src|href)=["\']([^"\']+\.m?js[^"\']*)["\']', txt, re.I):
                x = x if x.startswith('http') else ('https:' + x if x.startswith('//') else baza + '/' + x.lstrip('/'))
                if x not in js_widz: js_widz.add(x); js.append(x)
        zapisane = 0; j = 0
        while j < len(js) and j < 60 and time.time() - START < LIMIT + 300:
            x = js[j]; j += 1
            meta, txt = pobierz(s, x)
            if not txt: continue
            baza = x.rsplit('/', 1)[0]
            for y in re.findall(r'["\']((?:https?://|\.{0,2}/)?[A-Za-z0-9_\-/.]{3,140}\.m?js)["\']', txt)[:300]:
                y = y if y.startswith('http') else (re.match(r'https?://[^/]+', x).group(0) + y if y.startswith('/') else baza + '/' + y.lstrip('./'))
                if y not in js_widz: js_widz.add(y); js.append(y)
            traf = len(SLOWA_JS.findall(txt))
            spis.append(dict(bukmacher=nazwa, js=x, rozmiar=len(txt), trafien=traf))
            if traf >= 15 and len(txt) < 4_000_000 and zapisane < 6:
                plik = f'surowe/{nazwa}_js{zapisane}.js'
                if zapisz_github(plik, txt, surowy=True): spis[-1]['plik'] = plik; zapisane += 1
        lp += 1

STRONY_SIEC = {
    'sts': ['https://www.sts.pl/pilka-nozna', 'https://www.sts.pl/tenis'],
    'fortuna': ['https://www.efortuna.pl/zaklady-bukmacherskie/pilka-nozna', 'https://www.efortuna.pl/zaklady-bukmacherskie/tenis'],
    'betclic': ['https://www.betclic.pl/pilka-nozna-sfootball', 'https://www.betclic.pl/tenis-stennis'],
}

def siec():
    """WERSJA 3: prawdziwa przeglądarka (Chromium) – zapisuje, skąd strona pobiera dane (zapytania i odpowiedzi JSON, websockety)."""
    from playwright.sync_api import sync_playwright
    spis = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        for nazwa, strony in STRONY_SIEC.items():
            ctx = br.new_context(locale='pl-PL', user_agent=UA, viewport={'width': 1366, 'height': 900})
            pg = ctx.new_page()
            odp, ws = [], []
            def na_odp(r, odp=odp):
                try:
                    typ = r.headers.get('content-type', '')
                    if r.request.resource_type in ('image', 'font', 'stylesheet', 'media'): return
                    if 'json' not in typ and 'text/plain' not in typ and 'protobuf' not in typ and 'grpc' not in typ: return
                    b = r.body()
                    odp.append(dict(url=r.url, metoda=r.request.method, kod=r.status, typ=typ[:40], rozmiar=len(b),
                                    post=(r.request.post_data or '')[:800], kursy=len(KURS.findall(b[:3_000_000].decode('utf-8', 'ignore'))),
                                    tresc=b[:400_000].decode('utf-8', 'ignore')))
                except Exception as e: pass
            def na_ws(w, ws=ws):
                item = dict(url=w.url, ramki=[])
                ws.append(item)
                w.on('framereceived', lambda f, item=item: len(item['ramki']) < 15 and item['ramki'].append(str(f)[:3000]))
                w.on('framesent', lambda f, item=item: len(item['ramki']) < 15 and item['ramki'].append('WYSLANE: ' + str(f)[:1500]))
            pg.on('response', na_odp); pg.on('websocket', na_ws)
            for url in strony:
                try:
                    pg.goto(url, wait_until='domcontentloaded', timeout=45000)
                    for _ in range(4):
                        pg.wait_for_timeout(3500); pg.mouse.wheel(0, 2500)
                    try:
                        tekst = pg.inner_text('body')[:20000]
                    except Exception: tekst = ''
                    spis.append(dict(bukmacher=nazwa, strona=url, tekst_strony=tekst[:6000]))
                except Exception as e:
                    spis.append(dict(bukmacher=nazwa, strona=url, blad=str(e)[:200]))
            ctx.close()
            odp.sort(key=lambda x: (-x['kursy'], -x['rozmiar']))
            for i, o in enumerate(odp[:8]):
                if o['kursy'] >= 5:
                    plik = f'surowe/{nazwa}_xhr{i}.txt'
                    if zapisz_github(plik, f"{o['metoda']} {o['url']}\nPOST: {o['post']}\n\n" + o['tresc'], surowy=True): o['plik'] = plik
            spis.append(dict(bukmacher=nazwa, zapytania=[{k: v for k, v in o.items() if k != 'tresc'} for o in odp[:80]],
                             websockety=ws[:6]))
            print(nazwa, 'gotowe:', len(odp), 'odpowiedzi JSON,', len(ws), 'websocketów', round(time.time() - START), 's')
        br.close()
    zapisz_github('surowe/siec.json', dict(czas=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), wyniki=spis))

LINK_MECZU = {'fortuna': r'/zaklady-bukmacherskie/pilka-nozna/[^/?#]+/[^/?#]+/[^/?#]+',
              'sts': r'/pilka-nozna/[^?#]*/[^?#]*/[^?#]*\d', 'betclic': r'-m\d{4,}'}

def siec2():
    """WERSJA 4: lista meczów + strona jednego meczu u każdego bukmachera; pełne ramki websocketów STS, dane strony Betclic."""
    from playwright.sync_api import sync_playwright
    spis = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        for nazwa in ('fortuna', 'betclic', 'sts'):
            ctx = br.new_context(locale='pl-PL', user_agent=UA, viewport={'width': 1366, 'height': 900})
            pg = ctx.new_page()
            stan = dict(etap='lista', odp=[], ramki=[])
            def na_odp(r, stan=stan):
                try:
                    typ = r.headers.get('content-type', '')
                    if r.request.resource_type in ('image', 'font', 'stylesheet', 'media', 'script'): return
                    if not any(x in typ for x in ('json', 'text/plain', 'proto', 'grpc')): return
                    if not re.search(r'efortuna|sts\.pl|begmedia|betclic', r.url): return
                    b = r.body()
                    stan['odp'].append(dict(etap=stan['etap'], url=r.url, metoda=r.request.method, rozmiar=len(b), typ=typ[:40],
                                            tresc=b[:300_000].decode('utf-8', 'ignore')))
                except Exception: pass
            def na_ws(w, stan=stan):
                if 'sbk/api/sbk' not in w.url and 'ws-offer' not in w.url: return
                w.on('framereceived', lambda f, stan=stan: len(stan['ramki']) < 400 and stan['ramki'].append(dict(etap=stan['etap'], k='<', r=str(f)[:60000])))
                w.on('framesent', lambda f, stan=stan: len(stan['ramki']) < 400 and stan['ramki'].append(dict(etap=stan['etap'], k='>', r=str(f)[:3000])))
            pg.on('response', na_odp); pg.on('websocket', na_ws)
            wynik = dict(bukmacher=nazwa)
            try:
                pg.goto(STRONY_SIEC[nazwa][0], wait_until='domcontentloaded', timeout=45000)
                for _ in range(3): pg.wait_for_timeout(3000); pg.mouse.wheel(0, 2500)
                ng = pg.evaluate("() => { const e = document.getElementById('ng-state'); return e ? e.textContent : '' }")
                if ng: zapisz_github(f'surowe/{nazwa}_ngstate_lista.json', ng[:3_000_000], surowy=True); wynik['ngstate_lista'] = len(ng)
                linki = pg.evaluate("() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)")
                mecze = [l for l in linki if re.search(LINK_MECZU[nazwa], l)]
                wynik['linki_meczow'] = mecze[:15]; wynik['linkow'] = len(linki)
                if not mecze: wynik['linki_przyklad'] = linki[:120]
                if mecze:
                    stan['etap'] = 'mecz'
                    pg.goto(mecze[0], wait_until='domcontentloaded', timeout=45000)
                    for _ in range(3): pg.wait_for_timeout(3000); pg.mouse.wheel(0, 2000)
                    ng = pg.evaluate("() => { const e = document.getElementById('ng-state'); return e ? e.textContent : '' }")
                    if ng: zapisz_github(f'surowe/{nazwa}_ngstate_mecz.json', ng[:3_000_000], surowy=True); wynik['ngstate_mecz'] = len(ng)
                    wynik['mecz_tekst'] = pg.inner_text('body')[:3000]
            except Exception as e: wynik['blad'] = str(e)[:300]
            ctx.close()
            wynik['zapytania'] = [{k: v for k, v in o.items() if k != 'tresc'} for o in stan['odp']][:150]
            # odpowiedzi ze strony meczu i największe z listy
            wybrane = [o for o in stan['odp'] if o['etap'] == 'mecz'] + sorted([o for o in stan['odp'] if o['etap'] == 'lista'], key=lambda o: -o['rozmiar'])[:4]
            tekst = '\n\n=====\n'.join(f"[{o['etap']}] {o['metoda']} {o['url']} ({o['rozmiar']} B)\n{o['tresc'][:120000]}" for o in wybrane[:14])
            if tekst: zapisz_github(f'surowe/{nazwa}_odp.txt', tekst[:4_000_000], surowy=True)
            if stan['ramki']:
                zapisz_github(f'surowe/{nazwa}_ws.txt', '\n\n'.join(f"[{x['etap']}] {x['k']} {x['r']}" for x in stan['ramki'])[:5_000_000], surowy=True)
            wynik['ramek'] = len(stan['ramki'])
            spis.append(wynik)
            print(nazwa, 'gotowe', round(time.time() - START), 's')
        br.close()
    zapisz_github('surowe/siec2.json', dict(czas=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), wyniki=spis))

# ======================================================================= CZYTNIK (wersja 1: Fortuna)
RAW = f'https://raw.githubusercontent.com/{REPO}/main'
FAPI = 'https://api.efortuna.pl/offer'
KATALOG = '/opt/typer/dane'

def _przygotuj(s):
    """Pobiera z repozytorium nasze listy meczów i moduł dopasowania (ten sam co dla Superbetu)."""
    os.makedirs(KATALOG, exist_ok=True)
    try: token = open(TOKEN_PLIK).read().strip()
    except Exception: token = None
    for plik in ('typer/kursy_pl.py', 'typer/nazwy.py', 'docs/data/dzis.json', 'docs/data/inne.json', 'docs/data/lista_vps.json'):
        cel = os.path.join(KATALOG, os.path.basename(plik))
        if token:   # API GitHuba – bez opóźnienia pamięci podręcznej (raw bywa nieaktualne do 5 min)
            r = s.get(f'https://api.github.com/repos/{REPO}/contents/{plik}', timeout=20,
                      headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github.raw', 'User-Agent': 'typer-vps'})
        else: r = s.get(f'{RAW}/{plik}?t={int(time.time())}', timeout=20)
        if plik.endswith('lista_vps.json') and r.status_code == 404:
            try: os.remove(cel)
            except Exception: pass
            continue
        r.raise_for_status()
        open(cel, 'wb').write(r.content)
    sys.path.insert(0, KATALOG)
    import kursy_pl as KP
    KP.OUT = KATALOG
    return KP

def _id_w(o, prefiks, wyn):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == 'id' and isinstance(v, str) and v.startswith(prefiks): wyn.append((v, o.get('name')))
            else: _id_w(v, prefiks, wyn)
    elif isinstance(o, list):
        for v in o: _id_w(v, prefiks, wyn)
    return wyn

def fortuna_mecze(s, diag):
    sporty = _id_w(s.get(f'{FAPI}/structure/api/v1_0/sports?timeFilter=all', timeout=20).json(), 'ufo:sprt:', [])
    diag['sporty'] = sporty[:40]
    ids = {}
    for sid, nazwa in sporty:
        n = (nazwa or '').lower()
        if 'piłka nożna' == n or n.startswith('piłka nożna'): ids.setdefault('pilka', sid)
        if n == 'tenis': ids.setdefault('tenis', sid)
        if n in ('mma', 'boks', 'sporty walki'): ids.setdefault(n, sid)
    ids.setdefault('pilka', 'ufo:sprt:00')
    diag['sporty_uzyte'] = ids
    mecze, turnieje, nazwy_tur = {}, set(), {}
    for sp, sid in ids.items():
        for filtr in ('today', 'tomorrow'):
            try:
                j = s.get(f'{FAPI}/structure/api/v1_0/sport/{sid}/tournaments?categories=true&timeFilter={filtr}', timeout=20).json()
                for tid, tn in _id_w(j, 'ufo:tour:', []): turnieje.add((sp, tid)); nazwy_tur[tid] = tn or ''
            except Exception as e: diag.setdefault('bledy', []).append(f'turnieje {sid} {filtr}: {e}'[:120])
    diag['turniejow'] = len(turnieje)
    for sp, tid in sorted(turnieje):
        if time.time() - START > 420: diag.setdefault('bledy', []).append('limit czasu (turnieje)'); break
        try:
            j = s.get(f'{FAPI}/structure/api/v1_0/tournament/{tid}/matches?timeFilter=all', timeout=20).json()
        except Exception as e:
            diag.setdefault('bledy', []).append(f'mecze {tid}: {e}'[:120]); continue
        for f in j.get('fixtures') or []:
            if f.get('kind') != 'PREMATCH': continue
            u = {p.get('type'): p.get('name') for p in f.get('participants') or []}
            h, a = u.get('HOME'), u.get('AWAY')
            if not (h and a):
                cz = re.split(r'\s+-\s+', f.get('name') or '')
                if len(cz) == 2: h, a = cz
            if h and a and f.get('startDatetime'):
                mecze[f['id']] = dict(id=f['id'], sp=sp, h=h, a=a, t=dt.datetime.fromtimestamp(f['startDatetime'] / 1000, dt.timezone.utc),
                                      tur=nazwy_tur.get(tid, ''))
        time.sleep(0.15)
    diag['meczow_fortuny'] = len(mecze)
    return list(mecze.values())

def _fortuna_klucze(rynki, odwr, sport, bo=3):
    k = {}
    for m in rynki or []:
        n = (m.get('marketTypeName') or m.get('name') or '').lower()
        for o in m.get('outcomes') or []:
            try: c = float(o.get('odds') or 0)
            except Exception: continue
            if c <= 1.0 or o.get('displayType', 'OPEN') != 'OPEN': continue
            on = str(o.get('name') or '').strip()
            if sport == 'pilka':
                if n == 'wynik meczu' and on in ('1', '0', '2'): k.setdefault({'1': '1', '0': 'X', '2': '2'}[on], c)
                elif n == 'mecz: dwójtyp' and on in ('10', '02', '12'): k.setdefault({'10': '1X', '02': 'X2', '12': '12'}[on], c)
                elif 'obie drużyny strzelą' in n and 'połow' not in n and ';' not in n:
                    if on.lower() == 'tak': k.setdefault('BTTS Tak', c)
                    elif on.lower() == 'nie': k.setdefault('BTTS Nie', c)
                elif re.fullmatch(r'(mecz: )?(liczba goli|gole|suma goli)( w meczu)?', n):
                    mm = re.search(r'([+-]|powyżej|poniżej)\s*(\d+[.,]5)', on.lower())
                    if mm: k.setdefault(('Over ' if mm.group(1) in ('+', 'powyżej') else 'Under ') + mm.group(2).replace(',', '.'), c)
            else:
                pierwszy = lambda nr: ('A' if (nr == '1') != odwr else 'B')
                if (n.startswith('zwycięzca meczu') or n in ('wynik meczu', 'zwycięzca', 'mecz')) and 'zwrot jeżeli' not in n and on in ('1', '2'):
                    k.setdefault(pierwszy(on), c)
                elif n.startswith('mecz: handicap setowy'):
                    mm = re.fullmatch(r'([12])\s*\(([+-]1[.,]5)\)', on)
                    if mm:
                        kto, h = pierwszy(mm.group(1)), mm.group(2).replace(',', '.')
                        if h == '-1.5': k.setdefault(f'{kto} -1.5', c)
                        elif int(bo or 3) == 3: k.setdefault(f'{kto} min. 1 set', c)
                        else: k.setdefault(f'{kto} +1.5', c)
    return k

# ---------------------------------------------------------------- KSW (Pinnacle nie wystawia – kursy tylko w Polsce)
def _czy_ksw(nazwa): return bool(re.search(r'\bksw\b|konfrontacja sztuk walki', str(nazwa or ''), re.I))

def ksw_fortuna(s, oferta, diag):
    """Wszystkie walki KSW z oferty Fortuny (dziś i jutro): zawodnicy, start, zwycięzca 1/2."""
    out = []
    for f in oferta:
        if f['sp'] in ('pilka', 'tenis') or not _czy_ksw(f.get('tur')): continue
        try:
            j = s.get(f'{FAPI}/markets/api/v1_0/fixtures/markets/overview', params={'fixtureIds': f['id']}, timeout=20).json()
            k = _fortuna_klucze(j.get(f['id']) or [], False, 'duel')
        except Exception as e:
            diag['bledy'].append(f'KSW Fortuna {f["id"]}: {e}'[:120]); continue
        if k.get('A') and k.get('B'):
            out.append(dict(a=f['h'], b=f['a'], t=f['t'].isoformat(), gala=_gala(f.get('tur')), kursy=dict(fortuna=dict(A=k['A'], B=k['B']))))
        time.sleep(0.2)
    return out

def _gala(nazwa):
    m = re.search(r'ksw\s*(\d+)', str(nazwa or ''), re.I)
    return f'KSW {m.group(1)}' if m else 'KSW'

def scal_ksw(fortuna, sts):
    """Łączy walki KSW z Fortuny i STS (te same nazwiska, start do 12 h różnicy). Zwraca listę walk z kursami obu bukmacherów."""
    import kursy_pl as KP
    out = [dict(w, kursy=dict(w['kursy'])) for w in fortuna]
    for w in sts:
        t = dt.datetime.fromisoformat(w['t'])
        best = None
        for x in out:
            if abs((dt.datetime.fromisoformat(x['t']) - t).total_seconds()) > 12 * 3600: continue
            s1 = min(KP.podobne_w(x['a'], w['a']), KP.podobne_w(x['b'], w['b'])); s2 = min(KP.podobne_w(x['a'], w['b']), KP.podobne_w(x['b'], w['a']))
            sc, odwr = (s1, False) if s1 >= s2 else (s2, True)
            if sc >= 0.55 and (best is None or sc > best[1]): best = (x, sc, odwr)
        k = w['kursy']['sts']
        if best:
            x, _, odwr = best
            x['kursy']['sts'] = dict(A=k['B'], B=k['A']) if odwr else dict(k)
            if w.get('gala') != 'KSW' and x.get('gala') == 'KSW': x['gala'] = w['gala']
        else: out.append(w)
    return out

def czytnik(KP=None):
    s = ses(); diag = dict(bledy=[]); wynik = {}; lista = None
    try:
        KP = KP or _przygotuj(s)
        try: lista = json.load(open(os.path.join(KATALOG, 'lista_vps.json'))).get('podpis')
        except Exception: lista = None
        nasze = KP.nasze_mecze(z_listy=True)
        diag['nasze_mecze'] = len(nasze)
        oferta = fortuna_mecze(s, diag)
        rynki_nazwy = {}
        for sp, eid, h, a, start, bo in nasze:
            t0 = KP._utc_nasz(start); tol = 35 if sp == 'pilka' else 360
            best = None
            for f in oferta:
                if (f['sp'] == 'pilka') != (sp == 'pilka'): continue
                if abs((f['t'] - t0).total_seconds()) / 60 > tol: continue
                s1 = min(KP.podobne_w(h, f['h']), KP.podobne_w(a, f['a']))
                s2 = min(KP.podobne_w(h, f['a']), KP.podobne_w(a, f['h'])) if sp != 'pilka' else 0
                sc, odwr = (s1, False) if s1 >= s2 else (s2, True)
                if sc >= 0.55 and (best is None or sc > best[1]): best = (f, sc, odwr)
            if not best: diag.setdefault('niedopasowane', []).append(f'{sp}: {h} – {a}'); continue
            f, sc, odwr = best
            try:
                j = s.get(f'{FAPI}/markets/api/v1_0/fixtures/markets/overview', params={'fixtureIds': f['id']}, timeout=20).json()
                rynki = j.get(f['id']) or []
            except Exception as e:
                diag['bledy'].append(f'kursy {f["id"]}: {e}'[:120]); continue
            for m in rynki:
                rn = m.get('marketTypeName') or m.get('name')
                if rn and len(rynki_nazwy) < 60: rynki_nazwy.setdefault(rn, [o.get('name') for o in (m.get('outcomes') or [])][:4])
            k = _fortuna_klucze(rynki, odwr, 'pilka' if sp == 'pilka' else 'duel', bo)
            if not k: diag.setdefault('bez_kursow', []).append(f'{sp}: {h} – {a} ({f["h"]} - {f["a"]})')
            if k: wynik[eid] = dict(fortuna=dict(id=f['id'], nazwa=f'{f["h"]} - {f["a"]}', zgodnosc=round(sc, 2), kursy=k))
            time.sleep(0.2)
        diag['rynki_nazwy'] = rynki_nazwy
        ksw_f = ksw_fortuna(s, oferta, diag)
    except Exception as e:
        diag['bledy'].append(f'{type(e).__name__}: {e}'[:200]); ksw_f = []
    ile_fortuna = len(wynik)
    sts, diag_sts = sts_z_przegladarki() if os.path.isdir(KATALOG) else ({}, dict(bledy=['brak danych']))
    for eid, v in sts.items(): wynik.setdefault(eid, {})['sts'] = v
    diag['sts'] = diag_sts
    try: ksw = scal_ksw(ksw_f, diag_sts.pop('ksw', []) if isinstance(diag_sts, dict) else [])
    except Exception as e: diag['bledy'].append(f'KSW: {e}'[:160]); ksw = []
    diag['ksw'] = dict(fortuna=len(ksw_f), razem=len(ksw))
    dane = dict(czas=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), wersja='czytnik-2',
                bukmacherzy=dict(fortuna=dict(ok=not diag['bledy'] or bool(ile_fortuna), dopasowane=ile_fortuna),
                                 sts=dict(ok=not diag_sts.get('bledy') or bool(sts), dopasowane=len(sts))),
                mecze=wynik, ksw=ksw, diag=diag, lista=lista, sekund=round(time.time() - START))
    print('Fortuna: dopasowane', ile_fortuna, 'z', diag.get('nasze_mecze'), '| błędy:', diag['bledy'][:3])
    print('STS: dopasowane', len(sts), '| błędy:', (diag_sts.get('bledy') or [])[:3])
    return zapisz_github('docs/data/kursy_vps.json', dane)

STAN_CRON = '/opt/typer/stan_cron.json'

def tryb_cron():
    """Cron co kilka minut: pełny odczyt kursów tylko gdy zmieniła się lista meczów (np. nowe typy rano – liczenie
    na GitHubie czeka na serwer) albo minęło ~110 min od ostatniego. Inaczej kończy w kilka sekund."""
    import fcntl
    blokada = open('/opt/typer/cron.lock', 'w')
    try: fcntl.flock(blokada, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: return            # poprzedni odczyt jeszcze trwa
    try: stan = json.load(open(STAN_CRON))
    except Exception: stan = {}
    try:
        from zoneinfo import ZoneInfo; teraz = dt.datetime.now(ZoneInfo('Europe/Warsaw'))
    except Exception: teraz = dt.datetime.now(dt.timezone(dt.timedelta(hours=2)))
    s = ses()
    try: KP = _przygotuj(s)
    except Exception as e: print(teraz.strftime('%H:%M'), 'cron: brak danych z GitHuba:', e); return
    nasze = KP.nasze_mecze(z_listy=True)
    podpis = KP.lista_podpis(nasze)
    try: lista = json.load(open(os.path.join(KATALOG, 'lista_vps.json'))).get('podpis')
    except Exception: lista = None
    minut = (time.time() - stan.get('czas', 0)) / 60
    zmiana = podpis != stan.get('podpis') or lista != stan.get('lista')
    if not zmiana and (minut < 110 or teraz.hour < 7): return
    print(teraz.strftime('%Y-%m-%d %H:%M'), 'cron:', 'nowa lista meczów' if zmiana else f'{round(minut)} min od ostatniego odczytu')
    if czytnik(KP):
        stan.update(podpis=podpis, lista=lista, czas=time.time())
        json.dump(stan, open(STAN_CRON, 'w'))
    # raz dziennie (po 9:00) rozpoznanie pełnej oferty meczu Fortuny – do dalszej pracy nad golami
    if teraz.hour >= 9 and stan.get('rozpoznanie') != teraz.strftime('%Y-%m-%d'):
        stan['rozpoznanie'] = teraz.strftime('%Y-%m-%d'); json.dump(stan, open(STAN_CRON, 'w'))
        import subprocess
        try: subprocess.run([PW_PYTHON if os.path.exists(PW_PYTHON) else sys.executable, os.path.abspath(__file__), '--fortuna-mecz'], timeout=400)
        except Exception as e: print('rozpoznanie Fortuny:', e)

# ======================================================================= CZYTNIK STS (websocket, przez przeglądarkę)
STS_WS = 'wss://www.sts.pl/sbk/api/sbk'
STS_SPORTY = {'1': 'pilka', '3': 'tenis', '166': 'walki', '19': 'walki'}   # piłka, tenis, MMA, boks
PW_PYTHON = '/opt/typer/pw/bin/python'
STS_WYNIK = '/opt/typer/sts_wynik.json'
_JS_SZCZEGOLY = """async ({ids, ms}) => await new Promise(res => {
  const out = []; let rozm = 0, ws, zamkn = false;
  const koniec = (x) => { if (zamkn) return; zamkn = true; try { ws.close(); } catch (e) {} res(Object.assign({out}, x || {})); };
  const dodaj = (t) => { if (typeof t !== 'string' || t.startsWith('{"s":"i_pl"') || t.startsWith('{"t":5')) return;
                         if (rozm < 6e6) { out.push(t); rozm += t.length; } };
  try { ws = new WebSocket('""" + STS_WS + """'); } catch (e) { res({out, blad: String(e)}); return; }
  ws.onopen = () => {
    ws.send(JSON.stringify({t: 1, u: [{s: 'i_pl', n: 0}]}));
    setTimeout(() => ws.send(JSON.stringify({t: 1, u: [{s: 'i_pl'}].concat(ids.map(i => ({s: 'f_' + i + '_pl', n: 0})))})), 2500);
    setTimeout(koniec, ms);
  };
  ws.onmessage = (e) => { if (typeof e.data === 'string') dodaj(e.data); else if (e.data && e.data.text) e.data.text().then(dodaj); };
  ws.onerror = () => out.push('BLAD_WS');
  setTimeout(() => koniec({limit: true}), ms + 10000);
})"""

def _sts_wiadomosc(tekst):
    """Ramka STS = nagłówek JSON + '\n' + treść JSON. Zwraca (nagłówek, treść)."""
    if not isinstance(tekst, str): tekst = tekst.decode('utf-8', 'ignore')
    nag, _, tresc = tekst.partition('\n')
    try: nag = json.loads(nag)
    except Exception: nag = {}
    try: tresc = json.loads(tresc) if tresc.strip() else None
    except Exception: tresc = None
    return nag, tresc

def _scal(cel, zrodlo):
    """Scalanie aktualizacji STS (None = usunięcie)."""
    for k, v in (zrodlo or {}).items():
        if v is None: cel.pop(k, None)
        elif isinstance(v, dict) and isinstance(cel.get(k), dict): _scal(cel[k], v)
        else: cel[k] = v
    return cel

def sts_mecze(snap):
    """Z migawki i_pl: lista meczów [dict(id, sp, h, a, t, klucze_cen)] i opisy rynków sportów."""
    mecze, opisy = [], {}
    for sid, sport in ((snap.get('B') or {}).get('S') or {}).items():
        if sid not in STS_SPORTY: continue
        opisy[sid] = sport.get('m') or {}
        for kat in (sport.get('C') or {}).values():
            for tur in (kat.get('T') or {}).values():
                for fid, f in (tur.get('FX') or {}).items():
                    if f.get('ft') != 'm' or not f.get('H') or not f.get('A') or not f.get('t'): continue
                    try: t = dt.datetime.fromisoformat(f['t'].replace('Z', '+00:00'))
                    except Exception: continue
                    mecze.append(dict(id=fid, sid=sid, sp=STS_SPORTY[sid], h=f['H'].get('n'), a=f['A'].get('n'), t=t,
                                      turniej=f"{kat.get('n', '')} / {tur.get('n', '')}", ceny=list((f.get('a') or {}).keys())))
    return mecze, opisy

def _liczba_ou(tekst):
    """'+2.5' / 'powyżej 2.5' → ('Over', '2.5'); '-2.5' / 'poniżej 2.5' → ('Under', '2.5')."""
    t = str(tekst or '').strip().lower()
    m = re.search(r'(\d+)[.,]5', t)
    if not m: return None, None
    ln = m.group(1) + '.5'
    if t.startswith('+') or 'powyżej' in t or 'więcej' in t or 'over' in t: return 'Over', ln
    if t.startswith('-') or 'poniżej' in t or 'mniej' in t or 'under' in t: return 'Under', ln
    return None, ln

def _liczba_ou_linia(nazwa, linia):
    """Jak _liczba_ou, a gdy w nazwie wyniku brak liczby (np. 'powyżej'), liczba z nazwy linii."""
    ou, ln = _liczba_ou(nazwa)
    if ou and ln: return ou, ln
    t = str(nazwa or '').strip().lower()
    _, ln2 = _liczba_ou((linia or {}).get('n'))
    kier = 'Over' if (t in ('+', 'powyżej', 'więcej', 'over') or t.startswith('powyżej')) else \
           'Under' if (t in ('-', 'poniżej', 'mniej', 'under') or t.startswith('poniżej')) else None
    return (kier, ln2) if kier and ln2 else (None, None)

def sts_klucze(rynki, opis, sp, odwr, bo=3):
    """Rynki STS jednego meczu → nasze klucze. rynki = {id_rynku: {'l': {linia: {'n', 'o': {id: {'O', 'n'}}}}}}."""
    k = {}
    def nazwa_wyn(mid, oid, o):
        return str(o.get('n') or (((opis.get(mid) or {}).get('o') or {}).get(oid) or {}).get('n') or '').strip()
    for mid, m in (rynki or {}).items():
        if not isinstance(m, dict): continue
        for lid, linia in (m.get('l') or {}).items():
            if not isinstance(linia, dict): continue
            for oid, o in (linia.get('o') or {}).items():
                if not isinstance(o, dict): continue
                try: c = float(o.get('O') or 0)
                except Exception: continue
                if c <= 1.0: continue
                n = nazwa_wyn(mid, oid, o); nl = n.lower()
                if sp == 'pilka':
                    if mid == '1' and n in ('1', 'X', '2'): k.setdefault(n, c)
                    elif mid == '10' and n.replace(' ', '') in ('1X', 'X2', '12'): k.setdefault(n.replace(' ', ''), c)
                    elif mid == '43':
                        if nl == 'tak': k.setdefault('BTTS Tak', c)
                        elif nl == 'nie': k.setdefault('BTTS Nie', c)
                    elif mid == '25':
                        ou, ln = _liczba_ou_linia(n, linia)
                        if ou: k.setdefault(f'{ou} {ln}', c)
                    elif mid in ('28', '31'):
                        ou, ln = _liczba_ou_linia(n, linia)
                        if ou == 'Over': k.setdefault(f"{'H' if mid == '28' else 'A'} o{ln}", c)
                else:
                    pierwszy = lambda nr: ('A' if (nr == 1) != odwr else 'B')
                    if mid == '259' and oid in ('4', '5'): k.setdefault(pierwszy(1 if oid == '4' else 2), c)
                    elif sp == 'tenis' and mid in ('275', '276') and nl == 'tak': k.setdefault(pierwszy(1 if mid == '275' else 2) + ' min. 1 set', c)
                    elif sp == 'tenis' and mid in ('285', '286'):
                        mm = re.fullmatch(r'(\d):(\d)', n)
                        if mm:
                            x, y = int(mm.group(1)), int(mm.group(2))
                            kto = pierwszy(1 if x > y else 2); kl = f'{kto} {max(x, y)}:{min(x, y)}'
                            k.setdefault(kl, c)
                            if int(bo or 3) == 3 and min(x, y) == 0: k.setdefault(f'{kto} -1.5', c)
                    elif sp == 'tenis' and mid == '479':
                        ou, ln = _liczba_ou_linia(n, linia)
                        if ou: k.setdefault(f"{'Ponad' if ou == 'Over' else 'Poniżej'} {ln} seta", c)
    return k

def _opis_rynkow(rynki, opis, ile=40):
    """Skrót rynków meczu do diagnostyki: 'id nazwa': ['linia | wynik=kurs', ...]."""
    wyn = {}
    for mid, m in (rynki or {}).items():
        if not isinstance(m, dict) or not m.get('l') or len(wyn) >= ile: continue
        el = []
        for lid, linia in list((m.get('l') or {}).items())[:3]:
            for oid, o in list(((linia or {}).get('o') or {}).items())[:4]:
                if isinstance(o, dict):
                    el.append(f"{(linia or {}).get('n', '')} | {oid}:{o.get('n') or ((opis.get(mid) or {}).get('o') or {}).get(oid, {}).get('n', '')}={o.get('O')}")
        wyn[f"{mid} {(opis.get(mid) or {}).get('n', '')}"] = el[:8]
    return wyn

def sts_kursy():
    """Uruchamiane pythonem z przeglądarką (pw): migawka oferty STS + szczegóły naszych meczów → STS_WYNIK."""
    from playwright.sync_api import sync_playwright
    sys.path.insert(0, KATALOG)
    import kursy_pl as KP
    KP.OUT = KATALOG
    diag = dict(bledy=[]); wynik = {}
    try:
        nasze = KP.nasze_mecze(z_listy=True)
        migawki = []
        with sync_playwright() as pw:
            br = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            pg = br.new_context(locale='pl-PL', user_agent=UA).new_page()
            def na_ws(w):
                if 'sbk/api/sbk' not in w.url: return
                w.on('framereceived', lambda f: migawki.append(f) if str(f)[:40].startswith('{"s":"i_pl"') and '"f":1' in str(f)[:80] else None)
            pg.on('websocket', na_ws)
            pg.goto('https://www.sts.pl/pilka-nozna', wait_until='domcontentloaded', timeout=60000)
            for _ in range(40):
                if migawki: break
                pg.wait_for_timeout(500)
            if not migawki: raise RuntimeError('brak migawki oferty (i_pl) w 20 s')
            _, snap = _sts_wiadomosc(migawki[-1])
            mecze, opisy = sts_mecze(snap or {})
            ceny = (snap or {}).get('P') or {}
            diag['meczow_sts'] = len(mecze)
            diag['sporty'] = {sid: sum(1 for m in mecze if m['sid'] == sid) for sid in STS_SPORTY}
            ksw = []   # walki KSW: zwycięzca z migawki oferty
            for f in mecze:
                if f['sp'] != 'walki' or not _czy_ksw(f.get('turniej')): continue
                rynki = {}
                for kl in f['ceny']:
                    for mid, mm in (((ceny.get(kl) or {}).get('m')) or {}).items():
                        if isinstance(mm, dict) and mm.get('l'): rynki[mid] = mm
                try: k = sts_klucze(rynki, opisy.get(f['sid']) or {}, 'walki', False)
                except Exception: k = {}
                if k.get('A') and k.get('B'):
                    ksw.append(dict(a=f['h'], b=f['a'], t=f['t'].isoformat(), gala=_gala(f.get('turniej')), kursy=dict(sts=dict(A=k['A'], B=k['B']))))
            diag['ksw'] = ksw
            dopas = []
            for sp, eid, h, a, start, bo in nasze:
                t0 = KP._utc_nasz(start); tol = {'pilka': 35, 'tenis': 360, 'walki': 720}[sp]
                best = None
                for f in mecze:
                    if f['sp'] != sp or abs((f['t'] - t0).total_seconds()) / 60 > tol: continue
                    s1 = min(KP.podobne_w(h, f['h']), KP.podobne_w(a, f['a']))
                    s2 = min(KP.podobne_w(h, f['a']), KP.podobne_w(a, f['h'])) if sp != 'pilka' else 0
                    sc, odwr = (s1, False) if s1 >= s2 else (s2, True)
                    if sc >= 0.55 and (best is None or sc > best[1]): best = (f, sc, odwr)
                if best: dopas.append((sp, eid, h, a, bo) + best)
                else: diag.setdefault('niedopasowane', []).append(f'{sp}: {h} – {a}')
            # szczegóły (pełna oferta meczu) – własne połączenie z tej samej strony
            szczeg = {}
            if dopas:
                try:
                    r = pg.evaluate(_JS_SZCZEGOLY, dict(ids=[d[5]['id'] for d in dopas], ms=20000))
                    diag['szczegoly_ramek'] = len(r.get('out') or [])
                    if r.get('blad') or r.get('limit'): diag['bledy'].append(f"szczegóły: {r.get('blad') or 'limit czasu'}")
                    tematy = {}
                    for t in r.get('out') or []:
                        nag, tresc = _sts_wiadomosc(t)
                        tematy[str(nag.get('s'))] = tematy.get(str(nag.get('s')), 0) + 1
                        if isinstance(tresc, dict) and isinstance(tresc.get('P'), dict):
                            for kl, v in tresc['P'].items():
                                if isinstance(v, dict): _scal(szczeg.setdefault(kl, {}), v)
                    diag['szczegoly_tematy'] = dict(list(tematy.items())[:20])
                except Exception as e: diag['bledy'].append(f'szczegóły: {type(e).__name__}: {e}'[:160])
            br.close()
        przyklady = {}
        for sp, eid, h, a, bo, f, sc, odwr in dopas:
            rynki = {}
            def dodaj_rynki(mm):                                # tylko rynki z kursami; puste/null nie kasują tego, co już jest
                for mid, m in (mm or {}).items():
                    if isinstance(m, dict) and m.get('l'): rynki[mid] = m
            for kl in f['ceny']: dodaj_rynki((ceny.get(kl) or {}).get('m'))
            klucze_sz = [kl for kl, v in szczeg.items() if kl in f['ceny'] or (isinstance(v, dict) and v.get('f') == f['id'])]
            for kl in klucze_sz: dodaj_rynki((szczeg.get(kl) or {}).get('m'))
            diag.setdefault('szczegoly_meczow', {})[f"{f['h']} - {f['a']}"[:50]] = \
                {kl[:14]: sum(1 for m in ((szczeg[kl] or {}).get('m') or {}).values() if isinstance(m, dict) and m.get('l')) for kl in klucze_sz}
            k = sts_klucze(rynki, opisy.get(f['sid']) or {}, sp, odwr, bo)
            if len(przyklady) < 3 and sum(1 for m in rynki.values() if isinstance(m, dict) and m.get('l')) > 1:
                przyklady[f"{f['h']} - {f['a']}"] = _opis_rynkow(rynki, opisy.get(f['sid']) or {})
            if k: wynik[eid] = dict(id=f['id'], nazwa=f"{f['h']} - {f['a']}", zgodnosc=round(sc, 2), kursy=k)
            else: diag.setdefault('bez_kursow', []).append(f"{sp}: {h} – {a} ({f['h']} - {f['a']})")
        diag['rynki_przyklad'] = przyklady
        diag['z_wieloma_rynkami'] = sum(1 for v in wynik.values() if len(v['kursy']) > 3)
    except Exception as e:
        diag['bledy'].append(f'{type(e).__name__}: {e}'[:200])
    json.dump(dict(mecze=wynik, diag=diag), open(STS_WYNIK, 'w'), ensure_ascii=False)
    print('STS: dopasowane', len(wynik), '| błędy:', diag['bledy'][:3])

def sts_z_przegladarki():
    """Wywołanie czytnika STS pythonem z Playwright (cron uruchamia zwykły python3)."""
    import subprocess
    try: os.remove(STS_WYNIK)
    except Exception: pass
    py = PW_PYTHON if os.path.exists(PW_PYTHON) else sys.executable
    try:
        r = subprocess.run([py, os.path.abspath(__file__), '--sts-kursy'], capture_output=True, text=True, timeout=300)
        if r.returncode != 0 and not os.path.exists(STS_WYNIK):
            return {}, dict(bledy=[f'proces STS: {(r.stderr or r.stdout)[-300:]}'])
        d = json.load(open(STS_WYNIK))
        return d.get('mecze') or {}, d.get('diag') or {}
    except Exception as e:
        return {}, dict(bledy=[f'STS: {type(e).__name__}: {e}'[:200]])

def fortuna_mecz_rozpoznanie():
    """Rozpoznanie pełnej oferty meczu Fortuny (gole powyżej/poniżej): próby adresów API + strona meczu w przeglądarce.
    Wynik: surowe/fortuna_mecz.json (do analizy)."""
    s = ses(); wyn = dict(czas=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), proby=[], strona={})
    diag = {}
    try:
        oferta = [m for m in fortuna_mecze(s, diag) if m['sp'] == 'pilka']
        oferta.sort(key=lambda m: m['t'])
        mecz = next((m for m in oferta if m['t'] > dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)), oferta[0] if oferta else None)
    except Exception as e:
        wyn['blad'] = str(e)[:200]; mecz = None
    if mecz:
        fid = mecz['id']; wyn['mecz'] = dict(id=fid, nazwa=f"{mecz['h']} - {mecz['a']}", t=str(mecz['t']))
        from urllib.parse import quote
        q = quote(fid, safe='')
        for url in [f'{FAPI}/markets/api/v1_0/fixtures/markets?fixtureIds={q}', f'{FAPI}/markets/api/v1_0/fixtures/{q}/markets',
                    f'{FAPI}/markets/api/v1_0/fixture/{q}/markets', f'{FAPI}/markets/api/v1_0/fixtures/markets/detail?fixtureIds={q}',
                    f'{FAPI}/markets/api/v1_0/fixtures/markets/all?fixtureIds={q}', f'{FAPI}/markets/api/v1_0/fixtures/{q}',
                    f'{FAPI}/markets/api/v1_0/fixture/{q}', f'{FAPI}/structure/api/v1_0/fixture/{q}', f'{FAPI}/structure/api/v1_0/fixtures/{q}',
                    f'{FAPI}/markets/api/v1_0/fixtures/markets/groups?fixtureIds={q}', f'{FAPI}/markets/api/v1_0/fixture/{q}/marketGroups',
                    f'{FAPI}/markets/api/v1_0/fixtures/markets/overview?fixtureIds={q}']:
            try:
                r = s.get(url, timeout=20)
                wyn['proby'].append(dict(url=url, kod=r.status_code, rozmiar=len(r.content), tresc=r.text[:20000]))
            except Exception as e: wyn['proby'].append(dict(url=url, blad=str(e)[:120]))
            time.sleep(0.3)
    try:
        from playwright.sync_api import sync_playwright
        odp, linki = [], []
        with sync_playwright() as pw:
            br = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            pg = br.new_context(locale='pl-PL', user_agent=UA, viewport={'width': 1366, 'height': 900}).new_page()
            def na_odp(r):
                try:
                    if 'api.efortuna.pl/offer' not in r.url or r.request.resource_type in ('image', 'font', 'stylesheet', 'script'): return
                    b = r.body(); odp.append(dict(url=r.url, rozmiar=len(b), tresc=b[:60000].decode('utf-8', 'ignore')))
                except Exception: pass
            pg.on('response', na_odp)
            for url in ('https://www.efortuna.pl/zaklady-bukmacherskie/pilka-nozna/anglia-2?tab=matches',
                        'https://www.efortuna.pl/zaklady-bukmacherskie/pilka-nozna/polska-6?tab=matches'):
                pg.goto(url, wait_until='domcontentloaded', timeout=45000)
                for _ in range(3): pg.wait_for_timeout(2500); pg.mouse.wheel(0, 1500)
                linki += pg.evaluate("() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)")
            wyn['strona']['linki_przyklad'] = [l for l in dict.fromkeys(linki) if '/pilka-nozna/' in l][:80]
            kandydaci = [l for l in dict.fromkeys(linki) if re.search(r'/pilka-nozna/[^/?#]+/[^/?#]+/[^/?#]+', l) and 'tab=' not in l]
            wyn['strona']['linki_meczow'] = kandydaci[:20]
            przed = len(odp)
            if kandydaci:
                pg.goto(kandydaci[0], wait_until='domcontentloaded', timeout=45000)
            else:                                   # bez linków – klik w pierwszy element z nazwą meczu
                el = pg.query_selector('[class*="fixture"] a, [class*="event"] a, [data-test*="fixture"], [class*="match-name"], [class*="fixture-name"]')
                wyn['strona']['klik'] = bool(el)
                if el: el.click()
            for _ in range(4): pg.wait_for_timeout(2500); pg.mouse.wheel(0, 1500)
            wyn['strona']['adres_po'] = pg.url
            wyn['strona']['tekst'] = pg.inner_text('body')[:4000]
            br.close()
        wyn['strona']['zapytania_lista'] = [dict(url=o['url'], rozmiar=o['rozmiar']) for o in odp[:przed]][:60]
        wyn['strona']['zapytania_mecz'] = odp[przed:][:25]
    except Exception as e: wyn['strona']['blad'] = f'{type(e).__name__}: {e}'[:300]
    zapisz_github('surowe/fortuna_mecz.json', wyn)
    print('Fortuna – rozpoznanie meczu zapisane:', [(p.get('kod'), p.get('rozmiar')) for p in wyn['proby']])

def sts_zrzut():
    """Pełne wiadomości websocketu STS (lista + turniej + mecz) – do napisania czytnika STS."""
    from playwright.sync_api import sync_playwright
    ramki = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        pg = br.new_context(locale='pl-PL', user_agent=UA).new_page()
        def na_ws(w):
            if 'sbk/api/sbk' not in w.url: return
            w.on('framereceived', lambda f: sum(len(x) for x in ramki) < 9_000_000 and ramki.append('< ' + str(f)))
            w.on('framesent', lambda f: ramki.append('> ' + str(f)))
        pg.on('websocket', na_ws)
        for url in ('https://www.sts.pl/zaklady-bukmacherskie/pilka-nozna/miedzynarodowe/liga-narodow-uefa/1/3/12277',
                    'https://www.sts.pl/pilka-nozna', 'https://www.sts.pl/tenis'):
            try:
                pg.goto(url, wait_until='domcontentloaded', timeout=45000); pg.wait_for_timeout(9000)
                ramki.append('#### ' + url)
            except Exception as e: ramki.append(f'#### BLAD {url}: {e}')
        br.close()
    zapisz_github('surowe/sts_ws_pelne.txt', '\n\n'.join(ramki)[:9_500_000], surowy=True)
    try:
        r = ses().get('https://content.sts.pl/devices/common/any/market_description/json/markets_description.json?lang=pl', timeout=30)
        zapisz_github('surowe/sts_rynki.json', r.text, surowy=True)
    except Exception as e: print('rynki STS:', e)

def main():
    if '--cron' in sys.argv:
        tryb_cron(); return
    if '--test' not in sys.argv and not any(a.startswith('--siec') or a in ('--zrzut', '--sts', '--sts-kursy', '--fortuna-mecz') for a in sys.argv[1:]):
        czytnik(); return
    if '--sts-kursy' in sys.argv:
        sts_kursy(); return
    if '--fortuna-mecz' in sys.argv:
        fortuna_mecz_rozpoznanie(); return
    if '--sts' in sys.argv:
        sts_zrzut(); return
    if '--siec2' in sys.argv:
        siec2(); return
    if '--siec' in sys.argv:
        siec(); return
    s = ses(); wynik = {}
    for nazwa in STRONY:
        try: wynik[nazwa] = rozpoznaj(nazwa, s)
        except Exception as e: wynik[nazwa] = dict(blad=f'{type(e).__name__}: {e}'[:200])
        print(nazwa, 'gotowe', round(time.time() - START), 's')
    try: ip = s.get('https://api.ipify.org', timeout=10).text
    except Exception: ip = None
    dane = dict(czas=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), wersja='vps-test-2', ip=ip,
                sekund=round(time.time() - START), bukmacherzy=wynik)
    tekst = json.dumps(dane, ensure_ascii=False)
    if len(tekst) > 900_000:                           # limit rozmiaru – skracamy bloby
        for v in wynik.values():
            for b in v.get('bloby', []): b['poczatek'] = b['poczatek'][:400]
    zapisz_github(PLIK_WYNIKU, dane)
    if '--zrzut' in sys.argv:
        spis = []
        try: zrzut(s, spis)
        except Exception as e: spis.append(dict(blad=f'{type(e).__name__}: {e}'[:200]))
        zapisz_github('surowe/spis.json', dict(czas=dane['czas'], pliki=spis))

if __name__ == '__main__':
    main()
