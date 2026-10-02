"""Analityk – rozpoznanie źródeł danych z polskiego serwera (wersja 33).
Uruchamiane raz dziennie przez cron serwera (9–22, po odczycie kursów) albo ręcznie:
    cd /opt/typer && pw/bin/python k.py --analityk
Dla dzisiejszych meczów z listy (dzis/inne/lista_vps) sprawdza, czy i jak da się pobrać:
  • FotMob     – składy (przewidywane/potwierdzone), nieobecni, formacje, oceny, sędzia, tabela;
  • Sofascore  – to samo + „missing players”, forma; tenis: ostatnie mecze zawodnika (przerwa), MMA;
  • Transfermarkt – kontuzje i pauzy, wartości zawodników (waga braków);
  • UFCStats   – statystyki stylu zawodników (ciosy/min zadane i przyjęte, obalenia, obrona, wiek, zasięg, ostatnia walka).
Najpierw zwykłe zapytania (requests), gdy blokada – przeglądarka (Playwright z /opt/typer/pw).
Wyniki (przycięte próbki + dopasowanie do naszych meczów): surowe/analityk/{spis,fotmob,sofascore,transfermarkt,ufcstats}.json."""
import os, re, json, time, datetime as dt

KAT = 'surowe/analityk'
LIMIT_S = 840                      # cały tryb maks. ok. 14 min (cron trzyma blokadę – w tym czasie nie ma odczytu kursów)
START = time.time()
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')


def zostalo(): return LIMIT_S - (time.time() - START)


def przytnij(o, lst=30, txt=1500, g=0, gmax=12):
    """Próbka danych do zapisu: listy do `lst` elementów, teksty do `txt` znaków, głębokość do `gmax`."""
    if g > gmax: return f'<{type(o).__name__}>'
    if isinstance(o, dict): return {str(k): przytnij(v, lst, txt, g + 1, gmax) for k, v in list(o.items())[:80]}
    if isinstance(o, list):
        w = [przytnij(v, lst, txt, g + 1, gmax) for v in o[:lst]]
        if len(o) > lst: w.append(f'… (+{len(o) - lst})')
        return w
    if isinstance(o, str) and len(o) > txt: return o[:txt] + '…'
    return o


def _blad(e): return f'{type(e).__name__}: {str(e)[:200]}'


def req(s, url, **kw):
    """(info, odpowiedź|None) – status, rozmiar, czas; bez wyjątku."""
    t0 = time.time()
    try:
        r = s.get(url, timeout=kw.pop('timeout', 20), **kw)
        return dict(url=url, kod=r.status_code, typ=r.headers.get('content-type', '')[:60], rozmiar=len(r.content),
                    ms=int((time.time() - t0) * 1000)), r
    except Exception as e: return dict(url=url, kod=None, blad=_blad(e)), None


def jjson(r):
    try: return r.json()
    except Exception: return None


# ------------------------------------------------------------------ nasze mecze i dopasowanie
def nasze(KP):
    out = {'pilka': [], 'tenis': [], 'walki': []}
    for m in KP.nasze_mecze(z_listy=True):
        try:
            sp, eid, h, a, start = m[0], m[1], m[2], m[3], m[4]
            t = KP._utc_nasz(start)
        except Exception: continue
        if sp in out: out[sp].append(dict(event_id=eid, h=h, a=a, start=str(start), utc=t))
    teraz = dt.datetime.now(dt.timezone.utc)
    for sp in out: out[sp] = sorted([m for m in out[sp] if m['utc'] > teraz - dt.timedelta(hours=3)], key=lambda m: m['utc'])
    return out


def dopasuj(KP, nasz, kandydaci, tol_min):
    """kandydaci: [(id, gosp, gosc, czas_utc, dane)] → (kandydat, zgodność, odwrócone) albo None."""
    best = None
    for k in kandydaci:
        if k[3] is None or abs((k[3] - nasz['utc']).total_seconds()) / 60 > tol_min: continue
        s1 = min(KP.podobne_w(nasz['h'], k[1]), KP.podobne_w(nasz['a'], k[2]))
        s2 = min(KP.podobne_w(nasz['h'], k[2]), KP.podobne_w(nasz['a'], k[1]))
        s, odw = (s1, False) if s1 >= s2 else (s2, True)
        if s >= 0.55 and (best is None or s > best[1]): best = (k, round(s, 3), odw)
    return best


