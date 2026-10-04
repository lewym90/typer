"""Wersja 51 – LUSTRO POLSKIEGO RYNKU: polscy bukmacherzy (Fortuna, Superbet) vs Pinnacle (świat) na tych samych meczach.
Pomysł użytkownika (03.10): skoro gramy tylko w Polsce, nauczmy się, JAK polski rynek różni się od światowego, i liczmy szansę
z polskich kursów poprawionych o te różnice (także tam, gdzie Pinnacle nie ma meczu: żużel, KSW, niższe ligi, rynki tylko PL).

Co liczy (codziennie przy pełnym liczeniu, z archiwum – bez nowych zapytań):
  1) „lustro”: dla każdego bukmachera, sportu i rynku (1X2 / gole 2,5 / zwycięzca) w przedziałach szansy Pinnacle:
     średnia szansa Pinnacle, średnia szansa z kursu PL po zdjęciu marży, różnica (pkt) i marża – to jest „mapa przeliczenia”
     polski kurs → prawdziwa szansa (funkcja `prawdziwa_szansa`),
  2) „okazje”: kursy PL wyższe niż uczciwy kurs Pinnacle (EV ≥ 3%) – zapis z wynikiem, gdy mecz rozliczony w archiwum
     (czy strategia „gram tylko w Polsce, gdy polski kurs przebija świat” zarabia na naszych danych),
  3) gdy rozliczonych meczów przybędzie – kalibracja na wynikach (czy prawdę lepiej oddaje Pinnacle, czy poprawiony kurs PL).
Wynik: docs/data/archiwum/lustro_pl.json, status.json → lustro_pl."""
import os, json, gzip, glob
import numpy as np, pandas as pd

BAZA = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data', 'archiwum')
PLIK = os.path.join(BAZA, 'lustro_pl.json')
PRZEDZIALY = [0, .15, .3, .45, .6, .75, .9, 1.0]
STAN = dict(par=0, bledy=[])


def _gz(p):
    try:
        with gzip.open(p, 'rt', encoding='utf-8') as f: return json.load(f)
    except Exception: return None


def _devig(kursy):
    p = 1 / np.array(kursy, dtype=float); return p / p.sum(), float(p.sum() - 1)


def _pinnacle(dni):
    """{sp: [(h, a, t UTC, rynki)]} – odczyt zamknięcia, a gdy go brak – poranny."""
    out = {}
    for d in dni:
        for tryb in ('rano', 'zamk'):
            z = _gz(os.path.join(BAZA, 'pinnacle', f'{d}_{tryb}.json.gz'))
            for mid, m in ((z or {}).get('mecze') or {}).items():
                out.setdefault(mid, m)
                if tryb == 'zamk': out[mid] = m
    po = {}
    for m in out.values():
        try: t = pd.Timestamp(m['t'], tz='UTC')
        except Exception: continue
        po.setdefault(m['sp'], []).append((m['h'], m['a'], t, m['r']))
    return po


def _polskie(dni):
    """[(buk, sp, h, a, t, {klucz: kurs}, tryb)] – Fortuna (klucze) i Superbet (piłka przez czytnik kluczy)."""
    import archiwum as A
    out = []
    for d in dni:
        for p in sorted(glob.glob(os.path.join(BAZA, 'kursy', f'{d}_*.json.gz'))):
            z = _gz(p)
            if not z: continue
            buk = z.get('buk') or 'fortuna'; tryb = z.get('tryb') or ''
            for m in z.get('mecze') or []:
                sp = {'sporty walki': 'mma'}.get(m.get('sp'), m.get('sp'))
                if sp not in ('pilka', 'tenis', 'mma') or '/' in str(m.get('h')): continue
                if buk == 'superbet':
                    k = A.sb_klucze(m.get('r'), m['h'], m['a']) if sp == 'pilka' else {}
                    if sp != 'pilka':
                        for rn, wy in (m.get('r') or []):
                            if rn in ('Mecz', 'Zwycięzca meczu', 'Zwycięzca'):
                                for nz, _, c in wy:
                                    if nz in ('1', '2'): k['A' if nz == '1' else 'B'] = c
                else: k = m.get('k') or {}
                if k:
                    try: out.append((buk, sp, m['h'], m['a'], pd.Timestamp(m['t'], tz='UTC'), k, tryb))
                    except Exception: pass
    return out


