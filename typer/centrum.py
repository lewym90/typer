"""Centrum (wersja 64) – uruchamiane na końcu każdego przebiegu. Liczy wszystko, co aplikacja pokazuje o programie, z zapisanych danych, bez AI:
 • przejrzystość: rzeczywista skuteczność typów dnia, ROI (z podatkiem i bez), CLV, Brier, log loss, kalibracja, dryf – docs/data/centrum.json,
 • historia prognoz (prognozy.csv): zapis tylko dopisywany – pierwotna prognoza i każda korekta osobno,
 • historia kursów (historia_kursow.json): kurs każdego typu u każdego bukmachera przy każdym odczycie (wykres, ruchy rynku),
 • segmenty do obserwacji, alerty kursowe, ustawienia alertów z Telegrama, raport dzienny.
Błąd tutaj nie dotyka reszty programu (osobny krok workflow)."""
import csv, datetime as dt, hashlib, json, math, os, re, sys, time
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
import powiadomienia as tg

TZ = ZoneInfo('Europe/Warsaw')
KAT = os.environ.get('TYPER_DANE') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'data')
P_PROGNOZ = os.path.join(KAT, 'prognozy.csv')
P_KURSOW = os.path.join(KAT, 'historia_kursow.json')
P_ALERTY = os.path.join(KAT, 'alerty.json')
P_CENTRUM = os.path.join(KAT, 'centrum.json')
PODATEK = 0.12
METODOLOGIA = [
    ('wersja 5', 'Szanse z kursów Pinnacle i Betfair; mecze bez tych kursów są pomijane.'),
    ('wersja 33', 'Dziennik liczy zysk od najlepszego polskiego kursu z rana.'),
    ('wersja 57–59', 'Value: przewaga min. 5%, kurs 1,30–2,60; powyżej 1,90 przewaga min. 7%.'),
    ('wersja 63', 'AI na darmowym kluczu Gemini: bez wyszukiwania Google, tylko dane zebrane przez program.'),
    ('wersja 64', 'Skuteczność w aplikacji liczona z dziennika zamiast z testów historycznych.')]
OPISY_KAT = ('value', 'zmiana', 'utrata', 'sklad', 'kontuzja', 'prognoza', 'start', 'gol', 'koniec', 'rozliczenie', 'raport')
DOMYSLNE = dict(kategorie={k: True for k in OPISY_KAT}, od=8, do=23, prog_spadku=5, kursy=[], wlasciciel=None, tg_ost=0)


def teraz(): return dt.datetime.now(TZ)
def wczytaj(n, d=None):
    try: return json.load(open(os.path.join(KAT, n), encoding='utf-8'))
    except Exception: return {} if d is None else d
def zapisz(p, o):
    with open(p, 'w', encoding='utf-8') as f: json.dump(o, f, ensure_ascii=False, separators=(',', ':'))
def wiersze(n):
    try: return list(csv.DictReader(open(os.path.join(KAT, n), encoding='utf-8')))
    except Exception: return []
def fl(x):
    try:
        v = float(x); return None if math.isnan(v) else v
    except Exception: return None
def wilson(t, n, z=1.96):
    if not n: return None, None
    p = t / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0, c - m), 4), round(min(1, c + m), 4)