def _ts(x):
    try:
        if isinstance(x, (int, float)): return dt.datetime.fromtimestamp(x / (1000 if x > 1e11 else 1), dt.timezone.utc)
        x = str(x).replace('Z', '+00:00')
        t = dt.datetime.fromisoformat(x)
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except Exception: return None


# ------------------------------------------------------------------ przeglądarka
class Przegladarka:
    def __init__(self):
        self.pw = self.br = self.ctx = None; self.blad = None
        try:
            from playwright.sync_api import sync_playwright
            self.pw = sync_playwright().start()
            self.br = self.pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            self.ctx = self.br.new_context(locale='pl-PL', timezone_id='Europe/Warsaw', user_agent=UA, viewport={'width': 1366, 'height': 900})
        except Exception as e: self.blad = _blad(e)

    def strona(self, url, czekaj=4000, filtr=None, limit_odp=60):
        """Otwiera stronę, zbiera odpowiedzi JSON (adresy z `filtr`). Zwraca (page, info, [(url, status, tekst)])."""
        if not self.ctx: return None, dict(url=url, blad=self.blad or 'brak przeglądarki'), []
        pg = self.ctx.new_page(); odp = []; nag = []
        def na_odp(r):
            try:
                if (filtr is None or re.search(filtr, r.url)) and len(odp) < limit_odp: odp.append(r)
            except Exception: pass
        def na_zap(r):
            try:
                if filtr and re.search(filtr, r.url) and len(nag) < 10:
                    h = r.headers; nag.append(dict(url=r.url[:200], naglowki={k: (v[:80] if isinstance(v, str) else v) for k, v in h.items()
                                                                            if k.lower() not in ('cookie', 'user-agent')}))
            except Exception: pass
        pg.on('response', na_odp); pg.on('request', na_zap)
        info = dict(url=url)
        try:
            r = pg.goto(url, wait_until='domcontentloaded', timeout=45000)
            info['kod'] = r.status if r else None; pg.wait_for_timeout(czekaj)
            for t in ('Zgadzam się', 'Akceptuj', 'Accept', 'AGREE', 'Akceptuję', 'Consent', 'Zaakceptuj wszystkie'):
                try:
                    b = pg.get_by_role('button', name=re.compile(t, re.I))
                    if b.count(): b.first.click(timeout=1500); pg.wait_for_timeout(1500); info['zgoda'] = t; break
                except Exception: pass
            info['adres_koncowy'] = pg.url; info['tytul'] = pg.title()[:120]
        except Exception as e: info['blad'] = _blad(e)
        teksty = []
        for r in odp:
            try:
                t = r.text()
                teksty.append((r.url, r.status, t))
            except Exception: teksty.append((r.url, r.status, None))
        info['naglowki_zapytan'] = nag[:6]
        return pg, info, teksty

    def fetch(self, pg, url, ile=3_000_000):
        """fetch z wnętrza strony (to samo pochodzenie, ciasteczka strony)."""
        try:
            return pg.evaluate("""async ([u, ile]) => { try { const r = await fetch(u, {credentials: 'include'});
                const t = await r.text(); return {kod: r.status, tekst: t.slice(0, ile)}; } catch (e) { return {kod: null, blad: String(e)}; } }""", [url, ile])
        except Exception as e: return dict(kod=None, blad=_blad(e))

    def zamknij(self):
        for x in (self.ctx, self.br):
            try: x and x.close()
            except Exception: pass
        try: self.pw and self.pw.stop()
        except Exception: pass


# ------------------------------------------------------------------ FotMob
def _fotmob_mecze(o, out):
    """Wszystkie mecze z odpowiedzi FotMob (różne wersje API): id, gospodarz, gość, czas."""
    if isinstance(o, dict):
        h, a = o.get('home'), o.get('away')
        if o.get('id') and isinstance(h, dict) and isinstance(a, dict) and (h.get('name') or h.get('longName')):
            st = o.get('status') or {}
            t = _ts(st.get('utcTime') or o.get('time') or o.get('utcTime') or o.get('timeTS'))
            out[str(o['id'])] = (str(o['id']), h.get('longName') or h.get('name'), a.get('longName') or a.get('name'), t,
                                 dict(liga=o.get('leagueName') or o.get('tournamentStage'), url=o.get('pageUrl')))
        for v in o.values(): _fotmob_mecze(v, out)
    elif isinstance(o, list):
        for v in o: _fotmob_mecze(v, out)
    return out


