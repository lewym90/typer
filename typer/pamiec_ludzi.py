"""Wersja 52 – PAMIĘĆ LUDZI: co program wie o konkretnych zawodnikach i drużynach z własnych analiz (nie reguły, nie schematy).
Każdy wpis jest przypisany do osoby/drużyny i daty: obserwacje „ludzkie” z porannych analiz (zdrowie, głowa, życie prywatne,
motywacja, zachowanie w trudnych chwilach) i wnioski z sekcji zwłok (czego nie zrozumieliśmy, gdy typ nie wszedł).
AI dostaje te notatki przy kolejnym meczu tej osoby jako tło do własnego myślenia – waży je sama, wiedząc, kiedy i skąd są.
Plik: docs/data/pamiec_ludzi.json  {klucz: {nazwa, wpisy: [{data, zrodlo, tekst}]}}  (maks. 12 wpisów na osobę, 120 dni)."""
import os, re, json, unicodedata
import pandas as pd

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
PLIK = os.path.join(OUT, 'pamiec_ludzi.json')
MAKS = 12


def klucz(n):
    t = unicodedata.normalize('NFKD', str(n or '').lower().replace('ł', 'l')).encode('ascii', 'ignore').decode()
    t = re.sub(r'\(.*?\)|[^a-z ]', ' ', t)
    sl = [x for x in t.split() if len(x) > 2]
    return ' '.join(sorted(sl))


def wczytaj():
    try: return json.load(open(PLIK))
    except Exception: return {}


def zapisz(p):
    granica = (pd.Timestamp.now(tz='Europe/Warsaw') - pd.Timedelta(days=120)).strftime('%Y-%m-%d')
    for k in list(p):
        p[k]['wpisy'] = [w for w in p[k].get('wpisy', []) if w.get('data', '') >= granica][-MAKS:]
        if not p[k]['wpisy']: del p[k]
    with open(PLIK, 'w', encoding='utf-8') as f: json.dump(p, f, ensure_ascii=False)


def dopisz(p, nazwa, tekst, zrodlo, data=None):
    tekst = str(tekst or '').strip()
    if not nazwa or len(tekst) < 15: return
    k = klucz(nazwa)
    if not k: return
    o = p.setdefault(k, dict(nazwa=str(nazwa), wpisy=[]))
    data = data or pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d')
    if any(w['tekst'] == tekst[:300] for w in o['wpisy']): return
    o['wpisy'].append(dict(data=data, zrodlo=zrodlo, tekst=tekst[:300]))


def kontekst(nazwy, p=None):
    """Tekst do polecenia AI: notatki o tych osobach/drużynach (najnowsze), albo pusty."""
    p = p if p is not None else wczytaj()
    lin = []
    for n in nazwy:
        o = p.get(klucz(n))
        if not o: continue
        for w in o['wpisy'][-4:]: lin.append(f"- {o['nazwa']} ({w['data']}, {w['zrodlo']}): {w['tekst']}")
    if not lin: return ''
    return ('NASZE WCZEŚNIEJSZE OBSERWACJE O TYCH LUDZIACH (z naszych analiz i wpadek; to tło, nie reguła – sprawdź, co jest aktualne, '
            'i oceń sam, czy ma znaczenie w TYM meczu):\n' + '\n'.join(lin[:10]))


def z_analizy(nazwy, ai, data=None):
    """Po porannej analizie: obserwacje „ludzkie” AI przy każdej z osób/drużyn."""
    if not ai: return
    cz = ai.get('czlowiek') or {}
    if not isinstance(cz, dict) or not any(cz.values()): return
    p = wczytaj()
    for strona, n in zip(('a', 'b'), nazwy):
        if cz.get(strona): dopisz(p, n, cz[strona], 'analiza poranna', data)
    zapisz(p)


def z_sekcji_zwlok():
    """Wnioski z sekcji zwłok przypisane do osób/drużyn z meczu (raz na analizę)."""
    try: st = json.load(open(os.path.join(OUT, 'sekcje_zwlok.json')))
    except Exception: return 0
    p = wczytaj(); n = 0
    for a in st.get('analizy', []):
        if a.get('w_pamieci'): continue
        osoby = [x.strip() for x in re.split(r'\s+[–-]\s+', str(a.get('mecz') or '')) if x.strip()][:2]
        tekst = a.get('wniosek') or ''
        sygn = '; '.join(s['opis'] for s in a.get('sygnaly', []) if s.get('przed_meczem'))[:200]
        for o in osoby:
            dopisz(p, o, f"Wpadka typu „{a.get('zaklad')}” ({a.get('wynik')}): {tekst}" + (f" Sygnały przed meczem: {sygn}" if sygn else ''),
                   'sekcja zwłok', str(a.get('start') or '')[:10] or None)
        a['w_pamieci'] = True; n += 1
    if n:
        zapisz(p)
        with open(os.path.join(OUT, 'sekcje_zwlok.json'), 'w', encoding='utf-8') as f: json.dump(st, f, ensure_ascii=False)
    return n
