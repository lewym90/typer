"""Raport i ocena typu po polsku pisane przez AI (Google Gemini, plan płatny Tier 1 – wyszukiwanie Google w cenie do limitu).
Model sam szuka wiadomości w Google (grounding); gdy wyszukiwanie jest niedostępne, dostaje to, co zebrał program
(nieobecni z BSD/Big Balls, zapowiedź BSD, nagłówki) i tylko to streszcza. Bez klucza GEMINI_API_KEY moduł nic nie robi."""
import os, re, json, time, requests
import pandas as pd

KLUCZ = os.environ.get('GEMINI_API_KEY', '')
URL = 'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent'
MODELE = ['gemini-flash-latest', 'gemini-flash-lite-latest']   # zapas, gdy nie uda się pobrać listy modeli
BEZ_SZUKANIA = 'Nie masz dostępu do internetu – opieraj się tylko na danych poniżej (a nazwy źródeł pomiń). '
MAKS_DZIENNIE = 400     # wszystkie zapytania (także ponowienia) – bezpiecznik
MAKS_ANALIZ = 120       # analiz meczów dziennie – bezpiecznik; właściwy limit to budżet miesięczny niżej
BUDZET_ZL = float(os.environ.get('AI_BUDZET_ZL') or 85)   # miesięczny limit kosztu (zł): GitHub 85 + serwer (analiza ręczna) 15 = 100 zł
# Cennik (USD za 1 mln tokenów, ostrożnie – z zapasem): Flash wejście 0,50 / wyjście (z „myśleniem”) 3,00; Flash-Lite 0,10 / 0,40.
# Wyszukiwanie Google: w planie płatnym 1 500 zapytań dziennie bez opłat (używamy dużo mniej).
CENY = {'lite': (0.10, 0.40), 'flash': (0.50, 3.00)}
USD_PLN = 3.75
AI_PILKA, AI_INNE = 20, 15   # podział przy pełnym liczeniu; resztę uzupełnia „uzupelnij_ai” przy każdym sprawdzeniu
WAZNOSC_H = 8                # raport z pamięci podręcznej jest używany ponownie przez 8 h (ten sam mecz i ten sam typ)
STAN = dict(klucz=bool(KLUCZ), zapytania=0, dzis=0, analiz_dzis=0, udane=0, z_pamieci=0, koszt_miesiac_zl=0.0, budzet_zl=BUDZET_ZL,
            model=None, wyszukiwanie=None, werdykty={}, bledy=[])
_KAT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
PLIK_LICZNIKA = os.path.join(_KAT, 'ai_licznik.json')
PLIK_PAMIECI = os.path.join(_KAT, 'ai_pamiec.json')

def _plik_licznika():
    # wersja 41: doba programu (od 6:00 czasu polskiego) – wcześniej doba pacyficzna, przez co poranne liczenie (7:10)
    # dzieliło limit z poprzednim popołudniem i wieczorem; plan płatny nie ma już dziennego limitu Google
    teraz = pd.Timestamp.now(tz='Europe/Warsaw')
    dzien, mies = (teraz - pd.Timedelta(hours=6)).strftime('%Y-%m-%d'), teraz.strftime('%Y-%m')
    try: d = json.load(open(PLIK_LICZNIKA))
    except Exception: d = {}
    if d.get('data') != dzien: d.update({'data': dzien, 'n': 0, 'analizy': 0})
    if d.get('miesiac') != mies: d.update({'miesiac': mies, 'koszt_zl': 0.0})
    return d

def _zapisz_licznik(d):
    try:
        os.makedirs(os.path.dirname(PLIK_LICZNIKA), exist_ok=True); json.dump(d, open(PLIK_LICZNIKA, 'w'))
    except Exception: pass

def analiz_dzis(dodaj=0):
    """Ile analiz meczów zrobiono dziś (bezpiecznik MAKS_ANALIZ)."""
    d = _plik_licznika(); d['analizy'] = d.get('analizy', 0) + dodaj
    if dodaj: _zapisz_licznik(d)
    STAN['analiz_dzis'] = d['analizy']; STAN['koszt_miesiac_zl'] = round(d.get('koszt_zl', 0.0), 2)
    return d['analizy']

def koszt_miesiac(dodaj_zl=0.0):
    d = _plik_licznika()
    if dodaj_zl: d['koszt_zl'] = round(d.get('koszt_zl', 0.0) + dodaj_zl, 4); _zapisz_licznik(d)
    STAN['koszt_miesiac_zl'] = round(d.get('koszt_zl', 0.0), 2)
    return d.get('koszt_zl', 0.0)

