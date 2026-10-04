"""Sekcja zwłok (wersja 39) – po każdej wpadce typu dnia (🔒 nie wszedł) AI szuka sygnałów, które BYŁY widoczne przed meczem.
Wynik: docs/data/sekcje_zwlok.json – lista analiz + zliczenie czynników. To materiał do detektora niespodzianek:
czynnik, który powtarza się w wielu wpadkach, sprawdzamy na archiwum i – jeśli działa – wchodzi do programu.
Koszt: Gemini Flash z wyszukiwaniem (~0,1 zł za mecz), maks. 6 dziennie, w ramach budżetu Flash."""
import os, json
import pandas as pd
import ai_raport

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
PLIK = os.path.join(OUT, 'sekcje_zwlok.json')
MAKS_NA_RAZ = 6
CZYNNIKI = ['motywacja/stawka', 'rotacja/skład', 'kontuzje/braki', 'zmęczenie/terminarz/podróż', 'forma (realna gra)', 'styl/zestawienie',
            'trener/atmosfera', 'pogoda/boisko', 'sędzia', 'przewaga własnego boiska/kibice', 'przypadek (kartka, karny, błąd)', 'inne']
STAN = dict(nowe=0, bledy=[])

POLECENIE = """Jesteś analitykiem sportowym. Typ programu NIE wszedł – zrób uczciwą „sekcję zwłok”.
Mecz: {mecz} ({liga}), {start} czasu polskiego. Wynik: {wynik}. Program typował: „{zaklad}” (szansa {szansa}).
Wyszukaj w Google informacje OPUBLIKOWANE PRZED MECZEM (zapowiedzi, konferencje, składy, kontuzje, nastroje) i relację z meczu.
Odpowiedz na pytanie: czy przed meczem były sygnały, że ten typ jest zagrożony? Oddziel to, co dało się wiedzieć wcześniej,
od przypadku w trakcie meczu (czerwona kartka, karny, błąd bramkarza, kontuzja w meczu).
Czynniki do wyboru: {czynniki}.
ZASADY: tylko fakty ze źródeł; nie wymyślaj; jeśli wynik to raczej przypadek – napisz to wprost.
Odpowiedz WYŁĄCZNIE obiektem JSON (bez ```):
{{"sygnaly": [{{"czynnik": "z listy", "opis": "konkretny fakt", "przed_meczem": true/false, "zrodlo": "link"}}],
  "czynnik_glowny": "z listy", "przypadek": true/false, "dalo_sie_przewidziec": "tak" | "czesciowo" | "nie",
  "wniosek": "1–2 zdania – czego nie zrozumieliśmy o TYCH konkretnych ludziach w TYM meczu (zdrowie, głowa, motywacja, sytuacja) – bez ogólnych reguł"}}
Myśl jak człowiek, który zna tych zawodników: nie szukaj schematu („kontuzja = porażka”), tylko tego, co w tej sytuacji było inne."""


def _wczytaj():
    try: return json.load(open(PLIK))
    except Exception: return dict(analizy=[], czynniki={})


def kandydaci(pewne_csv, inne_csv, dni=2):
    """Wpadki typów dnia (🔒, lista pewne, nie wszedł) z ostatnich dni – piłka, tenis, walki."""
    out = []
    granica = pd.Timestamp.now(tz='Europe/Warsaw').tz_localize(None) - pd.Timedelta(days=dni)
    for plik, sp_kol in ((pewne_csv, None), (inne_csv, 'sport')):
        try: d = pd.read_csv(plik, dtype={'event_id': str})
        except Exception: continue
        if 'trafiony' not in d: continue
        x = d[(d.get('poziom') == 'najpewniejszy') & (pd.to_numeric(d.trafiony, errors='coerce') == 0) & (pd.to_datetime(d.start, errors='coerce') > granica)]
        if 'lista' in x: x = x[x.lista.fillna('pewne') == 'pewne']
        if 'rodzaj' in x: x = x[x.rodzaj == 'pewne']
        for _, r in x.iterrows():
            out.append(dict(sport=(r.get(sp_kol) if sp_kol else 'pilka') or 'pilka', event_id=str(r.event_id), mecz=r.get('mecz'), liga=r.get('liga', ''),
                            start=str(r.start), wynik=str(r.get('wynik', '')), zaklad=r.get('zaklad'), szansa=float(r.get('szansa') or 0)))
    return out


