"""Wersja 50 – ROZLICZANIE SUROWYCH RYNKÓW FORTUNY (hokej, koszykówka, siatkówka, piłka ręczna, baseball, żużel…).
Zbieracz zapisuje dla nowych dyscyplin rynki tak, jak je nazywa Fortuna: [nazwa rynku, [[wynik, kurs], ...]].
Tu z wyniku meczu (baza wyników: Flashscore/ESPN) wyznaczamy, czy dany zakład wszedł.

Czas gry: rynek z dopiskiem „z dogrywką”, „z … rzutami karnymi”, „razem z dodatkowymi inningami” → wynik końcowy;
bez dopisku: hokej, ręczna, koszykówka (gdy rynek ma remis) → wynik regulaminowy (suma tercji/połów/kwart),
rynek 2-drogowy bez remisu („Zwycięzca meczu”) → wynik końcowy. Zakłady z możliwym zwrotem (linia całkowita równa
wynikowi, remis w „bez remisu”) → None (nie liczymy). Rynki części meczu, zawodników, kombinacje – pomijane (None).
Wynik funkcji `rozlicz`: (trafiony 0/1, kategoria) albo None."""
import re

POMIJANE = ('połow', 'polow', 'kwart', 'tercj', 'bieg', 'inning', 'zawodnik', 'hit', 'rzuty roż', 'rzutów roż', 'rzut roż', 'kartk', 'faul', 'asy', 'as ',
            'wynik po', 'najpopularniejsze', 'kto ', 'pierwsz', 'ostatni', 'przedział', 'przedzial', 'minut', 'set:', 'seta',
            'gem', 'runda', 'rund', 'metoda', 'dokładny wynik po', 'wyścig', 'kwalifikac', 'czy ', 'najwię', 'najmniej',
            'liczba punktów zawodnika', 'serii', 'strzel', 'łączon', '/')
CALOSC = ('dogryw', 'dodatkow', 'karn', 'z og', 'łącznie z')


def _txt(s): return re.sub(r'\s+', ' ', str(s or '').replace('\xa0', ' ').replace('\t', ' ')).strip()


def _strona(nazwa, h, a):
    """'h' / 'a' gdy tekst wskazuje drużynę (nazwa albo „1”/„2”), None gdy niepewne."""
    n = _txt(nazwa).lower()
    if n in ('1', '1.'): return 'h'
    if n in ('2', '2.'): return 'a'
    try:
        import kursy_pl as KP
        ph, pa = KP.podobne(n, h), KP.podobne(n, a)
    except Exception:
        import difflib
        ph = difflib.SequenceMatcher(None, n, str(h).lower()).ratio(); pa = difflib.SequenceMatcher(None, n, str(a).lower()).ratio()
    if max(ph, pa) < 0.6 or abs(ph - pa) < 0.1: return None
    return 'h' if ph > pa else 'a'


def _ou(o):
    m = re.fullmatch(r'([+-]|powyżej|poniżej|więcej niż|mniej niż)\s*(\d+(?:[.,]\d+)?)', _txt(o).lower())
    if not m: return None
    return ('o' if m.group(1) in ('+', 'powyżej', 'więcej niż') else 'u'), float(m.group(2).replace(',', '.'))


def _ponad(wartosc, kier, linia):
    if abs(wartosc - linia) < 1e-9: return None                        # zwrot
    return int(wartosc > linia) if kier == 'o' else int(wartosc < linia)


def _handicap(o, h, a):
    """„1 (-3.5)”, „2 +10.5”, „Unia Leszno +6.5” → (strona, linia)."""
    t = _txt(o)
    m = re.fullmatch(r'(.+?)\s*\(?\s*([+-]\d+(?:[.,]\d+)?)\s*\)?', t)
    if not m: return None
    st = _strona(m.group(1), h, a)
    return (st, float(m.group(2).replace(',', '.'))) if st else None


