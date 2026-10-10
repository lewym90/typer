"""Serwer analizy AI dla ręcznej analizy meczu w aplikacji (działa na polskim VPS za Caddy z HTTPS).
POST /analiza  {sport: pilka|tenis|walki, a, b, rozgrywki, start?, typ: {zaklad, szansa}?, szanse: {1,X,2}?, szansa_a?, szansa_b?}
GET  /zdrowie  → stan (limit, koszt w miesiącu)
Ten sam moduł AI co w programie (ai_raport / sporty), ten sam raport. Klucz Gemini w zmiennej GEMINI_API_KEY (plik /opt/typer/gemini_key).
Limity: AI_BUDZET_ZL (domyślnie 15 zł/mies. na analizy ręczne) i RECZNE_DZIENNIE (domyślnie 40)."""
import os, sys, json, time, threading, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('AI_BUDZET_ZL', '15')
os.environ.setdefault('AI_PRO_BUDZET_ZL', '30'); os.environ.setdefault('AI_PRO_RECZNE', '1')     # wersja 36: analiza ręczna Pro – 30 zł z łącznych 200 zł na Gemini Pro


def _dociagnij(nazwy=('analityk', 'analityk_ai', 'kursy_pl')):
    """start.sh pobiera stałą listę plików – nowsze moduły (wersja 34+) dociągamy tutaj, przy każdym starcie (restart codziennie 5:30)."""
    import urllib.request
    kat = os.path.dirname(os.path.abspath(__file__))
    for n in nazwy:
        try:
            with urllib.request.urlopen(f'https://raw.githubusercontent.com/lewym90/typer/main/typer/{n}.py?t={int(time.time())}', timeout=20) as r:
                tresc = r.read()
            if len(tresc) > 500: open(os.path.join(kat, n + '.py'), 'wb').write(tresc)
        except Exception as e: print('dociągnięcie', n, e, flush=True)


_dociagnij()
import pandas as pd
import ai_raport, sporty
try: import analityk_ai, analityk
except Exception as e: analityk_ai = analityk = None; print('Analityk Pro niedostępny:', e, flush=True)
RECZNE_PRO_DZIENNIE = int(os.environ.get('RECZNE_PRO_DZIENNIE', '2'))
_dzis_pro = {'data': None, 'n': 0}


def analiza_pro(z, sp, a, b, typ_t, start):
    """Ręczna analiza Pro (3 kroki): piłka – z teczką FotMob (jeśli mecz się znajdzie), tenis/walki – szanse A/B z kursów."""
    if not analityk_ai: return 503, {'blad': 'Analityk Pro jeszcze niedostępny na serwerze.'}
    d = time.strftime('%Y-%m-%d')
    if _dzis_pro['data'] != d: _dzis_pro.update(data=d, n=0)
    if _dzis_pro['n'] >= RECZNE_PRO_DZIENNIE: return 429, {'blad': f'Dzisiejszy limit analiz Pro ({RECZNE_PRO_DZIENNIE}) wyczerpany.'}
    if not analityk_ai.mozna(): return 429, {'blad': 'Wyczerpany budżet analiz Pro na dziś albo w tym miesiącu.'}
    with _blokada:
        if sp == 'pilka':
            sz = z.get('szanse') or {}
            try: rynek = {k: float(sz[k]) for k in ('1', 'X', '2')}
            except Exception: return 400, {'blad': 'Do analizy Pro potrzebne są kursy 1X2 (szanse).'}
            fm = None
            if analityk and start is not None:
                try:
                    mid, _ = analityk.fotmob_szukaj(a, b, start)
                    fm = analityk.fotmob_szczegoly(mid) if mid else None
                except Exception: fm = None
            lista = {'1': (f'wygra {a}', rynek['1']), 'X': ('remis', rynek['X']), '2': (f'wygra {b}', rynek['2']),
                     '1X': (f'{a} lub remis', rynek['1'] + rynek['X']), 'X2': (f'{b} lub remis', rynek['X'] + rynek['2']), '12': ('bez remisu', rynek['1'] + rynek['2'])}
            pro = analityk_ai.analiza_pilka(a, b, a, b, str(z.get('rozgrywki') or '')[:80], start if start is not None else pd.Timestamp.now(),
                                            fm, rynek, typ_t, lista)
        else:
            try: sa = float(z.get('szansa_a'))
            except Exception: return 400, {'blad': 'Do analizy Pro potrzebne są kursy (szansa A/B).'}
            m = dict(sport=sp, a=a, b=b, mecz=f'{a} – {b}', turniej=str(z.get('rozgrywki') or 'analiza ręczna')[:80], szansa_a=sa,
                     dzien=start.strftime('%d.%m') if start is not None else '', godzina=start.strftime('%H:%M') if start is not None else '')
            if typ_t: m['najpewniejszy'] = dict(zaklad=typ_t[0], szansa=typ_t[1])
            pro = analityk_ai.analiza_inne(m)
    if not pro: return 502, {'blad': 'Analityk Pro nie przygotował analizy (limit albo chwilowy błąd).', 'szczegoly': analityk_ai.STAN['bledy'][-2:]}
    _dzis_pro['n'] += 1
    return 200, {'pro': pro}