# ---------------------------------------------------------------- przejrzystość
def rekordy():
    """Wszystkie rozliczone typy: {sport, rodzaj, poziom, data, szansa, traf, kurs}."""
    out = []
    for x in wiersze('typy_pewne.csv'):
        t = fl(x.get('trafiony'))
        if t is None: continue
        z = fl(x.get('zysk_na_1zl')); kurs = fl(x.get('kurs_pl_rano')) or (z + 1 if z and z > 0 else None)
        out.append(dict(sport='pilka', rodzaj='odradzane' if x.get('lista') == 'odradzane' else 'pewne', poziom=x.get('poziom'), nizsza=str(x.get('nizsza')) == 'True',
                        data=str(x.get('start'))[:10], szansa=fl(x.get('szansa')), traf=t, kurs=kurs, ai=x.get('ai') or '', clv=None))
    for x in wiersze('typy_inne.csv'):
        t = fl(x.get('trafiony'))
        if t is None or x.get('status') in ('krecz', 'brak wyniku', 'remis'): continue
        out.append(dict(sport=x.get('sport') or 'tenis', rodzaj=x.get('rodzaj') or 'pewne', poziom=x.get('poziom'), nizsza=str(x.get('nizsza')) == 'True',
                        data=str(x.get('start'))[:10], szansa=fl(x.get('szansa')), traf=t, kurs=fl(x.get('kurs_pl_rano')) or fl(x.get('kurs')), ai=x.get('ai') or '', clv=None))
    for x in wiersze('typy_value.csv'):
        z = fl(x.get('zysk_na_1zl'))
        if z is None or not x.get('wynik'): continue
        out.append(dict(sport='pilka', rodzaj='value', poziom='value', nizsza=False, data=str(x.get('start'))[:10], szansa=fl(x.get('szansa')),
                        traf=1.0 if z > 0 else 0.0, kurs=z + 1 if z > 0 else (fl(x.get('kurs_pl_rano')) or fl(x.get('kurs_betclic'))), ai='',
                        clv=(fl(x.get('kurs_pl_rano')) / fl(x.get('kurs_pl_zamk')) - 1) if fl(x.get('kurs_pl_rano')) and fl(x.get('kurs_pl_zamk')) else None))
    return [r for r in out if r['szansa'] is not None]


def miary(R):
    if not R: return dict(n=0)
    n = len(R); t = int(sum(r['traf'] for r in R)); lo, hi = wilson(t, n)
    eps = 1e-6
    brier = sum((r['szansa'] - r['traf']) ** 2 for r in R) / n
    ll = -sum(math.log(max(eps, r['szansa'] if r['traf'] else 1 - r['szansa'])) for r in R) / n
    zk = [r for r in R if r['kurs'] and r['kurs'] > 1]
    roi = sum((r['kurs'] - 1) if r['traf'] else -1 for r in zk) / len(zk) if zk else None
    roi_p = sum((r['kurs'] * (1 - PODATEK) - 1) if r['traf'] else -1 for r in zk) / len(zk) if zk else None
    clv = [r['clv'] for r in R if r.get('clv') is not None]
    daty = sorted(r['data'] for r in R)
    return dict(n=n, trafione=t, skutecznosc=round(t / n, 4), od_do=[daty[0], daty[-1]], przedzial=[lo, hi], przewidywane=round(sum(r['szansa'] for r in R) / n, 4),
                brier=round(brier, 4), logloss=round(ll, 4), roi=None if roi is None else round(roi, 4), roi_podatek=None if roi_p is None else round(roi_p, 4),
                z_kursem=len(zk), sredni_kurs=round(sum(r['kurs'] for r in zk) / len(zk), 2) if zk else None,
                zysk_10zl=round(roi * len(zk) * 10, 1) if zk else None, clv=round(sum(clv) / len(clv), 4) if clv else None)


def kalibracja(R):
    kos = []
    for a in range(0, 100, 10):
        G = [r for r in R if a / 100 <= r['szansa'] < (a + 10) / 100 or (a == 90 and r['szansa'] >= 1)]
        if len(G) >= 5: kos.append(dict(od=a, n=len(G), przewidywane=round(sum(r['szansa'] for r in G) / len(G), 4), weszlo=round(sum(r['traf'] for r in G) / len(G), 4)))
    return kos


