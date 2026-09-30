"""Kursy polskich bukmacherów – WERSJA TESTOWA (rozpoznanie).
Nic nie zmienia w typach ani w aplikacji. Sprawdza, czy strony Betclic, STS, Fortuny i Superbetu
wpuszczają serwer GitHuba i skąd biorą kursy. Wynik: docs/data/kursy_test.json + krótko status.json → kursy_pl.
Uruchamiany jako osobny krok workflow (błąd tutaj nie dotyka reszty programu).
Częstotliwość: przy push / ręcznym uruchomieniu zawsze, z harmonogramu co ok. 2 godziny."""
import os, re, json, time, datetime as dt
from zoneinfo import ZoneInfo

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
LIMIT_CZASU = 150          # sekundy na cały test
TIMEOUT = 12               # sekundy na jedno zapytanie
CO_ILE_MIN = 115           # z harmonogramu: nie częściej niż co ok. 2 h

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/128.0.0.0 Safari/537.36')
NAGL = {'User-Agent': UA, 'Accept-Language': 'pl-PL,pl;q=0.9,en;q=0.6',
        'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8'}

def _dzis_super():
    d = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')
    return f'{d}%2000:00:00'

BUKMACHERZY = {
    'betclic': dict(
        strony=['https://www.betclic.pl/', 'https://www.betclic.pl/pilka-nozna-s1'],
        api=['https://offer.cdn.betclic.pl/api/pub/v4/events?application=2&countrycode=pl&language=pl&limit=20&offset=0&sitecode=plpl&sportIds=1',
             'https://offer.cdn.betclic.pl/api/pub/v2/sports/1?application=2&countrycode=pl&language=pl&sitecode=plpl',
             'https://offer.cdn.begmedia.com/api/pub/v4/events?application=2&countrycode=pl&language=pl&limit=20&offset=0&sitecode=plpl&sportIds=1',
             'https://offer.cdn.begmedia.com/api/pub/v2/sports/1?application=2&countrycode=pl&language=pl&sitecode=plpl']),
    'sts': dict(
        strony=['https://www.sts.pl/', 'https://www.sts.pl/pilka-nozna'],
        api=[]),
    'fortuna': dict(
        strony=['https://www.efortuna.pl/', 'https://www.efortuna.pl/zaklady-bukmacherskie/pilka-nozna'],
        api=[]),
    'superbet': dict(
        strony=['https://superbet.pl/', 'https://superbet.pl/zaklady-bukmacherskie/pilka-nozna'],
        api=[f'https://production-superbet-offer-pl.freetls.fastly.net/sb-pl/api/v2/pl-PL/events/by-date?currentStatus=active&offerState=prematch&startDate={_dzis_super()}',
             f'https://production-superbet-offer-pl.freetls.fastly.net/sb-offer/api/v2/pl-PL/events/by-date?currentStatus=active&offerState=prematch&startDate={_dzis_super()}',
             f'https://production-superbet-offer-pl.freetls.fastly.net/v2/pl-PL/events/by-date?currentStatus=active&offerState=prematch&startDate={_dzis_super()}',
             'https://production-superbet-offer-pl.freetls.fastly.net/sb-pl/api/v2/pl-PL/sport/5/tournaments']),
}

BLOKADA = ['cf-chl', 'challenge-platform', 'captcha', 'access denied', 'attention required', 'incapsula',
           '_incapsula_', 'akamai', 'request unsuccessful', 'are you a robot', 'jestes robotem', 'jesteś robotem',
           'niedostępna w twoim kraju', 'not available in your country', 'geoblock']
SLOWA_API = re.compile(r'''["'`](https?://[a-z0-9.\-]+(?:/[^"'`\s<>]*)?)["'`]''', re.I)
SLOWA_WZGL = re.compile(r'''["'`](/(?:api|rest|offer|oferta|sb-|sportsbook|feed|odds|web/v|v\d/)[^"'`\s<>]{2,120})["'`]''', re.I)
INTERESUJACE = re.compile(r'api|offer|odds|sport|feed|market|event|prematch|graphql|cdn', re.I)
KURS = re.compile(r'(?<![\d.,])(?:1[.,]\d{2}|[2-9][.,]\d{2}|1\d[.,]\d{2})(?![\d])')
TEKST = re.compile(r'(?i)(?:odds|price|kurs|rate|value)["\']?\s*[:=]\s*["\']?(\d{1,3}\.\d{1,3})')

START = time.time()

def _czas_zostal(): return LIMIT_CZASU - (time.time() - START)

def _sesje():
    s = {}
    import requests
    r = requests.Session(); r.headers.update(NAGL); s['requests'] = r
    try:
        from curl_cffi import requests as cr
        c = cr.Session(impersonate='chrome'); c.headers.update({'Accept-Language': NAGL['Accept-Language']}); s['chrome'] = c
    except Exception as e:
        s['_brak_chrome'] = str(e)[:120]
    return s

