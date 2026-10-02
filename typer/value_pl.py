"""💰 Value z polskich kursów (STS, Fortuna, Superbet, Betclic PL).

Liczona w kursy_pl.main() zaraz po pobraniu kursów: rano przed wiadomością na Telegram i przy każdym odświeżeniu kursów w ciągu dnia.
Uczciwa szansa z rynku Pinnacle/Betfair (bez marży):
 - piłka: macierz wyników z rynku (dzis.json → analiza.lam) – wszystkie rodzaje zakładów, które czytamy u bukmacherów;
 - tenis, MMA, boks: zwycięzca (szansa_a / szansa_b z Pinnacle/Betfair; inne rynki tylko z modelu – za mało pewne na Value);
 - KSW (bez Pinnacle) – bez zmian, liczone w sporty.py z rynku polskiego (rynek_pl).
Zakład = najwyższy kurs spośród polskich bukmacherów; przewaga min. 3%, kurs 1,30–4,00. Przewaga ponad 25% = prawie zawsze błąd
odczytu kursu → pomijana. Mecze już rozpoczęte: Value zostaje taka, jak była przed startem."""
import os, json, datetime as dt
import numpy as np, pandas as pd

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
MIN_EV = 0.03
MAX_EV = 0.25
KURS_MIN, KURS_MAX = 1.30, 4.00
NA_MECZ = 2

def _ostry(zr): return any(x in str(zr or '') for x in ('Pinnacle', 'Betfair'))

def _teraz(): return pd.Timestamp.now(tz='Europe/Warsaw')

def _rozpoczety(m):
    try: return pd.Timestamp(m['start']).tz_localize('Europe/Warsaw') <= _teraz()
    except Exception: return False

def _najlepszy(zrodla, klucz):
    kk = {b: float(k[klucz]) for b, k in zrodla.items() if k.get(klucz) and float(k[klucz]) > 1}
    if not kk: return None, None, {}
    b = max(kk, key=kk.get)
    return b, kk[b], kk

def _zapisz(p, d):
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: json.dump(d, f, ensure_ascii=False, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o))
    json.load(open(tmp)); os.replace(tmp, p)

def value_pilka(dzis, kursy, vps, KP):
    import core, run_daily as RD
    wyn, odrzucone = [], 0
    for m in dzis.get('mecze') or []:
        eid = m.get('event_id'); lam = (m.get('analiza') or {}).get('lam')
        if not eid or not lam or not _ostry(m.get('zrodlo')) or _rozpoczety(m): continue
        M = core.score_matrix(float(lam[0]), float(lam[1]), -0.05)
        r = RD.rynki_rozszerzone(M, m['gospodarz'], m['gosc'])
        zrodla, stan = KP.zrodla_meczu(kursy, vps, m, eid)
        kand = []
        for z, (p, nazwa, opis, _) in r.items():
            b, kurs, kk = _najlepszy(zrodla, z)
            if not b: continue
            e = p * kurs - 1
            if not (KURS_MIN <= kurs <= KURS_MAX) or e < MIN_EV: continue
            if e > MAX_EV: odrzucone += 1; continue
            kand.append((e, z, p, nazwa, opis, b, kurs, kk))
        for e, z, p, nazwa, opis, b, kurs, kk in sorted(kand, key=lambda x: -x[0])[:NA_MECZ]:
            pola = {k: v for k, v in m.items() if k not in ('klucz', 'zaklad', 'opis', 'kursy_pl', 'kursy_odczyt', 'kursy_czas', 'szansa', 'kurs_uczciwy', 'kurs_min', 'kurs_betclic', 'ev')}
            wyn.append(dict(pola, klucz=z, zaklad=nazwa, opis=opis, kurs=round(kurs, 2), bukmacher=b, kursy_pl=kk,
                            kursy_odczyt=sorted(x for x, d in stan.items() if KP.czytany(x, 'pilka', z, d)),
                            kursy_czas=dt.datetime.now(KP.TZ).strftime('%H:%M'),
                            szansa=round(p, 4), kurs_uczciwy=round(1 / p, 2), kurs_szukaj=round(1.02 / p, 2), ev=round(e, 4),
                            stawka_proc=round(core.kelly(p, kurs), 4), rynek='klucz', strona=z, linia=0))
    return wyn, odrzucone