def _para(sp, h, a, t, pin):
    import archiwum as A, archiwum_inne as AI
    best = None
    for ph, pa, pt, r in pin.get(sp, []):
        if abs((pt - t).total_seconds()) > 45 * 60: continue
        for odwr in (False, True):
            x, y = (pa, ph) if odwr else (ph, pa)
            if sp == 'pilka':
                if odwr: continue
                sc = min(A._podobne(h, x), A._podobne(a, y))
                ok = sc >= 0.6
            else:
                ok = AI._zgodne(h, x, 'tenis' if sp == 'tenis' else sp) and AI._zgodne(a, y, 'tenis' if sp == 'tenis' else sp); sc = 1.0 if ok else 0
            if ok and (best is None or sc > best[0]): best = (sc, r, odwr)
    return best


def _wiersze(buk, sp, k, r, odwr):
    """[(rynek, klucz, szansa Pinnacle, szansa PL bez marży, kurs PL, marża PL)]."""
    out = []
    ml = r.get('ml|0') or {}
    if sp == 'pilka':
        if all(x in k for x in '1X2') and all(ml.get(x) for x in ('home', 'draw', 'away')):
            pp, _ = _devig([ml['home'], ml['draw'], ml['away']]); pl, mz = _devig([k['1'], k['X'], k['2']])
            out += [('1X2', n, pp[i], pl[i], k[n], mz) for i, n in enumerate('1X2')]
        t = r.get('tot|0|2.5') or {}
        if k.get('Over 2.5') and k.get('Under 2.5') and t.get('over') and t.get('under'):
            pp, _ = _devig([t['over'], t['under']]); pl, mz = _devig([k['Over 2.5'], k['Under 2.5']])
            out += [('gole 2,5', 'Over 2.5', pp[0], pl[0], k['Over 2.5'], mz), ('gole 2,5', 'Under 2.5', pp[1], pl[1], k['Under 2.5'], mz)]
    elif k.get('A') and k.get('B') and ml.get('home') and ml.get('away'):
        h, a = (ml['away'], ml['home']) if odwr else (ml['home'], ml['away'])
        pp, _ = _devig([h, a]); pl, mz = _devig([k['A'], k['B']])
        out += [('zwycięzca', 'A', pp[0], pl[0], k['A'], mz), ('zwycięzca', 'B', pp[1], pl[1], k['B'], mz)]
    return out


def _wyniki_archiwum():
    """(buk, mecz, start, rynek) → trafiony z archiwum piłki i innych sportów."""
    out = {}
    for kat in ('rozliczone', 'rozliczone_inne'):
        for p in glob.glob(os.path.join(BAZA, kat, '*.csv.gz')):
            try: d = pd.read_csv(p)
            except Exception: continue
            buk = d['buk'].fillna('fortuna') if 'buk' in d else pd.Series(['fortuna'] * len(d))
            for b, m, s, r, tr in zip(buk, d.mecz, d.start, d.rynek, d.trafiony): out[(b, str(m), str(s), str(r))] = tr
    return out


