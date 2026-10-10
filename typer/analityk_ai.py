"""Analityk AI (wersja 35) – Gemini Pro w trzech osobnych krokach, bez przytakiwania i bez konfabulacji.
 1) ANALITYK NA ŚLEPO – nie widzi kursów ani naszego typu; dostaje teczkę meczu (FotMob: składy, braki z wartościami, sędzia,
    forma, tabela, H2H, pogoda) i szuka w Google; zwraca fakty ze źródłami, własne szanse, 3 scenariusze z wynikiem.
 2) ADWOKAT DIABŁA – osobne wywołanie: rozbija analizę z kroku 1 (najmocniejsze argumenty przeciw, przeoczenia, przesadna pewność,
    twierdzenia bez źródła) i buduje najmocniejszy realny scenariusz niespodzianki.
 3) SĘDZIA – dopiero teraz widzi kursy rynku i typ programu; min. 2 argumenty za i 2 przeciw, końcowe szanse, werdykt
    i własny typ Analityka (z listy zakładów – także outsider, remis, dokładny wynik).
Kontrola faktów przez program: fakt bez źródła → usunięty; nazwisko zawodnika spoza kadry z FotMob → fakt odrzucony.
Każda analiza trafia do dziennika docs/data/typy_analityk.csv (rozliczany: trafność szans AI vs rynek, typ Analityka po kursie rynku).
Budżet: AI_PRO_BUDZET_ZL (domyślnie 150 zł/mies.), dzienny limit = reszta budżetu / dni do końca miesiąca."""
import os, re, json, time, datetime as dt
import numpy as np, pandas as pd, requests

KLUCZ = os.environ.get('GEMINI_API_KEY', '')
URL = 'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent'
BUDZET_ZL = float(os.environ.get('AI_PRO_BUDZET_ZL') or 170)   # wariant A: Pro 200 zł = GitHub 170 + serwer (analiza ręczna Pro) 30
# Cennik Gemini 3.1 Pro (10.2026): wejście 2,00 / wyjście z „myśleniem” 12,00 USD za 1 mln tokenów; wyszukiwanie Google: 5 000 zapytań/mies.
# gratis (wspólne dla Gemini 3.x), potem 14 USD/1000 – liczymy ostrożnie 0,05 zł za krok z wyszukiwaniem.
CENA_WE, CENA_WY, USD_PLN, SZUKANIE_ZL = 2.0, 12.0, 3.75, 0.05
MAKS_MECZOW_DZIENNIE = 12
OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
PLIK_LICZNIKA = os.path.join(OUT, 'analityk_ai_licznik.json')
PLIK_DZIENNIKA = os.path.join(OUT, 'typy_analityk.csv')
PLIK_FLASH = os.path.join(OUT, 'typy_flash.csv')     # wersja 44: szanse Flash przy każdym analizowanym meczu (większa próba)
STAN = dict(klucz=bool(KLUCZ), model=None, analiz=0, kroki=0, koszt_dzis_zl=0.0, koszt_miesiac_zl=0.0, budzet_zl=BUDZET_ZL,
            odrzucone_fakty=0, bledy=[])
_modele = {}


def _blad(t):
    t = str(t)[:200]; print('Analityk AI:', t)
    if t not in STAN['bledy'] and len(STAN['bledy']) < 8: STAN['bledy'].append(t)


# ------------------------------------------------------------------ budżet
def _licznik():
    teraz = pd.Timestamp.now(tz='Europe/Warsaw'); dz, mies = teraz.strftime('%Y-%m-%d'), teraz.strftime('%Y-%m')
    try: d = json.load(open(PLIK_LICZNIKA))
    except Exception: d = {}
    if d.get('miesiac') != mies: d = dict(miesiac=mies, koszt_zl=0.0)
    if d.get('data') != dz: d.update(data=dz, koszt_dzis_zl=0.0, meczow=0)
    return d


def _dodaj_koszt(zl=0.0, mecz=0):
    d = _licznik(); d['koszt_zl'] = round(d.get('koszt_zl', 0) + zl, 4); d['koszt_dzis_zl'] = round(d.get('koszt_dzis_zl', 0) + zl, 4)
    d['meczow'] = d.get('meczow', 0) + mecz
    try: os.makedirs(os.path.dirname(PLIK_LICZNIKA), exist_ok=True); json.dump(d, open(PLIK_LICZNIKA, 'w'))
    except Exception: pass
    STAN['koszt_dzis_zl'], STAN['koszt_miesiac_zl'] = d['koszt_dzis_zl'], d['koszt_zl']


def limit_dzis():
    """Ile zł wolno dziś wydać: reszta budżetu miesiąca / dni do końca miesiąca (z dzisiejszym)."""
    d = _licznik(); teraz = pd.Timestamp.now(tz='Europe/Warsaw')
    dni = (teraz + pd.offsets.MonthEnd(0)).day - teraz.day + 1
    reszta = max(0.0, BUDZET_ZL - d.get('koszt_zl', 0) + d.get('koszt_dzis_zl', 0))
    return reszta / max(dni, 1)


def mozna_sedzia():
    """Wersja 45: ponowny werdykt (sam krok 3, bez wyszukiwania – ułamek kosztu pełnej analizy) – tylko limit miesięczny."""
    d = _licznik()
    return bool(KLUCZ) and d.get('koszt_zl', 0) + 0.3 <= BUDZET_ZL


def mozna():
    d = _licznik()
    STAN['koszt_dzis_zl'], STAN['koszt_miesiac_zl'] = d.get('koszt_dzis_zl', 0), d.get('koszt_zl', 0)
    if not KLUCZ or d.get('koszt_zl', 0) + 1.0 > BUDZET_ZL or d.get('meczow', 0) >= MAKS_MECZOW_DZIENNIE: return False
    if os.environ.get('AI_PRO_RECZNE'): return True        # serwer (analiza ręczna): tylko limit miesięczny + limit dzienny serwera
    return d.get('koszt_dzis_zl', 0) + 1.0 <= limit_dzis()     # ~1 zł = zapas na jeden mecz (3 kroki Pro z wyszukiwaniem)


# ------------------------------------------------------------------ pamięć analiz Pro (wersja 38)
# Pełne liczenie budowało karty od nowa i gubiło analizy Pro z wcześniejszego uruchomienia (budżet dnia już wydany).
# Każda analiza jest zapamiętywana na 20 h (ten sam mecz) i używana ponownie bez kosztu.
PLIK_PAMIECI = os.path.join(OUT, 'analityk_ai_pamiec.json')
WAZNOSC_H = 20


def _pamiec():
    try: return json.load(open(PLIK_PAMIECI))
    except Exception: return {}


def z_pamieci(sport, event_id):
    x = _pamiec().get(f'{sport}|{event_id}')
    if not x: return None
    try:
        if pd.Timestamp.now(tz='UTC') - pd.Timestamp(x['czas']) > pd.Timedelta(hours=WAZNOSC_H): return None
    except Exception: return None
    return x.get('a')


def do_pamieci(sport, event_id, a):
    if not a: return
    p = _pamiec(); teraz = pd.Timestamp.now(tz='UTC')
    p = {k: v for k, v in p.items() if teraz - pd.Timestamp(v.get('czas', '2000-01-01T00:00:00+00:00')) < pd.Timedelta(hours=WAZNOSC_H)}
    p[f'{sport}|{event_id}'] = dict(czas=teraz.isoformat(), a=a)
    try:
        os.makedirs(os.path.dirname(PLIK_PAMIECI), exist_ok=True)
        with open(PLIK_PAMIECI, 'w', encoding='utf-8') as f: json.dump(p, f, ensure_ascii=False)
    except Exception: pass


