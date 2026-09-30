"""Kursy z polskiego serwera (VPS) – STS, Fortuna, Betclic PL.
Serwer pobiera ten plik z repozytorium przy każdym uruchomieniu (cron co 2 h), więc zmiany wprowadza się tylko w repozytorium.
Wynik trafia do repozytorium przez GitHub API (token w /opt/typer/token).

WERSJA 1 = ROZPOZNANIE: sprawdza, skąd strony biorą kursy (adresy danych w kodzie strony, osadzone dane),
i zapisuje docs/data/kursy_vps_test.json. Na tej podstawie powstaną właściwe czytniki."""
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
    for plik in ('typer/kursy_pl.py', 'typer/nazwy.py', 'docs/data/dzis.json', 'docs/data/inne.json'):
        r = s.get(f'{RAW}/{plik}?t={int(time.time())}', timeout=20); r.raise_for_status()
        open(os.path.join(KATALOG, os.path.basename(plik)), 'wb').write(r.content)
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
    mecze, turnieje = {}, set()
    for sp, sid in ids.items():
        for filtr in ('today', 'tomorrow'):
            try:
                j = s.get(f'{FAPI}/structure/api/v1_0/sport/{sid}/tournaments?categories=true&timeFilter={filtr}', timeout=20).json()
                turnieje |= {(sp, tid) for tid, _ in _id_w(j, 'ufo:tour:', [])}
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
                mecze[f['id']] = dict(id=f['id'], sp=sp, h=h, a=a, t=dt.datetime.fromtimestamp(f['startDatetime'] / 1000, dt.timezone.utc))
        time.sleep(0.15)
    diag['meczow_fortuny'] = len(mecze)
    return list(mecze.values())

def _fortuna_klucze(rynki, odwr, sport):
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
                if n in ('zwycięzca meczu', 'wynik meczu', 'zwycięzca', 'mecz') and on in ('1', '2'):
                    kl = 'A' if (on == '1') != odwr else 'B'
                    k.setdefault(kl, c)
    return k

def czytnik():
    s = ses(); diag = dict(bledy=[]); wynik = {}
    try:
        KP = _przygotuj(s)
        nasze = KP.nasze_mecze()
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
            k = _fortuna_klucze(rynki, odwr, 'pilka' if sp == 'pilka' else 'duel')
            if k: wynik[eid] = dict(fortuna=dict(id=f['id'], nazwa=f'{f["h"]} - {f["a"]}', zgodnosc=round(sc, 2), kursy=k))
            time.sleep(0.2)
        diag['rynki_nazwy'] = rynki_nazwy
    except Exception as e:
        diag['bledy'].append(f'{type(e).__name__}: {e}'[:200])
    dane = dict(czas=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), wersja='czytnik-1',
                bukmacherzy=dict(fortuna=dict(ok=not diag['bledy'] or bool(wynik), dopasowane=len(wynik))),
                mecze=wynik, diag=diag, sekund=round(time.time() - START))
    print('Fortuna: dopasowane', len(wynik), 'z', diag.get('nasze_mecze'), '| błędy:', diag['bledy'][:3])
    zapisz_github('docs/data/kursy_vps.json', dane)

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
    if '--test' not in sys.argv and not any(a.startswith('--siec') or a in ('--zrzut', '--sts') for a in sys.argv[1:]):
        czytnik(); return
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