def licz(dni_wstecz=14):
    dzis = pd.Timestamp.now(tz='Europe/Warsaw').normalize()
    dni = [(dzis - pd.Timedelta(days=i)).strftime('%Y-%m-%d') for i in range(dni_wstecz, -1, -1)]
    pin = _pinnacle(dni)
    if not pin: return dict(par=0, uwaga='brak odczytów Pinnacle')
    wiersze = []
    for buk, sp, h, a, t, k, tryb in _polskie(dni):
        b = _para(sp, h, a, t, pin)
        if not b: continue
        for rynek, kl, pp, pl, kurs, mz in _wiersze(buk, sp, k, b[1], b[2]):
            wiersze.append(dict(buk=buk, sp=sp, rynek=rynek, klucz=kl, mecz=f'{h} – {a}', start=t.strftime('%Y-%m-%d %H:%M'), tryb=tryb,
                                pin=pp, pl=pl, kurs=kurs, marza=mz, ev=kurs * pp - 1))
    if not wiersze: return dict(par=0)
    d = pd.DataFrame(wiersze).drop_duplicates(['buk', 'mecz', 'start', 'klucz', 'tryb'])
    d['przedzial'] = pd.cut(d.pin, PRZEDZIALY)
    lustro = []
    for (b, sp, r, pz), g in d.groupby(['buk', 'sp', 'rynek', 'przedzial'], observed=True):
        if len(g) < 10: continue
        lustro.append(dict(buk=b, sp=sp, rynek=r, przedzial=str(pz), n=int(len(g)), pin=round(float(g.pin.mean()), 4), pl=round(float(g.pl.mean()), 4),
                           roznica_pkt=round(float((g.pl - g.pin).mean() * 100), 2), ev_sr=round(float(g.ev.mean()), 4), ev_dodatnie=round(float((g.ev > 0).mean()), 3)))
    ogolne = {f'{b}/{sp}': dict(meczow=int(g.mecz.nunique()), marza=round(float(g.marza.mean()), 4), korelacja=round(float(np.corrcoef(g.pin, g.pl)[0, 1]), 4) if len(g) > 2 else None,
                                roznica_sr_pkt=round(float((g.pl - g.pin).abs().mean() * 100), 2))
              for (b, sp), g in d.groupby(['buk', 'sp'])}
    # okazje: polski kurs powyżej uczciwego kursu Pinnacle; wynik z archiwum (gdy rozliczony)
    W = _wyniki_archiwum()
    ok = d[(d.ev >= 0.03) & (d.ev <= 0.6)].copy()        # > 60% = prawie na pewno złe dopasowanie
    ok['trafiony'] = [W.get((b, m, s, kl)) for b, m, s, kl in zip(ok.buk, ok.mecz, ok.start, ok.klucz)]
    rozl = ok[ok.trafiony.notna()]
    okazje = dict(n=int(len(ok)), rozliczone=int(len(rozl)),
                  trafione=round(float(rozl.trafiony.mean()), 4) if len(rozl) else None,
                  przewidywane=round(float(rozl.pin.mean()), 4) if len(rozl) else None,
                  roi=round(float(np.where(rozl.trafiony > 0, rozl.kurs - 1, -1).mean()), 4) if len(rozl) else None,
                  przyklady=[dict(buk=b, mecz=m, zaklad=kl, kurs=round(float(k_), 2), uczciwy=round(float(1 / p), 2), ev=round(float(e), 3))
                             for b, m, kl, k_, p, e in ok.sort_values('ev', ascending=False).head(10)[['buk', 'mecz', 'klucz', 'kurs', 'pin', 'ev']].itertuples(index=False)])
    wynik = dict(czas=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'), par=int(len(d)), ogolne=ogolne, lustro=lustro, okazje=okazje)
    try:
        with open(PLIK, 'w', encoding='utf-8') as f: json.dump(wynik, f, ensure_ascii=False)
    except Exception as e: STAN['bledy'].append(str(e)[:120])
    return dict(czas=wynik['czas'], par=wynik['par'], ogolne=ogolne, okazje={k: v for k, v in okazje.items() if k != 'przyklady'})


def prawdziwa_szansa(p_pl, buk, sp, rynek, lustro=None):
    """Szansa z polskiego kursu (po zdjęciu marży) poprawiona o średnią różnicę PL – Pinnacle w tym przedziale (mapa z `licz`).
    Do użycia tam, gdzie Pinnacle nie ma meczu. Bez mapy – zwraca p_pl."""
    try: lustro = lustro or json.load(open(PLIK)).get('lustro') or []
    except Exception: return p_pl
    for x in lustro:
        if x['buk'] == buk and x['sp'] == sp and x['rynek'] == rynek:
            lo, hi = [float(v) for v in x['przedzial'].strip('(]').split(',')]
            if lo < p_pl <= hi: return max(0.001, min(0.999, p_pl - x['roznica_pkt'] / 100))
    return p_pl