def przeprowadz(pewne_csv, inne_csv):
    """Analizuje nowe wpadki (maks. MAKS_NA_RAZ), zapisuje i zwraca liczbę nowych analiz."""
    st = _wczytaj(); juz = {a['event_id'] for a in st['analizy']}
    for k in kandydaci(pewne_csv, inne_csv):
        if STAN['nowe'] >= MAKS_NA_RAZ: break
        if k['event_id'] in juz: continue
        if not ai_raport.KLUCZ or ai_raport.zostalo_analiz() <= 0: break
        t = POLECENIE.format(czynniki=', '.join(CZYNNIKI), **dict(k, szansa=f"{k['szansa']:.0%}"))
        try:
            txt, zr, szukal = ai_raport._zapytaj(t, t.replace('Wyszukaj w Google', 'Na podstawie własnej wiedzy oceń'))
            d = ai_raport._wyciagnij_json(txt) if txt else None
        except Exception as e: STAN['bledy'].append(str(e)[:120]); d = None
        if not d: continue
        ai_raport.analiz_dzis(1)
        sygn = [dict(czynnik=str(s.get('czynnik'))[:40], opis=str(s.get('opis'))[:240], przed_meczem=bool(s.get('przed_meczem')),
                     zrodlo=str(s.get('zrodlo') or '')[:200]) for s in (d.get('sygnaly') or []) if isinstance(s, dict)][:6]
        a = dict(k, sygnaly=sygn, czynnik_glowny=str(d.get('czynnik_glowny') or 'inne')[:40], przypadek=bool(d.get('przypadek')),
                 dalo_sie=str(d.get('dalo_sie_przewidziec') or '')[:10], wniosek=str(d.get('wniosek') or '')[:400],
                 zrodla=zr[:4], czas=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'))
        st['analizy'].insert(0, a); juz.add(k['event_id']); STAN['nowe'] += 1
    st['analizy'] = st['analizy'][:300]
    cz = {}
    for a in st['analizy']:
        for s in a['sygnaly']:
            if s['przed_meczem']: cz[s['czynnik']] = cz.get(s['czynnik'], 0) + 1
    st['czynniki'] = dict(sorted(cz.items(), key=lambda x: -x[1]))
    st['podsumowanie'] = dict(n=len(st['analizy']), przypadek=sum(1 for a in st['analizy'] if a['przypadek']),
                              dalo_sie=sum(1 for a in st['analizy'] if a['dalo_sie'] in ('tak', 'czesciowo')))
    with open(PLIK, 'w', encoding='utf-8') as f: json.dump(st, f, ensure_ascii=False)
    try:                                           # wersja 52: wnioski trafiają do pamięci konkretnych ludzi
        import pamiec_ludzi; pamiec_ludzi.z_sekcji_zwlok()
    except Exception as e: STAN['bledy'].append(f'pamięć ludzi: {e}'[:120])
    try:
        pd_ = os.path.join(OUT, 'dziennik.json'); dz = json.load(open(pd_)) if os.path.exists(pd_) else {}
        dz['sekcje'] = skrot()
        with open(pd_, 'w', encoding='utf-8') as f: json.dump(dz, f, ensure_ascii=False)
    except Exception as e: STAN['bledy'].append(f'dziennik: {e}')
    return STAN['nowe']


def skrot():
    st = _wczytaj()
    if not st.get('analizy'): return None
    return dict(podsumowanie=st.get('podsumowanie'), czynniki=dict(list((st.get('czynniki') or {}).items())[:8]),
                ostatnie=[{k: a.get(k) for k in ('sport', 'mecz', 'wynik', 'zaklad', 'czynnik_glowny', 'przypadek', 'dalo_sie', 'wniosek')} for a in st['analizy'][:8]])