# ------------------------------------------------------------------ model Pro
def model_pro():
    if 'm' in _modele: return _modele['m']
    nazwy = []
    try:
        j = requests.get('https://generativelanguage.googleapis.com/v1beta/models', params={'pageSize': 200}, timeout=30,
                         headers={'x-goog-api-key': KLUCZ}).json()
        for m in j.get('models', []):
            n = m.get('name', '').replace('models/', '')
            if 'generateContent' in (m.get('supportedGenerationMethods') or []) and re.search(r'gemini-[\d.]+-pro', n) \
                    and not re.search(r'image|tts|audio|live|embed|vision|customtools|computer', n): nazwy.append(n)
    except Exception as e: _blad(f'lista modeli: {e}')
    def ranga(n):
        w = re.search(r'gemini-([\d.]+)', n); wer = float(w.group(1)) if w else 0
        return (-wer, 'preview' in n, 'exp' in n, len(n))
    nazwy = sorted(set(nazwy), key=ranga) or ['gemini-2.5-pro']
    _modele['m'] = nazwy[:3]; STAN['model'] = nazwy[0]
    return _modele['m']


def _json(txt):
    """Wersja 41: naprawa składni (lokalnie, potem tanim modelem) – opłacony krok Pro nie przepada przez przecinek."""
    import ai_raport
    d = ai_raport._wyciagnij_json(txt)
    if d is None: raise ValueError('nieczytelny JSON')
    return d