def value_duel(m, kursy, vps, KP, sp):
    import core
    zrodla, stan = KP.zrodla_meczu(kursy, vps, m, m['event_id'])
    out = []
    for strona, sz, kto in (('A', m.get('szansa_a'), m.get('a')), ('B', m.get('szansa_b'), m.get('b')), ('D', m.get('szansa_remis'), None)):
        if not sz: continue
        b, kurs, kk = _najlepszy(zrodla, strona)
        if not b: continue
        e = sz * kurs - 1
        if not (KURS_MIN <= kurs <= KURS_MAX) or not (MIN_EV <= e <= MAX_EV): continue
        out.append(dict(klucz=strona, zaklad=f'wygra {kto}' if kto else 'remis', kurs=round(kurs, 2), bukmacher=b, kursy_pl=kk,
                        kursy_odczyt=sorted(x for x, d in stan.items() if KP.czytany(x, sp, strona, d)),
                        kursy_czas=dt.datetime.now(KP.TZ).strftime('%H:%M'),
                        szansa=sz, ev=round(e, 4), kurs_uczciwy=round(1 / sz, 3), kurs_szukaj=round(1.02 / sz, 2),
                        stawka_proc=round(core.kelly(sz, kurs), 4)))
    return out

def licz(kursy, vps):
    import kursy_pl as KP, core, sporty, wspolne
    diag = dict(pilka=0, tenis=0, walki=0, odrzucone_podejrzane=0)
    dzien = wspolne.dzien_str()
    # ⚽ piłka
    p = os.path.join(OUT, 'dzis.json')
    try:
        dzis = json.load(open(p))
        if dzis.get('data') == dzien:
            stare = [v for v in dzis.get('value') or [] if v.get('bukmacher') and _rozpoczety(v)]   # po starcie – bez zmian
            nowe, odrz = value_pilka(dzis, kursy, vps, KP)
            ids = {str(v['event_id']) for v in stare}
            dzis['value'] = stare + [v for v in nowe if str(v['event_id']) not in ids]
            diag['pilka'] = len(dzis['value']); diag['odrzucone_podejrzane'] += odrz
            _zapisz(p, dzis)
            wiersze = [dict(data_zapisu=_teraz().strftime('%Y-%m-%d %H:%M'), event_id=v['event_id'], liga=v.get('sport_key'), start=v['start'],
                            mecz=v['mecz'], gospodarz=v['gospodarz'], gosc=v['gosc'], zaklad=v['zaklad'], rynek='klucz', strona=v['klucz'], linia=0,
                            kurs_betclic=v['kurs'], bukmacher=v['bukmacher'], kurs_uczciwy=round(1 / v['szansa'], 3), szansa=round(v['szansa'], 3),
                            EV=v['ev'], stawka_sugerowana=round(core.BANKROLL * core.kelly(v['szansa'], v['kurs']), 0), wynik='', zysk_na_1zl=np.nan)
                       for v in nowe]
            if wiersze: core.zapisz_value(wiersze)   # dziennik: pierwszy kurs, przy którym pojawiła się Value
    except FileNotFoundError: pass
    # 🎾 tenis, 🥊 walki
    p = os.path.join(OUT, 'inne.json')
    try:
        inne = json.load(open(p))
        if True:
            wiersze = []
            for sp in ('tenis', 'walki'):
                s = inne.get(sp) or {}
                for m in s.get('mecze') or []:
                    if m.get('rynek_pl'): continue                       # KSW – Value z rynku PL liczona w sporty.py
                    if _rozpoczety(m): m['value'] = [v for v in m.get('value') or [] if v.get('bukmacher')]; continue
                    m['value'] = value_duel(m, kursy, vps, KP, sp) if _ostry(m.get('zrodlo')) else []
                    for v in m['value']:
                        wiersze.append(dict(data=dzien, sport=sp, dyscyplina=m.get('dyscyplina'), sport_key=m.get('sport_key'), turniej=m.get('turniej'),
                                            event_id=m['event_id'], start=m['start'], a=m['a'], b=m['b'], bo=m.get('bo'), ai=sporty.werdykt(m) or '',
                                            rodzaj='value', poziom='value', klucz=v['klucz'], zaklad=v['zaklad'], szansa=v['szansa'], kurs=v['kurs'], nizsza=False))
                s['value'] = [dict(v, **{k: m[k] for k in ('mecz', 'a', 'b', 'turniej', 'godzina', 'dzien', 'start', 'event_id', 'dyscyplina', 'sport', 'zrodlo') if k in m})
                              for m in s.get('mecze') or [] for v in m.get('value') or []]
                diag[sp] = len(s['value'])
            _zapisz(p, inne)
            if wiersze: sporty.zapisz_typy(wiersze)
    except FileNotFoundError: pass
    # główna lista Value (zakładka Główne) – Pewne zostają bez zmian
    try:
        gl = wspolne.wczytaj()
        if gl.get('data') == dzien:
            nowe = wspolne.wybierz(json.load(open(os.path.join(OUT, 'dzis.json'))), json.load(open(os.path.join(OUT, 'inne.json'))))
            gl['value'] = nowe['value']
            for sp, v in (nowe.get('liczby') or {}).items(): gl.setdefault('liczby', {}).setdefault(sp, {})['value'] = v.get('value', 0)
            wspolne.zapisz(gl)
    except Exception as e: diag['blad_glowne'] = str(e)[:120]
    print('Value z polskich kursów:', diag)
    return diag
