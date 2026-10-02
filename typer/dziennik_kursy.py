"""Dziennik – najlepszy polski kurs przy każdym typie (wersja 33).
Przy każdym odczycie kursów (rano przed Telegramem i przy każdym odświeżeniu w ciągu dnia) dla typów z dzienników,
które jeszcze się nie zaczęły:
  kurs_pl_rano / buk_rano – najlepszy polski kurs z chwili pierwszego odczytu (rano = to, co przyszło na Telegram),
  kurs_pl_zamk / buk_zamk / czas_zamk – ostatni odczyt przed startem (kurs „zamknięcia”).
CLV = kurs_pl_rano / kurs_pl_zamk − 1: dodatnie = kurs po wysłaniu typu spadł, czyli rynek poszedł w stronę typu
(test 02.10 na 41 559 meczach: zakład na stronę, której szansa potem wzrosła o ≥3 pkt, dawał +10%).
Zysk typów dnia liczony jest od kursu z rana (najlepszy polski)."""
import os, json, datetime as dt
import numpy as np, pandas as pd

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
TZ = dt.timezone(dt.timedelta(hours=2))
try:
    from zoneinfo import ZoneInfo; TZ = ZoneInfo('Europe/Warsaw')
except Exception: pass

PLIKI = {'pewne': 'typy_pewne.csv', 'inne': 'typy_inne.csv', 'value': 'typy_value.csv'}
KOLUMNY = ['kurs_pl_rano', 'buk_rano', 'kurs_pl_zamk', 'buk_zamk', 'czas_zamk']


def najlepszy(kp):
    """(kurs, bukmacher) – najwyższy kurs spośród polskich bukmacherów."""
    best = None
    for b, k in (kp or {}).items():
        try: k = float(k)
        except Exception: continue
        if k > 1 and (best is None or k > best[0]): best = (k, b)
    return best


def _typy(obj):
    if isinstance(obj, dict):
        if 'klucz' in obj and 'szansa' in obj: yield obj
        for v in obj.values():
            if isinstance(v, dict) and 'klucz' in v and 'szansa' in v: yield v


def mapa_kursow(out=None):
    """{(event_id, klucz): (kurs, bukmacher)} z dzis.json (piłka) i inne.json (tenis, walki)."""
    out = out or OUT; m = {}
    def dodaj(eid, t):
        b = najlepszy(t.get('kursy_pl'))
        if eid and b:
            k = (str(eid), str(t['klucz']))
            if k not in m or b[0] > m[k][0]: m[k] = b
    try:
        d = json.load(open(os.path.join(out, 'dzis.json')))
        for x in (d.get('pewne') or []) + (d.get('odradzane') or []) + (d.get('mecze') or []) + (d.get('value') or []):
            if isinstance(x, dict):
                for t in _typy(x): dodaj(x.get('event_id'), t)
    except Exception: pass
    try:
        d = json.load(open(os.path.join(out, 'inne.json')))
        for sp in ('tenis', 'walki'):
            s = d.get(sp) or {}
            for x in (s.get('mecze') or []) + (s.get('value') or []):
                if isinstance(x, dict):
                    for t in _typy(x): dodaj(x.get('event_id'), t)
                    for v in x.get('value') or []:
                        if isinstance(v, dict) and v.get('klucz'): dodaj(x.get('event_id'), v)
    except Exception: pass
    return m


def _klucz_wiersza(nazwa, r):
    if nazwa == 'value':
        return str(r.get('strona')) if str(r.get('rynek')) == 'klucz' else None
    return str(r.get('klucz'))