def _fotmob_szczegoly(d):
    """Z odpowiedzi szczegółów meczu FotMob – to, co ważne dla Analityka (bez całej reszty)."""
    w = {}
    if not isinstance(d, dict): return w
    c = d.get('content') or {}
    lu = c.get('lineup') or c.get('lineups') or {}
    w['lineup_klucze'] = list(lu)[:40] if isinstance(lu, dict) else type(lu).__name__
    if isinstance(lu, dict):
        w['lineup_typ'] = lu.get('lineupType') or lu.get('type')
        for strona in ('homeTeam', 'awayTeam'):
            t = lu.get(strona) or {}
            if not isinstance(t, dict): continue
            w[strona] = dict(formacja=t.get('formation'), ocena=t.get('rating'), klucze=list(t)[:40],
                             wyjsciowi=przytnij(t.get('starters'), 12, 300, gmax=4), lawka_ile=len(t.get('subs') or []),
                             nieobecni=przytnij(t.get('unavailable'), 20, 300, gmax=5), trener=przytnij(t.get('coach'), 5, 200, gmax=3))
    mf = c.get('matchFacts') or {}
    w['matchFacts_klucze'] = list(mf)[:40] if isinstance(mf, dict) else None
    if isinstance(mf, dict): w['infoBox'] = przytnij(mf.get('infoBox'), 20, 300, gmax=4)
    w['content_klucze'] = list(c)[:40]
    w['general'] = przytnij(d.get('general'), 20, 200, gmax=3)
    w['header'] = przytnij(d.get('header'), 10, 200, gmax=4)
    w['tabela_jest'] = bool(c.get('table'))
    w['h2h_jest'] = bool(c.get('h2h'))
    return w


def fotmob(s, B, N, KP, dzien):
    wyn = dict(zrodlo='FotMob', proby=[], dopasowane=[], niedopasowane=[])
    ymd = dzien.strftime('%Y%m%d')
    adresy = [f'https://www.fotmob.com/api/data/matches?date={ymd}&timezone=Europe%2FWarsaw&ccode3=POL',
              f'https://www.fotmob.com/api/matches?date={ymd}&timezone=Europe%2FWarsaw&ccode3=POL',
              f'https://www.fotmob.com/api/data/matches?date={ymd}']
    mecze = {}
    for u in adresy:
        info, r = req(s, u, headers={'Referer': 'https://www.fotmob.com/', 'Accept': 'application/json'})
        j = jjson(r) if r is not None and info.get('kod') == 200 else None
        if j: info['mecze'] = len(_fotmob_mecze(j, mecze))
        elif r is not None: info['poczatek'] = r.text[:200]
        wyn['proby'].append(info)
    wyn['requests_dziala'] = bool(mecze)
    pg = None
    if not mecze and zostalo() > 120 and B.ctx:      # przeglądarka: strona sama pobiera listę meczów
        pg, info, odp = B.strona(f'https://www.fotmob.com/?date={ymd}', 6000, filtr=r'fotmob\.com/api/')
        wyn['przegladarka'] = info
        wyn['przegladarka_odpowiedzi'] = [dict(url=u[:200], kod=k, rozmiar=len(t or '')) for u, k, t in odp][:30]
        for u, k, t in odp:
            try:
                if t and k == 200: _fotmob_mecze(json.loads(t), mecze)
            except Exception: pass
        if not mecze and pg:   # __NEXT_DATA__ strony
            try:
                nd = pg.evaluate("() => { const e = document.getElementById('__NEXT_DATA__'); return e ? e.textContent : null; }")
                if nd: _fotmob_mecze(json.loads(nd), mecze); wyn['next_data'] = True
            except Exception as e: wyn['next_data_blad'] = _blad(e)
    wyn['meczow'] = len(mecze)
    kand = list(mecze.values())
    for m in N['pilka']:
        d = dopasuj(KP, m, kand, 40)
        if not d: wyn['niedopasowane'].append(f"{m['h']} – {m['a']} {m['start']}"); continue
        wyn['dopasowane'].append(dict(nasz=f"{m['h']} – {m['a']}", event_id=m['event_id'], start=m['start'], fotmob_id=d[0][0],
                                      fotmob=f'{d[0][1]} – {d[0][2]}', zgodnosc=d[1], odwrocone=d[2], url=d[0][4].get('url')))
    # szczegóły do 3 meczów: requests, potem przeglądarka
    for x in wyn['dopasowane'][:3]:
        if zostalo() < 90: break
        mid = x['fotmob_id']; x['szczegoly'] = {}
        for u in (f'https://www.fotmob.com/api/data/matchDetails?matchId={mid}', f'https://www.fotmob.com/api/matchDetails?matchId={mid}'):
            info, r = req(s, u, headers={'Referer': 'https://www.fotmob.com/', 'Accept': 'application/json'})
            j = jjson(r) if r is not None and info.get('kod') == 200 else None
            x['szczegoly'].setdefault('requests', []).append(info)
            if j: x['szczegoly']['dane'] = _fotmob_szczegoly(j); x['szczegoly']['skad'] = 'requests'; break
        if 'dane' not in x['szczegoly'] and getattr(B, 'ctx', None):
            url = f"https://www.fotmob.com{x['url']}" if x.get('url') else f'https://www.fotmob.com/match/{mid}'
            p2, info, odp = B.strona(url, 6000, filtr=r'fotmob\.com/api/')
            x['szczegoly']['przegladarka'] = dict(info, odpowiedzi=[dict(url=u[:200], kod=k, rozmiar=len(t or '')) for u, k, t in odp][:25])
            for u, k, t in odp:
                if t and k == 200 and 'matchDetails' in u:
                    try: x['szczegoly']['dane'] = _fotmob_szczegoly(json.loads(t)); x['szczegoly']['skad'] = 'przeglądarka (api)'; break
                    except Exception: pass
            if 'dane' not in x['szczegoly'] and p2:
                try:
                    nd = p2.evaluate("() => { const e = document.getElementById('__NEXT_DATA__'); return e ? e.textContent : null; }")
                    if nd:
                        j = json.loads(nd); pp = ((j.get('props') or {}).get('pageProps') or {})
                        x['szczegoly']['next_klucze'] = list(pp)[:30]
                        x['szczegoly']['dane'] = _fotmob_szczegoly(pp if 'content' in pp else (pp.get('data') or pp)); x['szczegoly']['skad'] = '__NEXT_DATA__'
                except Exception as e: x['szczegoly']['next_blad'] = _blad(e)
            try: p2 and p2.close()
            except Exception: pass
    try: pg and pg.close()
    except Exception: pass
    return wyn