def rozlicz(sp, rynek, wynik, w, h, a):
    """sp – sport, rynek/wynik – nazwy z Fortuny, w – dict(final=(x, y), reg=(x, y)|None, punkty=(x, y)|None), h/a – nazwy
    drużyn u Fortuny (w tej kolejności jest wynik w). Zwraca (trafiony, kategoria) albo None."""
    n = _txt(rynek).lower(); o = _txt(wynik)
    if ';' in n or any(x in n for x in POMIJANE): return None
    calosc = any(x in n for x in CALOSC)
    fin, reg = w.get('final'), w.get('reg')
    if not fin or None in fin: return None
    # punkty w siatkówce = suma punktów ze wszystkich setów (wynik meczu to sety)
    druz_m = re.fullmatch(r'(?:mecz: )?(.+?)\s*-?\s*liczba (?:goli|punktów|bramek)(?: w meczu)?(?: \(.*\))?', n)
    # ---- zwycięzca / 1X2 / bez remisu / dwójtyp
    if n in ('wynik meczu', 'mecz', 'zwycięzca', 'zwycięzca meczu') or n.startswith(('zwycięzca meczu', 'wynik meczu')) \
            or 'bez remisu' in n or 'dwójtyp' in n:
        ol = o.lower()
        dwojtyp = 'dwójtyp' in n
        if dwojtyp:
            if ol not in ('10', '02', '12'): return None
        elif ol in ('0', 'remis', 'x'): strona = 'r'
        else:
            strona = _strona(o, h, a)
            if not strona: return None
        # rynek 3-drogowy (z remisem): „Wynik meczu” (1/0/2) – czas regulaminowy; „Zwycięzca meczu” – 2-drogowy, z dogrywką
        trzy = not dwojtyp and 'bez remisu' not in n and (n.startswith('wynik meczu') or strona == 'r')
        regulamin = (trzy or dwojtyp or 'bez remisu' in n) and not calosc
        if regulamin and sp == 'baseball': return None                      # 9 inningów – brak wyniku po 9. inningu
        if regulamin and sp in ('hokej', 'pilka_reczna', 'koszykowka') and not reg: return None
        x, y = reg if (regulamin and reg) else fin
        wyn = 'h' if x > y else ('a' if y > x else 'r')
        if dwojtyp: return int(wyn in {'10': 'hr', '02': 'ra', '12': 'ha'}[ol]), 'podwójna szansa'
        if 'bez remisu' in n:
            if wyn == 'r': return None
            return int(wyn == strona), 'bez remisu'
        if not trzy and wyn == 'r': return None                          # 2-drogowy rynek, a remis – nie wiemy, jak liczony
        return int(wyn == strona), ('1X2' if trzy else 'zwycięzca')
    # ---- handicap
    if 'handicap' in n:
        hc = _handicap(o, h, a)
        if not hc: return None
        st, linia = hc
        sety = 'set' in n
        if sety:
            x, y = fin
        else:
            x, y = (fin if calosc or not reg else reg)
            if not calosc and sp in ('hokej', 'pilka_reczna', 'koszykowka') and not reg: return None
        roznica = (x - y) if st == 'h' else (y - x)
        v = roznica + linia
        if abs(v) < 1e-9: return None
        return int(v > 0), 'handicap'
    # ---- parzystość
    if o.lower().startswith(('parz', 'niep')) and ('suma' in n or 'liczba' in n):
        x, y = fin if calosc or not reg else reg
        if not calosc and sp in ('hokej', 'pilka_reczna', 'koszykowka') and not reg: return None
        par = (x + y) % 2 == 0
        return int(par == o.lower().startswith('parz')), 'parzystość'
    # ---- dokładny wynik (siatkówka – sety)
    if 'dokładny wynik' in n:
        m = re.fullmatch(r'(\d+)\s*:\s*(\d+)', o)
        if not m or sp not in ('siatkowka',): return None
        return int((int(m.group(1)), int(m.group(2))) == tuple(fin)), 'dokładny wynik'
    # ---- suma (cały mecz) i suma drużyny
    ou = _ou(o)
    if not ou: return None
    kier, linia = ou
    punkty = w.get('punkty')
    if 'liczba setów' in n or 'liczba setow' in n:
        if sp != 'siatkowka' or ' - ' in n: return None
        return (lambda r: None if r is None else (r, 'suma setów'))(_ponad(sum(fin), kier, linia))
    if re.search(r'(liczba|suma) (goli|punktów|bramek)', n):
        if sp == 'siatkowka':
            if not punkty: return None
            x, y = punkty
        else:
            x, y = fin if calosc or not reg else reg
            if not calosc and sp in ('hokej', 'pilka_reczna', 'koszykowka') and not reg: return None
        if druz_m and druz_m.group(1).strip() not in ('mecz', 'mecz:', '') and not druz_m.group(1).strip().startswith(('liczba', 'suma')):
            st = _strona(druz_m.group(1), h, a)
            if not st: return None
            r = _ponad(x if st == 'h' else y, kier, linia)
            return None if r is None else (r, 'suma drużyny')
        r = _ponad(x + y, kier, linia)
        return None if r is None else (r, 'suma')
    return None
