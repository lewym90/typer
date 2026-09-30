"""Wspólne listy ze wszystkich dyscyplin: 5 Pewnych i Value (zakładki główne i jedna wiadomość na Telegramie).
Szanse we wszystkich sportach są skalibrowane (testy: piłka, tenis, MMA), więc można je porównywać między dyscyplinami.
Nowa dyscyplina = nowy wpis w SPORTY i funkcja w KANDYDACI."""
import os, json
import pandas as pd

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
SPORTY = [('pilka', '⚽', 'Piłka nożna'), ('tenis', '🎾', 'Tenis'), ('walki', '🥊', 'Sporty walki')]
IKONA = {k: i for k, i, _ in SPORTY}
PEWNE_ILE = 5
MIN_SZANSA = 0.68

def _pewne_pilka(dzis):
    for m in dzis.get('pewne', []):
        yield dict(sport='pilka', event_id=str(m.get('event_id') or m['mecz']), szansa=float(m['szansa']), start=m['start'],
                   ostrz=bool((m.get('raport') or {}).get('powazne')), niz=bool(m.get('nizsza_pewnosc')))

def _pewne_inne(inne, sp):
    s = inne.get(sp) or {}; byid = {m['event_id']: m for m in s.get('mecze', [])}
    for i in s.get('pewne', []):
        m = byid.get(i)
        if not m or not m.get('najpewniejszy'): continue
        yield dict(sport=sp, event_id=str(i), szansa=float(m['najpewniejszy']['szansa']), start=m['start'],
                   ostrz=bool((m.get('raport') or {}).get('ostrzezenie')), niz=bool(m.get('nizsza_pewnosc')))

def _value_pilka(dzis):
    for v in dzis.get('value', []):
        yield dict(sport='pilka', event_id=str(v.get('event_id') or v['mecz']), zaklad=v['zaklad'], ev=float(v['ev']), start=v['start'])

def _value_inne(inne, sp):
    for v in (inne.get(sp) or {}).get('value', []):
        yield dict(sport=sp, event_id=str(v['event_id']), zaklad=v['zaklad'], ev=float(v['ev']), start=v['start'])

def wybierz(dzis, inne):
    """Najlepsze typy ze wszystkich dyscyplin: najpierw bez ostrzeżeń i z szansą ≥68%, potem najwyższa szansa."""
    dzien = pd.Timestamp.now(tz='Europe/Warsaw').strftime('%Y-%m-%d')
    inne = inne if (inne or {}).get('data') == dzien else {}
    dzis = dzis if (dzis or {}).get('data') == dzien else {}
    kand = list(_pewne_pilka(dzis))
    for sp in ('tenis', 'walki'): kand += list(_pewne_inne(inne, sp))
    kand.sort(key=lambda k: (k['ostrz'], k['niz'] or k['szansa'] < MIN_SZANSA, -k['szansa']))
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
