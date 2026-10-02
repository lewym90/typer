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


def mozna():
    d = _licznik()
    STAN['koszt_dzis_zl'], STAN['koszt_miesiac_zl'] = d.get('koszt_dzis_zl', 0), d.get('koszt_zl', 0)
    if not KLUCZ or d.get('koszt_zl', 0) + 1.0 > BUDZET_ZL or d.get('meczow', 0) >= MAKS_MECZOW_DZIENNIE: return False
    if os.environ.get('AI_PRO_RECZNE'): return True        # serwer (analiza ręczna): tylko limit miesięczny + limit dzienny serwera
    return d.get('koszt_dzis_zl', 0) + 1.0 <= limit_dzis()     # ~1 zł = zapas na jeden mecz (3 kroki Pro z wyszukiwaniem)


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
    txt = re.sub(r'^```(?:json)?|```$', '', (txt or '').strip(), flags=re.M).strip()
    i, j = txt.find('{'), txt.rfind('}')
    return json.loads(txt[i:j + 1])


def zapytaj(tekst, szukaj=True):
    """(dane JSON, źródła z wyszukiwania) albo (None, [])."""
    for m in model_pro():
        body = {'contents': [{'parts': [{'text': tekst}]}],
                'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 12000}}
        if szukaj: body['tools'] = [{'google_search': {}}]
        else: body['generationConfig']['responseMimeType'] = 'application/json'
        try: r = requests.post(URL.format(m=m), json=body, timeout=240, headers={'x-goog-api-key': KLUCZ})
        except Exception as e: _blad(f'{m}: {e}'); continue
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
        except Exception: _blad(f'{m}: nieczytelny JSON: {txt[:120]}'); continue
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
                if re.search(r'(liga|league|cup|puchar|stadion|stadium|arena|fc|uefa|fifa|nations|world|euro)', k): continue
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
    rk = f"wygra {dom_pl} {rynek['1']:.1%}, remis {rynek['X']:.1%}, wygra {gosc_pl} {rynek['2']:.1%}"
    lst = '; '.join(f'{k}: {o} – {p:.1%}' for k, (o, p) in lista.items())
    s, _ = zapytaj(KROK3.format(rynek=rk, typ=(f'{typ[0]} (szansa rynku {typ[1]:.1%})' if typ else 'brak'), lista=lst,
                                analiza=json.dumps(a, ensure_ascii=False)[:9000], recenzja=json.dumps(r or {}, ensure_ascii=False)[:6000], **wsp),
                   szukaj=False)
    _dodaj_koszt(0, mecz=1); STAN['analiz'] += 1
    if not s: return None
    w = str(s.get('werdykt') or '').lower().strip()
    if w not in ('mocna_zgoda', 'zgoda', 'ryzyko', 'odradza'): w = 'ryzyko'
    za, przeciw = [str(x)[:260] for x in (s.get('za') or [])][:4], [str(x)[:260] for x in (s.get('przeciw') or [])][:4]
    if w in ('mocna_zgoda', 'zgoda') and len(przeciw) < 2: w = 'ryzyko'          # bez rzetelnych „przeciw” nie ma zgody
    ta = s.get('typ_analityka') or {}
    kl = str(ta.get('klucz') or 'brak')
    if kl not in lista: kl = 'brak'
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
                typ_analityka=dict(klucz=kl, opis=lista[kl][0] if kl in lista else None, szansa=ta.get('szansa'),
                                   szansa_rynku=lista[kl][1] if kl in lista else None, uzasadnienie=str(ta.get('uzasadnienie') or '')[:260]),
                wynik_dokladny=s.get('wynik_dokladny'), zrodla=list(zr)[:10],
                czas=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'))


# ------------------------------------------------------------------ dziennik Analityka
KOL = ['data_zapisu', 'sport', 'liga', 'event_id', 'mecz', 'start', 'werdykt', 'typ_programu', 'ai_1', 'ai_x', 'ai_2', 'rynek_1', 'rynek_x', 'rynek_2',
       'typ_klucz', 'typ_opis', 'typ_szansa_ai', 'typ_szansa_rynku', 'wynik_ai', 'wynik', 'typ_trafiony', 'wynik_trafiony', 'model']


def zapisz(sport, event_id, mecz, start, typ_prog, rynek, a, liga=''):
    w = dict(data_zapisu=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'), sport=sport, liga=liga, event_id=event_id, mecz=mecz,
             start=pd.Timestamp(start).strftime('%Y-%m-%d %H:%M'), werdykt=a.get('werdykt'), typ_programu=typ_prog or '',
             ai_1=(a.get('szanse') or {}).get('1'), ai_x=(a.get('szanse') or {}).get('X'), ai_2=(a.get('szanse') or {}).get('2'),
             rynek_1=rynek.get('1'), rynek_x=rynek.get('X'), rynek_2=rynek.get('2'),
             typ_klucz=a['typ_analityka']['klucz'], typ_opis=a['typ_analityka']['opis'] or '', typ_szansa_ai=a['typ_analityka']['szansa'],
             typ_szansa_rynku=a['typ_analityka']['szansa_rynku'], wynik_ai=str((a.get('wynik_dokladny') or {}).get('wynik') or ''),
             wynik='', typ_trafiony=np.nan, wynik_trafiony=np.nan, model=a.get('model'))
    try: d = pd.read_csv(PLIK_DZIENNIKA, dtype={'event_id': str})
    except Exception: d = pd.DataFrame(columns=KOL)
    d = d[~((d.event_id.astype(str) == str(event_id)) & (d.wynik.isna() | (d.wynik.astype(str) == '')))]
    d = pd.concat([d, pd.DataFrame([w])], ignore_index=True)
    d.to_csv(PLIK_DZIENNIKA, index=False)


def rozlicz(wynik_meczu, maski, maxg):
    """wynik_meczu(event_id, gosp, gosc, start, liga) -> (gh, ga) albo None."""
    try: d = pd.read_csv(PLIK_DZIENNIKA, dtype={'event_id': str, 'wynik': str})
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
        d.loc[i, 'wynik_trafiony'] = float(str(r.wynik_ai).replace('-', ':').strip() == f'{hg}:{ag}')
    if zm: d.to_csv(PLIK_DZIENNIKA, index=False)


def statystyki():
    """Czy Analityk bije rynek: log-loss 1X2 AI vs rynek, typy Analityka po kursie rynku (bez marży), dokładne wyniki."""
    try: d = pd.read_csv(PLIK_DZIENNIKA)
    except Exception: return None
    r_all = d[d.wynik.notna() & (d.wynik.astype(str) != '')].copy()
    if not len(r_all): return dict(n=0, wszystkich=len(d))
    r = r_all[r_all.wynik.astype(str).str.contains(':')].copy()
    if not len(r): r = r_all.iloc[0:0]
    gh = r.wynik.str.split(':').str[0].astype(int); ga = r.wynik.str.split(':').str[1].astype(int)
    y = np.where(gh > ga, 0, np.where(gh == ga, 1, 2))
    A = r[['ai_1', 'ai_x', 'ai_2']].astype(float).values; M = r[['rynek_1', 'rynek_x', 'rynek_2']].astype(float).values
    ok = np.isfinite(A).all(1) & np.isfinite(M).all(1)
    ll = lambda X: float(-np.log(np.clip(X[ok][np.arange(ok.sum()), y[ok]], 1e-6, 1)).mean()) if ok.any() else None
    t = r_all[r_all.typ_trafiony.notna()]
    zysk = [(1 / float(p) - 1) if tr >= 0.5 else -1.0 for p, tr in zip(t.typ_szansa_rynku, t.typ_trafiony) if p and float(p) > 0]
    return dict(n=len(r_all), n_pilka=len(r), wszystkich=len(d), logloss_ai=ll(A), logloss_rynek=ll(M),
                typy=dict(n=len(zysk), trafione=int((t.typ_trafiony >= 0.5).sum()), sredni_kurs=round(float(np.mean([1 / float(p) for p in t.typ_szansa_rynku if p])), 2) if len(t) else None,
                          roi=round(float(np.mean(zysk)), 4) if zysk else None),
                wyniki_dokladne=dict(n=int(r.wynik_trafiony.notna().sum()), trafione=int((r.wynik_trafiony >= 0.5).sum())),
                werdykty={k: int(len(g)) for k, g in r_all.groupby('werdykt')})


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
    if w in ('mocna_zgoda', 'zgoda') and len(przeciw) < 2: w = 'ryzyko'
    ta = s.get('typ_analityka') or {}; kl = str(ta.get('klucz') or 'brak')
    if kl not in lista: kl = 'brak'
    sz = _szanse_ab(s.get('szanse'))
    return dict(model=STAN['model'], werdykt=w, powod=str(s.get('powod') or '')[:260], podsumowanie=str(s.get('podsumowanie') or '')[:900],
                za=za, przeciw=przeciw, szanse_ab=sz, szanse_na_slepo_ab=_szanse_ab(a.get('szanse')), szanse_adwokat_ab=_szanse_ab((r or {}).get('szanse')),
                scenariusze=[dict(opis=str(x.get('opis'))[:220], wynik=str(x.get('wynik'))[:60], szansa=x.get('szansa'))
                             for x in (a.get('scenariusze') or []) if isinstance(x, dict)][:3],
                scenariusz_przeciw=(r or {}).get('scenariusz_przeciw'),
                bledy_analizy=[str((x or {}).get('problem'))[:200] for x in ((r or {}).get('bledy') or [])][:4],
                fakty=[dict(tekst=str(f.get('tekst'))[:240], zrodlo=str(f.get('zrodlo'))[:200]) for f in (a.get('fakty') or [])][:12],
                niewiadome=[str(x)[:160] for x in (a.get('niewiadome') or [])][:5], pewnosc=a.get('pewnosc_analizy'),
                typ_analityka=dict(klucz=kl, opis=lista[kl][0] if kl in lista else None, szansa=ta.get('szansa'),
                                   szansa_rynku=lista[kl][1] if kl in lista else None, uzasadnienie=str(ta.get('uzasadnienie') or '')[:260]),
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