def zapytaj(tekst, szukaj=True):
    """(dane JSON, źródła z wyszukiwania) albo (None, [])."""
    import ai_raport
    if ai_raport._BLOK_RUN['stop'] or (ai_raport.blokada() and ai_raport._minut_od(ai_raport.blokada().get('ostatnia_proba')) < ai_raport.PONOW_PO_MIN): return None, []
    for m in model_pro():
        body = {'contents': [{'parts': [{'text': tekst}]}],
                'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 20000}}
        if szukaj: body['tools'] = [{'google_search': {}}]
        else: body['generationConfig']['responseMimeType'] = 'application/json'
        try: r = requests.post(URL.format(m=m), json=body, timeout=240, headers={'x-goog-api-key': KLUCZ})
        except Exception as e: _blad(f'{m}: {e}'); continue
        if r.status_code in (401, 402):                  # wersja 61: rozliczenia/klucz – koniec prób w tym uruchomieniu
            _blad(f'{m}: HTTP {r.status_code} ' + re.sub(r'\s+', ' ', r.text)[:160]); ai_raport.ustaw_blokade(r.status_code, r.text); return None, []
        if r.status_code != 200:
            opis = re.sub(r'\s+', ' ', r.text)[:200]; _blad(f'{m}: HTTP {r.status_code} {opis}')
            if r.status_code in (400, 403) and szukaj: szukaj = False; continue
            continue
        j = r.json(); c = (j.get('candidates') or [{}])[0]; u = j.get('usageMetadata') or {}
        we = u.get('promptTokenCount', 0) + u.get('toolUsePromptTokenCount', 0); wy = u.get('candidatesTokenCount', 0) + u.get('thoughtsTokenCount', 0)
        _dodaj_koszt((we * CENA_WE + wy * CENA_WY) / 1e6 * USD_PLN + (SZUKANIE_ZL if szukaj else 0))
        STAN['kroki'] += 1; STAN['model'] = m
        txt = ''.join(p.get('text', '') for p in (c.get('content') or {}).get('parts', []))
        zr = [dict(tytul=(ch.get('web') or {}).get('title', ''), link=(ch.get('web') or {}).get('uri', ''))
              for ch in ((c.get('groundingMetadata') or {}).get('groundingChunks') or []) if (ch.get('web') or {}).get('uri')]
        try: return _json(txt), zr
        except Exception:
            _blad(f"{m}: nieczytelny JSON mimo naprawy ({len(txt)} znaków, {c.get('finishReason')}): {txt[:100]}")
            return None, []          # bez powtarzania kroku innym modelem (podwójny koszt)
    return None, []


# ------------------------------------------------------------------ teczka meczu (piłka – FotMob)
def _przytnij(o, lst=14, txt=300, g=0):
    if g > 6: return None
    if isinstance(o, dict): return {k: _przytnij(v, lst, txt, g + 1) for k, v in o.items()
                                    if k not in ('imageUrl', 'imgUrl', 'horizontalLayout', 'verticalLayout', 'pageUrl', 'id', 'primaryTeamId', 'link', 'lat', 'long')}
    if isinstance(o, list): return [_przytnij(v, lst, txt, g + 1) for v in o[:lst]]
    if isinstance(o, str) and len(o) > txt: return o[:txt]
    return o


POZYCJE = {0: 'bramkarz', 1: 'obrońca', 2: 'pomocnik', 3: 'napastnik'}


def teczka_pilka(fm):
    """Tekst teczki z danych FotMob (matchDetails) + zbiór nazwisk z kadr (do kontroli faktów)."""
    if not isinstance(fm, dict): return '', set()
    c = fm.get('content') or {}; lu = c.get('lineup') or {}; mf = c.get('matchFacts') or {}
    nazwiska, t = set(), {}
    t['naglowek'] = _przytnij((fm.get('header') or {}).get('teams'))
    t['rozgrywki_stadion_sedzia'] = _przytnij({k: (mf.get('infoBox') or {}).get(k) for k in ('Tournament', 'Stadium', 'Referee')})
    t['sklad_typ'] = lu.get('lineupType')
    for strona in ('homeTeam', 'awayTeam'):
        d = lu.get(strona) or {}
        def zaw(p):
            n = p.get('name'); nazwiska.add(str(n))
            return dict(nazwa=n, wiek=p.get('age'), pozycja=POZYCJE.get(p.get('usualPlayingPositionId'), p.get('positionId')),
                        klub=p.get('primaryTeamName'), wartosc_eur=p.get('marketValue'))
        t[strona] = dict(nazwa=d.get('name'), formacja=d.get('formation'), trener=_przytnij(d.get('coach')),
                         sredni_wiek=d.get('averageStarterAge'), wartosc_jedenastki=d.get('totalStarterMarketValue'),
                         przewidywana_jedenastka=[zaw(p) for p in (d.get('starters') or []) if isinstance(p, dict)],
                         lawka=[p.get('name') for p in (d.get('subs') or []) if isinstance(p, dict)][:15],
                         niedostepni=[dict(nazwa=u.get('name'), powod=(u.get('unavailability') or {}).get('type'),
                                           powrot=(u.get('unavailability') or {}).get('expectedReturn'), wartosc_eur=u.get('marketValue'))
                                      for u in (d.get('unavailable') or []) if isinstance(u, dict)])
        for p in (d.get('subs') or []) + (d.get('unavailable') or []):
            if isinstance(p, dict) and p.get('name'): nazwiska.add(str(p['name']))
    t['forma'] = _przytnij(mf.get('teamForm'), lst=6)
    t['ciekawostki'] = _przytnij(mf.get('insights'), lst=8)
    t['pogoda'] = _przytnij(c.get('weather'))
    t['tabela'] = _przytnij(c.get('table'), lst=24, g=1)
    t['h2h'] = _przytnij(c.get('h2h'), lst=8)
    s = json.dumps(t, ensure_ascii=False, default=str)
    return s[:16000], nazwiska


# ------------------------------------------------------------------ polecenia
ZASADY = """ZASADY (bezwzględne):
- Jesteś niezależnym analitykiem najwyższej klasy. Nie zgadzasz się domyślnie z nikim – ani z faworytem, ani z popularną opinią.
- Każdy fakt musi mieć źródło: link z wyszukiwania albo „teczka” (dane powyżej). Fakt bez źródła = nie istnieje. Niczego nie wymyślaj:
  nazwisk, kontuzji, liczb, cytatów, serii. Jeśli czegoś nie wiesz – wpisz to do „niewiadome”.
- Nazwiska zawodników tylko z teczki albo potwierdzone w źródle z ostatnich 7 dni dotyczącym TEGO meczu.
- Szanse podawaj jako ułamki (0–1) sumujące się do 1 tam, gdzie to rozkład. Nie zaokrąglaj do „ładnych” liczb.
- Odpowiedz WYŁĄCZNIE obiektem JSON (bez ```)."""

KROK1 = """ZADANIE: krok 1 z 3 – ANALIZA NA ŚLEPO. Nie znasz kursów bukmacherów i nie szukaj ich (nie wpisuj w wyszukiwarkę „odds”, „kursy”,
„typy”, „prediction”) – ocena ma być całkowicie Twoja.
Mecz: {mecz} ({rozgrywki}), {kiedy} czasu polskiego. Gospodarz: {dom}. Gość: {gosc}.
Wyszukaj najnowsze informacje (ostatnie 7 dni): konferencje trenerów, kontuzje i zawieszenia, przewidywane składy, nastroje i motywację,
o co grają, zmęczenie i podróże, styl gry i to, jak style do siebie pasują, formę (także xG), sędziego, pogodę i boisko.
TECZKA MECZU (dane FotMob – pewne): {teczka}
{zasady}
Postać odpowiedzi:
{{"fakty": [{{"tekst": "konkretny fakt", "zrodlo": "link albo teczka", "znaczenie": "dla kogo i jak wpływa na mecz"}}],
  "styl": "jak style obu drużyn do siebie pasują (2-3 zdania)",
  "motywacja": "kto czego potrzebuje (1-2 zdania)",
  "szanse": {{"1": 0.0, "X": 0.0, "2": 0.0}},
  "gole": {{"0-1": 0.0, "2": 0.0, "3": 0.0, "4+": 0.0}}, "obie_strzela": 0.0,
  "scenariusze": [{{"opis": "jak potoczy się mecz", "wynik": "2:1", "szansa": 0.0}}, {{...}}, {{...}}],
  "pewnosc_analizy": "niska" | "srednia" | "wysoka", "niewiadome": ["czego nie udało się ustalić"]}}"""

KROK2 = """ZADANIE: krok 2 z 3 – ADWOKAT DIABŁA. Inny analityk przygotował analizę meczu {mecz} ({rozgrywki}, {kiedy}).
Twoja rola: znaleźć w niej błędy. Nie jesteś miły – jesteś najostrzejszym recenzentem. Sprawdź w Google każde ważne twierdzenie.
1) Które fakty są nieprawdziwe, nieaktualne albo bez źródła?  2) Co ważnego przeoczył (kontuzje, rotacja, motywacja, styl, sędzia, pogoda)?
3) Gdzie jest przesadnie pewny?  4) Zbuduj NAJMOCNIEJSZY REALNY scenariusz, w którym jego główny wniosek się nie sprawdza – na faktach.
5) Podaj swoje szanse 1X2 po poprawkach.
ANALIZA DO SPRAWDZENIA: {analiza}
TECZKA MECZU (dane FotMob – pewne): {teczka}
{zasady}
Postać odpowiedzi:
{{"bledy": [{{"twierdzenie": "...", "problem": "dlaczego błędne/bez źródła", "zrodlo": "link albo teczka"}}],
  "przeoczone": [{{"tekst": "...", "zrodlo": "link albo teczka", "znaczenie": "..."}}],
  "przesadna_pewnosc": "gdzie i dlaczego",
  "scenariusz_przeciw": {{"opis": "...", "wynik": "1:1", "szansa": 0.0}},
  "szanse": {{"1": 0.0, "X": 0.0, "2": 0.0}}}}"""

KROK3 = """ZADANIE: krok 3 z 3 – SĘDZIA. Mecz {mecz} ({rozgrywki}, {kiedy}). Masz analizę (krok 1) i jej recenzję (krok 2).
Dopiero teraz widzisz rynek: szanse z kursów (bez marży) {rynek}. Program proponuje typ: {typ}.
Kurs zawiera wiedzę tysięcy graczy – nie ignoruj go, ale też go nie powtarzaj. Twoja wartość to to, czego rynek może nie uwzględniać.
Zważ wszystko uczciwie: podaj CO NAJMNIEJ 2 argumenty ZA typem programu i CO NAJMNIEJ 2 PRZECIW – każdy oparty na fakcie z kroku 1 lub 2
(nie na kursie). Jeśli zgadzasz się z rynkiem – uzasadnij to faktami. Jeśli widzisz przewagę przeciw rynkowi (także outsider, remis,
dokładny wynik) – powiedz to wprost i wybierz zakład.
Werdykt dla typu programu: "mocna_zgoda" (fakty wyraźnie za), "zgoda", "ryzyko" (konkretny powód do ostrożności),
"odradza" (poważny, potwierdzony powód przeciw, którego rynek prawdopodobnie nie uwzględnia).
UWAGA KALIBRACYJNA: analitycy AI systematycznie zawyżają remisy i mecze z małą liczbą goli (scenariusze 1:0, 1:1). Odejście od rynku
w stronę remisu albo „poniżej” wymaga konkretnego faktu (braki ofensywne, pogoda, styl obu drużyn, stawka), nie ogólnej ostrożności.
Typ Analityka: wybierz JEDEN zakład z listy (klucz) – ten, w którym Twoja szansa najbardziej przewyższa szansę rynku – albo "brak",
jeśli nigdzie nie masz przewagi. Lista zakładów (klucz: opis – szansa rynku): {lista}
ANALIZA (krok 1): {analiza}
RECENZJA (krok 2): {recenzja}
{zasady}
Postać odpowiedzi:
{{"za": ["argument z faktem", "..."], "przeciw": ["argument z faktem", "..."],
  "szanse": {{"1": 0.0, "X": 0.0, "2": 0.0}}, "werdykt": "mocna_zgoda" | "zgoda" | "ryzyko" | "odradza",
  "powod": "jedno zdanie – rozstrzygający argument",
  "typ_analityka": {{"klucz": "klucz z listy albo brak", "szansa": 0.0, "uzasadnienie": "dlaczego rynek się tu myli"}},
  "gole": {{"ponizej_2_5": 0.0, "obie_strzela": 0.0}},
  "wynik_dokladny": {{"wynik": "2:1", "szansa": 0.0}},
  "podsumowanie": "4-6 zdań: jak widzisz ten mecz i dlaczego"}}"""


# ------------------------------------------------------------------ kontrola faktów
_NAZW = re.compile(r"\b([A-ZŁŚŻŹĆŃÓĘĄÁÉÍÚÜÖÄÇ][\w'’\-]+(?:\s+[A-ZŁŚŻŹĆŃÓĘĄÁÉÍÚÜÖÄÇ][\w'’\-]+)+)")


def _sprawdz_fakty(fakty, nazwiska, druzyny):
    """Usuwa fakty bez źródła i z nazwiskami spoza kadr (gdy kadry znane)."""
    znane = {n.lower() for n in nazwiska} | {x.split()[-1].lower() for x in nazwiska if x and x.split()}
    druz = {str(d).lower() for d in druzyny if d}
    ok = []
    for f in fakty or []:
        if not isinstance(f, dict): continue
        zr = str(f.get('zrodlo') or '').strip()
        if not zr or zr.lower() in ('brak', 'none', '-'): STAN['odrzucone_fakty'] += 1; continue
        if nazwiska:
            obce = []
            for kand in _NAZW.findall(str(f.get('tekst') or '')):
                k = kand.lower()
                if k in znane or k.split()[-1] in znane or any(k in d or d in k for d in druz): continue
                if re.search(r'(liga|league|cup|puchar|stadion|stadium|arena|fc|uefa|fifa|nations|world|euro|mistrzost|świat|swiat|europ|narod|'
                             r'reprezentac|turniej|kolejk|grup|finał|final|igrzysk|olimp|copa|serie|bundes|premier|primera|ekstraklas|'
                             r'konferencj|federacj|związ|zwiaz|klub|trener|selekcjoner|sędzi|sedzi|var\b)', k): continue
                # wersja 45: nazwy własne niebędące nazwiskami (kraje, miasta, drużyny w odmianie – „Chorwacją”, „Rijece”)
                if any(len(w) >= 4 and any(w[:5] in d for d in druz) for w in k.split()): continue
                obce.append(kand)
            if obce and zr == 'teczka': STAN['odrzucone_fakty'] += 1; continue   # „z teczki”, a teczka tego nie zawiera
            if obce: f = dict(f, niezweryfikowane=obce)
        ok.append(f)
    return ok


def _szanse(d):
    try:
        s = {k: float((d or {}).get(k)) for k in ('1', 'X', '2')}
        t = sum(s.values())
        return {k: round(v / t, 4) for k, v in s.items()} if t > 0 else None
    except Exception: return None


# ------------------------------------------------------------------ wersja 44: korekta Analityka
# Diagnoza 03.10 (9 analiz): AI zawyża remis (+7,6 pkt vs rynek), „poniżej 2,5” (+10–12 pkt) – a typ wybierał tam, gdzie najbardziej
# różnił się od rynku, czyli właśnie w swoim błędzie (5 z 6 typów piłki „Poniżej 2,5”). Teraz: 1) odjęcie stałego skrzywienia AI
# (średnia różnica AI − rynek z dziennika, mieszana z wartością startową), 2) ściągnięcie w stronę rynku (WAGA_AI – ile różnicy
# wierzymy; do ustalenia na rozliczonych meczach), 3) typ wybiera program: największa przewaga po korekcie ≥ MIN_PRZEWAGA, inaczej „brak”.
# Własny wybór AI zostaje w dzienniku (typ_klucz_ai) – porównanie obu metod.
SKRZYWIENIE_START = {'x': 0.06, 'u25': 0.10, 'btts': 0.0, 'gamma': 1.25}   # punkt startowy (03.10), z czasem przeważa dziennik
WAGA_STARTU = 10
WAGA_AI = 0.5
MIN_PRZEWAGA = 0.04          # względna przewaga po korekcie (szansa / szansa rynku − 1)
MIN_ROZNICA = 0.025          # i bezwzględna (pkt) – żeby nie wybierać outsiderów tylko dlatego, że mały mianownik


def _wyostrz(p, g):
    """AI spłaszcza szanse (faworyt za nisko, remis i outsider za wysoko) – potęga g > 1 przywraca ostrość rynku."""
    v = {k: max(float(p[k]), 1e-4) ** g for k in ('1', 'X', '2')}; t = sum(v.values())
    return {k: v[k] / t for k in v}


def skrzywienie():
    """Skrzywienie AI z dziennika (mieszane z wartością startową): gamma = ostrość szans 1X2 (minimum rozbieżności KL z rynkiem),
    potem średnie (AI − rynek) dla remisu (po wyostrzeniu), „poniżej 2,5” i „obie strzelą”. Nie potrzebuje wyników meczów."""
    out = dict(SKRZYWIENIE_START)
    try: d = pd.read_csv(PLIK_DZIENNIKA)
    except Exception: return out
    d = d[d.sport.fillna('pilka') == 'pilka'].tail(200) if 'sport' in d else d.tail(200)
    try:
        A = d[['ai_1', 'ai_x', 'ai_2']].apply(pd.to_numeric, errors='coerce'); M = d[['rynek_1', 'rynek_x', 'rynek_2']].apply(pd.to_numeric, errors='coerce')
        ok = A.notna().all(1) & M.notna().all(1) & (M > 0).all(1); A, M = A[ok].values.clip(1e-4, 1), M[ok].values
        n = len(A)
        if n:
            def kl(g):
                P = A ** g; P = P / P.sum(1, keepdims=True); return float((M * np.log(M / P)).sum(1).mean())
            siatka = np.arange(0.8, 3.01, 0.05); g = float(siatka[int(np.argmin([kl(x) for x in siatka]))])
            out['gamma'] = round((n * g + WAGA_STARTU * SKRZYWIENIE_START['gamma']) / (n + WAGA_STARTU), 3)
            P = A ** out['gamma']; P = P / P.sum(1, keepdims=True)
            out['x'] = round(float(((P[:, 1] - M[:, 1]).sum() + WAGA_STARTU * SKRZYWIENIE_START['x']) / (n + WAGA_STARTU)), 4)
    except Exception: pass
    for k, (ca, cr) in {'u25': ('ai_u25', 'rynek_u25'), 'btts': ('ai_btts', 'rynek_btts')}.items():
        if ca not in d or cr not in d: continue
        r = (pd.to_numeric(d[ca], errors='coerce') - pd.to_numeric(d[cr], errors='coerce')).dropna()
        out[k] = round(float((r.sum() + WAGA_STARTU * SKRZYWIENIE_START[k]) / (len(r) + WAGA_STARTU)), 4)
    return out


def _p01(x):
    try:
        x = float(x); return x if 0 < x < 1 else None
    except Exception: return None


def korekta(ai1x2, ai_u, ai_b, lista, sk=None):
    """Szanse AI po korekcie skrzywienia i ściągnięciu do rynku → {klucz: (szansa po korekcie, szansa rynku)}."""
    sk = sk or skrzywienie(); r = {k: v[1] for k, v in lista.items()}; out = {}
    if ai1x2 and all(k in r for k in ('1', 'X', '2')):
        ai1x2 = _wyostrz(ai1x2, sk.get('gamma', 1.0))
        x = max(0.02, ai1x2['X'] - sk['x']); reszta = ai1x2['1'] + ai1x2['2']
        a = {'1': ai1x2['1'] / reszta * (1 - x), 'X': x, '2': ai1x2['2'] / reszta * (1 - x)}
        c = {k: r[k] + WAGA_AI * (a[k] - r[k]) for k in a}
        for k, v in {'1': c['1'], 'X': c['X'], '2': c['2'], '1X': c['1'] + c['X'], 'X2': c['X'] + c['2'], '12': c['1'] + c['2']}.items():
            if k in r: out[k] = (v, r[k])
    if ai_u is not None and 'Under 2.5' in r:
        u = r['Under 2.5'] + WAGA_AI * (ai_u - sk['u25'] - r['Under 2.5'])
        out['Under 2.5'] = (u, r['Under 2.5'])
        if 'Over 2.5' in r: out['Over 2.5'] = (1 - u, r['Over 2.5'])
    if ai_b is not None and 'BTTS Tak' in r:
        b = r['BTTS Tak'] + WAGA_AI * (ai_b - sk['btts'] - r['BTTS Tak'])
        out['BTTS Tak'] = (b, r['BTTS Tak'])
        if 'BTTS Nie' in r: out['BTTS Nie'] = (1 - b, r['BTTS Nie'])
    return out


def typ_po_korekcie(kor):
    """Klucz z największą przewagą (szansa po korekcie / szansa rynku − 1) ≥ MIN_PRZEWAGA albo None."""
    best = max(((p / r - 1, k) for k, (p, r) in kor.items() if r and 0.05 <= r <= 0.95 and p - r >= MIN_ROZNICA), default=None)
    return best[1] if best and best[0] >= MIN_PRZEWAGA else None


def _u25_z_kubelkow(g):
    try: return float(g.get('0-1', 0)) + float(g.get('2', 0)) if isinstance(g, dict) and g else None
    except Exception: return None


# ------------------------------------------------------------------ analiza meczu piłki
def analiza_pilka(dom, gosc, dom_pl, gosc_pl, rozgrywki, start, fm, rynek, typ, lista):
    """rynek: {'1','X','2'} szanse z kursów; typ: (opis, szansa) albo None; lista: {klucz: (opis, szansa rynku)}."""
    if not mozna(): return None
    teczka, nazwiska = teczka_pilka(fm)
    kiedy = pd.Timestamp(start).strftime('%d.%m.%Y %H:%M')
    wsp = dict(mecz=f'{dom_pl} – {gosc_pl}', rozgrywki=rozgrywki, kiedy=kiedy, zasady=ZASADY, teczka=teczka or 'brak danych FotMob')
    a, zr1 = zapytaj(KROK1.format(dom=f'{dom_pl} ({dom})', gosc=f'{gosc_pl} ({gosc})', **wsp))
    if not a: return None
    a['fakty'] = _sprawdz_fakty(a.get('fakty'), nazwiska, (dom, gosc, dom_pl, gosc_pl))
    r, zr2 = zapytaj(KROK2.format(analiza=json.dumps(a, ensure_ascii=False)[:9000], **wsp))
    if r: r['przeoczone'] = _sprawdz_fakty(r.get('przeoczone'), nazwiska, (dom, gosc, dom_pl, gosc_pl))
    _dodaj_koszt(0, mecz=1); STAN['analiz'] += 1
    return sedzia(dict(a=a, r=r, zr=[x for x in zr1 + zr2], nazwiska=sorted(nazwiska)[:400], wsp=wsp, dom_pl=dom_pl, gosc_pl=gosc_pl), rynek, typ, lista)


def sedzia(kroki, rynek, typ, lista):
    """Wersja 45: krok 3 (sędzia, bez wyszukiwania) na zapamiętanych krokach 1–2 – wołany po pełnej analizie i ponownie,
    gdy zmieni się typ główny meczu (nowy werdykt dla aktualnego typu, tanio – bez powtarzania wyszukiwania)."""
    a, r, wsp, dom_pl, gosc_pl = kroki['a'], kroki.get('r'), kroki['wsp'], kroki['dom_pl'], kroki['gosc_pl']
    zr1, zr2 = kroki.get('zr') or [], []
    rk = f"wygra {dom_pl} {rynek['1']:.1%}, remis {rynek['X']:.1%}, wygra {gosc_pl} {rynek['2']:.1%}"
    lst = '; '.join(f'{k}: {o} – {p:.1%}' for k, (o, p) in lista.items())
    s, _ = zapytaj(KROK3.format(rynek=rk, typ=(f'{typ[0]} (szansa rynku {typ[1]:.1%})' if typ else 'brak'), lista=lst,
                                analiza=json.dumps(a, ensure_ascii=False)[:9000], recenzja=json.dumps(r or {}, ensure_ascii=False)[:6000], **wsp),
                   szukaj=False)
    if not s: return None
    w = str(s.get('werdykt') or '').lower().strip()
    if w not in ('mocna_zgoda', 'zgoda', 'ryzyko', 'odradza'): w = 'ryzyko'
    za, przeciw = [str(x)[:260] for x in (s.get('za') or [])][:4], [str(x)[:260] for x in (s.get('przeciw') or [])][:4]
    if w in ('mocna_zgoda', 'zgoda') and len(przeciw) < 2: w = 'niepelna'        # wersja 45: bez rzetelnych „przeciw” – ocena niepełna (nie „ryzyko”)
    ta = s.get('typ_analityka') or {}
    kl_ai = str(ta.get('klucz') or 'brak')
    if kl_ai not in lista: kl_ai = 'brak'
    g3 = s.get('gole') if isinstance(s.get('gole'), dict) else {}
    ai_u = _p01(g3.get('ponizej_2_5')) or _u25_z_kubelkow(a.get('gole'))
    ai_b = _p01(g3.get('obie_strzela')) or _p01(a.get('obie_strzela'))
    sk = skrzywienie()
    kor = korekta(_szanse(s.get('szanse')) or _szanse(a.get('szanse')), ai_u, ai_b, lista, sk)
    kl = typ_po_korekcie(kor) or 'brak'
    uz = str(ta.get('uzasadnienie') or '')[:260] if kl == kl_ai else ''
    zr = {x['link']: x for x in zr1 + zr2}.values()
    return dict(model=STAN['model'], werdykt=w, powod=str(s.get('powod') or '')[:260], podsumowanie=str(s.get('podsumowanie') or '')[:900],
                za=za, przeciw=przeciw, szanse=_szanse(s.get('szanse')), szanse_na_slepo=_szanse(a.get('szanse')),
                szanse_adwokat=_szanse((r or {}).get('szanse')), gole=a.get('gole'), obie_strzela=a.get('obie_strzela'),
                scenariusze=[dict(opis=str(x.get('opis'))[:220], wynik=str(x.get('wynik'))[:6], szansa=x.get('szansa'))
                             for x in (a.get('scenariusze') or []) if isinstance(x, dict)][:3],
                scenariusz_przeciw=(r or {}).get('scenariusz_przeciw'),
                bledy_analizy=[str((x or {}).get('problem'))[:200] for x in ((r or {}).get('bledy') or [])][:4],
                fakty=[dict(tekst=str(f.get('tekst'))[:240], zrodlo=str(f.get('zrodlo'))[:200], niezweryfikowane=f.get('niezweryfikowane'))
                       for f in (a.get('fakty') or [])][:12],
                niewiadome=[str(x)[:160] for x in (a.get('niewiadome') or [])][:5], pewnosc=a.get('pewnosc_analizy'),
                typ_analityka=dict(klucz=kl, opis=lista[kl][0] if kl in lista else None,
                                   szansa=round(kor[kl][0], 4) if kl in kor else None,
                                   szansa_rynku=lista[kl][1] if kl in lista else None, uzasadnienie=uz,
                                   klucz_ai=kl_ai, szansa_ai=ta.get('szansa'), po_korekcie=True),
                _rynek_typu_ai=lista[kl_ai][1] if kl_ai in lista else None, ai_u25=ai_u, ai_btts=ai_b, rynek_u25=(lista.get('Under 2.5') or (None, None))[1],
                rynek_btts=(lista.get('BTTS Tak') or (None, None))[1], skrzywienie=sk,
                wynik_dokladny=s.get('wynik_dokladny'), zrodla=list(zr)[:10], typ=typ[0] if typ else None, kroki=kroki,
                czas=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'))


# ------------------------------------------------------------------ dziennik Analityka
KOL = ['data_zapisu', 'sport', 'liga', 'event_id', 'mecz', 'start', 'werdykt', 'typ_programu', 'ai_1', 'ai_x', 'ai_2', 'rynek_1', 'rynek_x', 'rynek_2',
       'typ_klucz', 'typ_opis', 'typ_szansa_ai', 'typ_szansa_rynku', 'wynik_ai', 'wynik', 'typ_trafiony', 'wynik_trafiony', 'model',
       'ai_u25', 'rynek_u25', 'ai_btts', 'rynek_btts', 'typ_klucz_ai', 'typ_szansa_ai_wlasna', 'typ_szansa_rynku_ai', 'typ_ai_trafiony']


def zapisz(sport, event_id, mecz, start, typ_prog, rynek, a, liga=''):
    w = dict(data_zapisu=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'), sport=sport, liga=liga, event_id=event_id, mecz=mecz,
             start=pd.Timestamp(start).strftime('%Y-%m-%d %H:%M'), werdykt=a.get('werdykt'), typ_programu=typ_prog or '',
             ai_1=(a.get('szanse') or {}).get('1'), ai_x=(a.get('szanse') or {}).get('X'), ai_2=(a.get('szanse') or {}).get('2'),
             rynek_1=rynek.get('1'), rynek_x=rynek.get('X'), rynek_2=rynek.get('2'),
             typ_klucz=a['typ_analityka']['klucz'], typ_opis=a['typ_analityka']['opis'] or '', typ_szansa_ai=a['typ_analityka']['szansa'],
             typ_szansa_rynku=a['typ_analityka']['szansa_rynku'], wynik_ai=str((a.get('wynik_dokladny') or {}).get('wynik') or ''),
             wynik='', typ_trafiony=np.nan, wynik_trafiony=np.nan, model=a.get('model'),
             ai_u25=a.get('ai_u25'), rynek_u25=a.get('rynek_u25'), ai_btts=a.get('ai_btts'), rynek_btts=a.get('rynek_btts'),
             typ_klucz_ai=a['typ_analityka'].get('klucz_ai'), typ_szansa_ai_wlasna=a['typ_analityka'].get('szansa_ai'),
             typ_szansa_rynku_ai=a.get('_rynek_typu_ai'), typ_ai_trafiony=np.nan)
    try: d = pd.read_csv(PLIK_DZIENNIKA, dtype={'event_id': str})
    except Exception: d = pd.DataFrame(columns=KOL)
    d = d[~((d.event_id.astype(str) == str(event_id)) & (d.wynik.isna() | (d.wynik.astype(str) == '')))]
    d = pd.concat([d, pd.DataFrame([w])], ignore_index=True)
    d.to_csv(PLIK_DZIENNIKA, index=False)


def rozlicz(wynik_meczu, maski, maxg, plik=None):
    """wynik_meczu(event_id, gosp, gosc, start, liga) -> (gh, ga) albo None. plik – inny dziennik o tych samych kolumnach (Flash)."""
    plik = plik or PLIK_DZIENNIKA
    try: d = pd.read_csv(plik, dtype={'event_id': str, 'wynik': str})
    except Exception: return
    teraz = pd.Timestamp.now(tz='Europe/Warsaw').tz_localize(None); zm = False
    pil = d.sport.fillna('pilka').astype(str) == 'pilka' if 'sport' in d else True
    for i, r in d[pil & (d.wynik.isna() | (d.wynik == '')) & (pd.to_datetime(d.start) < teraz - pd.Timedelta(hours=2.5))].iterrows():
        try: g, a_ = str(r.mecz).split(' – ', 1)
        except Exception: continue
        w = wynik_meczu(str(r.event_id), g, a_, r.start, str(r.get('liga') or ''))
        if not w or None in w: continue
        hg, ag = int(w[0]), int(w[1]); d.loc[i, 'wynik'] = f'{hg}:{ag}'; zm = True
        if r.typ_klucz in maski: d.loc[i, 'typ_trafiony'] = float(bool(maski[r.typ_klucz][min(hg, maxg), min(ag, maxg)]))
        kai = r.get('typ_klucz_ai')
        if isinstance(kai, str) and kai in maski: d.loc[i, 'typ_ai_trafiony'] = float(bool(maski[kai][min(hg, maxg), min(ag, maxg)]))
        d.loc[i, 'wynik_trafiony'] = float(str(r.wynik_ai).replace('-', ':').strip() == f'{hg}:{ag}')
    if zm: d.to_csv(plik, index=False)


KOL_FLASH = ['data_zapisu', 'sport', 'liga', 'event_id', 'mecz', 'start', 'ai_1', 'ai_x', 'ai_2', 'rynek_1', 'rynek_x', 'rynek_2',
             'ai_u25', 'rynek_u25', 'typ_klucz', 'wynik_ai', 'wynik', 'typ_trafiony', 'wynik_trafiony', 'model']


def zapisz_flash(event_id, mecz, start, liga, rynek, ai):
    """Wersja 44: szanse Flash (1X2, poniżej 2,5) przy każdym meczu z analizą – ocena „czy AI bije rynek” na dużej próbie."""
    sw = (ai or {}).get('szanse_wlasne')
    if not sw or not rynek or not all(k in rynek for k in ('1', 'X', '2')): return
    u = rynek.get('Under 2.5') if rynek.get('Under 2.5') is not None else (1 - rynek['Over 2.5'] if rynek.get('Over 2.5') is not None else None)
    w = dict(data_zapisu=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'), sport='pilka', liga=liga, event_id=str(event_id), mecz=mecz,
             start=pd.Timestamp(start).strftime('%Y-%m-%d %H:%M'), ai_1=sw['1'], ai_x=sw['X'], ai_2=sw['2'],
             rynek_1=rynek['1'], rynek_x=rynek['X'], rynek_2=rynek['2'], ai_u25=ai.get('ponizej_2_5'), rynek_u25=u,
             typ_klucz='', wynik_ai='', wynik='', typ_trafiony=np.nan, wynik_trafiony=np.nan, model=ai.get('model'))
    try: d = pd.read_csv(PLIK_FLASH, dtype={'event_id': str, 'wynik': str})
    except Exception: d = pd.DataFrame(columns=KOL_FLASH)
    d = d[~((d.event_id.astype(str) == str(event_id)) & (d.wynik.isna() | (d.wynik.astype(str) == '')))]
    pd.concat([d, pd.DataFrame([w])], ignore_index=True).to_csv(PLIK_FLASH, index=False)


def statystyki_flash():
    """Trafność szans 1X2 Flash vs rynek (log-loss) i jego skrzywienie (remis, poniżej 2,5)."""
    try: d = pd.read_csv(PLIK_FLASH, dtype={'wynik': str})
    except Exception: return None
    out = dict(wszystkich=len(d))
    num = lambda c: pd.to_numeric(d[c], errors='coerce')
    out['skrzywienie_x'] = round(float((num('ai_x') - num('rynek_x')).mean()), 4) if len(d) else None
    out['skrzywienie_u25'] = round(float((num('ai_u25') - num('rynek_u25')).mean()), 4) if num('ai_u25').notna().any() else None
    r = d[d.wynik.fillna('').str.contains(':')]
    out['n'] = len(r)
    if len(r):
        gh = r.wynik.str.split(':').str[0].astype(int); ga = r.wynik.str.split(':').str[1].astype(int)
        y = np.where(gh > ga, 0, np.where(gh == ga, 1, 2))
        A = r[['ai_1', 'ai_x', 'ai_2']].apply(pd.to_numeric, errors='coerce').values; M = r[['rynek_1', 'rynek_x', 'rynek_2']].apply(pd.to_numeric, errors='coerce').values
        ok = np.isfinite(A).all(1) & np.isfinite(M).all(1)
        if ok.any():
            out['logloss_ai'] = round(float(-np.log(np.clip(A[ok][np.arange(ok.sum()), y[ok]], 1e-6, 1)).mean()), 4)
            out['logloss_rynek'] = round(float(-np.log(np.clip(M[ok][np.arange(ok.sum()), y[ok]], 1e-6, 1)).mean()), 4)
    return out


def statystyki():
    """Czy Analityk bije rynek: log-loss 1X2 AI vs rynek, typy Analityka po kursie rynku (bez marży), dokładne wyniki."""
    try: d = pd.read_csv(PLIK_DZIENNIKA)
    except Exception: return None
    for c in KOL:                      # starsze dzienniki bez kolumn wersji 44
        if c not in d: d[c] = np.nan
    r_all = d[d.wynik.notna() & (d.wynik.astype(str) != '')].copy()
    if not len(r_all): return dict(n=0, wszystkich=len(d), flash=statystyki_flash())
    r = r_all[r_all.wynik.astype(str).str.contains(':')].copy()
    if not len(r): r = r_all.iloc[0:0]
    gh = r.wynik.str.split(':').str[0].astype(int); ga = r.wynik.str.split(':').str[1].astype(int)
    y = np.where(gh > ga, 0, np.where(gh == ga, 1, 2))
    A = r[['ai_1', 'ai_x', 'ai_2']].astype(float).values; M = r[['rynek_1', 'rynek_x', 'rynek_2']].astype(float).values
    ok = np.isfinite(A).all(1) & np.isfinite(M).all(1)
    ll = lambda X: float(-np.log(np.clip(X[ok][np.arange(ok.sum()), y[ok]], 1e-6, 1)).mean()) if ok.any() else None
    def _typy(t, ps, tr):
        z = [(1 / float(p) - 1) if x >= 0.5 else -1.0 for p, x in zip(t[ps], t[tr]) if pd.notna(p) and float(p) > 0 and pd.notna(x)]
        kursy = [1 / float(p) for p in t[ps] if pd.notna(p) and float(p) > 0]
        return dict(n=len(z), trafione=int(sum(1 for p, x in zip(t[ps], t[tr]) if pd.notna(p) and pd.notna(x) and x >= 0.5)),
                    sredni_kurs=round(float(np.mean(kursy)), 2) if kursy else None, roi=round(float(np.mean(z)), 4) if z else None)
    nowe = r_all['typ_klucz_ai'].notna() if 'typ_klucz_ai' in r_all else pd.Series(False, index=r_all.index)
    t_kor = r_all[nowe & r_all.typ_trafiony.notna()]                                  # wersja 44: typ po korekcie (wybór programu)
    t_ai = pd.concat([r_all[nowe & r_all.get('typ_ai_trafiony', pd.Series(index=r_all.index, dtype=float)).notna()]
                      .assign(_p=lambda x: x.typ_szansa_rynku_ai, _t=lambda x: x.typ_ai_trafiony),
                      r_all[~nowe & r_all.typ_trafiony.notna()].assign(_p=lambda x: x.typ_szansa_rynku, _t=lambda x: x.typ_trafiony)])
    return dict(n=len(r_all), n_pilka=len(r), wszystkich=len(d), logloss_ai=ll(A), logloss_rynek=ll(M), skrzywienie=skrzywienie(),
                typy=_typy(t_kor, 'typ_szansa_rynku', 'typ_trafiony'), typy_ai=_typy(t_ai, '_p', '_t') if len(t_ai) else dict(n=0),
                wyniki_dokladne=dict(n=int(r.wynik_trafiony.notna().sum()), trafione=int((r.wynik_trafiony >= 0.5).sum())),
                werdykty={k: int(len(g)) for k, g in r_all.groupby('werdykt')}, flash=statystyki_flash())


# ------------------------------------------------------------------ tenis i sporty walki (wersja 36)
OPIS_SPORTU = {'tenis': ('mecz tenisowy', 'zawodników', 'forma i wyniki z ostatnich turniejów, nawierzchnia i to, jak każdy na niej gra, '
                         'kontuzje i krecze, zmęczenie (długie mecze dzień wcześniej, podróże), bilans bezpośredni, styl (serwis, return, '
                         'gra z głębi kortu) i jak style do siebie pasują, motywacja (punkty rankingowe, obrona punktów), warunki (hala, wysokość, pogoda)',
                         'wynik w setach, np. 2:1'),
               'walki': ('walka', 'zawodników', 'bilans i forma, ostatnie walki i sposób zwycięstw/porażek, styl (stójka, zapasy, parter), zasięg, wiek, '
                         'przerwa od ostatniej walki, problemy z wagą i ważenie, obóz przygotowawczy i trener, kontuzje, zmiana kategorii, '
                         'liczba rund (3 czy 5), motywacja (pas, kontrakt)', 'zwycięzca i sposób, np. A przez KO w 2. rundzie albo B na punkty')}

KROK1_INNE = """ZADANIE: krok 1 z 3 – ANALIZA NA ŚLEPO. Nie znasz kursów bukmacherów i nie szukaj ich („odds”, „kursy”, „typy”, „prediction”).
{co}: A = {a}, B = {b} ({turniej}), {kiedy} czasu polskiego.
Wyszukaj najnowsze informacje (ostatnie 14 dni) i oceń: {tematy}.
DANE PROGRAMU (pewne): {teczka}
{zasady}
Postać odpowiedzi:
{{"fakty": [{{"tekst": "konkretny fakt", "zrodlo": "link albo teczka", "znaczenie": "dla kogo i jak wpływa"}}],
  "styl": "jak style obu {kogo} do siebie pasują (2-3 zdania)", "szanse": {{"A": 0.0, "B": 0.0}},
  "scenariusze": [{{"opis": "jak przebiegnie", "wynik": "{wynik}", "szansa": 0.0}}, {{...}}, {{...}}],
  "pewnosc_analizy": "niska" | "srednia" | "wysoka", "niewiadome": ["czego nie udało się ustalić"]}}"""

KROK2_INNE = """ZADANIE: krok 2 z 3 – ADWOKAT DIABŁA. Inny analityk przygotował analizę: {co} A = {a}, B = {b} ({turniej}, {kiedy}).
Znajdź w niej błędy – jesteś najostrzejszym recenzentem. Sprawdź w Google ważne twierdzenia. 1) fakty nieprawdziwe, nieaktualne, bez źródła;
2) przeoczenia; 3) przesadna pewność; 4) NAJMOCNIEJSZY REALNY scenariusz przeciw jego wnioskowi; 5) Twoje szanse A/B po poprawkach.
ANALIZA: {analiza}
DANE PROGRAMU (pewne): {teczka}
{zasady}
Postać odpowiedzi:
{{"bledy": [{{"twierdzenie": "...", "problem": "...", "zrodlo": "link albo teczka"}}], "przeoczone": [{{"tekst": "...", "zrodlo": "...", "znaczenie": "..."}}],
  "przesadna_pewnosc": "...", "scenariusz_przeciw": {{"opis": "...", "wynik": "...", "szansa": 0.0}}, "szanse": {{"A": 0.0, "B": 0.0}}}}"""

KROK3_INNE = """ZADANIE: krok 3 z 3 – SĘDZIA. {co}: A = {a}, B = {b} ({turniej}, {kiedy}). Masz analizę (krok 1) i recenzję (krok 2).
Dopiero teraz widzisz rynek: szanse z kursów (bez marży): A {ra:.1%}, B {rb:.1%}. Program proponuje typ: {typ}.
Kurs zawiera wiedzę tysięcy graczy – nie ignoruj go, ale go nie powtarzaj. CO NAJMNIEJ 2 argumenty ZA typem programu i 2 PRZECIW, każdy
z faktem z kroku 1 lub 2. Werdykt dla typu programu: "mocna_zgoda" | "zgoda" | "ryzyko" | "odradza".
Typ Analityka: JEDEN zakład z listy (klucz), w którym Twoja szansa najbardziej przewyższa szansę rynku, albo "brak".
Lista (klucz: opis – szansa rynku): {lista}
ANALIZA (krok 1): {analiza}
RECENZJA (krok 2): {recenzja}
{zasady}
Postać odpowiedzi:
{{"za": ["...", "..."], "przeciw": ["...", "..."], "szanse": {{"A": 0.0, "B": 0.0}}, "werdykt": "...", "powod": "jedno zdanie",
  "typ_analityka": {{"klucz": "klucz z listy albo brak", "szansa": 0.0, "uzasadnienie": "dlaczego rynek się tu myli"}},
  "wynik_dokladny": {{"wynik": "{wynik}", "szansa": 0.0}}, "podsumowanie": "4-6 zdań"}}"""


def _szanse_ab(d):
    try:
        a, b = float((d or {}).get('A')), float((d or {}).get('B')); t = a + b
        return {'A': round(a / t, 4), 'B': round(b / t, 4)} if t > 0 else None
    except Exception: return None


def analiza_inne(m, lista=None):
    """Tenis / MMA / boks – m: mecz z inne.json (a, b, turniej, start, szansa_a, rynki, najpewniejszy, analityk…)."""
    if not mozna(): return None
    sp = m.get('sport') if m.get('sport') in OPIS_SPORTU else 'tenis'
    co, kogo, tematy, wynik = OPIS_SPORTU[sp]
    lista = lista or {k: (v[0], float(v[1])) for k, v in (m.get('rynki') or {}).items()}
    if not lista and m.get('szansa_a'):
        lista = {'A': (f"wygra {m['a']}", float(m['szansa_a'])), 'B': (f"wygra {m['b']}", 1 - float(m['szansa_a']))}
    tecz = {k: m.get(k) for k in ('turniej', 'dyscyplina', 'bo', 'kategoria', 'rundy', 'wta') if m.get(k) is not None}
    if (m.get('analityk') or {}).get('powody'): tecz['czynniki_programu'] = m['analityk']['powody']
    teczka = json.dumps(tecz, ensure_ascii=False)
    kiedy = f"{m.get('dzien', '')} {m.get('godzina', '')}".strip() or str(m.get('start', ''))
    wsp = dict(co=co, a=m['a'], b=m['b'], turniej=m.get('turniej', ''), kiedy=kiedy, zasady=ZASADY, teczka=teczka, kogo=kogo)
    a, zr1 = zapytaj(KROK1_INNE.format(tematy=tematy, wynik=wynik, **wsp))
    if not a: return None
    a['fakty'] = _sprawdz_fakty(a.get('fakty'), set(), (m['a'], m['b']))
    r, zr2 = zapytaj(KROK2_INNE.format(analiza=json.dumps(a, ensure_ascii=False)[:9000], **wsp))
    t = m.get('najpewniejszy') or {}
    typ = f"{t.get('zaklad')} (szansa rynku {float(t.get('szansa')):.1%})" if t.get('zaklad') and t.get('szansa') else 'brak'
    ra = float(m.get('szansa_a') or 0.5)
    lst = '; '.join(f'{k}: {o} – {p:.1%}' for k, (o, p) in lista.items())
    s, _ = zapytaj(KROK3_INNE.format(ra=ra, rb=1 - ra, typ=typ, lista=lst, wynik=wynik, analiza=json.dumps(a, ensure_ascii=False)[:9000],
                                     recenzja=json.dumps(r or {}, ensure_ascii=False)[:6000], **wsp), szukaj=False)
    _dodaj_koszt(0, mecz=1); STAN['analiz'] += 1
    if not s: return None
    w = str(s.get('werdykt') or '').lower().strip()
    if w not in ('mocna_zgoda', 'zgoda', 'ryzyko', 'odradza'): w = 'ryzyko'
    za, przeciw = [str(x)[:260] for x in (s.get('za') or [])][:4], [str(x)[:260] for x in (s.get('przeciw') or [])][:4]
    if w in ('mocna_zgoda', 'zgoda') and len(przeciw) < 2: w = 'niepelna'        # wersja 45
    ta = s.get('typ_analityka') or {}; kl_ai = str(ta.get('klucz') or 'brak')
    if kl_ai not in lista: kl_ai = 'brak'
    sz = _szanse_ab(s.get('szanse'))
    # wersja 47: korekta jak w piłce – wyostrzenie szans AI (AI spłaszcza faworytów), ściągnięcie do rynku, typ wybiera program
    kor = {}
    if sz and 'A' in lista and 'B' in lista:
        g = SKRZYWIENIE_START['gamma']; pa, pb = max(sz['A'], 1e-4) ** g, max(sz['B'], 1e-4) ** g; pa = pa / (pa + pb)
        ca = lista['A'][1] + WAGA_AI * (pa - lista['A'][1])
        kor = {'A': (ca, lista['A'][1]), 'B': (1 - ca, lista['B'][1])}
    try:
        if kl_ai not in ('brak', 'A', 'B') and _p01(ta.get('szansa')):
            r0 = lista[kl_ai][1]; kor[kl_ai] = (r0 + WAGA_AI * (float(ta['szansa']) - r0), r0)
    except Exception: pass
    kl = typ_po_korekcie(kor) or 'brak'
    uz = str(ta.get('uzasadnienie') or '')[:260] if kl == kl_ai else ''
    return dict(model=STAN['model'], werdykt=w, powod=str(s.get('powod') or '')[:260], podsumowanie=str(s.get('podsumowanie') or '')[:900],
                za=za, przeciw=przeciw, szanse_ab=sz, szanse_na_slepo_ab=_szanse_ab(a.get('szanse')), szanse_adwokat_ab=_szanse_ab((r or {}).get('szanse')),
                scenariusze=[dict(opis=str(x.get('opis'))[:220], wynik=str(x.get('wynik'))[:60], szansa=x.get('szansa'))
                             for x in (a.get('scenariusze') or []) if isinstance(x, dict)][:3],
                scenariusz_przeciw=(r or {}).get('scenariusz_przeciw'),
                bledy_analizy=[str((x or {}).get('problem'))[:200] for x in ((r or {}).get('bledy') or [])][:4],
                fakty=[dict(tekst=str(f.get('tekst'))[:240], zrodlo=str(f.get('zrodlo'))[:200]) for f in (a.get('fakty') or [])][:12],
                niewiadome=[str(x)[:160] for x in (a.get('niewiadome') or [])][:5], pewnosc=a.get('pewnosc_analizy'),
                typ_analityka=dict(klucz=kl, opis=lista[kl][0] if kl in lista else None,
                                   szansa=round(kor[kl][0], 4) if kl in kor else None,
                                   szansa_rynku=lista[kl][1] if kl in lista else None, uzasadnienie=uz,
                                   klucz_ai=kl_ai, szansa_ai=ta.get('szansa'), po_korekcie=True),
                _rynek_typu_ai=lista[kl_ai][1] if kl_ai in lista else None,
                wynik_dokladny=s.get('wynik_dokladny'), zrodla=list({x['link']: x for x in zr1 + zr2}.values())[:10],
                czas=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'))


def zapisz_inne(m, a):
    """Dziennik Analityka – tenis/walki: szanse A/B AI i rynku (ai_1 = A, ai_2 = B), typ Analityka."""
    sz = a.get('szanse_ab') or {}; ra = float(m.get('szansa_a') or 0)
    w = dict(data_zapisu=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'), sport=m.get('sport'), liga=m.get('sport_key', ''),
             event_id=m.get('event_id'), mecz=m.get('mecz') or f"{m['a']} – {m['b']}", start=str(m.get('start', ''))[:16], werdykt=a.get('werdykt'),
             typ_programu=(m.get('najpewniejszy') or {}).get('zaklad', ''), ai_1=sz.get('A'), ai_x=0.0, ai_2=sz.get('B'),
             rynek_1=ra, rynek_x=0.0, rynek_2=round(1 - ra, 4) if ra else None,
             typ_klucz=a['typ_analityka']['klucz'], typ_opis=a['typ_analityka']['opis'] or '', typ_szansa_ai=a['typ_analityka']['szansa'],
             typ_szansa_rynku=a['typ_analityka']['szansa_rynku'], wynik_ai=str((a.get('wynik_dokladny') or {}).get('wynik') or '')[:40],
             wynik='', typ_trafiony=np.nan, wynik_trafiony=np.nan, model=a.get('model'))
    try: d = pd.read_csv(PLIK_DZIENNIKA, dtype={'event_id': str})
    except Exception: d = pd.DataFrame(columns=KOL)
    d = d[~((d.event_id.astype(str) == str(w['event_id'])) & (d.wynik.isna() | (d.wynik.astype(str) == '')))]
    pd.concat([d, pd.DataFrame([w])], ignore_index=True).to_csv(PLIK_DZIENNIKA, index=False)


def rozlicz_inne(typy_inne_csv):
    """Tenis/walki: zwycięzca z rozliczonego dziennika typy_inne.csv (typ 'A'/'B' tego samego meczu) → wynik 'A'/'B'; typ Analityka 'A'/'B'."""
    try:
        d = pd.read_csv(PLIK_DZIENNIKA, dtype={'event_id': str, 'wynik': str}); t = pd.read_csv(typy_inne_csv, dtype={'event_id': str})
    except Exception: return
    zm = False
    for i, r in d[(d.sport.isin(['tenis', 'walki'])) & (d.wynik.isna() | (d.wynik == ''))].iterrows():
        x = t[(t.event_id == str(r.event_id)) & t.trafiony.notna() & t.klucz.isin(['A', 'B'])]
        if not len(x): continue
        k, tr = x.iloc[0].klucz, float(x.iloc[0].trafiony)
        zw = k if tr >= 0.5 else ('B' if k == 'A' else 'A')
        d.loc[i, 'wynik'] = zw; zm = True
        if r.typ_klucz in ('A', 'B'): d.loc[i, 'typ_trafiony'] = float(r.typ_klucz == zw)
    if zm: d.to_csv(PLIK_DZIENNIKA, index=False)
