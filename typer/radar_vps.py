"""Radar typerów (wersja 40) – rozpoznanie serwisów z typami i zbieranie ich stron z polskiego serwera.
NIC nie trafia do aplikacji ani na Telegram – tylko dane do analizy (decyzja użytkownika 02.10).

Tryby (uruchamia cron serwera przez kursy_vps.py, pythonem z /opt/typer/pw):
  --radar rozpoznanie  raz dziennie (10–22): każdy serwis z ZRODLA – zwykłe zapytanie, przy blokadzie/pustej stronie
                       przeglądarka (zapytania JSON strony), linki z typami (1 poziom w głąb), ile naszych meczów widać,
                       liczby wyglądające na kursy, bloby JSON → surowe/radar/spis.json, surowe/radar/<zrodlo>.json,
                       strony HTML (gzip) → surowe/radar/strony/; lista stron wartych zbierania → /opt/typer/radar_strony.json.
  --radar migawka      3× dziennie (ok. 10:30, 14:30, 18:30): strony z radar_strony.json zapisywane na serwerze
                       /opt/typer/radar/<data>/<GGMM>_<zrodlo>_<n>.html.gz (90 dni) – archiwum typów z chwili przed meczem,
                       na którym później policzymy każdemu typerowi wynik i przewagę nad kursem zamknięcia.
Ręcznie: cd /opt/typer && curl -fsS https://raw.githubusercontent.com/lewym90/typer/main/typer/kursy_vps.py -o k.py && pw/bin/python k.py --radar rozpoznanie
"""
import os, re, json, gzip, time, base64, shutil, datetime as dt
from urllib.parse import urljoin, urlparse

KAT = 'surowe/radar'
LIMIT_S = 900                              # ok. 15 min (cron trzyma blokadę)
START = time.time()
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')
LISTA_STRON = '/opt/typer/radar_strony.json'
ARCH = '/opt/typer/radar'
DNI_ARCH = 90