# ------------------------------------------------------------------ Sofascore
SOFA = 'https://api.sofascore.com/api/v1'
SOFA_WWW = 'https://www.sofascore.com/api/v1'


class Sofa:
    """Pobieranie z Sofascore: requests (api.sofascore.com, www) albo – przy blokadzie – fetch z wnętrza strony."""
    def __init__(self, s, B):
        self.s, self.B, self.tryb, self.pg, self.log = s, B, None, None, []

    def get(self, sciezka):
        if self.tryb in (None, 'api', 'www'):
            for tryb, baza in (('api', SOFA), ('www', SOFA_WWW)):
                if self.tryb not in (None, tryb): continue
                info, r = req(self.s, baza + sciezka, headers={'Referer': 'https://www.sofascore.com/', 'Origin': 'https://www.sofascore.com',
                                                               'Accept': 'application/json'})
                if len(self.log) < 30: self.log.append(dict(info, tryb=tryb))
                if r is not None and info.get('kod') == 200:
                    self.tryb = tryb; return jjson(r)
                if r is not None and info.get('kod') == 404 and self.tryb: return None
            if self.tryb in ('api', 'www'): return None
        if self.B.ctx and self.pg is None and zostalo() > 60:
            self.pg, info, _ = self.B.strona('https://www.sofascore.com/', 5000)
            self.log.append(dict(info, tryb='przeglądarka – strona'))
        if self.pg is None: return None
        w = self.B.fetch(self.pg, '/api/v1' + sciezka)
        if len(self.log) < 40: self.log.append(dict(url=sciezka, kod=w.get('kod'), tryb='przeglądarka', blad=w.get('blad')))
        if w.get('kod') == 200:
            self.tryb = 'przegladarka'
            try: return json.loads(w['tekst'])
            except Exception: return None
        return None