PORT = int(os.environ.get('PORT_AI', '8787'))
DOZWOLONE = ('https://lewym90.github.io',)
RECZNE_DZIENNIE = int(os.environ.get('RECZNE_DZIENNIE', '40'))
WERSJA = '3'
_blokada = threading.Lock()   # jedna analiza naraz (1 GB RAM, limit Gemini)
_dzis = {'data': None, 'n': 0}


def _licz_reczne():
    d = time.strftime('%Y-%m-%d')
    if _dzis['data'] != d: _dzis.update(data=d, n=0)
    return _dzis['n']


def analiza(z):
    sp = z.get('sport') if z.get('sport') in ('pilka', 'tenis', 'walki') else 'pilka'
    a, b = str(z.get('a') or '').strip()[:60], str(z.get('b') or '').strip()[:60]
    if not a or not b: return 400, {'blad': 'Brak nazw drużyn/zawodników.'}
    typ = z.get('typ') or {}
    typ_t = (str(typ.get('zaklad'))[:120], float(typ.get('szansa'))) if typ.get('zaklad') and typ.get('szansa') else None
    start = None
    if z.get('start'):
        try: start = pd.Timestamp(str(z['start'])[:16])
        except Exception: start = None
    if sp == 'pilka':
        kp = ai_raport.klucz_pamieci('pilka', a, b, str(start)[:10] if start is not None else '', typ_t[0] if typ_t else '')
    else:
        kp = ai_raport.klucz_pamieci(sp, a, b, (start.strftime('%d.%m') if start is not None else ''), typ_t[0] if typ_t else '')
    if z.get('pro'): return analiza_pro(z, sp, a, b, typ_t, start)
    z_p = ai_raport.z_pamieci(kp, 6)
    if z_p and (z_p.get('werdykt') or not typ_t): return 200, {'ai': z_p, 'z_pamieci': True}
    if _licz_reczne() >= RECZNE_DZIENNIE: return 429, {'blad': f'Dzisiejszy limit analiz ręcznych ({RECZNE_DZIENNIE}) wyczerpany.'}
    if ai_raport.zostalo_analiz() <= 0:
        b = ai_raport.blokada()
        return (503, {'blad': b.get('opis') or 'AI wstrzymane (konto Google).'}) if b else (429, {'blad': 'Wyczerpany miesięczny budżet analiz AI.'})
    with _blokada:
        if sp == 'pilka':
            sz = z.get('szanse') or {}
            sz = {k: float(sz[k]) for k in ('1', 'X', '2') if k in sz} or None
            ai = ai_raport.raport_ai(a, b, a, b, str(z.get('rozgrywki') or '')[:80], start, polski=sporty.polski(a, b) or 'Polska' in (a, b),
                                     typ=typ_t, szanse=sz if sz and len(sz) == 3 else None)
        else:
            m = dict(sport=sp, a=a, b=b, mecz=f'{a} – {b}', turniej=str(z.get('rozgrywki') or 'analiza ręczna')[:80],
                     dzien=start.strftime('%d.%m') if start is not None else 'najbliższy termin', godzina=start.strftime('%H:%M') if start is not None else '',
                     szansa_a=z.get('szansa_a'), szansa_b=z.get('szansa_b'), polski=sporty.polski(a, b), rynek_pl=False)
            if typ_t: m['najpewniejszy'] = dict(zaklad=typ_t[0], szansa=typ_t[1])
            try: m['naglowki'] = {'a': sporty.naglowki(a), 'b': sporty.naglowki(b)}
            except Exception: m['naglowki'] = {}
            ai = sporty.raport_ai(m, m['polski'])
        if ai and typ_t and not ai.get('werdykt'):   # brak oceny typu – jeszcze jedna próba z wyszukiwaniem
            ai2 = (ai_raport.raport_ai(a, b, a, b, str(z.get('rozgrywki') or '')[:80], start, polski=sporty.polski(a, b) or 'Polska' in (a, b),
                                       typ=typ_t, szanse=sz if sz and len(sz) == 3 else None, wymus=True) if sp == 'pilka'
                   else sporty.raport_ai(m, m['polski'], wymus=True))
            if ai2: ai = ai2
        if ai and typ_t and not ai.get('werdykt'):   # nadal bez oceny: AI nie znalazło świeżych źródeł – uczciwie: ostrożnie
            ai = dict(ai, werdykt='ryzyko', powod=ai.get('powod') or 'AI nie znalazło świeżych, pewnych źródeł o tym meczu – graj ostrożnie.')
    if not ai: return 502, {'blad': 'AI nie przygotowało analizy (limit, brak źródeł albo chwilowy błąd). Spróbuj za kilka minut.',
                             'szczegoly': ai_raport.STAN['bledy'][-2:]}
    _dzis['n'] += 1
    ai_raport.do_pamieci(kp, ai)
    return 200, {'ai': ai}