def _pobierz(ses, url, json_=False):
    t0 = time.time()
    h = dict(Accept='application/json, text/plain, */*') if json_ else {}
    try:
        r = ses.get(url, headers=h, timeout=TIMEOUT, allow_redirects=True)
        txt = r.text if len(r.content) < 6_000_000 else r.text[:6_000_000]
        return dict(kod=r.status_code, url=str(r.url), typ=r.headers.get('content-type', '')[:60],
                    serwer=(r.headers.get('server') or '')[:40],
                    cdn=[k for k in r.headers if k.lower() in ('cf-ray', 'x-akamai-transformed', 'x-iinfo', 'x-cdn', 'x-served-by', 'x-amz-cf-id', 'via')][:5],
                    rozmiar=len(r.content), ms=int((time.time() - t0) * 1000)), txt
    except Exception as e:
        return dict(kod=None, blad=f'{type(e).__name__}: {str(e)[:160]}', ms=int((time.time() - t0) * 1000)), ''

def _analiza_html(txt, druzyny):
    low = txt.lower()
    info = dict(blokada=[b for b in BLOKADA if b in low][:4],
                next_data='__NEXT_DATA__' in txt, nuxt='__NUXT__' in txt, ng_state='ng-state' in txt or 'serverApp-state' in txt,
                stan_okna=sorted(set(re.findall(r'window\.(__[A-Z_]{3,40}__)', txt)))[:6],
                liczb_jak_kursy=len(KURS.findall(txt)), pola_kursow=len(TEKST.findall(txt)),
                druzyny=[d for d in druzyny if d.lower() in low][:6],
                tytul=(re.search(r'<title[^>]*>(.*?)</title>', txt, re.S | re.I).group(1).strip()[:90]
                       if re.search(r'<title[^>]*>(.*?)</title>', txt, re.S | re.I) else None))
    return info

def _adresy(txt, baza):
    abs_ = {u for u in SLOWA_API.findall(txt) if INTERESUJACE.search(u) and not re.search(r'\.(png|jpe?g|svg|webp|gif|woff2?|css|ico)(\?|$)', u, re.I)}
    wzg = set(SLOWA_WZGL.findall(txt))
    skrypty = re.findall(r'<script[^>]+src=["\']([^"\']+\.js[^"\']*)["\']', txt, re.I)
    skrypty = [s if s.startswith('http') else (baza.rstrip('/') + '/' + s.lstrip('/') if not s.startswith('//') else 'https:' + s) for s in skrypty]
    return abs_, wzg, skrypty

def _probka_json(txt):
    try: j = json.loads(txt)
    except Exception: return dict(json=False, poczatek=txt[:300])
    def ksztalt(o, g=0):
        if g > 2: return type(o).__name__
        if isinstance(o, dict): return {k: ksztalt(v, g + 1) for k in list(o)[:12] for v in [o[k]]}
        if isinstance(o, list): return [len(o), ksztalt(o[0], g + 1) if o else None]
        return type(o).__name__
    return dict(json=True, ksztalt=ksztalt(j), poczatek=txt[:700])

def testuj_bukmachera(nazwa, cfg, sesje, druzyny):
    wynik = dict(strony=[], api=[], adresy_z_kodu=[], skrypty_przejrzane=0)
    abs_all, wzg_all, skr_all = set(), set(), []
    for url in cfg['strony']:
        for tryb in ('requests', 'chrome'):
            if tryb not in sesje or _czas_zostal() < 15: continue
            meta, txt = _pobierz(sesje[tryb], url)
            meta['tryb'] = tryb; meta['strona'] = url
            if txt: meta.update(_analiza_html(txt, druzyny))
            wynik['strony'].append(meta)
            if txt and meta.get('kod') == 200:
                a, w, s = _adresy(txt, re.match(r'https?://[^/]+', meta['url']).group(0))
                abs_all |= a; wzg_all |= w; skr_all += [x for x in s if x not in skr_all]
                if tryb == 'requests' and meta.get('liczb_jak_kursy', 0) > 30: break   # zwykłe zapytanie wystarcza
    # skrypty strony: szukamy adresów API z kursami
    ses = sesje.get('chrome') or sesje['requests']
    for s in skr_all[:8]:
        if _czas_zostal() < 25: break
        meta, txt = _pobierz(ses, s)
        wynik['skrypty_przejrzane'] += 1
        if txt:
            a, w, _ = _adresy(txt, '')
            abs_all |= a; wzg_all |= w
    wynik['adresy_z_kodu'] = sorted(abs_all)[:70]
    wynik['sciezki_z_kodu'] = sorted(wzg_all)[:50]
    for url in cfg['api']:
        for tryb in ('requests', 'chrome'):
            if tryb not in sesje or _czas_zostal() < 10: continue
            meta, txt = _pobierz(sesje[tryb], url, json_=True)
            meta['tryb'] = tryb; meta['adres'] = url
            if txt: meta.update(_probka_json(txt)); meta['druzyny'] = [d for d in druzyny if d.lower() in txt.lower()][:6]
            wynik['api'].append(meta)
            if meta.get('kod') == 200: break
    # krótka ocena
    ok_strona = any(x.get('kod') == 200 and not x.get('blokada') for x in wynik['strony'])
    ok_api = [x['adres'] for x in wynik['api'] if x.get('kod') == 200 and x.get('json')]
    kursy_html = max([x.get('liczb_jak_kursy', 0) for x in wynik['strony']] or [0])
    wynik['ocena'] = dict(strona_dostepna=ok_strona, api_dziala=len(ok_api), kursy_w_html=kursy_html,
                          blokada=sorted({b for x in wynik['strony'] for b in x.get('blokada', [])}),
                          kody=[f"{x.get('tryb')}:{x.get('kod')}" for x in wynik['strony']],
                          adresow_znalezionych=len(abs_all) + len(wzg_all))
    return wynik

