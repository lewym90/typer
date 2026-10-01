"""Raport i ocena typu po polsku pisane przez AI (Google Gemini, plan płatny Tier 1 – wyszukiwanie Google w cenie do limitu).
Model sam szuka wiadomości w Google (grounding); gdy wyszukiwanie jest niedostępne, dostaje to, co zebrał program
(nieobecni z BSD/Big Balls, zapowiedź BSD, nagłówki) i tylko to streszcza. Bez klucza GEMINI_API_KEY moduł nic nie robi."""
import os, re, json, time, requests
import pandas as pd

KLUCZ = os.environ.get('GEMINI_API_KEY', '')
URL = 'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent'
MODELE = ['gemini-flash-latest', 'gemini-flash-lite-latest']   # zapas, gdy nie uda się pobrać listy modeli
BEZ_SZUKANIA = 'Nie masz dostępu do internetu – opieraj się tylko na danych poniżej (a nazwy źródeł pomiń). '
MAKS_DZIENNIE = 150     # wszystkie zapytania (także ponowienia)
MAKS_ANALIZ = 40        # analiz meczów dziennie (wyszukiwanie Google: 5 000 zapytań/mies. w cenie, ~30–50 zł/mies. za tekst)
AI_PILKA, AI_INNE = 20, 15   # podział przy pełnym liczeniu o 12:00; reszta zostaje na odświeżenie przed meczem
STAN = dict(klucz=bool(KLUCZ), zapytania=0, dzis=0, analiz_dzis=0, udane=0, model=None, wyszukiwanie=None, werdykty={}, bledy=[])
PLIK_LICZNIKA = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data', 'ai_licznik.json')

def _plik_licznika():
    dzien = pd.Timestamp.now(tz='America/Los_Angeles').strftime('%Y-%m-%d')
    try: d = json.load(open(PLIK_LICZNIKA))
    except Exception: d = {}
    if d.get('data') != dzien: d = {'data': dzien, 'n': 0, 'analizy': 0}
    return d

def analiz_dzis(dodaj=0):
    """Ile analiz meczów zrobiono dziś (limit MAKS_ANALIZ – pilnuje kosztu)."""
    d = _plik_licznika(); d['analizy'] = d.get('analizy', 0) + dodaj
    if dodaj:
        try: json.dump(d, open(PLIK_LICZNIKA, 'w'))
        except Exception: pass
    STAN['analiz_dzis'] = d['analizy']
    return d['analizy']

def zostalo_analiz(): return max(0, MAKS_ANALIZ - analiz_dzis())

def _licznik(dodaj=0):
    """Liczba zapytań do Gemini dzisiaj (czas pacyficzny – wtedy Google zeruje limit), zapisywana między uruchomieniami."""
    d = _plik_licznika()
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

POLECENIE = """Jesteś profesjonalnym analitykiem sportowym i typerem. Przygotuj po polsku analizę meczu piłkarskiego:
{mecz} ({rozgrywki}), {kiedy} czasu polskiego. Gospodarz: {dom}. Gość: {gosc}.
{szukaj}
{rynek}
Sprawdź wszystko, co wpływa na wynik: kto na pewno nie zagra (kontuzja, zawieszenie, powołanie), kto jest niepewny, zapowiadana rotacja,
zmiana trenera, o co grają (tabela, motywacja), zmęczenie i terminarz (mecz 2–3 dni wcześniej lub zaraz potem ważniejszy), forma z ostatnich
meczów, styl gry obu drużyn i to, jak do siebie pasują (pressing, kontry, stałe fragmenty, gra w obronie).
{zasady}
{ocena}
{kontekst}
Odpowiedz WYŁĄCZNIE obiektem JSON (bez ```), dokładnie w tej postaci:
{{"werdykt": "zgoda" | "ryzyko" | "odradza",
  "powod": "jedno zdanie – najważniejszy powód werdyktu",
  "podsumowanie": "analiza 3–5 zdań, maks. 600 znaków",
  "forma": "jedno zdanie o formie obu drużyn",
  "styl": "jedno zdanie – jak style pasują do siebie",
  "lepszy_zaklad": "inny zakład w tym meczu, który uważasz za rozsądniejszy, albo pusty tekst",
  "braki_gosp": ["Nazwisko (powód)", ...], "braki_gosc": ["Nazwisko (powód)", ...],
  "niepewni": ["Nazwisko (drużyna, powód)", ...],
  "powazne": true/false, "powazne_dla": "gosp" | "gosc" | "oba" | "brak",
  "uzasadnienie": "jedno zdanie – dlaczego braki są / nie są poważne"}}
"powazne" = true tylko, gdy brakuje co najmniej jednego kluczowego zawodnika (najlepszy strzelec, kapitan, podstawowy bramkarz)
albo zapowiedziano dużą rotację (4+ zmiany w składzie)."""

