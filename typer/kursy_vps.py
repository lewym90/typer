"""Kursy z polskiego serwera (VPS) – STS, Fortuna, Betclic PL.
Serwer pobiera ten plik z repozytorium przy każdym uruchomieniu (cron co 2 h), więc zmiany wprowadza się tylko w repozytorium.
Wynik trafia do repozytorium przez GitHub API (token w /opt/typer/token).

Czytniki: Fortuna (REST), STS (websocket wss://www.sts.pl/sbk/api/sbk przez przeglądarkę Playwright – python z /opt/typer/pw).
Rozpoznanie Betclic PL: --betclic (wersja 26, cała oferta), --betclic2 (wersja 27, zakładki rynków) (pythonem z /opt/typer/pw) → surowe/betclic/*.json.
Starsze tryby rozpoznania: --test, --zrzut, --siec, --siec2, --sts, --fortuna-mecz."""
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

def _strona_fortuna(nazwa, druzyny):
    """Nazwa drużyny z rynku Fortuny ('Mecz: Al Gharafa - liczba goli') → 'H' / 'A' wg uczestników meczu."""
    if not druzyny: return None
    n = re.sub(r'\s+', ' ', str(nazwa or '')).strip().lower()
    h, a = (re.sub(r'\s+', ' ', str(x or '')).strip().lower() for x in druzyny)
    if n == h: return 'H'
    if n == a: return 'A'
    if h and (n.startswith(h) or h.startswith(n)): return 'H'
    if a and (n.startswith(a) or a.startswith(n)): return 'A'
    return None

def _fortuna_klucze(rynki, odwr, sport, bo=3, druzyny=None):
    """Rynki Fortuny jednego meczu → nasze klucze. Nazwy rynków pełnej oferty sprawdzone na prawdziwym meczu 01.10
    (adres /offer/markets/api/v1_0/fixture/<id>/markets): „Mecz: liczba goli” („+ 2.5”), „Mecz: <Drużyna> - liczba goli”,
    „Mecz: handicap” („1 (-1.5)”), „Mecz: wynik/liczba goli” („1/+ 1.5”). Linie całkowite (z możliwym zwrotem) pomijamy."""
    k = {}
    for m in rynki or []:
        if m.get('kind') not in (None, 'PREMATCH'): continue
        n_oryg = re.sub(r'\s+', ' ', str(m.get('marketTypeName') or m.get('name') or '')).strip()
        n = n_oryg.lower()
        for o in m.get('outcomes') or []:
            try: c = float(o.get('odds') or 0)
            except Exception: continue
            if c <= 1.0 or o.get('displayType', 'OPEN') != 'OPEN': continue
            on = re.sub(r'\s+', ' ', str(o.get('name') or '').replace('\xa0', ' ')).strip()
            onl = on.lower()
            if sport == 'pilka':
                if 'połow' in n or 'polow' in n: continue
                if n == 'wynik meczu' and on in ('1', '0', '2'): k.setdefault({'1': '1', '0': 'X', '2': '2'}[on], c)
                elif n == 'mecz: dwójtyp' and on in ('10', '02', '12'): k.setdefault({'10': '1X', '02': 'X2', '12': '12'}[on], c)
                elif 'obie drużyny strzelą' in n and 'liczba goli' in n:          # obie strzelą i powyżej 2.5
                    if re.fullmatch(r'tak\s*/\s*\+\s*2[.,]5', onl): k.setdefault('BTTS & o2.5', c)
                elif n in ('mecz: obie drużyny strzelą gola', 'obie drużyny strzelą gola', 'mecz: obie drużyny strzelą'):
                    if onl == 'tak': k.setdefault('BTTS Tak', c)
                    elif onl == 'nie': k.setdefault('BTTS Nie', c)
                elif re.fullmatch(r'(mecz: )?(liczba goli|gole|suma goli)( w meczu)?', n):
                    mm = re.fullmatch(r'([+-]|powyżej|poniżej)\s*(\d+[.,]5)', onl)
                    if mm: k.setdefault(('Over ' if mm.group(1) in ('+', 'powyżej') else 'Under ') + mm.group(2).replace(',', '.'), c)
                elif n.startswith('mecz: ') and n.endswith(' - liczba goli'):     # gole jednej drużyny
                    st = _strona_fortuna(n_oryg[len('Mecz: '):-len(' - liczba goli')], druzyny)
                    mm = re.fullmatch(r'\+\s*(\d+[.,]5)', onl)
                    if st and mm: k.setdefault(f"{st} o{mm.group(1).replace(',', '.')}", c)
                elif n == 'mecz: handicap':                                      # „1 (-1.5)” / „2 (+1.5)”
                    mm = re.fullmatch(r'([12])\s*\(\s*(-[1-9]\d*[.,]5)\s*\)', on)
                    if mm: k.setdefault(f"{'H' if mm.group(1) == '1' else 'A'} {mm.group(2).replace(',', '.')}", c)
                elif n == 'mecz: wynik/liczba goli':                             # „1/+ 1.5”, „0/- 2.5”
                    mm = re.fullmatch(r'([102])\s*/\s*([+-])\s*(\d)[.,]5', on)
                    if mm: k.setdefault(f"{ {'1': '1', '0': 'X', '2': '2'}[mm.group(1)]} & {'o' if mm.group(2) == '+' else 'u'}{mm.group(3)}.5", c)
            else:
                pierwszy = lambda nr: ('A' if (nr == '1') != odwr else 'B')
                if (n.startswith('zwycięzca meczu') or n in ('wynik meczu', 'zwycięzca', 'mecz')) and 'zwrot jeżeli' not in n and on in ('1', '2'):
                    k.setdefault(pierwszy(on), c)
                elif sport == 'tenis' and ('set' in n) and 'handicap' in n and 'gem' not in n and not re.search(r'\d\.\s*set', n):
                    mm = re.fullmatch(r'([12])\s*\(([+-]1[.,]5)\)', on)
                    if mm:
                        kto, h = pierwszy(mm.group(1)), mm.group(2).replace(',', '.')
                        if h == '-1.5': k.setdefault(f'{kto} -1.5', c)
                        elif int(bo or 3) == 3: k.setdefault(f'{kto} min. 1 set', c)
                        else: k.setdefault(f'{kto} +1.5', c)
                elif sport == 'tenis' and n.startswith('mecz: ') and n.endswith(' - wygra co najmniej jeden set'):
                    st = _strona_fortuna(n_oryg[len('Mecz: '):-len(' - wygra co najmniej jeden set')], druzyny)
                    if st and onl == 'tak': k.setdefault(f"{pierwszy('1' if st == 'H' else '2')} min. 1 set", c)
                elif sport == 'tenis' and 'liczba setów' in n and not re.search(r'\d\.\s*set|gem', n) and n.count(' - ') == 0:
                    mm = re.fullmatch(r'([+-]|powyżej|poniżej|więcej niż|mniej niż)\s*(\d)[.,]5', onl)
                    if mm: k.setdefault(f"{'Ponad' if mm.group(1) in ('+', 'powyżej', 'więcej niż') else 'Poniżej'} {mm.group(2)}.5 seta", c)
                elif sport == 'tenis' and ('dokładny wynik' in n or 'wynik w setach' in n or 'wynik setowy' in n) and not re.search(r'\d\.\s*set|gem', n):
                    mm = re.fullmatch(r'(\d)\s*:\s*(\d)', on)
                    if mm:
                        x, y = int(mm.group(1)), int(mm.group(2))
                        if x == y: continue
                        kto = pierwszy('1' if x > y else '2')
                        k.setdefault(f'{kto} {max(x, y)}:{min(x, y)}', c)
                        if int(bo or 3) == 3 and min(x, y) == 0: k.setdefault(f'{kto} -1.5', c)
    return k