def przejrzystosc():
    R = rekordy()
    dnia = [r for r in R if r['rodzaj'] == 'pewne' and r['poziom'] == 'najpewniejszy' and not r['nizsza']]
    val = [r for r in R if r['rodzaj'] == 'value']
    gr = teraz().date() - dt.timedelta(days=30)
    d30 = [r for r in dnia if r['data'] >= gr.isoformat()]
    v30 = [r for r in val if r['data'] >= gr.isoformat()]
    wcz = [r for r in dnia if r['data'] < gr.isoformat()]
    sporty = {s: miary([r for r in dnia if r['sport'] == s]) for s in ('pilka', 'tenis', 'walki')}
    poziomy = {p: miary([r for r in R if r['rodzaj'] == 'pewne' and r['poziom'] == p]) for p in ('najpewniejszy', 'lepszy_kurs', 'ryzykowny')}
    zb = dnia + [r for r in R if r['rodzaj'] == 'odradzane']
    ai = {w: miary([r for r in zb if r['ai'] == w or (w == 'odradza' and r['rodzaj'] == 'odradzane')]) for w in ('zgoda', 'ryzyko', 'odradza')}
    dryf = None
    if len(d30) >= 30 and len(wcz) >= 30:
        a, b = miary(d30), miary(wcz); dryf = dict(brier_30=a['brier'], brier_wczesniej=b['brier'], zmiana=round(a['brier'] - b['brier'], 4))
    wszystkie = wiersze('typy_pewne.csv') + wiersze('typy_inne.csv') + wiersze('typy_value.csv')
    return dict(skutecznosc=miary(dnia), skutecznosc_30=miary(d30), value=miary(val), value_30=miary(v30), sporty=sporty, poziomy=poziomy, ai=ai, dryf=dryf,
                kalibracja=kalibracja(dnia), kalibracja_wszystkie=kalibracja([r for r in R if r['rodzaj'] == 'pewne']),
                opublikowane=len(wszystkie), rozliczone=len(R), metodologia=[dict(data=a, zmiana=b) for a, b in METODOLOGIA])


# ---------------------------------------------------------------- bieżące typy
def biezace(dz, inne):
    """[(sport, event_id, mecz, start, poziom, klucz, zaklad, szansa, kurs_uczciwy, werdykt, kursy_pl)]"""
    out = []
    def dodaj(sp, eid, mecz, start, poz, t, w):
        if not isinstance(t, dict) or t.get('szansa') is None: return
        out.append(dict(sp=sp, eid=str(eid), mecz=mecz, start=start, poz=poz, klucz=str(t.get('klucz') or t.get('zaklad') or ''), zaklad=t.get('zaklad') or '',
                        szansa=t.get('szansa'), uczciwy=t.get('kurs_uczciwy'), w=w or '', kursy=t.get('kursy_pl') or {}))
    for m in dz.get('pewne') or []:
        w = (m.get('raport') or {}).get('werdykt') or m.get('werdykt')
        dodaj('pilka', m.get('event_id'), m.get('mecz'), m.get('start'), 'najpewniejszy', m, w)
        for p in ('lepszy_kurs', 'ryzykowny'): dodaj('pilka', m.get('event_id'), m.get('mecz'), m.get('start'), p, m.get(p), '')
    for v in dz.get('value') or []:
        dodaj('pilka', v.get('event_id'), v.get('mecz'), v.get('start'), 'value', dict(v, kursy_pl=dict({v.get('bukmacher') or 'Buk': v.get('kurs')}, **(v.get('kursy_pl') or {}))), (v.get('raport') or {}).get('werdykt'))
    for sp in ('tenis', 'walki'):
        s = inne.get(sp) or {}; byid = {m.get('event_id'): m for m in s.get('mecze') or []}
        for i in s.get('pewne') or []:
            m = byid.get(i)
            if not m: continue
            w = (m.get('raport') or {}).get('werdykt')
            for p in ('najpewniejszy', 'lepszy_kurs', 'ryzykowny'): dodaj(sp, i, m.get('mecz') or f"{m.get('a')} – {m.get('b')}", m.get('start'), p, m.get(p), w if p == 'najpewniejszy' else '')
        for v in s.get('value') or []:
            m = byid.get(v.get('event_id')) or {}
            dodaj(sp, v.get('event_id'), m.get('mecz') or f"{v.get('a')} – {v.get('b')}", v.get('start') or m.get('start'), 'value', dict(v, kursy_pl=dict({v.get('bukmacher') or 'Buk': v.get('kurs')}, **(v.get('kursy_pl') or {}))), (v.get('raport') or {}).get('werdykt'))
    return out