def _sofa_kand(j):
    out = []
    for e in (j or {}).get('events') or []:
        try: out.append((str(e['id']), e['homeTeam']['name'], e['awayTeam']['name'], _ts(e.get('startTimestamp')),
                         dict(turniej=((e.get('tournament') or {}).get('name')), dom_id=e['homeTeam'].get('id'), gosc_id=e['awayTeam'].get('id'),
                              status=(e.get('status') or {}).get('type'))))
        except Exception: pass
    return out


def _sofa_sklad(j):
    if not isinstance(j, dict): return None
    w = dict(potwierdzone=j.get('confirmed'), klucze=list(j)[:20])
    for strona in ('home', 'away'):
        t = j.get(strona) or {}
        gr = t.get('players') or []
        w[strona] = dict(formacja=t.get('formation'), zawodnikow=len(gr),
                         wyjsciowi=[dict(nazwa=(p.get('player') or {}).get('name'), poz=(p.get('player') or {}).get('position'),
                                         ocena=((p.get('statistics') or {}).get('rating'))) for p in gr if not p.get('substitute')][:11],
                         nieobecni=przytnij(t.get('missingPlayers'), 25, 300, gmax=4))
    return w


def _ostatnie(j, przed):
    """Ostatnie zakończone mecze zawodnika/drużyny przed `przed`: daty, turnieje, dni przerwy."""
    ev = [e for e in ((j or {}).get('events') or []) if (e.get('status') or {}).get('type') == 'finished']
    ev = sorted(ev, key=lambda e: e.get('startTimestamp') or 0, reverse=True)
    out = [dict(data=_ts(e.get('startTimestamp')).strftime('%Y-%m-%d') if _ts(e.get('startTimestamp')) else None,
                turniej=(e.get('tournament') or {}).get('name'), mecz=f"{(e.get('homeTeam') or {}).get('name')} – {(e.get('awayTeam') or {}).get('name')}",
                zwyciezca=e.get('winnerCode')) for e in ev[:8]]
    dni = None
    if ev and _ts(ev[0].get('startTimestamp')): dni = round((przed - _ts(ev[0]['startTimestamp'])).total_seconds() / 86400, 1)
    m14 = sum(1 for e in ev if _ts(e.get('startTimestamp')) and (przed - _ts(e['startTimestamp'])).days <= 14)
    return dict(ostatnie=out, dni_od_ostatniego=dni, mecze_14_dni=m14)


def sofascore(s, B, N, KP, dzien):
    wyn = dict(zrodlo='Sofascore', pilka={}, tenis={}, walki={})
    S = Sofa(s, B)
    daty = sorted({dzien.strftime('%Y-%m-%d')} | {m['utc'].astimezone(dzien.tzinfo).strftime('%Y-%m-%d') for sp in N for m in N[sp]})[:3]
    for sp, slug, tol in (('pilka', 'football', 40), ('tenis', 'tennis', 360), ('walki', 'mma', 720)):
        if zostalo() < 60: break
        w = wyn[sp]; kand = []
        for d in daty:
            j = S.get(f'/sport/{slug}/scheduled-events/{d}')
            k = _sofa_kand(j); kand += k; w.setdefault('wydarzen', {})[d] = len(k)
            if j and 'ksztalt' not in w: w['ksztalt'] = przytnij(((j.get('events') or [{}])[:1]), 1, 200, gmax=4)
        w['dopasowane'], w['niedopasowane'] = [], []
        for m in N[sp]:
            d = dopasuj(KP, m, kand, tol)
            if not d: w['niedopasowane'].append(f"{m['h']} – {m['a']} {m['start']}"); continue
            w['dopasowane'].append(dict(nasz=f"{m['h']} – {m['a']}", event_id=m['event_id'], start=m['start'], sofa_id=d[0][0],
                                        sofa=f'{d[0][1]} – {d[0][2]}', zgodnosc=d[1], odwrocone=d[2], _k=d[0], _utc=m['utc']))
        for x in w['dopasowane'][:3]:
            if zostalo() < 60: break
            k = x.pop('_k'); przed = x.pop('_utc')
            if sp == 'pilka':
                x['sklady'] = _sofa_sklad(S.get(f"/event/{k[0]}/lineups"))
                ev = S.get(f"/event/{k[0]}") or {}
                e = ev.get('event') or {}
                x['sedzia'] = przytnij(e.get('referee'), 5, 200, gmax=3); x['stadion'] = ((e.get('venue') or {}).get('name'))
                x['forma'] = przytnij(S.get(f"/event/{k[0]}/pregame-form"), 10, 200, gmax=4)
            else:
                for strona, tid in (('a', k[4].get('dom_id')), ('b', k[4].get('gosc_id'))):
                    if tid: x[strona] = dict(nazwa=k[1] if strona == 'a' else k[2], **_ostatnie(S.get(f'/team/{tid}/events/last/0'), przed))
        for x in w['dopasowane']: x.pop('_k', None); x.pop('_utc', None)
    wyn['tryb'] = S.tryb; wyn['log'] = S.log
    try: S.pg and S.pg.close()
    except Exception: pass
    return wyn