def _licznik(dodaj=0):
    """Liczba zapytań do Gemini w dobie programu (od 6:00), zapisywana między uruchomieniami."""
    d = _plik_licznika()
    if dodaj: d['n'] = d.get('n', 0) + dodaj; _zapisz_licznik(d)
    STAN['dzis'] = d.get('n', 0)
    return d.get('n', 0)

def zostalo_analiz():
    if koszt_miesiac() >= BUDZET_ZL: return 0
    return max(0, MAKS_ANALIZ - analiz_dzis())

def _koszt(model, usage):
    """Koszt jednego zapytania w zł z liczby tokenów (usageMetadata)."""
    c_we, c_wy = CENY['lite' if 'lite' in str(model) else 'flash']
    we = usage.get('promptTokenCount', 0) + usage.get('toolUsePromptTokenCount', 0)
    wy = usage.get('candidatesTokenCount', 0) + usage.get('thoughtsTokenCount', 0)
    return (we * c_we + wy * c_wy) / 1e6 * USD_PLN

# ---------------- pamięć raportów: ten sam mecz i typ nie jest analizowany ponownie przez WAZNOSC_H godzin ----------------
def _pamiec():
    try: return json.load(open(PLIK_PAMIECI))
    except Exception: return {}

def klucz_pamieci(*czesci): return '|'.join(str(c or '').strip().lower() for c in czesci)

def z_pamieci(k, godzin=None):
    x = _pamiec().get(k)
    if not x: return None
    try:
        if pd.Timestamp.now(tz='UTC') - pd.Timestamp(x['czas']) > pd.Timedelta(hours=godzin or WAZNOSC_H): return None
    except Exception: return None
    STAN['z_pamieci'] += 1
    return x.get('ai')

def do_pamieci(k, ai):
    if not ai: return
    p = _pamiec(); teraz = pd.Timestamp.now(tz='UTC')
    p = {kk: v for kk, v in p.items() if teraz - pd.Timestamp(v.get('czas', '2000-01-01T00:00:00+00:00')) < pd.Timedelta(days=2)}
    p[k] = dict(czas=teraz.isoformat(), ai=ai)
    try: os.makedirs(os.path.dirname(PLIK_PAMIECI), exist_ok=True); json.dump(p, open(PLIK_PAMIECI, 'w'), ensure_ascii=False)
    except Exception: pass

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
  "uzasadnienie": "jedno zdanie – dlaczego braki są / nie są poważne",
  "za": ["argument z faktem", ...], "przeciw": ["argument z faktem", ...], "szansa_wlasna": 0.0}}
"powazne" = true tylko, gdy brakuje co najmniej jednego kluczowego zawodnika (najlepszy strzelec, kapitan, podstawowy bramkarz)
albo zapowiedziano dużą rotację (4+ zmiany w składzie)."""

OCENA = """OCENA TYPU (wersja 36 – bez przytakiwania): program proponuje „{typ}” – szansa z kursów bukmacherów {szansa}.
Najpierw – zanim spojrzysz na tę liczbę – oceń SAM, na podstawie faktów, jaka jest szansa tego typu („szansa_wlasna”). Potem porównaj.
Podaj uczciwie argumenty ZA i PRZECIW (każdy oparty na fakcie ze źródła; co najmniej 2 przeciw – jeśli naprawdę ich nie ma, napisz dlaczego).
Nie zgadzasz się domyślnie z nikim. Werdykt:
 "zgoda" – fakty wspierają typ, a argumenty przeciw są słabsze (musisz je wymienić);
 "ryzyko" – istotny argument przeciw (niepewny ważny zawodnik, zmęczenie, rotacja, forma, zestawienie stylów, stawka meczu);
 "odradza" – mocny, potwierdzony w źródle powód przeciw, którego kurs prawdopodobnie nie uwzględnia.
Kurs zawiera to, co powszechnie wiadomo – Twoja wartość to fakty, których rynek może jeszcze nie wycenić."""

ZASADY = """ZASADY RZETELNOŚCI (najważniejsze):
- Podawaj WYŁĄCZNIE fakty, które znalazłeś w źródłach z ostatnich 7 dni albo w danych poniżej. Niczego nie wymyślaj: żadnych nazwisk,
  kontuzji, liczb, wyników, serii ani cytatów, których nie widziałeś w źródle. Liczby (gole, miejsca w tabeli, bilanse) tylko ze źródła.