KOL = ['czas', 'zdarzenie', 'sport', 'event_id', 'mecz', 'start', 'poziom', 'klucz', 'zaklad', 'szansa', 'kurs_uczciwy', 'werdykt', 'najlepszy_kurs']

def historia_prognoz(typy):
    """Plik tylko dopisywany: pierwszy wpis to prognoza z chwili publikacji, kolejne to korekty. Starych wierszy nie zmieniamy."""
    ost, nowy = {}, not os.path.exists(P_PROGNOZ)
    if not nowy:
        for x in csv.DictReader(open(P_PROGNOZ, encoding='utf-8')): ost[(x['event_id'], x['poziom'], x['klucz'])] = x
    wyn = []; cz = teraz().strftime('%Y-%m-%d %H:%M')
    for t in typy:
        k = (t['eid'], t['poz'], t['klucz']); b = ost.get(k)
        kursy = [float(v) for v in t['kursy'].values() if fl(v)]
        w = dict(czas=cz, zdarzenie='pierwotna' if not b else 'korekta', sport=t['sp'], event_id=t['eid'], mecz=t['mecz'], start=t['start'], poziom=t['poz'], klucz=t['klucz'],
                 zaklad=t['zaklad'], szansa=round(float(t['szansa']), 4), kurs_uczciwy=t['uczciwy'], werdykt=t['w'], najlepszy_kurs=max(kursy) if kursy else '')
        if not b or abs(float(b['szansa']) - float(t['szansa'])) >= 0.01 or (t['w'] and b['werdykt'] != t['w']): wyn.append(w)
    if wyn:
        with open(P_PROGNOZ, 'a', encoding='utf-8', newline='') as f:
            z = csv.DictWriter(f, fieldnames=KOL)
            if nowy: z.writeheader()
            z.writerows(wyn)
    return len(wyn)


def prognozy_dzis(typy):
    """{event_id|poziom: [{czas, szansa, werdykt, zdarzenie}]} – do karty meczu; tylko dzisiejsze typy."""
    id_ = {(t['eid'], t['poz']) for t in typy}; out = {}
    try:
        for x in csv.DictReader(open(P_PROGNOZ, encoding='utf-8')):
            if (x['event_id'], x['poziom']) in id_: out.setdefault(f"{x['event_id']}|{x['poziom']}", []).append(dict(c=x['czas'][5:], s=float(x['szansa']), w=x['werdykt'], z=x['zdarzenie']))
    except Exception: pass
    return out


def historia_kursow(typy):
    h = wczytaj('historia_kursow.json'); cz = teraz().strftime('%m-%d %H:%M')
    for t in typy:
        if not t['kursy']: continue
        k = hashlib.md5(f"{t['eid']}|{t['klucz']}".encode()).hexdigest()[:10]
        e = h.setdefault(k, dict(m=t['mecz'], z=t['zaklad'], s=t['start'], u=t['uczciwy'], e=t['eid'], kl=t['klucz'], p=[]))
        kursy = {b: float(v) for b, v in t['kursy'].items() if fl(v)}
        if kursy and (not e['p'] or e['p'][-1][1] != kursy): e['p'].append([cz, kursy])
        e['p'] = e['p'][-40:]
    gr = (teraz() - dt.timedelta(days=4)).strftime('%Y-%m-%d')
    h = {k: v for k, v in h.items() if str(v.get('s'))[:10] >= gr}
    zapisz(P_KURSOW, h)
    return h


