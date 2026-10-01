"""Serwer analizy AI dla ręcznej analizy meczu w aplikacji (działa na polskim VPS za Caddy z HTTPS).
POST /analiza  {sport: pilka|tenis|walki, a, b, rozgrywki, start?, typ: {zaklad, szansa}?, szanse: {1,X,2}?, szansa_a?, szansa_b?}
GET  /zdrowie  → stan (limit, koszt w miesiącu)
Ten sam moduł AI co w programie (ai_raport / sporty), ten sam raport. Klucz Gemini w zmiennej GEMINI_API_KEY (plik /opt/typer/gemini_key).
Limity: AI_BUDZET_ZL (domyślnie 15 zł/mies. na analizy ręczne) i RECZNE_DZIENNIE (domyślnie 40)."""
import os, sys, json, time, threading, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('AI_BUDZET_ZL', '15')
import pandas as pd
import ai_raport, sporty

PORT = int(os.environ.get('PORT_AI', '8787'))
DOZWOLONE = ('https://lewym90.github.io',)
RECZNE_DZIENNIE = int(os.environ.get('RECZNE_DZIENNIE', '40'))
WERSJA = '1'
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
    z_p = ai_raport.z_pamieci(kp, 6)
    if z_p: return 200, {'ai': z_p, 'z_pamieci': True}
    if _licz_reczne() >= RECZNE_DZIENNIE: return 429, {'blad': f'Dzisiejszy limit analiz ręcznych ({RECZNE_DZIENNIE}) wyczerpany.'}
    if ai_raport.zostalo_analiz() <= 0: return 429, {'blad': 'Wyczerpany miesięczny budżet analiz AI.'}
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
                                        koszt_miesiac_zl=round(ai_raport.koszt_miesiac(), 2), budzet_zl=ai_raport.BUDZET_ZL))
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