# rodzaj: weryfikowane = platformy, które zapisują typ przed meczem i rozliczają same; spolecznosc = polskie serwisy/fora;
# algorytm = przewidywania z modeli (osobny „głos”), eksperci = redakcyjne typy portali
ZRODLA = {
    # --- platformy z weryfikacją typów
    'blogabet':      ('weryfikowane', ['https://blogabet.com/tips', 'https://blogabet.com/tipsters', 'https://blogabet.com/']),
    'tipstrr':       ('weryfikowane', ['https://tipstrr.com/tips', 'https://tipstrr.com/tipsters', 'https://tipstrr.com/free-tips']),
    'olbg':          ('weryfikowane', ['https://www.olbg.com/betting-tips/Football/1', 'https://www.olbg.com/betting-tips/Tennis/2',
                                       'https://www.olbg.com/betting-tips']),
    'bettingexpert': ('weryfikowane', ['https://www.bettingexpert.com/tips', 'https://www.bettingexpert.com/football']),
    'oddsportal':    ('weryfikowane', ['https://www.oddsportal.com/predictions/', 'https://www.oddsportal.com/community/']),
    'bet2invest':    ('weryfikowane', ['https://bet2invest.com/tipsters', 'https://bet2invest.com/']),
    'tipsto':        ('weryfikowane', ['https://www.tipsto.io/', 'https://www.tipsto.io/tips']),
    'betrush':       ('weryfikowane', ['https://betrush.com/', 'https://betrush.com/tipsters']),
    # --- polskie serwisy i fora
    'typersi':       ('spolecznosc', ['https://typersi.pl/', 'https://typersi.pl/jutro/tomorrow', 'https://typersi.pl/wczoraj/yesterday']),
    'zagranie':      ('spolecznosc', ['https://zagranie.com/typy-bukmacherskie/', 'https://zagranie.com/']),
    'betonline':     ('spolecznosc', ['https://betonline.net.pl/', 'https://betonline.net.pl/forum/']),
    'legalni':       ('spolecznosc', ['https://legalnibukmacherzy.pl/typy-bukmacherskie/']),
    'meczyki':       ('eksperci',    ['https://www.meczyki.pl/typy-bukmacherskie', 'https://www.meczyki.pl/typy']),
    'zawodtyper':    ('eksperci',    ['https://zawodtyper.pl/', 'https://zawodtyper.pl/typy-bukmacherskie/']),
    'goal':          ('eksperci',    ['https://www.goal.pl/typy-bukmacherskie/']),
    'typydnia':      ('spolecznosc', ['https://typydnia.net.pl/']),
    'trafnetypy':    ('eksperci',    ['https://trafnetypy.com/']),
    'sportytrader':  ('eksperci',    ['https://www.sportytrader.com/en/betting-tips/football/', 'https://www.sportytrader.pl/typy/']),
    # --- przewidywania z modeli
    'forebet':       ('algorytm',    ['https://www.forebet.com/en/football-tips-and-predictions-for-today',
                                      'https://www.forebet.com/en/football-tips-and-predictions-for-tomorrow']),
    'predictz':      ('algorytm',    ['https://www.predictz.com/predictions/', 'https://www.predictz.com/predictions/tomorrow/']),
    'windrawwin':    ('algorytm',    ['https://www.windrawwin.com/predictions/today/', 'https://www.windrawwin.com/predictions/tomorrow/']),
    'vitibet':       ('algorytm',    ['https://www.vitibet.com/index.php?clanek=quicktips&sekce=fotbal&lang=en']),
    'betensured':    ('algorytm',    ['https://www.betensured.com/']),
}
SLOWA_LINK = re.compile(r'typ|tip|predict|pick|prognoz|kupon|ranking|tipster|typer|forecast', re.I)
BLOKADA = re.compile(r'cf-chl|just a moment|captcha|access denied|attention required|are you a robot|ddos-guard|request blocked', re.I)
KURS = re.compile(r'(?<![\d.,])(?:1[.,]\d{2}|[2-9][.,]\d{2}|1\d[.,]\d{2})(?![\d])')
BLOBY = [r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>',
         r'window\.__([A-Z_]{3,40})__\s*=\s*(\{.*?\});?\s*</script>', r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
         r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>']


def zostalo(): return LIMIT_S - (time.time() - START)
def _blad(e): return f'{type(e).__name__}: {str(e)[:200]}'


def _teraz_pl():
    try:
        from zoneinfo import ZoneInfo; return dt.datetime.now(ZoneInfo('Europe/Warsaw'))
    except Exception: return dt.datetime.now(dt.timezone(dt.timedelta(hours=2)))


def tekst_strony(html):
    t = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', ' ', html)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', t))


# ------------------------------------------------------------------ nasze mecze widoczne na stronie
def slowa_meczow(A, KP):
    """[(sport, opis, [słowa gospodarza], [słowa gościa])] – znaczące słowa nazw (z wariantem polskim)."""
    out = []
    N = A.nasze(KP)
    for sp, lista in N.items():
        for m in lista:
            ws = []
            for nazwa in (m['h'], m['a']):
                sl = set()
                for w in KP.warianty(nazwa):
                    sl |= {x for x in KP.tokeny(w) if len(x) >= 4 and x not in ('kobiety', 'united', 'city', 'town')}
                ws.append(sorted(sl))
            if ws[0] and ws[1]: out.append((sp, f"{m['h']} – {m['a']}", ws[0], ws[1]))
    return out


def nasze_na_stronie(txt, SL, KP):
    low = ' ' + ' '.join(KP.tokeny(txt[:600000])) + ' '
    tr = []
    for sp, opis, a, b in SL:
        if any(f' {x} ' in low for x in a) and any(f' {x} ' in low for x in b): tr.append(opis)
    return tr


