"""Wspólne listy ze wszystkich dyscyplin: 5 Pewnych i Value (zakładki główne i jedna wiadomość na Telegramie).
Szanse we wszystkich sportach są skalibrowane (testy: piłka, tenis, MMA), więc można je porównywać między dyscyplinami.
Nowa dyscyplina = nowy wpis w SPORTY i funkcja w KANDYDACI."""
import os, json
import pandas as pd

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
SPORTY = [('pilka', '⚽', 'Piłka nożna'), ('tenis', '🎾', 'Tenis'), ('walki', '🥊', 'Sporty walki')]
IKONA = {k: i for k, i, _ in SPORTY}
PEWNE_ILE = 5
MIN_SZANSA = 0.70

# ---------- doba programu: mecze ZACZYNAJĄCE SIĘ od 8:00 do 6:00 następnego dnia (nocne mecze należą do poprzedniego dnia;
# mecze 6:00–8:00 rano pomijane). Liczenie typów ok. 7:10, wiadomość na Telegram ok. 8:00. ----------
GODZINA_DOBY = 6
POCZATEK_LISTY = 8
TZ = 'Europe/Warsaw'

def teraz(): return pd.Timestamp.now(tz=TZ)

def dzien_programu(t=None):
    """Dzień programu (Timestamp o północy): mecz o 2:00 w nocy należy do dnia poprzedniego."""
    t = teraz() if t is None else pd.Timestamp(t)
    if t.tzinfo is None: t = t.tz_localize(TZ)
    return (t.tz_convert(TZ) - pd.Timedelta(hours=GODZINA_DOBY)).normalize()

def dzien_str(t=None): return dzien_programu(t).strftime('%Y-%m-%d')

def poczatek_listy(t=None):
    """Od kiedy liczymy mecze dnia: najwcześniej od 8:00 (liczenie o 7:10 nie bierze meczów 7:10–8:00), później od teraz."""
    t = teraz() if t is None else pd.Timestamp(t)
    if t.tzinfo is None: t = t.tz_localize(TZ)
    return max(t.tz_convert(TZ), dzien_programu(t) + pd.Timedelta(hours=POCZATEK_LISTY))

def koniec_doby(sport='pilka', t=None):
    """Do kiedy liczymy mecze dnia: 6:00 następnego dnia; walki do 9:00 (gale w USA kończą się rano)."""
    return dzien_programu(t) + pd.Timedelta(days=1, hours=9 if sport == 'walki' else GODZINA_DOBY)

def mozna_podmienic_typy(t=None):
    """Nierozliczony typ z dziennika wolno zastąpić nowym tylko tego samego dnia programu i gdy nowe typy pójdą na Telegram
    (w nocy 0–7 wiadomości są wstrzymane – wtedy zostaje typ, który już dostałeś)."""
    t = teraz() if t is None else pd.Timestamp(t)
    if t.tz_convert(TZ).hour < 7: return False
    try:   # po porannej wiadomości typy na Telegramie już się nie zmieniają – dziennik rozlicza te, które dostałeś
        st = json.load(open(os.path.join(OUT, 'status.json')))
        if (st.get('tg_typy') or {}).get('data') == dzien_str(): return False
    except Exception: pass
    return True

def _pewne_pilka(dzis):
    for m in dzis.get('pewne', []):
        yield dict(sport='pilka', event_id=str(m.get('event_id') or m['mecz']), szansa=float(m['szansa']), start=m['start'],
                   werdykt=(m.get('raport') or {}).get('werdykt') or m.get('werdykt'), niz=bool(m.get('nizsza_pewnosc')), ksw=False)

def _pewne_inne(inne, sp):
    s = inne.get(sp) or {}; byid = {m['event_id']: m for m in s.get('mecze', [])}
    for i in s.get('pewne', []):
        m = byid.get(i)
        if not m or not m.get('najpewniejszy'): continue
        yield dict(sport=sp, event_id=str(i), szansa=float(m['najpewniejszy']['szansa']), start=m['start'],
                   werdykt=((m.get('raport') or {}).get('ai') or {}).get('werdykt'), niz=bool(m.get('nizsza_pewnosc')), ksw=bool(m.get('rynek_pl')))

def _value_pilka(dzis):
    for v in dzis.get('value', []):
        yield dict(sport='pilka', event_id=str(v.get('event_id') or v['mecz']), zaklad=v['zaklad'], ev=float(v['ev']), start=v['start'])

def _value_inne(inne, sp):
    for v in (inne.get(sp) or {}).get('value', []):
        yield dict(sport=sp, event_id=str(v['event_id']), zaklad=v['zaklad'], ev=float(v['ev']), start=v['start'])

def wybierz(dzis, inne):
    """Najlepsze typy ze wszystkich dyscyplin: nigdy typy odradzane przez AI; najpierw szansa ≥70% z oceną „zgoda” (lub bez oceny),
    potem „ryzyko”, na końcu dopełnienie poniżej 70%. KSW (kursy tylko z rynku PL) dopiero po 100 rozliczonych walkach w dzienniku."""
    dzien = dzien_str()
    inne = inne if (inne or {}).get('data') == dzien else {}
    dzis = dzis if (dzis or {}).get('data') == dzien else {}
    kand = list(_pewne_pilka(dzis))
    for sp in ('tenis', 'walki'): kand += list(_pewne_inne(inne, sp))
    ksw_ok = bool((inne or {}).get('ksw_do_glownych'))
    kand = [k for k in kand if k['werdykt'] != 'odradza' and (ksw_ok or not k['ksw'])]
    kand.sort(key=lambda k: (k['niz'] or k['szansa'] < MIN_SZANSA, k['werdykt'] == 'ryzyko', -k['szansa']))
    pewne = sorted(kand[:PEWNE_ILE], key=lambda k: k['start'])
    val = list(_value_pilka(dzis))
    for sp in ('tenis', 'walki'): val += list(_value_inne(inne, sp))
    val.sort(key=lambda v: -v['ev'])
    licz = {sp: dict(pewne=sum(1 for k in kand if k['sport'] == sp), value=sum(1 for v in val if v['sport'] == sp)) for sp, _, _ in SPORTY}
    licz['pilka']['mecze'] = len(dzis.get('mecze', []))
    for sp in ('tenis', 'walki'): licz[sp]['mecze'] = len((inne.get(sp) or {}).get('mecze', []))
    return dict(data=dzien, wygenerowano=pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d %H:%M'),
                pewne=[{k: p[k] for k in ('sport', 'event_id')} for p in pewne], value=[{k: v[k] for k in ('sport', 'event_id', 'zaklad')} for v in val],
                liczby=licz)

def zapisz(gl):
    with open(os.path.join(OUT, 'glowne.json'), 'w', encoding='utf-8') as f: json.dump(gl, f, ensure_ascii=False)

def wczytaj():
    try: return json.load(open(os.path.join(OUT, 'glowne.json')))
    except Exception: return {}