OCENA = """OCENA TYPU: program typuje „{typ}” – szansa z kursów bukmacherów {szansa}. Kurs już zawiera to, co powszechnie wiadomo.
Oceń jak zawodowy typer, czy coś przemawia przeciw temu typowi:
 "zgoda" – nic istotnego przeciw (najczęstszy werdykt);
 "ryzyko" – konkretny powód do ostrożności (niepewny ważny zawodnik, zmęczenie, rotacja, zła forma, niekorzystne zestawienie stylów);
 "odradza" – poważny, potwierdzony w źródłach powód, którego kurs prawdopodobnie jeszcze nie uwzględnia (kluczowy zawodnik na pewno nie gra,
   duża zapowiedziana rotacja, zastępstwo w ostatniej chwili, choroba/kontuzja, nieudane ważenie). Używaj rzadko i tylko z konkretnym źródłem."""

ZASADY = """ZASADY RZETELNOŚCI (najważniejsze):
- Podawaj WYŁĄCZNIE fakty, które znalazłeś w źródłach z ostatnich 7 dni albo w danych poniżej. Niczego nie wymyślaj: żadnych nazwisk,
  kontuzji, liczb, wyników, serii ani cytatów, których nie widziałeś w źródle. Liczby (gole, miejsca w tabeli, bilanse) tylko ze źródła.
- Jeśli o czymś nie znalazłeś informacji – napisz „brak informacji” albo zostaw pustą listę. Lepiej mniej niż nieprawdziwie.
- Informacje niepotwierdzone (plotki, „może nie zagrać”) oznacz słowem „podobno” i nie opieraj na nich werdyktu „odradza”.
- Nie myl zawodników z innymi o podobnym nazwisku ani drużyn z drużynami z innych lig; sprawdź, że wiadomość dotyczy TEGO meczu.
- Nie powtarzaj kursów jako argumentu – oceniasz to, czego kursy mogą jeszcze nie uwzględniać.
- Nazwiska zawodników zostaw w oryginalnej pisowni. Pisz rzeczowo, jak doświadczony analityk, bez ozdobników."""

WERDYKTY = ('zgoda', 'ryzyko', 'odradza')
def werdykt_z(d):
    w = str((d or {}).get('werdykt') or '').strip().lower()
    w = {'zgoda z faworytem': 'zgoda', 'ryzyko niespodzianki': 'ryzyko', 'odradzam': 'odradza'}.get(w, w)
    return w if w in WERDYKTY else None

def pilnuj_werdyktu(w, szukal, zrodla, d):
    """Ocena typu tylko na podstawie źródeł: bez wyszukiwania i bez źródeł – brak oceny; „odradza” bez źródła
    albo oparte na plotce („podobno”) – najwyżej „ryzyko”."""
    if not w: return None
    if not szukal and not zrodla: return None          # AI pisało tylko z nagłówków – nie wystawia oceny typu
    if w == 'odradza' and (not zrodla or 'podobno' in str(d.get('powod') or '').lower()): return 'ryzyko'
    return w

def ocena_txt(typ=None):
    """typ = (opis zakładu, szansa 0–1)."""
    if not typ: return ''
    return OCENA.format(typ=typ[0], szansa=f"{typ[1] * 100:.0f}%".replace('.', ','))

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
_proby = {}             # ponowienia po błędzie 503 (przeciążenie)
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
    def ranga(n):   # plan płatny: Flash (najlepsza analiza) przed Flash-Lite; stabilne przed "preview"; nowsze przed starszymi
        w = re.search(r'(\d+(?:\.\d+)?)', n); wer = float(w.group(1)) if w else 0
        return ('lite' in n, 'preview' in n, 'latest' in n, 'omni' in n, -wer, n)
    lista = sorted(set(nazwy), key=ranga) or MODELE
    flash = [n for n in lista if 'lite' not in n][:3]; lite = [n for n in lista if 'lite' in n][:2]
    _modele['lista'] = flash + lite; STAN['modele'] = _modele['lista']
    return _modele['lista']