def aktualizuj(out=None, teraz=None):
    """Dopisuje kursy do otwartych typów, które się jeszcze nie zaczęły. Zwraca {plik: liczba zmienionych wierszy}."""
    out = out or OUT
    teraz = teraz or dt.datetime.now(TZ)
    teraz_naive = pd.Timestamp(teraz).tz_localize(None) if pd.Timestamp(teraz).tzinfo else pd.Timestamp(teraz)
    mapa = mapa_kursow(out); wynik = {}
    if not mapa: return wynik
    for nazwa, plik in PLIKI.items():
        p = os.path.join(out, plik)
        if not os.path.exists(p): continue
        try: d = pd.read_csv(p, dtype=str, keep_default_na=False)
        except Exception: continue
        if not len(d) or 'start' not in d or 'event_id' not in d: continue
        for k in KOLUMNY:
            if k not in d: d[k] = ''
        zm = 0
        for i, r in d.iterrows():
            if str(r.get('wynik', '')).strip(): continue
            try: start = pd.Timestamp(str(r['start']))
            except Exception: continue
            if start <= teraz_naive: continue                         # po starcie kursy już się nie liczą
            kl = _klucz_wiersza(nazwa, r)
            b = mapa.get((str(r['event_id']), kl)) if kl else None
            if not b: continue
            kurs = f'{b[0]:.2f}'
            if not str(r['kurs_pl_rano']).strip():
                d.at[i, 'kurs_pl_rano'] = kurs; d.at[i, 'buk_rano'] = b[1]; zm += 1
            if str(r['kurs_pl_zamk']) != kurs or str(r['buk_zamk']) != b[1]:
                d.at[i, 'kurs_pl_zamk'] = kurs; d.at[i, 'buk_zamk'] = b[1]; zm += 1
            d.at[i, 'czas_zamk'] = pd.Timestamp(teraz).strftime('%Y-%m-%d %H:%M')
        if zm:
            d.to_csv(p, index=False); wynik[nazwa] = zm
    try:   # statystyki od razu w dzienniku aplikacji
        pd_ = os.path.join(out, 'dziennik.json')
        dz = json.load(open(pd_)) if os.path.exists(pd_) else {}
        dz['kursy_pl'] = statystyki(out)
        with open(pd_, 'w', encoding='utf-8') as f: json.dump(dz, f, ensure_ascii=False)
    except Exception as e: print('dziennik.json – kursy PL:', e)
    return wynik


def _f(x):
    try:
        v = float(x); return v if np.isfinite(v) else None
    except Exception: return None


def _wiersze_typow_dnia(out):
    """Rozliczone typy dnia 🔒 (lista Pewne, bez dopełnień poniżej progu) ze wszystkich dyscyplin: (trafiony, kurs_rano, kurs_zamk, start)."""
    w = []
    try:
        d = pd.read_csv(os.path.join(out, PLIKI['pewne']), dtype=str, keep_default_na=False)
        for _, r in d.iterrows():
            if r.get('poziom') != 'najpewniejszy' or (r.get('lista') or 'pewne') != 'pewne': continue
            if str(r.get('nizsza', '')).lower() in ('true', '1', '1.0'): continue
            w.append((_f(r.get('trafiony')), _f(r.get('kurs_pl_rano')), _f(r.get('kurs_pl_zamk')), r.get('start'), 'pilka'))
    except Exception: pass
    try:
        d = pd.read_csv(os.path.join(out, PLIKI['inne']), dtype=str, keep_default_na=False)
        for _, r in d.iterrows():
            if r.get('rodzaj') != 'pewne' or r.get('poziom') != 'najpewniejszy': continue
            if str(r.get('nizsza', '')).lower() in ('true', '1', '1.0'): continue
            if str(r.get('status', '')).strip(): continue             # krecz / walkower / odwołany – zwrot
            w.append((_f(r.get('trafiony')), _f(r.get('kurs_pl_rano')), _f(r.get('kurs_pl_zamk')), r.get('start'), r.get('sport') or ''))
    except Exception: pass
    return w


def _clv(pary):
    v = [a / b - 1 for a, b in pary if a and b]
    if not v: return None
    return dict(n=len(v), srednio=round(float(np.mean(v)), 4), w_strone_typu=round(float(np.mean([x > 0.004 for x in v])), 3),
                przeciw=round(float(np.mean([x < -0.004 for x in v])), 3))


def statystyki(out=None):
    """Zysk typów dnia po najlepszym polskim kursie z rana i CLV (rano vs przed meczem) – dla aplikacji."""
    out = out or OUT
    W = _wiersze_typow_dnia(out)
    R = [x for x in W if x[0] is not None and x[1]]
    st = {}
    if R:
        z = [(k - 1) if t >= 0.5 else -1.0 for t, k, _, _, _ in R]
        st['typy_dnia'] = dict(n=len(R), trafione=int(sum(1 for t, *_ in R if t >= 0.5)), sredni_kurs=round(float(np.mean([k for _, k, *_ in R])), 3),
                               zysk_10zl=round(float(sum(z) * 10), 2), roi=round(float(np.mean(z)), 4))
    st['clv_typy_dnia'] = _clv([(k, c) for _, k, c, _, _ in W])
    try:
        d = pd.read_csv(os.path.join(out, PLIKI['value']), dtype=str, keep_default_na=False)
        st['clv_value'] = _clv([(_f(a), _f(b)) for a, b in zip(d.get('kurs_pl_rano', []), d.get('kurs_pl_zamk', []))])
    except Exception: st['clv_value'] = None
    st['czas'] = dt.datetime.now(TZ).strftime('%Y-%m-%d %H:%M')
    return st