def opis_html(html, SL, KP, url):
    t = tekst_strony(html)
    w = dict(tytul=(re.search(r'<title[^>]*>(.*?)</title>', html, re.S | re.I) or [None, ''])[1].strip()[:150],
             tekst_znakow=len(t), kursy_liczb=len(KURS.findall(t)), blokada=bool(BLOKADA.search(html[:20000])) and len(t) < 20000,
             tabel=html.count('<table'), wierszy=html.count('<tr'))
    tr = nasze_na_stronie(t, SL, KP); w['nasze_mecze'] = len(tr); w['nasze_przyklad'] = tr[:8]
    w['tekst_poczatek'] = t[:1500]
    bl = []
    for wz in BLOBY:
        for m in re.finditer(wz, html, re.S | re.I):
            b = m.group(m.lastindex)
            x = dict(rodzaj=(m.group(1) if m.lastindex == 2 else wz[13:40]), dlugosc=len(b), poczatek=b[:800])
            bl.append(x)
            if len(bl) >= 6: break
    w['bloby'] = bl
    dom = urlparse(url).netloc.replace('www.', '')
    linki = []
    for h in re.findall(r'href=["\']([^"\'#]+)["\']', html, re.I):
        u = urljoin(url, h)
        if dom in urlparse(u).netloc and SLOWA_LINK.search(urlparse(u).path or '') and u not in linki and u != url: linki.append(u)
    w['linki_z_typami'] = linki[:40]
    return w


def zapisz_bajty(V, sciezka, bajty):
    """Jak V.zapisz_github, ale dla danych binarnych (gzip)."""
    try: token = open(V.TOKEN_PLIK).read().strip()
    except Exception: return False
    import requests
    h = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'typer-vps'}
    api = f'https://api.github.com/repos/{V.REPO}/contents/{sciezka}'
    for _ in range(2):
        r = requests.get(api, headers=h, timeout=20)
        sha = r.json().get('sha') if r.status_code == 200 else None
        body = dict(message=f'Radar typerów {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M}', content=base64.b64encode(bajty).decode())
        if sha: body['sha'] = sha
        r = requests.put(api, headers=h, json=body, timeout=40)
        if r.status_code in (200, 201): return True
        time.sleep(4)
    return False


# ------------------------------------------------------------------ rozpoznanie
def rozpoznaj_zrodlo(nazwa, rodzaj, adresy, s, B, A, SL, KP, V):
    w = dict(zrodlo=nazwa, rodzaj=rodzaj, strony=[], przegladarka=[], glebiej=[])
    najlepsza = None
    for u in adresy:
        if zostalo() < 60: w['przerwane'] = 'brak czasu'; break
        info, r = A.req(s, u, headers={'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'})
        if r is not None and r.text:
            info['adres_koncowy'] = r.url
            info.update(opis_html(r.text, SL, KP, r.url))
            info['html'] = r.text
        w['strony'].append(info)
    ok = [x for x in w['strony'] if x.get('kod') == 200 and not x.get('blokada') and x.get('tekst_znakow', 0) > 3000]
    # przeglądarka, gdy zwykłe zapytania nic nie dały (blokada, pusta strona renderowana skryptem, zero naszych meczów)
    potrzebna = not ok or all(x.get('nasze_mecze', 0) == 0 and x.get('kursy_liczb', 0) < 10 for x in ok)
    if potrzebna and B.ctx and zostalo() > 120:
        for u in adresy[:2]:
            pg, info, odp = B.strona(u, czekaj=6000, filtr=r'api|json|tips|predict|feed|graphql|ajax|data', limit_odp=50)
            if pg is not None:
                try:
                    html = pg.content(); info['adres_koncowy'] = pg.url
                    info.update(opis_html(html, SL, KP, pg.url)); info['html'] = html
                except Exception as e: info['blad_tresci'] = _blad(e)
                try: pg.close()
                except Exception: pass
            js = []
            for (url, st, t) in odp:
                if not t or len(t) < 200: continue
                if not (t.lstrip()[:1] in '{[' ): continue
                tr = nasze_na_stronie(t, SL, KP)
                js.append(dict(url=url[:300], kod=st, dlugosc=len(t), nasze_mecze=len(tr), kursy_liczb=len(KURS.findall(t)), poczatek=t[:2500]))
            info['odpowiedzi_json'] = sorted(js, key=lambda x: (-x['nasze_mecze'], -x['dlugosc']))[:15]
            w['przegladarka'].append(info)
    # jeden poziom w głąb: linki z typami ze strony z najlepszym wynikiem
    wszystkie = [x for x in w['strony'] + w['przegladarka'] if x.get('linki_z_typami')]
    if wszystkie:
        najlepsza = max(wszystkie, key=lambda x: (x.get('nasze_mecze', 0), x.get('kursy_liczb', 0)))
        widziane = set(adresy)
        for u in najlepsza['linki_z_typami']:
            if len(w['glebiej']) >= 4 or zostalo() < 90: break
            if u in widziane: continue
            widziane.add(u)
            info, r = A.req(s, u, headers={'Accept': 'text/html,*/*;q=0.8'})
            if r is not None and r.text:
                info.update(opis_html(r.text, SL, KP, r.url)); info['html'] = r.text
            w['glebiej'].append(info)
    return w