def _zapytaj(tekst_szukaj, tekst_bez):
    """Pyta kolejne modele. Limit (429) przy wyszukiwaniu Google = spróbuj tego samego modelu bez wyszukiwania."""
    for m in modele():
        if m in _zly: continue
        for z_szukaniem in ((True, False) if _szukanie['ok'] and m not in _bez_szukania else (False,)):
            body = {'contents': [{'parts': [{'text': tekst_szukaj if z_szukaniem else tekst_bez}]}],
                    'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 6000}}
            if z_szukaniem: body['tools'] = [{'google_search': {}}]
            try:
                STAN['zapytania'] += 1; _licznik(1)
                r = requests.post(URL.format(m=m), json=body, timeout=150, headers={'x-goog-api-key': KLUCZ})
            except Exception as e: _blad(f'{m}: {e}'); continue
            if r.status_code == 200:
                j = r.json(); c = (j.get('candidates') or [{}])[0]
                txt = ''.join(p.get('text', '') for p in (c.get('content') or {}).get('parts', []))
                zr = []
                for ch in ((c.get('groundingMetadata') or {}).get('groundingChunks') or []):
                    w = ch.get('web') or {}
                    if w.get('uri'): zr.append(dict(tytul=w.get('title') or w['uri'][:40], link=w['uri']))
                STAN['model'] = m; STAN['wyszukiwanie'] = z_szukaniem
                time.sleep(1)
                return txt, zr, z_szukaniem
            opis = re.sub(r'\s+', ' ', r.text)[:260]
            _blad(f'{m}{" +Google" if z_szukaniem else ""}: HTTP {r.status_code} {opis}')
            if r.status_code in (500, 503) and not z_szukaniem and _proby.get(m, 0) < 2:   # przeciążenie – chwilowe
                _proby[m] = _proby.get(m, 0) + 1; time.sleep(15); return _zapytaj(tekst_szukaj, tekst_bez)
            if z_szukaniem and r.status_code in (400, 403, 429):
                _bez_szukania.add(m); _szukanie['odmowy'] = _szukanie.get('odmowy', 0) + 1
                if r.status_code != 429 or _szukanie['odmowy'] >= 2: _szukanie['ok'] = False   # darmowy plan bez wyszukiwania Google
                time.sleep(3); continue          # ten sam model bez wyszukiwania
            if r.status_code in (404, 403, 429, 500, 503): _zly.add(m)
            if r.status_code == 429: time.sleep(3)
            break
    return None, [], False

def raport_ai(dom, gosc, dom_pl, gosc_pl, rozgrywki, start, braki=None, zapowiedz=None, naglowki=None, polski=False, typ=None, szanse=None):
    """Zwraca słownik z analizą i werdyktem albo None (brak klucza, limit, błąd). typ = (zakład, szansa); szanse = {'1','X','2'}."""
    if not KLUCZ or _licznik() >= MAKS_DZIENNIE or zostalo_analiz() <= 0: return None
    kiedy = pd.Timestamp(start).strftime('%d.%m.%Y, %H:%M')
    szukaj_txt = ('Wyszukaj w Google najnowsze wiadomości o obu drużynach (konferencje trenerów, składy, kontuzje)'
                  + (' – koniecznie w polskich źródłach (Sport.pl, TVP Sport, Meczyki, WP SportoweFakty, Przegląd Sportowy, Interia)' if polski else
                     ' – w lokalnych mediach obu krajów i w mediach angielskojęzycznych') + '.')
    rynek = (f"Szanse z kursów bukmacherów: wygra {dom_pl} {szanse['1']*100:.0f}%, remis {szanse['X']*100:.0f}%, wygra {gosc_pl} {szanse['2']*100:.0f}%."
             if szanse and all(k in szanse for k in ('1', 'X', '2')) else '')
    t = lambda sz: POLECENIE.format(mecz=f'{dom_pl} – {gosc_pl}', rozgrywki=rozgrywki, kiedy=kiedy, dom=f'{dom_pl} ({dom})', gosc=f'{gosc_pl} ({gosc})',
                                    szukaj=sz, rynek=rynek, ocena=ocena_txt(typ), zasady=ZASADY, kontekst=_kontekst(braki, zapowiedz, naglowki))
    txt, zr, szukal = _zapytaj(t(szukaj_txt), t(BEZ_SZUKANIA))
    if not txt: return None
    try: d = _wyciagnij_json(txt)
    except Exception: d = None
    if not d or not d.get('podsumowanie'):
        _blad('nieczytelna odpowiedź modelu: ' + txt[:120]); return None
    STAN['udane'] += 1; analiz_dzis(1)
    lista = lambda k: [str(x)[:120] for x in (d.get(k) or []) if x][:10]
    w = pilnuj_werdyktu(werdykt_z(d) if typ else None, szukal, zr, d)
    if w: STAN['werdykty'][w] = STAN['werdykty'].get(w, 0) + 1
    return dict(tekst=str(d['podsumowanie'])[:700], braki_gosp=lista('braki_gosp'), braki_gosc=lista('braki_gosc'),
                niepewni=lista('niepewni'), powazne=bool(d.get('powazne')), powazne_dla=str(d.get('powazne_dla') or 'brak'),
                uzasadnienie=str(d.get('uzasadnienie') or '')[:200], zrodla=zr[:6], szukal=bool(szukal), model=STAN['model'],
                werdykt=w, powod=str(d.get('powod') or '')[:220], forma=str(d.get('forma') or '')[:260], styl=str(d.get('styl') or '')[:260],
                lepszy_zaklad=str(d.get('lepszy_zaklad') or '')[:160], typ=typ[0] if typ else None,
                czas=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%H:%M'))
    return None

def zmiana_istotna(stary, nowy):
    """Czy odświeżony raport przynosi coś nowego (nowy brak, zmiana oceny powagi)."""
    if not stary or not nowy: return bool(nowy) and not stary
    n = lambda r: {re.sub(r'\s*\(.*', '', x).strip().lower() for x in r.get('braki_gosp', []) + r.get('braki_gosc', [])}
    return bool(n(nowy) - n(stary)) or nowy.get('powazne') != stary.get('powazne') or nowy.get('werdykt') != stary.get('werdykt')