- Jeśli o czymś nie znalazłeś informacji – napisz „brak informacji” albo zostaw pustą listę. Lepiej mniej niż nieprawdziwie.
- Informacje niepotwierdzone (plotki, „może nie zagrać”) oznacz słowem „podobno” i nie opieraj na nich werdyktu „odradza”.
- Nie myl zawodników z innymi o podobnym nazwisku ani drużyn z drużynami z innych lig; sprawdź, że wiadomość dotyczy TEGO meczu.
- Nie powtarzaj kursów jako argumentu – oceniasz to, czego kursy mogą jeszcze nie uwzględniać.
- Nazwiska zawodników zostaw w oryginalnej pisowni. Pisz rzeczowo, jak doświadczony analityk, bez ozdobników."""

WERDYKTY = ('zgoda', 'ryzyko', 'odradza')
def wymagaj_przeciw(w, d):
    """Wersja 36: „zgoda” bez co najmniej 2 rzetelnych argumentów przeciw = „ryzyko” (AI musi rozważyć obie strony)."""
    if w == 'zgoda' and len([x for x in (d or {}).get('przeciw') or [] if str(x).strip()]) < 2: return 'ryzyko'
    return w

def za_przeciw(d):
    L = lambda k: [str(x)[:220] for x in ((d or {}).get(k) or []) if str(x).strip()][:4]
    try: sw = float((d or {}).get('szansa_wlasna'))
    except Exception: sw = None
    return dict(za=L('za'), przeciw=L('przeciw'), szansa_wlasna=sw if sw is not None and 0 < sw < 1 else None)

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

def _domknij(s):
    """Domyka urwany JSON (odpowiedź ucięta limitem): zamyka otwarty tekst, usuwa niedokończone pole, dopisuje nawiasy."""
    stos, w_tekscie, esc = [], False, False
    for ch in s:
        if w_tekscie:
            if esc: esc = False
            elif ch == '\\': esc = True
            elif ch == '"': w_tekscie = False
        elif ch == '"': w_tekscie = True
        elif ch in '{[': stos.append('}' if ch == '{' else ']')
        elif ch in '}]' and stos: stos.pop()
    if w_tekscie: s += '"'
    s = re.sub(r'[,:]\s*$', '', s.rstrip())
    s = re.sub(r',\s*"[^"]*"\s*$', '', s)             # klucz bez wartości
    return s + ''.join(reversed(stos))

def _pelne(d, s):
    """Naprawa nie zgubiła treści (co najmniej 70% długości tekstu) – inaczej lepiej poprosić model o poprawienie."""
    return len(json.dumps(d, ensure_ascii=False)) >= 0.7 * len(s.strip())

def _parsuj(t):
    """Próby odczytu JSON bez pomocy modelu (wersja 41): całość, json_repair (jeśli zainstalowany), domknięcie urwanego tekstu."""
    if not t: return None
    t = re.sub(r'^```(?:json)?|```$', '', t.strip(), flags=re.M).strip()
    a = t.find('{')
    if a < 0: return None
    s, b = t[a:], t.rfind('}')
    proby = [t[a:b + 1]] if b > a else []
    proby += [re.sub(r',\s*([}\]])', r'\1', x) for x in proby]
    for x in proby:
        try:
            d = json.loads(x)
            if isinstance(d, dict): return d
        except Exception: pass
    try:
        import json_repair
        d = json_repair.loads(s)
        if isinstance(d, dict) and d and _pelne(d, s): STAN['naprawione_json'] = STAN.get('naprawione_json', 0) + 1; return d
    except Exception: pass
    try:
        d = json.loads(_domknij(s))
        if isinstance(d, dict) and d and _pelne(d, s): STAN['naprawione_json'] = STAN.get('naprawione_json', 0) + 1; return d
    except Exception: pass
    return None

NAPRAW = ('Poniższy tekst miał być jednym obiektem JSON, ale ma błędy składni (cudzysłowy, przecinki, nawiasy) albo jest urwany. '
          'Zwróć ten sam obiekt jako poprawny JSON: zachowaj wszystkie pola i ich treść bez zmian merytorycznych, popraw tylko składnię, '
          'urwane pole na końcu utnij. Nic nie dodawaj.\n\n')

def _napraw_modelem(t):
    """Ostatnia próba: najtańszy model (Flash-Lite, tryb JSON, bez wyszukiwania) poprawia składnię. Koszt ułamka grosza."""
    if not KLUCZ or not t or _licznik() >= MAKS_DZIENNIE: return None
    lista = modele(); lite = [m for m in lista if 'lite' in m] or lista
    for m in lite[:2]:
        body = {'contents': [{'parts': [{'text': NAPRAW + t[:30000]}]}],
                'generationConfig': {'temperature': 0, 'maxOutputTokens': 12000, 'responseMimeType': 'application/json'}}
        try:
            _licznik(1); r = requests.post(URL.format(m=m), json=body, timeout=120, headers={'x-goog-api-key': KLUCZ})
            if r.status_code != 200: _blad(f'naprawa JSON {m}: HTTP {r.status_code}'); continue
            j = r.json(); c = (j.get('candidates') or [{}])[0]
            try: koszt_miesiac(_koszt(m, j.get('usageMetadata') or {}))
            except Exception: pass
            d = _parsuj(''.join(p.get('text', '') for p in (c.get('content') or {}).get('parts', [])))
            if d: STAN['naprawione_modelem'] = STAN.get('naprawione_modelem', 0) + 1; return d
        except Exception as e: _blad(f'naprawa JSON {m}: {e}')
    return None

def _wyciagnij_json(t, napraw=True):
    """Obiekt JSON z odpowiedzi modelu; przy błędach składni naprawa lokalna, potem modelem (wersja 41 – nie tracimy opłaconych analiz)."""
    d = _parsuj(t)
    if d is None and napraw: d = _napraw_modelem(t)
    return d

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
                    'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 12000}}
            if z_szukaniem: body['tools'] = [{'google_search': {}}]
            try:
                STAN['zapytania'] += 1; _licznik(1)
                r = requests.post(URL.format(m=m), json=body, timeout=150, headers={'x-goog-api-key': KLUCZ})
            except Exception as e: _blad(f'{m}: {e}'); continue
            if r.status_code == 200:
                j = r.json(); c = (j.get('candidates') or [{}])[0]
                try: koszt_miesiac(_koszt(m, j.get('usageMetadata') or {}))
                except Exception: pass
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

def raport_ai(dom, gosc, dom_pl, gosc_pl, rozgrywki, start, braki=None, zapowiedz=None, naglowki=None, polski=False, typ=None, szanse=None, wymus=False):
    """Zwraca słownik z analizą i werdyktem albo None (brak klucza, limit, błąd). typ = (zakład, szansa); szanse = {'1','X','2'}.
    Ten sam mecz i typ z ostatnich WAZNOSC_H godzin bierzemy z pamięci (wymus=True – zawsze nowa analiza, np. przed meczem)."""
    kp = klucz_pamieci('pilka', dom, gosc, str(start)[:10] if start is not None else '', typ[0] if typ else '')
    if not wymus:
        z = z_pamieci(kp)
        if z: return z
    if not KLUCZ or _licznik() >= MAKS_DZIENNIE or zostalo_analiz() <= 0: return None
    kiedy = pd.Timestamp(start).strftime('%d.%m.%Y, %H:%M') if start is not None else 'najbliższy mecz tych drużyn (data nieznana)'
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
        _blad(f'nieczytelna odpowiedź modelu ({len(txt)} znaków): ' + txt[:100]); return None
    STAN['udane'] += 1; analiz_dzis(1)
    lista = lambda k: [str(x)[:120] for x in (d.get(k) or []) if x][:10]
    w = pilnuj_werdyktu(werdykt_z(d) if typ else None, szukal, zr, d)
    w = wymagaj_przeciw(w, d)
    if w: STAN['werdykty'][w] = STAN['werdykty'].get(w, 0) + 1
    out = dict(za_przeciw(d), tekst=str(d['podsumowanie'])[:700], braki_gosp=lista('braki_gosp'), braki_gosc=lista('braki_gosc'),
                niepewni=lista('niepewni'), powazne=bool(d.get('powazne')), powazne_dla=str(d.get('powazne_dla') or 'brak'),
                uzasadnienie=str(d.get('uzasadnienie') or '')[:200], zrodla=zr[:6], szukal=bool(szukal), model=STAN['model'],
                werdykt=w, powod=str(d.get('powod') or '')[:220], forma=str(d.get('forma') or '')[:260], styl=str(d.get('styl') or '')[:260],
                lepszy_zaklad=str(d.get('lepszy_zaklad') or '')[:160], typ=typ[0] if typ else None,
                czas=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%H:%M'))
    do_pamieci(kp, out)
    return out

def zmiana_istotna(stary, nowy):
    """Czy odświeżony raport przynosi coś nowego (nowy brak, zmiana oceny powagi)."""
    if not stary or not nowy: return bool(nowy) and not stary
    n = lambda r: {re.sub(r'\s*\(.*', '', x).strip().lower() for x in r.get('braki_gosp', []) + r.get('braki_gosc', [])}
    return bool(n(nowy) - n(stary)) or nowy.get('powazne') != stary.get('powazne') or nowy.get('werdykt') != stary.get('werdykt')