def _metoda(x, w):
    return 'przegladarka' if x in w['przegladarka'] else 'requests'


def rozpoznanie(V, KP, s):
    import analityk_vps as A
    s.headers.update({'User-Agent': UA, 'Accept-Language': 'pl-PL,pl;q=0.9,en;q=0.6'})
    SL = slowa_meczow(A, KP)
    spis = dict(czas=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), wersja='radar-1', nasze_mecze=len(SL), zrodla={})
    B = A.Przegladarka(); spis['przegladarka'] = B.blad or 'ok'
    do_zbierania = []
    for nazwa, (rodzaj, adresy) in ZRODLA.items():
        if zostalo() < 60: spis['zrodla'][nazwa] = dict(pominiete='brak czasu'); continue
        t0 = time.time()
        try: w = rozpoznaj_zrodlo(nazwa, rodzaj, adresy, s, B, A, SL, KP, V)
        except Exception as e: w = dict(zrodlo=nazwa, rodzaj=rodzaj, blad=_blad(e), strony=[], przegladarka=[], glebiej=[])
        w['sekund'] = round(time.time() - t0)
        strony = w['strony'] + w['przegladarka'] + w['glebiej']
        # HTML do repozytorium (gzip) – 3 najciekawsze strony źródła, do pisania czytników
        cenne = sorted([x for x in strony if x.get('html') and x.get('kod') == 200 and not x.get('blokada')],
                       key=lambda x: (-x.get('nasze_mecze', 0), -x.get('kursy_liczb', 0)))
        pliki = []
        for i, x in enumerate(cenne[:3]):
            gz = gzip.compress(x['html'][:2_000_000].encode('utf-8', 'ignore'))
            p = f'{KAT}/strony/{nazwa}_{i}.html.gz'
            if zapisz_bajty(V, p, gz): pliki.append(dict(plik=p, url=x.get('adres_koncowy') or x.get('url'), metoda=_metoda(x, w)))
        for x in cenne:
            if x.get('nasze_mecze', 0) > 0 or x.get('kursy_liczb', 0) >= 20:
                do_zbierania.append(dict(zrodlo=nazwa, rodzaj=rodzaj, url=x.get('adres_koncowy') or x.get('url'), metoda=_metoda(x, w)))
        st = dict(rodzaj=rodzaj, sekund=w['sekund'], blad=w.get('blad'),
                  requests=[(x.get('kod'), x.get('rozmiar'), x.get('blokada'), x.get('nasze_mecze'), x.get('kursy_liczb')) for x in w['strony']],
                  przegladarka=[(x.get('kod'), x.get('blokada'), x.get('nasze_mecze'), len(x.get('odpowiedzi_json') or []),
                                 max([j['nasze_mecze'] for j in x.get('odpowiedzi_json') or []] or [0])) for x in w['przegladarka']],
                  glebiej=[(x.get('url', '')[-80:], x.get('kod'), x.get('nasze_mecze'), x.get('kursy_liczb')) for x in w['glebiej']],
                  max_naszych=max([x.get('nasze_mecze', 0) for x in strony] or [0]), pliki=pliki)
        spis['zrodla'][nazwa] = st
        for x in strony: x.pop('html', None)
        try: V.zapisz_github(f'{KAT}/{nazwa}.json', w)
        except Exception as e: st['zapis'] = _blad(e)
        print(nazwa, rodzaj, round(time.time() - START), 's | naszych meczów max', st['max_naszych'], '| requests', st['requests'])
    B.zamknij()
    # lista do codziennego zbierania (najwyżej 6 stron na źródło, przeglądarka maks. 8 stron łącznie)
    widz, lista, prz = set(), [], 0
    for x in do_zbierania:
        if x['url'] in widz or sum(1 for y in lista if y['zrodlo'] == x['zrodlo']) >= 6: continue
        if x['metoda'] == 'przegladarka':
            if prz >= 8: continue
            prz += 1
        widz.add(x['url']); lista.append(x)
    json.dump(dict(czas=spis['czas'], strony=lista), open(LISTA_STRON, 'w'), ensure_ascii=False, indent=1)
    spis['do_zbierania'] = len(lista); spis['sekund'] = round(time.time() - START)
    try: spis['archiwum'] = _stan_archiwum()
    except Exception: pass
    V.zapisz_github(f'{KAT}/spis.json', spis)
    print('Radar – rozpoznanie zapisane:', spis['sekund'], 's, stron do zbierania:', len(lista))