# ------------------------------------------------------------------ Transfermarkt
TM = 'https://www.transfermarkt.com'


def transfermarkt(s, B, N, KP):
    wyn = dict(zrodlo='Transfermarkt', proby=[], druzyny=[])
    h = {'Referer': TM + '/', 'Accept-Language': 'en-US,en;q=0.8'}
    info, r = req(s, TM + '/', headers=h); wyn['proby'].append(info)
    druzyny = []
    for m in N['pilka'][:3]: druzyny += [m['h'], m['a']]
    for nazwa in druzyny[:4]:
        if zostalo() < 60: break
        x = dict(nasza=nazwa)
        info, r = req(s, f'{TM}/schnellsuche/ergebnis/schnellsuche?query={nazwa.replace(" ", "+")}', headers=h); x['szukaj'] = info
        html = r.text if (r is not None and info.get('kod') == 200) else ''
        if not html and B.ctx:      # blokada – przeglądarka
            pg, inf, _ = B.strona(f'{TM}/schnellsuche/ergebnis/schnellsuche?query={nazwa.replace(" ", "+")}', 3000)
            x['szukaj_przegladarka'] = inf
            try: html = pg.content() if pg else ''
            except Exception: html = ''
            try: pg and pg.close()
            except Exception: pass
        mm = re.search(r'href="/([a-z0-9\-]+)/startseite/verein/(\d+)', html)
        if not mm: x['wynik'] = 'nie znaleziono klubu'; wyn['druzyny'].append(x); continue
        slug, vid = mm.group(1), mm.group(2); x['klub'] = dict(slug=slug, id=vid)
        info, r = req(s, f'{TM}/{slug}/sperrenundverletzungen/verein/{vid}', headers=h); x['kontuzje'] = info
        if r is not None and info.get('kod') == 200:
            t = r.text
            x['kontuzje']['wierszy'] = len(re.findall(r'<tr class="(?:odd|even)"', t))
            x['kontuzje']['zawodnicy'] = re.findall(r'title="([^"]{3,40})" href="/[^"]+/profil/spieler/\d+', t)[:12]
            x['kontuzje']['powody'] = re.findall(r'<td class="hauptlink">([^<]{3,60})</td>', t)[:12]
        info, r = req(s, f'{TM}/{slug}/kader/verein/{vid}/plus/1', headers=h); x['kadra'] = info
        if r is not None and info.get('kod') == 200:
            t = r.text
            x['kadra']['wartosci'] = re.findall(r'class="rechts hauptlink"><a[^>]*>([^<]+)</a>', t)[:30]
            x['kadra']['zawodnicy'] = re.findall(r'title="([^"]{3,40})" href="/[^"]+/profil/spieler/\d+', t)[:30]
        wyn['druzyny'].append(x)
    return wyn


# ------------------------------------------------------------------ UFCStats
UFC = 'http://ufcstats.com'
POLA_UFC = {'Height': 'wzrost', 'Weight': 'waga', 'Reach': 'zasieg', 'STANCE': 'pozycja', 'DOB': 'urodzony', 'SLpM': 'ciosy_zadane_min',
            'Str. Acc.': 'celnosc', 'SApM': 'ciosy_przyjete_min', 'Str. Def': 'obrona_ciosow', 'TD Avg.': 'obalenia_15min',
            'TD Acc.': 'obalenia_skutecznosc', 'TD Def.': 'obrona_obalen', 'Sub. Avg.': 'poddania_15min'}