def ruchy(h):
    """Rynek: największe zmiany najlepszego kursu od pierwszego odczytu (min. 2 odczyty)."""
    out = []
    for k, e in h.items():
        if len(e['p']) < 2 or str(e.get('s')) < teraz().strftime('%Y-%m-%d %H:%M'): continue
        a, b = max(e['p'][0][1].values()), max(e['p'][-1][1].values())
        if a > 1: out.append(dict(id=k, mecz=e['m'], zaklad=e['z'], start=e['s'], od=a, do=b, zmiana=round(b / a - 1, 4), odczytow=len(e['p'])))
    return sorted(out, key=lambda x: -abs(x['zmiana']))[:12]


def segmenty():
    """Segmenty do obserwacji: z archiwum, bez polecania ich jako typów. Tylko próby min. 150 i z dodatnim ROI."""
    s = wczytaj('archiwum/statystyki.json'); out = []
    for x in s.get('okazje') or []:
        if (x.get('n') or 0) >= 150 and (x.get('roi') or 0) > 0:
            out.append(dict(kategoria=x.get('kategoria'), przedzial=x.get('przedzial'), n=x.get('n'), trafione=x.get('trafione'), z_kursu=x.get('z_kursu'), roi=x.get('roi')))
    return out[:8]


# ---------------------------------------------------------------- alerty
def komendy(al):
    """Ustawienia z aplikacji przychodzą przez bota: /start al_<bity>_<od>_<do>_<próg> oraz /start ka_<id>_<kurs×100> i kx_<id>.
    Odczyt bez potwierdzania, żeby nie zabierać komend strażnikowi na żywo; przetworzone rozpoznajemy po numerze aktualizacji."""
    if not tg.TOKEN: return al
    try: r = requests.get(f'https://api.telegram.org/bot{tg.TOKEN}/getUpdates', params={'timeout': 0}, timeout=20).json()
    except Exception as e: print('alerty – getUpdates:', e); return al
    for u in r.get('result') or []:
        if u['update_id'] <= (al.get('tg_ost') or 0): continue
        al['tg_ost'] = u['update_id']
        msg = u.get('message') or {}; txt = (msg.get('text') or '').strip(); kto = (msg.get('from') or {}).get('id'); chat = (msg.get('chat') or {}).get('id')
        m = re.match(r'/start (al|ka|kx)_(.+)$', txt)
        if not m: continue
        if al.get('wlasciciel') and al['wlasciciel'] != kto: continue
        al['wlasciciel'] = kto
        ch, a = m.group(1), m.group(2).split('_')
        try:
            if ch == 'al':
                al['kategorie'] = {k: (a[0][i:i + 1] == '1') for i, k in enumerate(OPISY_KAT)}
                al['od'], al['do'], al['prog_spadku'] = int(a[1]), int(a[2]), int(a[3])
                tg.wyslij_do(chat, '✅ Zapisałem ustawienia alertów.')
            elif ch == 'ka':
                al['kursy'] = [x for x in al.get('kursy', []) if x['id'] != a[0]] + [dict(id=a[0], kurs=int(a[1]) / 100)]
                tg.wyslij_do(chat, f'🎯 Dam znać, gdy kurs dojdzie do {int(a[1]) / 100:.2f}. Sprawdzam przy każdym odczycie kursów, zwykle co ok. 2 godziny.')
            else:
                al['kursy'] = [x for x in al.get('kursy', []) if x['id'] != a[0]]; tg.wyslij_do(chat, '🔕 Alert kursowy usunięty.')
        except Exception as e: print('alerty – komenda:', e)
    return al


