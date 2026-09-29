"""Raport przedmeczowy po polsku pisany przez AI (Google Gemini, darmowy plan).
Model sam szuka wiadomości w Google (grounding); gdy wyszukiwanie jest niedostępne, dostaje to, co zebrał program
(nieobecni z BSD/Big Balls, zapowiedź BSD, nagłówki) i tylko to streszcza. Bez klucza GEMINI_API_KEY moduł nic nie robi."""
import os, re, json, time, requests
import pandas as pd

KLUCZ = os.environ.get('GEMINI_API_KEY', '')
URL = 'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent'
MODELE = ['gemini-flash-latest', 'gemini-flash-lite-latest']   # zapas, gdy nie uda się pobrać listy modeli
BEZ_SZUKANIA = 'Nie masz dostępu do internetu – opieraj się tylko na danych poniżej (a nazwy źródeł pomiń). '
MAKS_DZIENNIE = 45      # wszystkie zapytania (także ponowienia); modele Flash-Lite mają w darmowym planie ok. 500 dziennie
STAN = dict(klucz=bool(KLUCZ), zapytania=0, dzis=0, udane=0, model=None, wyszukiwanie=None, bledy=[])
PLIK_LICZNIKA = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data', 'ai_licznik.json')

def _licznik(dodaj=0):
    """Liczba zapytań do Gemini dzisiaj (czas pacyficzny – wtedy Google zeruje limit), zapisywana między uruchomieniami."""
    dzien = pd.Timestamp.now(tz='America/Los_Angeles').strftime('%Y-%m-%d')
    try: d = json.load(open(PLIK_LICZNIKA))
    except Exception: d = {}
    if d.get('data') != dzien: d = {'data': dzien, 'n': 0}
    if dodaj:
        d['n'] += dodaj
        try: json.dump(d, open(PLIK_LICZNIKA, 'w'))
        except Exception: pass
    STAN['dzis'] = d['n']
    return d['n']
_zly = set()            # modele, które odpowiedziały błędem limitu / brakiem – pomijamy do końca uruchomienia
_szukanie = {'ok': True}   # False, gdy Google odrzuca wyszukiwanie (400/403) – wtedy tylko streszczanie

def _blad(t):
    t = str(t)[:180]; print('AI:', t)
    if t not in STAN['bledy']: STAN['bledy'].append(t)

POLECENIE = """Jesteś dziennikarzem sportowym. Przygotuj po polsku krótki raport przed meczem piłkarskim:
{mecz} ({rozgrywki}), {kiedy} czasu polskiego. Gospodarz: {dom}. Gość: {gosc}.
{szukaj}
Interesuje mnie tylko to, co wpływa na mecz: kto na pewno nie zagra (kontuzja, zawieszenie, powołanie, odpoczynek),
kto jest niepewny, zapowiadana rotacja lub oszczędzanie zawodników, zmiana trenera, sytuacja w tabeli / o co grają,
zmęczenie (mecz 2–3 dni wcześniej lub zaraz potem ważniejszy mecz).
ZASADY: pisz wyłącznie to, co wynika ze źródeł z ostatnich 7 dni; nie zgaduj i nie dopisuj ogólników.
Informacje niepotwierdzone oznacz słowem „podobno”. Jeśli nic istotnego nie ma – napisz to wprost.
Nazwiska zawodników zostaw w oryginalnej pisowni.
{kontekst}
Odpowiedz WYŁĄCZNIE obiektem JSON (bez ```), dokładnie w tej postaci:
{{"podsumowanie": "2–4 zdania, maks. 450 znaków",
  "braki_gosp": ["Nazwisko (powód)", ...], "braki_gosc": ["Nazwisko (powód)", ...],
  "niepewni": ["Nazwisko (drużyna, powód)", ...],
  "powazne": true/false, "powazne_dla": "gosp" | "gosc" | "oba" | "brak",
  "uzasadnienie": "jedno zdanie – dlaczego braki są / nie są poważne"}}
"powazne" = true tylko, gdy brakuje co najmniej jednego kluczowego zawodnika (np. najlepszy strzelec, kapitan, podstawowy bramkarz)
albo zapowiedziano dużą rotację (4+ zmiany w składzie)."""

def _kontekst(braki, zapowiedz, naglowki):
    lin = []
    for s, kto in (('gosp', 'gospodarz'), ('gosc', 'gość')):
        b = (braki or {}).get(s) or []
        if b: lin.append(f"Nieobecni wg bazy danych ({kto}): " + '; '.join(f"{x['zawodnik']} ({x.get('powod') or x.get('typ')})" for x in b[:12]))
    if zapowiedz: lin.append('Zapowiedź meczu (serwis danych): ' + zapowiedz[:1200])
    if naglowki: lin.append('Nagłówki z ostatnich dni: ' + ' | '.join(naglowki[:10]))
    return ('DANE ZEBRANE PRZEZ PROGRAM (traktuj jako wskazówki):\n' + '\n'.join(lin)) if lin else ''

def _wyciagnij_json(t):
    t = re.sub(r'^```(?:json)?|```$', '', t.strip(), flags=re.M).strip()
    a, b = t.find('{'), t.rfind('}')
    return json.loads(t[a:b + 1]) if a >= 0 and b > a else None