def _druzyny_dnia():
    try: d = json.load(open(os.path.join(OUT, 'dzis.json')))
    except Exception: return []
    nazwy = []
    for m in (d.get('pewne') or []) + (d.get('mecze') or [])[:15]:
        for k in ('home', 'away', 'gospodarz', 'gosc', 'home_pl', 'away_pl'):
            v = m.get(k)
            if isinstance(v, str) and len(v) > 3 and v not in nazwy: nazwy.append(v)
        mecz = m.get('mecz')
        if isinstance(mecz, str):
            for v in re.split(r'\s+(?:-|–|vs\.?)\s+', mecz):
                if len(v) > 3 and v not in nazwy: nazwy.append(v.strip())
    for v in ('Legia', 'Lech', 'Jagiellonia', 'Barcelona', 'Real Madryt', 'Bayern', 'Arsenal', 'Liverpool', 'Inter', 'Juventus'):
        if v not in nazwy: nazwy.append(v)
    return nazwy[:30]

def czy_teraz(status):
    if os.environ.get('GITHUB_EVENT_NAME', 'push') != 'schedule': return True
    teraz = dt.datetime.now(dt.timezone.utc)
    ost = (status.get('kursy_pl') or {}).get('utc')
    if ost:
        try:
            if (teraz - dt.datetime.fromisoformat(ost)).total_seconds() < CO_ILE_MIN * 60: return False
        except Exception: pass
    return True

def main():
    try: st = json.load(open(os.path.join(OUT, 'status.json')))
    except Exception: st = {}
    if not czy_teraz(st): print('Kursy PL: za wcześnie (co ~2 h)'); return
    sesje = _sesje(); druzyny = _druzyny_dnia()
    wyniki = {}
    for nazwa, cfg in BUKMACHERZY.items():
        try: wyniki[nazwa] = testuj_bukmachera(nazwa, cfg, sesje, druzyny)
        except Exception as e: wyniki[nazwa] = dict(blad=f'{type(e).__name__}: {e}'[:200])
    teraz_pl = dt.datetime.now(ZoneInfo('Europe/Warsaw')).strftime('%Y-%m-%d %H:%M')
    pelny = dict(czas=teraz_pl, wersja='test-1', chrome=('chrome' in sesje) or sesje.get('_brak_chrome'),
                 druzyny_szukane=druzyny, sekund=round(time.time() - START), bukmacherzy=wyniki)
    with open(os.path.join(OUT, 'kursy_test.json'), 'w', encoding='utf-8') as f: json.dump(pelny, f, ensure_ascii=False, indent=1)
    krotko = {k: (v.get('ocena') or dict(blad=v.get('blad'))) for k, v in wyniki.items()}
    try: st = json.load(open(os.path.join(OUT, 'status.json')))   # świeży odczyt
    except Exception: st = {}
    st['kursy_pl'] = dict(czas=teraz_pl, utc=dt.datetime.now(dt.timezone.utc).isoformat(), tryb='test', sekund=pelny['sekund'], wyniki=krotko)
    with open(os.path.join(OUT, 'status.json'), 'w', encoding='utf-8') as f: json.dump(st, f, ensure_ascii=False)
    print('Kursy PL (test):', json.dumps(krotko, ensure_ascii=False))

if __name__ == '__main__':
    try: main()
    except Exception as e: print('Kursy PL – błąd testu (reszta programu działa):', e)
