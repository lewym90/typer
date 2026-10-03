"""Wersja 43 – laboratorium SKANERA SKŁADÓW (GitHub, przy pełnym liczeniu).
Wejście: docs/data/archiwum/sklady/<data>.json.gz (polski serwer: skład FotMob 2–4 h przed meczem = przewidywany,
45–75 min i 3–20 min przed meczem z kursami 1X2 Fortuny) + wyniki z archiwum/rozliczone/*.csv.gz.
Dla każdej drużyny: kto z przewidywanej jedenastki nie wyszedł w ogłoszonym składzie i ile to „waży” (wartość rynkowa
zawodnika z FotMob / wartość przewidywanej jedenastki), ilu ważnych jest niedostępnych. Potem: czy szansa z kursu
w chwili ogłoszenia składu (45–75 min) już to uwzględnia – porównanie z kursem tuż przed meczem (ruch) i z wynikiem.
Wynik: docs/data/archiwum/sklady_stat.json (grupy wg siły osłabienia: n, wygrane, szansa z kursu przed / zamknięcia,
zysk przy zakładzie na rywala osłabionej drużyny po kursie z chwili składu, ruch kursu). Bez zmian w aplikacji –
zgłaszamy, gdy próba będzie wystarczająca (≥ 150 osłabionych drużyn)."""
import os, json, gzip, glob
import numpy as np, pandas as pd

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data', 'archiwum')
PROGI = [(0.0, 0.05, 'pełny skład'), (0.05, 0.15, 'lekko osłabiony'), (0.15, 0.30, 'osłabiony'), (0.30, 1.01, 'mocno osłabiony')]


def _wczytaj():
    rek = []
    for p in sorted(glob.glob(os.path.join(OUT, 'sklady', '*.json.gz'))):
        try:
            with gzip.open(p, 'rt', encoding='utf-8') as f: rek += json.load(f).get('mecze') or []
        except Exception: pass
    return rek


def _ogloszony(sk): return bool(sk) and sk.get('typ') not in (None, 'lastStarting11', 'predicted') and len((sk.get('h') or {}).get('s') or []) >= 11


def oslabienie(przew, ogl):
    """(udział wartości przewidywanej jedenastki, który nie wyszedł; liczba zmian) – po id zawodników."""
    s0 = {p[0]: float(p[3] or 0) for p in (przew or {}).get('s') or [] if p and p[0] is not None}
    s1 = {p[0] for p in (ogl or {}).get('s') or [] if p and p[0] is not None}
    if len(s0) < 11 or len(s1) < 11: return None, None
    brak = [i for i in s0 if i not in s1]
    suma = sum(s0.values())
    return (sum(s0[i] for i in brak) / suma if suma > 0 else len(brak) / 11), len(brak)


def _p(k):
    try:
        inv = np.array([1 / float(k['1']), 1 / float(k['X']), 1 / float(k['2'])]); return inv / inv.sum()
    except Exception: return None


def licz():
    rek = _wczytaj()
    if not rek: return dict(meczow=0)
    po = {}
    for r in rek: po.setdefault(r['id'], {})[r['etap']] = r
    wyn = {}
    for p in glob.glob(os.path.join(OUT, 'rozliczone', '*.csv.gz')):
        try:
            d = pd.read_csv(p, usecols=['mecz', 'start', 'wynik']).drop_duplicates(['mecz', 'start'])
            wyn.update({(m, str(s)): w for m, s, w in d.itertuples(index=False)})
        except Exception: pass
    wiersze = []
    for fid, e in po.items():
        s0 = (e.get('s0') or {}).get('sk'); ogl = None; kiedy = None
        for etap in ('przed', 'zamk'):
            sk = (e.get(etap) or {}).get('sk')
            if _ogloszony(sk): ogl, kiedy = sk, etap; break
        if not s0 or not ogl: continue
        baza = next(iter(e.values()))
        w = wyn.get((f"{baza['h']} – {baza['a']}", str(baza['t'])))
        pp, pz = _p((e.get('przed') or {}).get('k1x2') or {}), _p((e.get('zamk') or {}).get('k1x2') or {})
        kp = (e.get('przed') or {}).get('k1x2') or {}
        for strona, i, j in (('h', 0, 2), ('a', 2, 0)):
            u, n = oslabienie(s0.get(strona), ogl.get(strona))
            if u is None: continue
            gh, ga = (int(x) for x in w.split(':')) if isinstance(w, str) and ':' in w else (None, None)
            wygral = None if gh is None else int(gh > ga if strona == 'h' else ga > gh)
            rywal_wygral = None if gh is None else int(ga > gh if strona == 'h' else gh > ga)
            wiersze.append(dict(id=fid, strona=strona, oslabienie=u, zmian=n, sklad_przy_kursie=kiedy == 'przed',
                                p_przed=pp[i] if pp is not None else np.nan, p_zamk=pz[i] if pz is not None else np.nan,
                                kurs_rywala=float(kp.get('2' if strona == 'h' else '1') or np.nan), wygral=wygral, rywal_wygral=rywal_wygral))
    d = pd.DataFrame(wiersze)
    out = dict(czas=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'), meczow=int(len(po)), druzyn=int(len(d)), grupy=[])
    if len(d):
        d['rozl'] = d.wygral.notna()
        out['z_wynikiem'] = int(d.rozl.sum())
        for a, b, nazwa in PROGI:
            g = d[(d.oslabienie >= a) & (d.oslabienie < b)]
            r = g[g.rozl & g.kurs_rywala.notna()]
            out['grupy'].append(dict(grupa=nazwa, n=int(len(g)), z_wynikiem=int(len(r)),
                                     wygrane=round(float(r.wygral.mean()), 4) if len(r) else None,
                                     szansa_przed=round(float(r.p_przed.mean()), 4) if len(r) else None,
                                     szansa_zamk=round(float(g.p_zamk.mean()), 4) if g.p_zamk.notna().any() else None,
                                     ruch=round(float((g.p_zamk - g.p_przed).mean()), 4) if (g.p_zamk.notna() & g.p_przed.notna()).any() else None,
                                     zysk_na_rywala=round(float(np.where(r.rywal_wygral == 1, r.kurs_rywala - 1, -1).mean()), 4) if len(r) else None))
    with open(os.path.join(OUT, 'sklady_stat.json'), 'w', encoding='utf-8') as f: json.dump(out, f, ensure_ascii=False)
    return {k: out.get(k) for k in ('meczow', 'druzyn', 'z_wynikiem')}