def alerty_kursowe(al, h):
    zostaw = []
    for x in al.get('kursy', []):
        e = h.get(x['id'])
        if not e or not e['p']: continue
        if str(e.get('s')) < teraz().strftime('%Y-%m-%d %H:%M'): continue
        b, k = max(e['p'][-1][1].items(), key=lambda t: t[1])
        if k >= x['kurs']: tg.wyslij(f"🎯 <b>Kurs dobił do Twojego poziomu</b>\n{e['m']}\n{e['z']}: <b>{k:.2f}</b> ({b}), Twój próg {x['kurs']:.2f}")
        else: zostaw.append(x)
    al['kursy'] = zostaw
    return al


# ---------------------------------------------------------------- raport dzienny
def raport(dz, gl, cen, al):
    t = teraz(); dzien = t.strftime('%Y-%m-%d')
    st = wczytaj('centrum_stan.json')
    if st.get('raport') == dzien or not (8 <= t.hour < 12) or dz.get('data') != dzien: return wczytaj('centrum.json').get('raport')
    p = cen['skutecznosc_30']; v = cen['value']
    zm = ruchy(wczytaj('historia_kursow.json'))[:3]
    lin = [f"📊 Raport dnia · {t.strftime('%d.%m')}", '', f"Typów dnia: {len(gl.get('pewne') or [])}, Value: {len(gl.get('value') or [])}."]
    if p.get('n'): lin.append(f"Typy dnia, 30 dni: {p['trafione']} z {p['n']} ({p['skutecznosc'] * 100:.0f}%).")
    if v.get('n') and v.get('roi') is not None: lin.append(f"Value od początku: ROI {v['roi'] * 100:+.1f}% na {v['n']} typach.")
    for z in zm: lin.append(f"Kurs: {z['mecz']}, {z['zaklad']}: {z['od']:.2f} → {z['do']:.2f}")
    if cen.get('dryf'): lin.append(f"Kondycja: Brier {cen['dryf']['brier_30']:.3f} (wcześniej {cen['dryf']['brier_wczesniej']:.3f}).")
    tekst = '\n'.join(lin)
    streszcz = None
    try:
        import ai_raport
        if ai_raport.zostalo_analiz() > 0:
            streszcz, _ = ai_raport._pytaj('Streść po polsku w 2–3 zdaniach, rzeczowo, bez zachęcania do gry i bez dodawania faktów:\n' + tekst, maks=600)
    except Exception as e: print('raport – AI:', e)
    if streszcz: tekst += '\n\n' + streszcz.strip()
    if (al.get('kategorie') or {}).get('raport', True):
        tg.wyslij(tekst.replace('📊 Raport dnia', '📊 <b>Raport dnia</b>'))
    st['raport'] = dzien; zapisz(os.path.join(KAT, 'centrum_stan.json'), st)
    return dict(data=dzien, tekst=tekst)


def main():
    dz, inne, gl = wczytaj('dzis.json'), wczytaj('inne.json'), wczytaj('glowne.json')
    al = dict(DOMYSLNE); al.update(wczytaj('alerty.json'))
    al = komendy(al)
    typy = biezace(dz, inne)
    np = historia_prognoz(typy)
    h = historia_kursow(typy)
    al = alerty_kursowe(al, h)
    zapisz(P_ALERTY, al)
    cen = przejrzystosc()
    cen.update(czas=teraz().strftime('%Y-%m-%d %H:%M'), ruchy=ruchy(h), segmenty=segmenty(), prognozy=prognozy_dzis(typy),
               kursy={k: v for k, v in h.items() if str(v.get('s')) >= teraz().strftime('%Y-%m-%d')})
    cen['ustawienia_alertow'] = {k: al.get(k) for k in ('kategorie', 'od', 'do', 'prog_spadku', 'kursy')}
    cen['raport'] = raport(dz, gl, cen, al)
    zapisz(P_CENTRUM, cen)
    print('centrum: nowe wpisy prognoz', np, '| rozliczonych', cen['rozliczone'], '| typy dnia', cen['skutecznosc'].get('n'))


if __name__ == '__main__': main()