def fortuna_pelna_oferta(s, fid):
    """Pełna oferta meczu Fortuny (wszystkie rynki) – adres potwierdzony rozpoznaniem 01.10."""
    from urllib.parse import quote
    r = s.get(f'{FAPI}/markets/api/v1_0/fixture/{quote(fid, safe="")}/markets', timeout=25)
    r.raise_for_status()
    j = r.json()
    return j if isinstance(j, list) else (j.get(fid) or j.get('markets') or [])

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
                diag['bledy'].append(f'kursy {f["id"]}: {e}'[:120]); rynki = []
            try:                                     # pełna oferta: gole, gole drużyn, handicap, wynik i gole; w tenisie sety
                pelne = fortuna_pelna_oferta(s, f['id']); rynki = list(rynki) + list(pelne)
                diag['pelna_oferta'] = diag.get('pelna_oferta', 0) + 1
            except Exception as e:
                diag.setdefault('pelna_oferta_bledy', []).append(f'{f["id"]}: {type(e).__name__}: {e}'[:120])
            if not rynki: continue
            spis = rynki_nazwy.setdefault(sp, {})
            for m in rynki:
                rn = m.get('marketTypeName') or m.get('name')
                if rn and len(spis) < 120: spis.setdefault(rn, [str(o.get('name') or '').replace('\xa0', ' ') for o in (m.get('outcomes') or [])][:4])
            k = _fortuna_klucze(rynki, odwr, sp if sp in ('pilka', 'tenis') else 'duel', bo, (f['h'], f['a']))
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