# ------------------------------------------------------------------ migawki (archiwum na serwerze)
def _stan_archiwum():
    if not os.path.isdir(ARCH): return dict(dni=0, plikow=0, mb=0)
    dni = sorted(os.listdir(ARCH)); n = b = 0
    for d in dni:
        for f in os.listdir(os.path.join(ARCH, d)):
            n += 1; b += os.path.getsize(os.path.join(ARCH, d, f))
    return dict(dni=len(dni), od=dni[0] if dni else None, plikow=n, mb=round(b / 1e6, 1))


def migawka(V, KP, s):
    try: lista = json.load(open(LISTA_STRON))['strony']
    except Exception: print('Radar – brak listy stron (najpierw rozpoznanie)'); return
    if shutil.disk_usage('/opt').free < 1.5e9: print('Radar – mało miejsca na dysku, pomijam'); return
    teraz = _teraz_pl(); kat = os.path.join(ARCH, teraz.strftime('%Y-%m-%d')); os.makedirs(kat, exist_ok=True)
    # sprzątanie: starsze niż 90 dni
    granica = (teraz - dt.timedelta(days=DNI_ARCH)).strftime('%Y-%m-%d')
    for d in os.listdir(ARCH):
        if d < granica: shutil.rmtree(os.path.join(ARCH, d), ignore_errors=True)
    s.headers.update({'User-Agent': UA, 'Accept-Language': 'pl-PL,pl;q=0.9,en;q=0.6'})
    import analityk_vps as A
    B = None; ok = zle = 0; licz = {}
    for x in lista:
        if zostalo() < 40: break
        html = None
        if x['metoda'] == 'przegladarka':
            if B is None: B = A.Przegladarka()
            pg, info, _ = B.strona(x['url'], czekaj=5000, filtr=r'^$', limit_odp=0)
            if pg is not None:
                try: html = pg.content()
                except Exception: pass
                try: pg.close()
                except Exception: pass
        else:
            info, r = A.req(s, x['url'], headers={'Accept': 'text/html,*/*;q=0.8'})
            if r is not None and r.status_code == 200: html = r.text
        if not html or len(html) < 2000: zle += 1; continue
        n = licz[x['zrodlo']] = licz.get(x['zrodlo'], 0) + 1
        plik = os.path.join(kat, f"{teraz:%H%M}_{x['zrodlo']}_{n}.html.gz")
        with gzip.open(plik, 'wt', encoding='utf-8') as f:
            f.write(f"<!-- radar url={x['url']} czas={dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M:%S}Z -->\n")
            f.write(html)
        ok += 1
    if B: B.zamknij()
    stan = _stan_archiwum(); stan.update(ostatnia=f'{teraz:%Y-%m-%d %H:%M}', zapisane=ok, nieudane=zle, zrodla=licz)
    print('Radar – migawka:', json.dumps(stan, ensure_ascii=False))
    try: V.zapisz_github(f'{KAT}/migawki.json', stan)
    except Exception as e: print('Radar – zapis stanu:', e)


def krok(V, KP, s, tryb):
    if tryb == 'migawka': migawka(V, KP, s)
    else: rozpoznanie(V, KP, s)