def _ufc_zawodnik(html):
    w = {}
    for k, nazwa in POLA_UFC.items():
        m = re.search(r'<i class="b-list__box-item-title[^"]*">\s*' + re.escape(k) + r':?\s*</i>\s*([^<]+?)\s*<', html, re.I)
        if m: w[nazwa] = m.group(1).strip()
    m = re.search(r'Record:\s*([\d]+-[\d]+-[\d]+)', html)
    if m: w['bilans'] = m.group(1)
    daty = re.findall(r'([A-Z][a-z]{2}\. \d{2}, \d{4})', html)
    w['daty_walk'] = daty[:6]
    return w


def ufcstats(s, B, N, KP):
    wyn = dict(zrodlo='UFCStats', proby=[], gale=[], dopasowane=[], niedopasowane=[])
    gale, html = [], ''
    for u in (f'{UFC}/statistics/events/upcoming', 'https://ufcstats.com/statistics/events/upcoming', f'{UFC}/statistics/events/upcoming?page=all'):
        info, r = req(s, u, headers={'Accept': 'text/html,application/xhtml+xml', 'Accept-Language': 'en-US,en;q=0.9'})
        if r is not None:
            html = r.text; info['poczatek'] = re.sub(r'\s+', ' ', html[:1200])
            gale = re.findall(r'href="(https?://(?:www\.)?ufcstats\.com/event-details/[0-9a-f]+)"[^>]*>\s*([^<]+?)\s*</a>', html)[:2]
        wyn['proby'].append(info)
        if gale: break
    if not gale and getattr(B, 'ctx', None):          # strona z ochroną – przeglądarka
        pg, inf, _ = B.strona(f'{UFC}/statistics/events/upcoming', 5000)
        try: html = pg.content() if pg else ''
        except Exception: html = ''
        inf['poczatek'] = re.sub(r'\s+', ' ', html[:1200]); wyn['przegladarka'] = inf
        gale = re.findall(r'href="(https?://(?:www\.)?ufcstats\.com/event-details/[0-9a-f]+)"[^>]*>\s*([^<]+?)\s*</a>', html)[:2]
        try: pg and pg.close()
        except Exception: pass
    if not gale: return wyn
    walki = []
    for url, nazwa in gale:
        info, r = req(s, url); g = dict(nazwa=nazwa, url=url, kod=info.get('kod'))
        if r is not None and info.get('kod') == 200:
            for wiersz in re.findall(r'<tr class="b-fight-details__table-row[^"]*"[^>]*>(.*?)</tr>', r.text, re.S):
                z = re.findall(r'href="(https?://(?:www\.)?ufcstats\.com/fighter-details/[0-9a-f]+)"[^>]*>\s*([^<]+?)\s*</a>', wiersz)
                if len(z) >= 2: walki.append(dict(gala=nazwa, a=z[0][1], b=z[1][1], a_url=z[0][0], b_url=z[1][0]))
            g['walk'] = sum(1 for w in walki if w['gala'] == nazwa)
        wyn['gale'].append(g)
    def sim(n, w): return max(KP.podobne_w(n, w['a']), KP.podobne_w(n, w['b']))
    wybrane = []
    for m in N['walki']:
        if str(m['event_id']).startswith('ksw-'): continue
        best = max(walki, key=lambda w: min(sim(m['h'], w), sim(m['a'], w)), default=None)
        if best and min(sim(m['h'], best), sim(m['a'], best)) >= 0.6:
            wybrane.append((m, best)); wyn['dopasowane'].append(dict(nasz=f"{m['h']} – {m['a']}", event_id=m['event_id'], ufc=f"{best['a']} – {best['b']}"))
        else: wyn['niedopasowane'].append(f"{m['h']} – {m['a']} {m['start']}")
    if not wybrane: wybrane = [(None, w) for w in walki[:2]]      # dziś bez UFC – próbka formatu z najbliższej gali
    for m, w in wybrane[:4]:
        if zostalo() < 45: break
        x = dict(walka=f"{w['a']} – {w['b']}", gala=w['gala'], nasz=bool(m))
        for strona in ('a', 'b'):
            info, r = req(s, w[f'{strona}_url'])
            x[strona] = dict(nazwa=w[strona], kod=info.get('kod'), **(_ufc_zawodnik(r.text) if r is not None and info.get('kod') == 200 else {}))
        wyn.setdefault('statystyki', []).append(x)
    return wyn