_modele = {}
_bez_szukania = set()   # modele, którym skończył się limit wyszukiwania Google
def modele():
    """Lista modeli dostępnych dla Twojego klucza (Google zmienia nazwy i wycofuje stare) – najpierw Flash, potem Flash-Lite."""
    if 'lista' in _modele: return _modele['lista']
    nazwy = []
    try:
        j = requests.get('https://generativelanguage.googleapis.com/v1beta/models', params={'pageSize': 200}, timeout=30,
                         headers={'x-goog-api-key': KLUCZ}).json()
        for m in j.get('models', []):
            n = m.get('name', '').replace('models/', '')
            if 'generateContent' not in (m.get('supportedGenerationMethods') or []): continue
            if 'flash' not in n or re.search(r'image|tts|audio|live|embed|thinking|exp|customtools', n): continue
            nazwy.append(n)
    except Exception as e: _blad(f'lista modeli: {e}')
    def ranga(n):   # stabilne przed "preview", nowsze wersje przed starszymi, Flash przed Flash-Lite
        w = re.search(r'(\d+(?:\.\d+)?)', n); wer = float(w.group(1)) if w else 0
        return ('lite' in n, 'preview' in n, 'latest' in n, -wer, n)
    lista = sorted(set(nazwy), key=ranga) or MODELE
    _modele['lista'] = lista[:6]; STAN['modele'] = _modele['lista']
    return _modele['lista']

def _zapytaj(tekst_szukaj, tekst_bez):
    """Pyta kolejne modele. Limit (429) przy wyszukiwaniu Google = spróbuj tego samego modelu bez wyszukiwania."""
    for m in modele():
        if m in _zly: continue
        for z_szukaniem in ((True, False) if _szukanie['ok'] and m not in _bez_szukania else (False,)):
            body = {'contents': [{'parts': [{'text': tekst_szukaj if z_szukaniem else tekst_bez}]}],
                    'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 1500}}
            if z_szukaniem: body['tools'] = [{'google_search': {}}]
            try:
                STAN['zapytania'] += 1; _licznik(1)
                r = requests.post(URL.format(m=m), json=body, timeout=90, headers={'x-goog-api-key': KLUCZ})
            except Exception as e: _blad(f'{m}: {e}'); continue
            if r.status_code == 200:
                j = r.json(); c = (j.get('candidates') or [{}])[0]
                txt = ''.join(p.get('text', '') for p in (c.get('content') or {}).get('parts', []))
                zr = []
                for ch in ((c.get('groundingMetadata') or {}).get('groundingChunks') or []):
                    w = ch.get('web') or {}
                    if w.get('uri'): zr.append(dict(tytul=w.get('title') or w['uri'][:40], link=w['uri']))
                STAN['model'] = m; STAN['wyszukiwanie'] = z_szukaniem
                time.sleep(4)   # darmowy plan: kilka zapytań na minutę
                return txt, zr, z_szukaniem
            opis = re.sub(r'\s+', ' ', r.text)[:260]
            _blad(f'{m}{" +Google" if z_szukaniem else ""}: HTTP {r.status_code} {opis}')
            if z_szukaniem and r.status_code in (400, 403, 429):
                if r.status_code != 429: _szukanie['ok'] = False
                else: _bez_szukania.add(m)
                time.sleep(3); continue          # ten sam model bez wyszukiwania
            if r.status_code in (404, 403, 429): _zly.add(m)
            if r.status_code == 429: time.sleep(3)
            break
    return None, [], False

def raport_ai(dom, gosc, dom_pl, gosc_pl, rozgrywki, start, braki=None, zapowiedz=None, naglowki=None, polski=False):
    """Zwraca słownik z raportem albo None (brak klucza, limit, błąd)."""
    if not KLUCZ or _licznik() >= MAKS_DZIENNIE: return None
    kiedy = pd.Timestamp(start).strftime('%d.%m.%Y, %H:%M')
    szukaj_txt = ('Wyszukaj w Google najnowsze wiadomości o obu drużynach (konferencje trenerów, składy, kontuzje)'
                  + (' – koniecznie w polskich źródłach (Sport.pl, TVP Sport, Meczyki, WP SportoweFakty, Przegląd Sportowy, Interia)' if polski else
                     ' – w lokalnych mediach obu krajów i w mediach angielskojęzycznych') + '.')
    t = lambda sz: POLECENIE.format(mecz=f'{dom_pl} – {gosc_pl}', rozgrywki=rozgrywki, kiedy=kiedy, dom=f'{dom_pl} ({dom})', gosc=f'{gosc_pl} ({gosc})',
                                    szukaj=sz, kontekst=_kontekst(braki, zapowiedz, naglowki))
    txt, zr, szukal = _zapytaj(t(szukaj_txt), t(BEZ_SZUKANIA))
    if not txt: return None
    try: d = _wyciagnij_json(txt)
    except Exception: d = None
    if not d or not d.get('podsumowanie'):
        _blad('nieczytelna odpowiedź modelu: ' + txt[:120]); return None
    STAN['udane'] += 1
    lista = lambda k: [str(x)[:120] for x in (d.get(k) or []) if x][:10]
    return dict(tekst=str(d['podsumowanie'])[:600], braki_gosp=lista('braki_gosp'), braki_gosc=lista('braki_gosc'),
                niepewni=lista('niepewni'), powazne=bool(d.get('powazne')), powazne_dla=str(d.get('powazne_dla') or 'brak'),
                uzasadnienie=str(d.get('uzasadnienie') or '')[:200], zrodla=zr[:6], szukal=bool(szukal), model=STAN['model'],
                czas=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%H:%M'))
    return None

def zmiana_istotna(stary, nowy):
    """Czy odświeżony raport przynosi coś nowego (nowy brak, zmiana oceny powagi)."""
    if not stary or not nowy: return bool(nowy) and not stary
    n = lambda r: {re.sub(r'\s*\(.*', '', x).strip().lower() for x in r.get('braki_gosp', []) + r.get('braki_gosc', [])}
    return bool(n(nowy) - n(stary)) or nowy.get('powazne') != stary.get('powazne')