class H(BaseHTTPRequestHandler):
    def _cors(self):
        o = self.headers.get('Origin') or ''
        if o in DOZWOLONE or o.startswith('http://localhost'): self.send_header('Access-Control-Allow-Origin', o)
        self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, kod, obj):
        tresc = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(kod); self._cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8'); self.send_header('Content-Length', str(len(tresc)))
        self.end_headers(); self.wfile.write(tresc)

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        if self.path.startswith('/zdrowie'):
            return self._json(200, dict(ok=True, wersja=WERSJA, klucz=bool(ai_raport.KLUCZ), reczne_dzis=_licz_reczne(), limit_dzienny=RECZNE_DZIENNIE,
                                        koszt_miesiac_zl=round(ai_raport.koszt_miesiac(), 2), budzet_zl=ai_raport.BUDZET_ZL,
                                        pro=dict(analityk_ai.STAN, reczne_dzis=_dzis_pro['n'], limit_dzienny=RECZNE_PRO_DZIENNIE) if analityk_ai else None))
        self._json(404, {'blad': 'nie ma'})

    def do_POST(self):
        if not self.path.startswith('/analiza'): return self._json(404, {'blad': 'nie ma'})
        o = self.headers.get('Origin') or ''
        if o and o not in DOZWOLONE and not o.startswith('http://localhost'): return self._json(403, {'blad': 'niedozwolone źródło'})
        try:
            n = min(int(self.headers.get('Content-Length') or 0), 20000)
            z = json.loads(self.rfile.read(n) or b'{}')
            kod, wyn = analiza(z)
        except Exception as e:
            traceback.print_exc(); kod, wyn = 500, {'blad': f'Błąd serwera: {e}'[:200]}
        self._json(kod, wyn)

    def log_message(self, f, *a): print(time.strftime('%H:%M:%S'), self.address_string(), f % a, flush=True)


if __name__ == '__main__':
    print('Serwer AI na porcie', PORT, 'klucz Gemini:', bool(ai_raport.KLUCZ), flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