# ======================================================================= CZYTNIK STS (websocket, przez przeglądarkę)
STS_WS = 'wss://www.sts.pl/sbk/api/sbk'
STS_SPORTY = {'1': 'pilka', '3': 'tenis', '166': 'walki', '19': 'walki'}   # piłka, tenis, MMA, boks
PW_PYTHON = '/opt/typer/pw/bin/python'
STS_WYNIK = '/opt/typer/sts_wynik.json'
_JS_SZCZEGOLY = """async ({ids, ms}) => await new Promise(res => {
  // Pełna oferta meczów: subskrypcje w małych paczkach (wszystkie naraz – serwer odpowiadał tylko na część),
  // czekamy na odpowiedź każdego meczu, brakujące ponawiamy pojedynczo.
  const out = [], dostal = new Set(); let rozm = 0, ws, zamkn = false;
  const start = Date.now();
  const koniec = (x) => { if (zamkn) return; zamkn = true; try { ws.close(); } catch (e) {} res(Object.assign({out, dostal: [...dostal]}, x || {})); };
  const dodaj = (t) => {
    if (typeof t !== 'string' || t.startsWith('{"s":"i_pl"') || t.startsWith('{"t":5')) return;
    try { const s = JSON.parse(t.slice(0, t.indexOf('\\n'))).s; if (s) dostal.add(s); } catch (e) {}
    if (rozm < 8e6) { out.push(t); rozm += t.length; }
  };
  const czekaj = (ms_) => new Promise(r => setTimeout(r, ms_));
  const subskrybuj = async (paczka, ile_ms) => {
    try { ws.send(JSON.stringify({t: 1, u: [{s: 'i_pl'}].concat(paczka.map(i => ({s: 'f_' + i + '_pl', n: 0})))})); } catch (e) { return; }
    const t0 = Date.now();
    while (Date.now() - t0 < ile_ms && paczka.some(i => !dostal.has('f_' + i + '_pl'))) await czekaj(250);
    await czekaj(600);   // ewentualne kolejne ramki tego samego meczu
  };
  try { ws = new WebSocket('""" + STS_WS + """'); } catch (e) { res({out, blad: String(e)}); return; }
  ws.onopen = async () => {
    ws.send(JSON.stringify({t: 1, u: [{s: 'i_pl', n: 0}]}));
    await czekaj(2500);
    for (let i = 0; i < ids.length && Date.now() - start < ms; i += 3) await subskrybuj(ids.slice(i, i + 3), 7000);
    for (const i of ids) {                       // ponowienie pojedynczo
      if (Date.now() - start >= ms) break;
      if (!dostal.has('f_' + i + '_pl')) await subskrybuj([i], 6000);
    }
    koniec();
  };
  ws.onmessage = (e) => { if (typeof e.data === 'string') dodaj(e.data); else if (e.data && e.data.text) e.data.text().then(dodaj); };
  ws.onerror = () => out.push('BLAD_WS');
  setTimeout(() => koniec({limit: true}), ms + 15000);
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
                rn = str((opis.get(mid) or {}).get('n') or '').strip().lower()
                if sp == 'pilka':
                    if any(x in rn for x in ('połow', 'kart', 'rożn', 'faul', 'strzał', 'zawodnik', 'superoferta', 'wysokie')): continue
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
                    elif mid in ('1229', '1224'):                                 # drużyna strzeli gola = gole drużyny powyżej 0.5
                        if nl == 'tak': k.setdefault(f"{'H' if mid == '1229' else 'A'} o0.5", c)
                    elif mid == '22' or rn == 'handicap':                         # „1 (-1.5)” / „2 (+1.5)” (jak „2. połowa - handicap”)
                        mm = re.fullmatch(r'([12])\s*\(\s*(-[1-9]\d*[.,]5)\s*\)', n)
                        if mm: k.setdefault(f"{'H' if mm.group(1) == '1' else 'A'} {mm.group(2).replace(',', '.')}", c)
                    elif mid == '51' or ('liczba goli' in rn and ('wynik' in rn or rn.startswith('mecz')) and 'obie' not in rn and 'dokładn' not in rn):
                        # „1 i +2.5” / „X i -2.5” (jak „1. połowa / wynik końcowy i liczba goli”: „1 / 1 i -2.5”)
                        mm = re.fullmatch(r'([1x2])\s*(?:i|&|/)\s*([+-]|powyżej|poniżej)?\s*(\d)?(?:[.,]5)?', nl)
                        if mm:
                            znak = mm.group(2); liczba = mm.group(3)
                            if not liczba:
                                _, ln = _liczba_ou((linia or {}).get('n')); liczba = ln[0] if ln else None
                            if znak and liczba:
                                k.setdefault(f"{mm.group(1).upper()} & {'o' if znak in ('+', 'powyżej') else 'u'}{liczba}.5", c)
                    elif 'obie' in rn and 'liczba goli' in rn:                     # obie strzelą i powyżej 2.5
                        if re.fullmatch(r'tak\s*(?:i|&|/)\s*(?:\+|powyżej)\s*2[.,]5', nl): k.setdefault('BTTS & o2.5', c)
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
                    elif sp == 'tenis' and mid == '265':                            # „1 (-1.5)” / „2 (+1.5)”
                        mm = re.fullmatch(r'([12])\s*\(\s*([+-])1[.,]5\s*\)', n)
                        if mm:
                            kto = pierwszy(int(mm.group(1)))
                            if mm.group(2) == '-': k.setdefault(f'{kto} -1.5', c)
                            elif int(bo or 3) == 3: k.setdefault(f'{kto} min. 1 set', c)
                            else: k.setdefault(f'{kto} +1.5', c)
                    elif sp == 'tenis' and mid == '479':
                        ou, ln = _liczba_ou_linia(n, linia)
                        if ou: k.setdefault(f"{'Ponad' if ou == 'Over' else 'Poniżej'} {ln} seta", c)
    return k

def _opis_rynkow(rynki, opis, ile=40):
    """Skrót rynków meczu do diagnostyki: 'id nazwa': ['linia | wynik=kurs', ...]."""
    wyn = {}
    pomin = ('połow', 'kart', 'rożn', 'faul', 'strzał', 'zawodnik', 'superoferta', 'wysokie', 'gem', 'asów', 'samobój', 'karny')
    def waga(mid):   # najpierw rynki, które czytamy lub możemy czytać (gole, handicap, sety)
        n = str((opis.get(mid) or {}).get('n') or '').lower()
        return (any(x in n for x in pomin), int(mid) if str(mid).isdigit() else 99999)
    for mid in sorted(rynki or {}, key=waga):
        m = rynki[mid]
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
                    r = pg.evaluate(_JS_SZCZEGOLY, dict(ids=[d[5]['id'] for d in dopas], ms=150000))
                    diag['szczegoly_ramek'] = len(r.get('out') or [])
                    diag['szczegoly_odpowiedzi'] = f"{len(r.get('dostal') or [])} z {len(dopas)}"
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


# ======================================================================= ROZPOZNANIE BETCLIC PL (wersja 24)
BC = 'https://www.betclic.pl'
BC_CDN = 'https://offer.cdn.begmedia.com/api'
BC_KATALOG = 'surowe/betclic'
BC_LIMIT = 50 * 60                      # całe rozpoznanie najwyżej ok. 50 min
BC_NASZE = ('football', 'tennis', 'mma', 'boxing', 'basketball', 'ice_hockey', 'volleyball', 'handball')
BC_TABY_JS = """() => {
  const wyn = [];
  const el = Array.from(document.querySelectorAll('[role="tab"], .tab, [class*="tab"] a, [class*="tab"] button, [class*="Tab"], [class*="filter"] button, [class*="chip"]'));
  for (const e of el) { const t = (e.innerText || '').trim(); if (t && t.length < 40 && !t.includes('\\n')) wyn.push(t); }
  return Array.from(new Set(wyn)).slice(0, 40);
}"""
BC_KLIKNIJ_JS = """(tekst) => {
  const el = Array.from(document.querySelectorAll('[role="tab"], .tab, [class*="tab"] a, [class*="tab"] button, [class*="Tab"], [class*="filter"] button, [class*="chip"], button, a'));
  for (const e of el) { if ((e.innerText || '').trim() === tekst) { e.click(); return true; } }
  return false;
}"""
BC_ROZWIN_JS = """() => {   // rozwija zwinięte rynki i 'pokaż więcej' (klik przez JS – baner cookies nie przeszkadza)
  let n = 0;
  const el = Array.from(document.querySelectorAll('button, a, [role="button"], [class*="expand"], [class*="more"], [class*="toggle"]'));
  for (const e of el) {
    const t = (e.innerText || '').trim().toLowerCase();
    if (/^(pokaż|zobacz|wyświetl) (więcej|wszystkie|wszystko)|^więcej$|^\\+\\s*\\d+$/.test(t) && n < 60) { try { e.click(); n++; } catch (x) {} }
  }
  for (const e of document.querySelectorAll('[aria-expanded="false"]')) { if (n < 120) { try { e.click(); n++; } catch (x) {} } }
  return n;
}"""

def _bc_ng(pg):
    try: t = pg.evaluate("() => { const e = document.getElementById('ng-state'); return e ? e.textContent : '' }")
    except Exception: return {}
    try: return json.loads(t) if t else {}
    except Exception: return {}

def _bc_mecze_z_ng(ng):
    """Mecze z ng-state (odpowiedzi gRPC zapisane przez serwer strony): id, nazwa, czas, na żywo, liga."""
    wyn = {}
    def chodz(o):
        if isinstance(o, dict):
            if o.get('matchId') and o.get('name'):
                kom = o.get('competition') or {}
                if str(o['matchId']) not in wyn or not wyn[str(o['matchId'])].get('t'): wyn[str(o['matchId'])] = dict(id=str(o['matchId']), nazwa=o['name'], t=o.get('matchDateUtc'), live=bool(o.get('isLive')),
                                              liga=kom.get('name'), liga_id=kom.get('id'), sport=(kom.get('sport') or {}).get('code'))
            for v in o.values(): chodz(v)
        elif isinstance(o, list):
            for v in o: chodz(v)
    for k, v in ng.items():
        if str(k).startswith('grpc:'): chodz(v)
    return wyn

def _bc_menu_z_ng(ng):
    """Menu sportów (SportMenuService) z ng-state: [(kod, nazwa, [(id ligi, nazwa)])]."""
    for k, v in ng.items():
        if not str(k).startswith('grpc:'): continue
        p = ((v or {}).get('response') or {}).get('payload') or {}
        if isinstance(p, dict) and isinstance(p.get('sports'), list) and p['sports'] and 'sportCode' in p['sports'][0]:
            menu = []
            for sp in p['sports']:
                ligi = []
                def zbierz(o):
                    if isinstance(o, dict):
                        if o.get('competitionId') and o.get('competitionName') and str(o['competitionId']) != '0':
                            ligi.append((str(o['competitionId']), o['competitionName']))
                        for x in o.values(): zbierz(x)
                    elif isinstance(o, list):
                        for x in o: zbierz(x)
                zbierz(sp)
                menu.append((sp.get('sportCode'), sp.get('sportName'), list(dict.fromkeys(ligi))))
            return menu
    return []

def _slug(t):
    import unicodedata
    t = (t or '').lower().replace('ł', 'l')
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', t).strip('-') or 'x'

def _bc_link_sportu(href):
    m = re.match(r'^https://www\.betclic\.pl/([a-z0-9\-]+)-s([a-z0-9_]+)/?$', href or '')
    return (m.group(2), href.rstrip('/')) if m else None

def _bc_odp(stan):
    """Zapisywanie odpowiedzi strony (JSON tekstem, gRPC/binarne jako base64) razem z nagłówkami i treścią zapytania."""
    def na_odp(r):
        try:
            if r.request.resource_type in ('image', 'font', 'stylesheet', 'media', 'script'): return
            if not re.search(r'begmedia|betclic\.pl', r.url) or re.search(r'analytics|experience-requests|dam\.begmedia|/footer|metatags', r.url): return
            typ = r.headers.get('content-type', '')
            b = r.body()
            wpis = dict(etap=stan['etap'], url=r.url, metoda=r.request.method, kod=r.status, typ=typ[:60], rozmiar=len(b),
                        naglowki={k: v for k, v in (r.request.headers or {}).items() if k.lower() not in ('cookie', 'authorization')})
            try:
                pb = r.request.post_data_buffer
                if pb: wpis['post_b64'] = base64.b64encode(pb[:20000]).decode()
            except Exception: pass
            if 'json' in typ or typ.startswith('text'): wpis['tresc'] = b[:300_000].decode('utf-8', 'ignore')
            else: wpis['tresc_b64'] = base64.b64encode(b[:700_000]).decode()
            if stan['rozmiar'] < 7_000_000:
                stan['odp'].append(wpis); stan['rozmiar'] += len(wpis.get('tresc', '')) + len(wpis.get('tresc_b64', ''))
        except Exception: pass
    return na_odp

def _bc_api(s):
    """Próby publicznego API ofert w JSON (offer.cdn.begmedia.com – adres z konfiguracji strony)."""
    wyn = []
    par = 'application=2&countrycode=pl&language=pl&sitecode=plpl'
    adresy = [f'{BC_CDN}/pub/v4/sports?{par}', f'{BC_CDN}/pub/v2/sports?{par}',
              f'{BC_CDN}/pub/v4/events?{par}&fetchMultipleDefaultMarkets=true&limit=20&offset=0&sortBy=ByLiveRankingPreliveDate&sportIds=1',
              f'{BC_CDN}/pub/v4/events?{par}&limit=20&offset=0&sportIds=1', f'{BC_CDN}/pub/v3/events?{par}&limit=20&offset=0&sportIds=1',
              f'{BC_CDN}/pub/v2/events?{par}&limit=20&offset=0&sportIds=1', f'{BC_CDN}/pub/v2/sports/1?{par}',
              f'{BC_CDN}/pub/v4/events?application=1024&countrycode=pl&language=pl&sitecode=plpl&limit=20&offset=0&sportIds=2',
              f'{BC_CDN}/pub/v4/events?application=2&countrycode=pl&language=pl&sitecode=pl&limit=20&offset=0&sportIds=1',
              f'{BC_CDN}/pub/v4/competitions/22676?{par}', f'{BC_CDN}/pub/v2/competitions/22676?{par}']
    idy = []
    for url in adresy:
        try:
            r = s.get(url, timeout=20, headers={'Accept': 'application/json', 'Origin': BC, 'Referer': BC + '/'})
            wyn.append(dict(url=url, kod=r.status_code, typ=r.headers.get('content-type', '')[:50], rozmiar=len(r.content), tresc=r.text[:150_000]))
            if r.status_code == 200: idy += re.findall(r'"(?:id|matchId|eventId)"\s*:\s*"?(\d{6,})', r.text)[:3]
        except Exception as e: wyn.append(dict(url=url, blad=f'{type(e).__name__}: {e}'[:150]))
        time.sleep(0.3)
    for i in list(dict.fromkeys(idy))[:3]:
        for w in ('v4', 'v3', 'v2'):
            url = f'{BC_CDN}/pub/{w}/events/{i}?{par}'
            try:
                r = s.get(url, timeout=20, headers={'Accept': 'application/json', 'Origin': BC, 'Referer': BC + '/'})
                wyn.append(dict(url=url, kod=r.status_code, typ=r.headers.get('content-type', '')[:50], rozmiar=len(r.content), tresc=r.text[:300_000]))
            except Exception as e: wyn.append(dict(url=url, blad=f'{type(e).__name__}: {e}'[:150]))
    return wyn

def _bc_strona(pg, url, przewin=3, czekaj=3500):
    pg.goto(url, wait_until='domcontentloaded', timeout=45000)
    for _ in range(przewin): pg.wait_for_timeout(czekaj); pg.mouse.wheel(0, 2500)
    return pg.evaluate("() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)")

def _bc_mecz(pg, stan, url, wszystkie_taby):
    """Strona meczu przedmeczowego: tekst każdej zakładki rynków (po rozwinięciu), ng-state, zapytania gRPC."""
    w = dict(url=url, zakladki=[])
    stan['etap'] = 'mecz ' + url
    try:
        _bc_strona(pg, url, przewin=2, czekaj=3000)
        w['rozwinieto'] = pg.evaluate(BC_ROZWIN_JS); pg.wait_for_timeout(1500)
        w['tekst'] = pg.inner_text('body')[:60000]
        ng = _bc_ng(pg); w['ngstate'] = json.dumps(ng, ensure_ascii=False)[:600_000]
        taby = pg.evaluate(BC_TABY_JS); w['taby'] = taby
        for t in taby[:(14 if wszystkie_taby else 5)]:
            if time.time() - START > BC_LIMIT: break
            stan['etap'] = f'mecz {url} zakladka {t}'
            try:
                if not pg.evaluate(BC_KLIKNIJ_JS, t): continue
                pg.wait_for_timeout(2500); pg.evaluate(BC_ROZWIN_JS); pg.wait_for_timeout(1200); pg.mouse.wheel(0, 3000); pg.wait_for_timeout(800)
                w['zakladki'].append(dict(nazwa=t, tekst=pg.inner_text('body')[:40000]))
            except Exception as e: w['zakladki'].append(dict(nazwa=t, blad=str(e)[:150]))
    except Exception as e: w['blad'] = f'{type(e).__name__}: {e}'[:300]
    return w

BC_SPORT = {'pilka': ('football',), 'tenis': ('tennis',), 'walki': ('mma', 'boxing')}

def _bc_nasze(pg, stan, KP, nasze, wszystkie, linki, spis, czas):
    """Nasze dzisiejsze mecze u Betclic: dopasowanie (nazwy + czas) i pełna oferta kilku z nich."""
    stan['odp'], stan['rozmiar'] = [], 0
    wyn = dict(czas=czas, dopasowane=[], niedopasowane=[], mecze=[])
    try:
        for sp, eid, h, a, start, bo in nasze:
            try: t0 = KP._utc_nasz(start)
            except Exception: t0 = None
            tol = {'pilka': 35, 'tenis': 360, 'walki': 720}.get(sp, 60)
            best = None
            for m in wszystkie.values():
                if m.get('sport') and m['sport'] not in BC_SPORT.get(sp, ()): continue
                cz = re.split(r'\s+-\s+', m.get('nazwa') or '', maxsplit=1)
                if len(cz) != 2: continue
                try: t = dt.datetime.fromisoformat(str(m['t'])[:19]).replace(tzinfo=dt.timezone.utc)
                except Exception: t = None
                dmin = abs((t - t0).total_seconds()) / 60 if (t and t0) else 0
                if t and t0 and dmin > tol: continue
                s1 = min(KP.podobne_w(h, cz[0]), KP.podobne_w(a, cz[1]))
                s2 = min(KP.podobne_w(h, cz[1]), KP.podobne_w(a, cz[0])) if sp != 'pilka' else 0
                sc = max(s1, s2)
                if sc >= 0.55 and (best is None or sc > best[0]): best = (sc, m, s2 > s1, round(dmin))
            if best:
                wyn['dopasowane'].append(dict(sp=sp, nasz=f'{h} – {a}', start=str(start), betclic=best[1]['nazwa'], id=best[1]['id'],
                                              zgodnosc=round(best[0], 2), odwrocone=best[2], roznica_min=best[3], link=linki.get(best[1]['id'])))
            else: wyn['niedopasowane'].append(f'{sp}: {h} – {a} ({start})')
        # pełna oferta: do 2 meczów z każdej naszej dyscypliny
        ile = {}
        for d in wyn['dopasowane']:
            if not d['link'] or ile.get(d['sp'], 0) >= 2 or time.time() - START > BC_LIMIT: continue
            ile[d['sp']] = ile.get(d['sp'], 0) + 1
            w = _bc_mecz(pg, stan, d['link'], True); w['nasz'] = d
            wyn['mecze'].append(w)
    except Exception as e: wyn['blad'] = f'{type(e).__name__}: {e}'[:300]
    wyn['odpowiedzi'] = stan['odp']
    zapisz_github(f'{BC_KATALOG}/nasze.json', wyn)
    spis['nasze'] = dict(dopasowane=len(wyn['dopasowane']), niedopasowane=wyn['niedopasowane'][:40],
                         z_linkiem=sum(1 for d in wyn['dopasowane'] if d['link']), stron_meczu=len(wyn['mecze']), blad=wyn.get('blad'))
    print('Nasze mecze u Betclic:', len(wyn['dopasowane']), 'dopasowanych,', len(wyn['niedopasowane']), 'niedopasowanych')
    stan['odp'], stan['rozmiar'] = [], 0

def betclic_rozpoznanie():
    """Rozpoznanie całej oferty Betclic PL: wszystkie sporty z menu, w każdym 1–2 mecze przedmeczowe z pełną ofertą
    (wszystkie zakładki rynków), zapytania gRPC strony (do odtworzenia bez przeglądarki) i próby publicznego API JSON.
    Wynik: surowe/betclic/*.json (plik na każdy sport) + surowe/betclic/spis.json. Czas: do ok. 50 min."""
    import fcntl
    blokada = open('/opt/typer/cron.lock', 'w')
    print('Czekam, aż skończy się bieżący odczyt kursów (jeśli trwa)...')
    fcntl.flock(blokada, fcntl.LOCK_EX)     # cron w tym czasie pominie odczyty
    s = ses()
    czas = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    spis = dict(czas=czas, wersja='betclic-rozpoznanie-1', sporty=[], bledy=[])
    try:
        api = _bc_api(s)
        spis['api'] = [{k: v for k, v in a.items() if k != 'tresc'} for a in api]
        zapisz_github(f'{BC_KATALOG}/api.json', dict(czas=czas, proby=api))
        print('API JSON:', [(a.get('kod'), a.get('rozmiar')) for a in api])
    except Exception as e: spis['bledy'].append(f'api: {e}'[:200])
    KP, nasze = None, []
    try:
        KP = _przygotuj(s)
        nasze = KP.nasze_mecze(z_listy=True)
    except Exception as e: spis['bledy'].append(f'nasze mecze: {e}'[:200])
    spis['nasze_mecze'] = len(nasze)
    wszystkie, linki_wszystkie = {}, {}          # mecze Betclic ze wszystkich odwiedzonych stron + linki do nich
    nasze_zrobione = [False]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        ctx = br.new_context(locale='pl-PL', timezone_id='Europe/Warsaw', user_agent=UA, viewport={'width': 1366, 'height': 900})
        pg = ctx.new_page()
        stan = dict(etap='start', odp=[], rozmiar=0)
        pg.on('response', _bc_odp(stan))
        # 1. menu sportów i linki
        linki_sportow, menu = {}, []
        for url in (BC + '/', BC + '/pilka-nozna-sfootball'):
            try:
                stan['etap'] = 'menu ' + url
                for h in _bc_strona(pg, url, przewin=2, czekaj=3000):
                    x = _bc_link_sportu(h)
                    if x: linki_sportow.setdefault(x[0], x[1])
                menu = menu or _bc_menu_z_ng(_bc_ng(pg))
            except Exception as e: spis['bledy'].append(f'menu {url}: {e}'[:200])
        spis['menu'] = [dict(kod=k, nazwa=n, lig=len(l)) for k, n, l in menu]
        spis['linki_sportow'] = linki_sportow
        start_odp = list(stan['odp']); stan['odp'] = []; stan['rozmiar'] = 0
        zapisz_github(f'{BC_KATALOG}/start.json', dict(czas=czas, menu=menu, linki_sportow=linki_sportow, odpowiedzi=start_odp))
        kody = [k for k, _, _ in menu] or list(linki_sportow)
        for k in linki_sportow:
            if k not in kody: kody.append(k)
        kody.sort(key=lambda k: (BC_NASZE.index(k) if k in BC_NASZE else 99))
        ligi_sportu = {k: l for k, _, l in menu}
        nazwy_sportu = {k: n for k, n, _ in menu}
        # 2. każdy sport: lista meczów → 1–2 mecze przedmeczowe → pełna oferta
        for kod in kody:
            if kod not in ('football', 'tennis', 'mma', 'boxing') and not nasze_zrobione[0]:
                nasze_zrobione[0] = True
                _bc_nasze(pg, stan, KP, nasze, wszystkie, linki_wszystkie, spis, czas)
            if time.time() - START > BC_LIMIT: spis['bledy'].append('limit czasu – pominięto: ' + ', '.join(kody[kody.index(kod):])); break
            t0 = time.time()
            stan['odp'], stan['rozmiar'] = [], 0
            wpis = dict(kod=kod, nazwa=nazwy_sportu.get(kod), strony=[], mecze=[])
            url_sportu = linki_sportow.get(kod) or f'{BC}/{_slug(nazwy_sportu.get(kod))}-s{kod}'
            mecze, linki = {}, []
            kandydaci_lig = []
            try:
                stan['etap'] = 'sport ' + url_sportu
                linki = _bc_strona(pg, url_sportu)
                wpis['strony'].append(dict(url=url_sportu, adres_po=pg.url, tekst=pg.inner_text('body')[:8000]))
                mecze.update(_bc_mecze_z_ng(_bc_ng(pg)))
            except Exception as e: wpis['strony'].append(dict(url=url_sportu, blad=str(e)[:200]))
            teraz = dt.datetime.now(dt.timezone.utc)
            def przedmeczowe():
                wyn = []
                for m in mecze.values():
                    if m['live']: continue
                    try: t = dt.datetime.fromisoformat(str(m['t'])[:19]).replace(tzinfo=dt.timezone.utc)
                    except Exception: t = None
                    if t and t < teraz + dt.timedelta(minutes=40): continue
                    wyn.append(m)
                wyn.sort(key=lambda m: str(m['t']))
                return wyn
            # za mało meczów przedmeczowych → strony lig (linki z menu sportu albo z listy lig w menu)
            # nasze dyscypliny: najważniejsze ligi (tam są nasze mecze); inne: tylko gdy brak meczów przedmeczowych
            nasza = kod in ('football', 'tennis', 'mma', 'boxing')
            if nasza or len(przedmeczowe()) < 2:
                z_menu = [f'{url_sportu}/{_slug(n)}-c{i}' for i, n in ligi_sportu.get(kod, [])]
                z_linkow = [h for h in dict.fromkeys(linki) if re.search(r'-c\d+/?$', h) and url_sportu.split('/')[-1] in h]
                kandydaci_lig = list(dict.fromkeys(z_linkow[:8] + z_menu)) if nasza else (z_linkow or z_menu)
                for lu in kandydaci_lig[:(8 if nasza else 3)]:
                    if (not nasza and len(przedmeczowe()) >= 2) or time.time() - START > BC_LIMIT: break
                    try:
                        stan['etap'] = 'liga ' + lu
                        linki += _bc_strona(pg, lu, przewin=2, czekaj=3000)
                        mecze.update(_bc_mecze_z_ng(_bc_ng(pg)))
                        wpis['strony'].append(dict(url=lu, adres_po=pg.url, tekst=pg.inner_text('body')[:4000]))
                    except Exception as e: wpis['strony'].append(dict(url=lu, blad=str(e)[:200]))
            wpis['meczow'] = len(mecze); pm = przedmeczowe(); wpis['przedmeczowych'] = len(pm)
            wpis['mecze_lista'] = list(mecze.values())[:60]
            linki_m = {}
            for h in dict.fromkeys(linki):
                m = re.search(r'-m(\d{6,})(?:[/?#]|$)', h)
                if m: linki_m.setdefault(m.group(1), h)
            linki_wszystkie.update(linki_m)
            for m in mecze.values():                          # link zapasowy, gdy na stronie nie było odnośnika
                if m.get('liga_id') and m['id'] not in linki_m and m.get('sport') in (kod, None):
                    linki_m[m['id']] = f"{url_sportu}/{_slug(m.get('liga'))}-c{m['liga_id']}/{_slug(m['nazwa'])}-m{m['id']}"
                    linki_wszystkie.setdefault(m['id'], linki_m[m['id']])
                wszystkie.setdefault(m['id'], m)
            ile = 2 if kod in BC_NASZE else 1
            wybrane = [m for m in pm if m['id'] in linki_m][:ile]
            if not wybrane and linki_m:                        # brak danych o czasie – bierzemy linki, które nie są na żywo
                wybrane = [dict(id=i) for i in linki_m if not (mecze.get(i) or {}).get('live')][:ile]
            for m in wybrane:
                if time.time() - START > BC_LIMIT: break
                w = _bc_mecz(pg, stan, linki_m[m['id']], kod in BC_NASZE)
                w['mecz'] = mecze.get(m['id'], m)
                wpis['mecze'].append(w)
            wpis['odpowiedzi'] = stan['odp']
            wpis['sekund'] = round(time.time() - t0)
            ok = zapisz_github(f'{BC_KATALOG}/{_slug(kod)}.json', wpis)
            spis['sporty'].append(dict(kod=kod, nazwa=wpis['nazwa'], meczow=wpis['meczow'], przedmeczowych=wpis['przedmeczowych'],
                                       stron_meczu=len(wpis['mecze']), zakladek=sum(len(x.get('zakladki', [])) for x in wpis['mecze']),
                                       odpowiedzi=len(stan['odp']), grpc=sum(1 for o in stan['odp'] if 'grpc' in o['typ']),
                                       sekund=wpis['sekund'], zapisano=ok))
            print(f"{kod}: meczów {wpis['meczow']}, przedmeczowych {wpis['przedmeczowych']}, stron meczu {len(wpis['mecze'])}, "
                  f"zapytań {len(stan['odp'])} – {round(time.time() - START)} s")
            if len(spis['sporty']) % 6 == 0:
                zapisz_github(f'{BC_KATALOG}/spis.json', dict(spis, sekund=round(time.time() - START), w_toku=True))
        if not nasze_zrobione[0]: _bc_nasze(pg, stan, KP, nasze, wszystkie, linki_wszystkie, spis, czas)
        br.close()
    spis['sekund'] = round(time.time() - START)
    zapisz_github(f'{BC_KATALOG}/spis.json', spis)
    print('Betclic – rozpoznanie zakończone:', len(spis['sporty']), 'sportów,', spis['sekund'], 's')


# ----------------------------------------------------------------------- ROZPOZNANIE 2: zakładki rynków meczu (wersja 27)
BC_ZAKL_JS = """() => {   // zakładki rynków meczu: kontener z 'Top' i 'MyCombi'
  const liscie = Array.from(document.querySelectorAll('body *')).filter(e => e.children.length === 0 && (e.innerText || '').trim() === 'Top');
  for (const top of liscie) {
    let c = top;
    for (let i = 0; i < 7 && c; i++) {
      c = c.parentElement;
      const tx = c ? (c.innerText || '') : '';
      if (tx.includes('MyCombi') && tx.length < 600) {
        const el = Array.from(c.querySelectorAll('a, button, [role="tab"], li, span, div')).filter(e => e.children.length === 0);
        const wyn = [];
        for (const e of el) {
          const t = (e.innerText || '').trim(); if (!t || t.length > 40) continue;
          const kl = e.closest('a, button, [role="tab"], li') || e;
          wyn.push({t, href: kl.href || (kl.closest('a') ? kl.closest('a').href : null), tag: kl.tagName});
        }
        return wyn;
      }
    }
  }
  return [];
}"""
BC_KLIK_ZAKL_JS = """(tekst) => {
  const liscie = Array.from(document.querySelectorAll('body *')).filter(e => e.children.length === 0 && (e.innerText || '').trim() === tekst);
  for (const e of liscie) {
    let c = e, ok = false;
    for (let i = 0; i < 7 && c; i++) { c = c.parentElement; if (c && (c.innerText || '').includes('MyCombi') && (c.innerText || '').length < 600) { ok = true; break; } }
    if (!ok) continue;
    (e.closest('a, button, [role="tab"], li') || e).click(); return true;
  }
  return false;
}"""

def _bc_rynki_ng(ng):
    """Rynki meczu z ng-state: [(nazwa rynku, ['zakład=kurs', ...])]."""
    out = []
    def chodz(o):
        if isinstance(o, dict):
            if 'name' in o and any(x in o for x in ('selections', 'mainSelections', 'selectionMatrix')):
                sel = []
                def ws(x):
                    if isinstance(x, dict):
                        if 'odds' in x and 'name' in x: sel.append(f"{x['name']}={x['odds']}")
                        for v in x.values(): ws(v)
                    elif isinstance(x, list):
                        for v in x: ws(v)
                ws(o); out.append((o['name'], sel)); return
            for v in o.values(): chodz(v)
        elif isinstance(o, list):
            for v in o: chodz(v)
    for k, g in ng.items():
        if not str(k).startswith('grpc:'): continue
        p = ((g or {}).get('response') or {}).get('payload') or {}
        if isinstance(p, dict) and 'match' in p: chodz(p['match'])
    return out

def _bc_requests(s, url):
    """Czy zwykłe zapytanie (bez przeglądarki) dostaje stronę z kursami w ng-state."""
    w = dict(url=url)
    try:
        r = s.get(url, timeout=25, headers={'Accept': 'text/html,application/xhtml+xml', 'Accept-Language': 'pl-PL,pl;q=0.9'})
        w.update(kod=r.status_code, rozmiar=len(r.content), adres_po=r.url)
        m = re.search(r'<script[^>]*id="ng-state"[^>]*>(.*?)</script>', r.text, re.S)
        if m:
            ng = json.loads(m.group(1)); ry = _bc_rynki_ng(ng)
            w.update(ngstate=len(m.group(1)), rynkow=len(ry), rynki=[n for n, _ in ry], mecze=len(_bc_mecze_z_ng(ng)))
        else: w['poczatek'] = r.text[:1500]
    except Exception as e: w['blad'] = f'{type(e).__name__}: {e}'[:200]
    return w

BC_ZAKL_SPORTY = [('football', 'pilka-nozna-sfootball', None), ('tennis', 'tenis-stennis', None), ('ice_hockey', 'hokej-sice_hockey', None),
                  ('basketball', 'koszykowka-sbasketball', None), ('volleyball', 'siatkowka-svolleyball', None),
                  ('handball', 'pilka-reczna-shandball', None), ('martial_arts', 'sztuki-walki-smartial_arts', 'ufc-c15946'),
                  ('martial_arts', 'sztuki-walki-smartial_arts', 'ksw-c4509'), ('boxing', 'boks-sboxing', None),
                  ('darts', 'dart-sdarts', None), ('cs2', 'counter-strike-2-scs2', None)]

def betclic_zakladki():
    """Rozpoznanie 2: wszystkie zakładki rynków meczu (adres po kliknięciu, tekst, zapytania strony) dla kilku sportów,
    UFC i KSW + test, czy zwykłe zapytanie bez przeglądarki dostaje stronę z kursami. Wynik: surowe/betclic/zakladki.json."""
    import fcntl
    blokada = open('/opt/typer/cron.lock', 'w')
    print('Czekam, aż skończy się bieżący odczyt kursów (jeśli trwa)...')
    fcntl.flock(blokada, fcntl.LOCK_EX)
    s = ses()
    wyn = dict(czas=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), wersja='betclic-zakladki-1', sporty=[], requests=[])
    for sciezka in ('pilka-nozna-sfootball', 'tenis-stennis/pekin-atp-c36052', 'sztuki-walki-smartial_arts/ufc-c15946'):
        wyn['requests'].append(_bc_requests(s, f'{BC}/{sciezka}'))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        ctx = br.new_context(locale='pl-PL', timezone_id='Europe/Warsaw', user_agent=UA, viewport={'width': 1366, 'height': 900})
        pg = ctx.new_page()
        stan = dict(etap='start', odp=[], rozmiar=0)
        pg.on('response', _bc_odp(stan))
        for kod, slug, liga in BC_ZAKL_SPORTY:
            if time.time() - START > 25 * 60: break
            stan['odp'], stan['rozmiar'] = [], 0
            url = f'{BC}/{slug}' + (f'/{liga}' if liga else '')
            w = dict(kod=kod, strona=url, zakladki=[])
            try:
                stan['etap'] = 'lista'
                linki = _bc_strona(pg, url, przewin=2, czekaj=3000)
                mecze = _bc_mecze_z_ng(_bc_ng(pg))
                w['adres_po'] = pg.url; w['meczow'] = len(mecze)
                if liga: w['tekst_ligi'] = pg.inner_text('body')[:5000]
                teraz = dt.datetime.now(dt.timezone.utc)
                linki_m = {}
                for h in dict.fromkeys(linki):
                    m = re.search(r'-m(\d{6,})(?:[/?#]|$)', h)
                    if m: linki_m.setdefault(m.group(1), h)
                kand = []
                for m in mecze.values():
                    try: t = dt.datetime.fromisoformat(str(m['t'])[:19]).replace(tzinfo=dt.timezone.utc)
                    except Exception: continue
                    if m['live'] or t < teraz + dt.timedelta(minutes=40): continue
                    link = linki_m.get(m['id']) or (f"{BC}/{slug}/{_slug(m.get('liga'))}-c{m['liga_id']}/{_slug(m['nazwa'])}-m{m['id']}" if m.get('liga_id') else None)
                    if link: kand.append((t, m, link))
                kand.sort(key=lambda x: x[0])
                if not kand: w['blad'] = 'brak meczu przedmeczowego'
                else:
                    _, mecz, link = kand[min(1, len(kand) - 1)] if kod == 'football' else kand[0]
                    w['mecz'] = mecz; w['link'] = link
                    w['requests_mecz'] = _bc_requests(s, link)
                    stan['etap'] = 'mecz'
                    _bc_strona(pg, link, przewin=1, czekaj=3500)
                    w['adres_meczu'] = pg.url
                    w['rynki_ng'] = [n for n, _ in _bc_rynki_ng(_bc_ng(pg))]
                    zak = pg.evaluate(BC_ZAKL_JS); w['lista_zakladek'] = zak
                    nazwy = [z['t'] for z in zak if z['t'] not in ('MyCombi',)]
                    for nz in list(dict.fromkeys(nazwy))[:10]:
                        przed = len(stan['odp'])
                        stan['etap'] = 'zakladka ' + nz
                        z = dict(nazwa=nz)
                        try:
                            z['klik'] = pg.evaluate(BC_KLIK_ZAKL_JS, nz)
                            pg.wait_for_timeout(3000); z['rozwinieto'] = pg.evaluate(BC_ROZWIN_JS); pg.wait_for_timeout(1200)
                            z['adres'] = pg.url
                            tx = pg.inner_text('body'); i = tx.find('MyCombi')
                            z['tekst'] = tx[i:i + 25000] if i >= 0 else tx[:25000]
                            z['nowe_zapytania'] = [dict(url=o['url'], typ=o['typ'], rozmiar=o['rozmiar']) for o in stan['odp'][przed:]]
                            if z['adres'] != link and z['adres'] not in (x.get('adres') for x in w['zakladki']):
                                z['requests'] = _bc_requests(s, z['adres'])
                        except Exception as e: z['blad'] = str(e)[:200]
                        w['zakladki'].append(z)
            except Exception as e: w['blad'] = f'{type(e).__name__}: {e}'[:300]
            w['odpowiedzi'] = [o for o in stan['odp'] if not re.search(r'rive-canvas|casino|tvbet|content-pages|/games/', o['url'])][:40]
            wyn['sporty'].append(w)
            print(f"{kod} {liga or ''}: zakładek {len(w['zakladki'])}, rynków Top {len(w.get('rynki_ng', []))} – {round(time.time() - START)} s")
        br.close()
    wyn['sekund'] = round(time.time() - START)
    zapisz_github(f'{BC_KATALOG}/zakladki.json', wyn)
    print('Betclic – rozpoznanie zakładek zakończone,', wyn['sekund'], 's')

def main():
    if '--cron' in sys.argv:
        tryb_cron(); return
    if '--betclic2' in sys.argv:
        betclic_zakladki(); return
    if '--betclic' in sys.argv:
        betclic_rozpoznanie(); return
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