# ------------------------------------------------------------------ typerzy (wersja 39) – zrzut stron do zbudowania czytnika typów
def typersi(s, B, N, KP):
    wyn = dict(zrodlo='Typersi.pl', strony=[])
    for u in ('https://typersi.pl/', 'https://typersi.pl/jutro/tomorrow', 'https://typersi.pl/wczoraj/yesterday'):
        info, r = req(s, u, headers={'Accept-Language': 'pl-PL,pl;q=0.9'})
        if r is not None and info.get('kod') == 200:
            t = r.text; i = t.find('<table')
            info['tabel'] = t.count('<table'); info['wierszy'] = t.count('<tr')
            info['html'] = t[i:i + 60000] if i >= 0 else t[:20000]
        wyn['strony'].append(info)
    return wyn


# ------------------------------------------------------------------ start
def rozpoznanie(V, KP, s):
    """V = moduł kursy_vps (zapis do repozytorium), KP = kursy_pl (nasze mecze, dopasowanie), s = sesja requests."""
    s.headers.update({'User-Agent': UA})
    try:
        from zoneinfo import ZoneInfo; dzien = dt.datetime.now(ZoneInfo('Europe/Warsaw'))
    except Exception: dzien = dt.datetime.now(dt.timezone(dt.timedelta(hours=2)))
    N = nasze(KP)
    spis = dict(czas=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), wersja='analityk-1',
                nasze={sp: len(v) for sp, v in N.items()}, zrodla={})
    try: spis['ip'] = s.get('https://api.ipify.org', timeout=10).text
    except Exception: pass
    B = Przegladarka(); spis['przegladarka'] = B.blad or 'ok'
    for nazwa, fn in (('ufcstats', lambda: ufcstats(s, B, N, KP)), ('sofascore', lambda: sofascore(s, B, N, KP, dzien)),
                      ('fotmob', lambda: fotmob(s, B, N, KP, dzien)), ('transfermarkt', lambda: transfermarkt(s, B, N, KP))):
        # Typersi od wersji 40 w Radarze typerów (radar_vps.py)
        t0 = time.time()
        if zostalo() < 45: spis['zrodla'][nazwa] = dict(pominiete='brak czasu'); continue
        try: w = fn()
        except Exception as e: w = dict(blad=_blad(e))
        w['sekund'] = round(time.time() - t0)
        spis['zrodla'][nazwa] = _streszczenie(nazwa, w)
        try: V.zapisz_github(f'{KAT}/{nazwa}.json', przytnij(w, 40, 70000 if nazwa == 'typersi' else 3000, gmax=14))
        except Exception as e: spis['zrodla'][nazwa]['zapis'] = _blad(e)
        print(nazwa, 'gotowe', round(time.time() - START), 's', json.dumps(spis['zrodla'][nazwa], ensure_ascii=False, default=str)[:300])
    B.zamknij()
    spis['sekund'] = round(time.time() - START)
    V.zapisz_github(f'{KAT}/spis.json', spis)
    print('Analityk – rozpoznanie zapisane:', spis['sekund'], 's')


def _streszczenie(nazwa, w):
    z = dict(sekund=w.get('sekund'), blad=w.get('blad'))
    if nazwa == 'fotmob':
        z.update(requests=w.get('requests_dziala'), meczow=w.get('meczow'), dopasowane=len(w.get('dopasowane') or []),
                 niedopasowane=len(w.get('niedopasowane') or []),
                 szczegoly=[(x.get('szczegoly') or {}).get('skad') for x in (w.get('dopasowane') or [])[:3]])
    elif nazwa == 'sofascore':
        z.update(tryb=w.get('tryb'), **{sp: dict(dopasowane=len((w.get(sp) or {}).get('dopasowane') or []),
                                                  niedopasowane=len((w.get(sp) or {}).get('niedopasowane') or [])) for sp in ('pilka', 'tenis', 'walki')})
    elif nazwa == 'transfermarkt':
        z.update(start=[p.get('kod') for p in w.get('proby') or []],
                 kluby=[((x.get('klub') or {}).get('slug'), (x.get('kontuzje') or {}).get('kod'), (x.get('kontuzje') or {}).get('wierszy'))
                        for x in w.get('druzyny') or []])
    elif nazwa == 'ufcstats':
        z.update(start=[p.get('kod') for p in w.get('proby') or []], gale=len(w.get('gale') or []), dopasowane=len(w.get('dopasowane') or []),
                 zawodnicy_ze_statystykami=sum(1 for x in w.get('statystyki') or [] for k in ('a', 'b') if (x.get(k) or {}).get('ciosy_zadane_min')))
    return z
