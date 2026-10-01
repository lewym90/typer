"""Strażnik na żywo: co minutę sprawdza wyniki w ESPN i wysyła na Telegram start, gole, gole anulowane i koniec
meczów z zakładek Pewne i Value oraz meczów obserwowanych dzwonkiem 🔔; po ostatnim wytypowanym meczu – podsumowanie dnia.
Uruchamiany przez GitHub Actions (tryb na_zywo). Działa maks. ok. 5 h 40 min, potem sam uruchamia swojego następcę."""
import os, sys, json, time, subprocess, requests
sys.path.insert(0, os.path.dirname(__file__))
import pandas as pd
import powiadomienia as tg
from nazwy import pl, pl_txt, pl_mecz
from core import MASKI, MAXG, zysk_zakladu
import sporty, wspolne

KATALOG = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
PLIK_STANU = os.path.join(KATALOG, 'na_zywo.json')
REPO = os.environ.get('GITHUB_REPOSITORY', '')
GH_TOKEN = os.environ.get('GH_TOKEN', '')
LIMIT_S = 5 * 3600 + 40 * 60
PRZERWA = 60
ESPN_URL = 'https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}'
ESPN_SLUG = tg.ESPN
esc = tg.esc
teraz = lambda: pd.Timestamp.now(tz='Europe/Warsaw')

# ---------------- stan ----------------
def wczytaj_stan():
    try: s = json.load(open(PLIK_STANU))
    except Exception: s = {}
    s.setdefault('obserwowane', []); s.setdefault('mecze', {}); s.setdefault('tg_offset', 0)
    dzis = wspolne.dzien_str()   # doba programu 6:00–6:00: nocne mecze należą do poprzedniego dnia
    if s.get('data') != dzis:   # nowy dzień: zostają tylko mecze i obserwowane od początku tej doby (6:00)
        od = (wspolne.dzien_programu() + pd.Timedelta(hours=wspolne.GODZINA_DOBY)).strftime('%Y-%m-%d %H:%M')
        s['mecze'] = {k: v for k, v in s['mecze'].items() if str(v.get('start', '')) >= od}
        s['obserwowane'] = [o for o in s['obserwowane'] if str(o.get('start', '')) >= od]
        s['data'] = dzis
    return s

def zapisz_stan(s, commit=False, opis='stan na żywo'):
    s['aktualizacja'] = teraz().strftime('%Y-%m-%d %H:%M')
    json.dump(s, open(PLIK_STANU, 'w'), ensure_ascii=False, indent=0)
    if commit and os.environ.get('GITHUB_ACTIONS'):
        for proba in range(4):
            try:
                subprocess.run(['git', 'add', PLIK_STANU], check=True)
                if subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode == 0: return
                subprocess.run(['git', '-c', 'user.name=typer-bot', '-c', 'user.email=typer-bot@users.noreply.github.com',
                                'commit', '-q', '-m', opis], check=True)
                subprocess.run(['git', 'pull', '-q', '--rebase', '-X', 'theirs'], check=True)
                subprocess.run(['git', 'push', '-q'], check=True); return
            except Exception as e:
                print('commit stanu:', e); time.sleep(5 * (proba + 1))

def odswiez_repo():
    """Pobiera najnowsze typy (dzis.json) z repozytorium – poranne liczenie mogło je zmienić."""
    if os.environ.get('GITHUB_ACTIONS'):
        try: subprocess.run(['git', 'pull', '-q', '--rebase', '--autostash'], check=True, timeout=60)
        except Exception as e: print('git pull:', e)

def dzis_json():
    try: return json.load(open(os.path.join(KATALOG, 'dzis.json')))
    except Exception: return {}

# ---------------- mecze do śledzenia ----------------
def typy_meczu(m):
    """[(ikona, nazwa, ocena(hg, ag) -> zysk na 1 zł: >0 weszło, 0 zwrot, <0 nie weszło)]"""
    out = []
    H, A = m['gospodarz'], m['gosc']
    for ik, pole in (('🔒', None), ('⚖️', 'lepszy_kurs'), ('🎯', 'ryzykowny')):
        t = m if pole is None else m.get(pole)
        if t and t.get('klucz') in MASKI:
            k = t['klucz']; out.append((ik, pl_txt(t['zaklad'], H, A), lambda h, a, k=k: 1.0 if MASKI[k][min(h, MAXG), min(a, MAXG)] else -1.0, 'pewne'))
    if m.get('rynek'):
        kurs = float(m.get('kurs') or 2)
        out.append(('💰', f"{pl_txt(m['zaklad'], H, A)} @ {m.get('kurs')}",
                    lambda h, a, m=m, kurs=kurs: zysk_zakladu(m['rynek'], m['strona'], m.get('linia'), kurs, h, a), 'value'))
    return out

def sledzone(d, stan):
    """Mecze z Pewne i Value (połączone, gdy ten sam mecz jest w obu) + obserwowane dzwonkiem."""
    out = {}
    for m in d.get('pewne', []) + d.get('value', []):
        k = str(m.get('event_id') or m['mecz'])
        if k not in out: out[k] = dict(klucz=k, mecz=m['mecz'], gospodarz=m['gospodarz'], gosc=m['gosc'], start=m['start'],
                                       sport_key=m.get('sport_key'), liga=m.get('liga', ''), typy=[], wytypowany=True)
        out[k]['typy'] += typy_meczu(m)
    for o in stan['obserwowane']:
        if sporty.obserwowany_slug(o.get('slug', '')): continue   # tenis/MMA obsługuje sporty.obieg_na_zywo
        k = f"o_{o['slug']}_{o['id']}"
        if not any(v.get('espn') == (o['slug'], str(o['id'])) for v in out.values()):
            out[k] = dict(klucz=k, mecz=o['mecz'], gospodarz=o['dom'], gosc=o['gosc'], start=o['start'], liga=o.get('liga', ''),
                          espn=(o['slug'], str(o['id'])), typy=[], wytypowany=False)
    return out

# ---------------- ESPN ----------------
_tablice = {}
def tablica(slug, data_ny):
    """Wyniki ESPN dla ligi i dnia (czas nowojorski, jak w ESPN) – odświeżane przy każdym obiegu."""
    k = (slug, data_ny)
    if k in _tablice: return _tablice[k]
    try: j = requests.get(ESPN_URL.format(slug=slug) + '/scoreboard', params={'dates': data_ny}, timeout=20).json()
    except Exception as e: print('ESPN', slug, e); j = {}
    out = {}
    for e in j.get('events', []):
        c = (e.get('competitions') or [{}])[0]; t = c.get('competitors', [])
        H = next((x for x in t if x.get('homeAway') == 'home'), None); A = next((x for x in t if x.get('homeAway') == 'away'), None)
        if not H or not A: continue
        st = (e.get('status') or c.get('status') or {}); ty = st.get('type') or {}
        gole = [dict(min=(z.get('clock') or {}).get('displayValue', ''), kto=((z.get('athletesInvolved') or [{}])[0] or {}).get('displayName', ''),
                     dom=(z.get('team') or {}).get('id') == H['team'].get('id'), karny=bool(z.get('penaltyKick')), samob=bool(z.get('ownGoal')))
                for z in (c.get('details') or []) if z.get('scoringPlay')]
        try: hg, ag = int(H.get('score')), int(A.get('score'))
        except (TypeError, ValueError): hg = ag = None
        out[str(e.get('id'))] = dict(id=str(e.get('id')), slug=slug, stan=ty.get('state', 'pre'), opis=ty.get('shortDetail', ''),
                                     minuta=st.get('displayClock', ''), start=e.get('date'), dom=H['team'].get('displayName', ''),
                                     gosc=A['team'].get('displayName', ''), hg=hg, ag=ag, gole=gole, liga=j.get('leagues', [{}])[0].get('name', slug) if j.get('leagues') else slug)
    _tablice[k] = out
    return out

def data_ny(start_pl):
    return pd.Timestamp(start_pl).tz_localize('Europe/Warsaw').tz_convert('America/New_York').strftime('%Y%m%d')

def espn_meczu(m):
    """Stan meczu w ESPN (dopasowanie nazw jak w programie; obserwowane – po id)."""
    if m.get('espn'):
        slug, eid = m['espn']
        return tablica(slug, data_ny(m['start'])).get(eid)
    slug = ESPN_SLUG.get(m.get('sport_key'))
    if not slug: return None
    if 'espn_id' not in m:
        _, e = tg.znajdz_espn(m['sport_key'], m['gospodarz'], m['gosc'], m['start'])
        m['espn_id'] = str(e['id']) if e else None
    return tablica(slug, data_ny(m['start'])).get(m['espn_id']) if m['espn_id'] else None

# ---------------- wiadomości ----------------
def ocena_na_zywo(f, hg, ag, koniec):
    """✅/❌/🟢/🔴 – czy typ już się rozstrzygnął niezależnie od kolejnych goli."""
    teraz_ = f(hg, ag)
    if koniec: return '✅ weszło' if teraz_ > 0 else ('↩️ zwrot' if teraz_ == 0 else ('❌ połowa przegrana' if teraz_ > -0.99 else '❌ nie weszło'))
    przyszle = [f(hg + i, ag + j) for i in range(0, 7) for j in range(0, 7)]
    if min(przyszle) > 0: return '✅ już weszło'
    if max(przyszle) < 0: return '❌ już przegrane'
    return '🟢 na razie wchodzi' if teraz_ > 0 else ('🟡 na razie zwrot' if teraz_ == 0 else '🔴 na razie nie wchodzi')

def linia_wyniku(m, e):
    return f"<b>{esc(pl(m['gospodarz']))} {e['hg']}:{e['ag']} {esc(pl(m['gosc']))}</b>"

def blok_typow(m, e, koniec=False):
    return [f"{ik} {esc(n)} – {ocena_na_zywo(f, e['hg'], e['ag'], koniec)}" for ik, n, f, _ in m['typy']]

def znak(m): return '' if m['wytypowany'] else '🔔 '

# ---------------- Telegram: dzwonek 🔔 (obserwowanie meczów) ----------------
def komendy(stan):
    """Odczytuje /start o_<liga>_<id> (obserwuj) i /start x_<liga>_<id> (przestań) wysłane do bota z aplikacji."""
    if not tg.TOKEN: return False
    try: r = requests.get(f'https://api.telegram.org/bot{tg.TOKEN}/getUpdates', params={'offset': stan['tg_offset'] + 1, 'timeout': 0}, timeout=20).json()
    except Exception as e: print('getUpdates:', e); return False
    zmiana = False
    for u in r.get('result', []):
        stan['tg_offset'] = max(stan['tg_offset'], u['update_id'])
        msg = u.get('message') or {}; txt = (msg.get('text') or '').strip(); chat = (msg.get('chat') or {}).get('id')
        if not txt.startswith('/start ') and not txt.startswith('/obserwowane'): continue
        if txt.startswith('/obserwowane'):
            lista = [f"• {o['mecz']} ({o['start'][11:16]})" for o in stan['obserwowane']] or ['brak']
            tg.wyslij_do(chat, '🔔 Obserwowane mecze:\n' + '\n'.join(lista)); continue
        arg = txt.split(' ', 1)[1]
        try: akcja, slug, eid = arg[0], arg[2:].rsplit('_', 1)[0].replace('-', '.'), arg.rsplit('_', 1)[1]
        except Exception: continue
        if akcja == 'x':
            przed = len(stan['obserwowane'])
            stan['obserwowane'] = [o for o in stan['obserwowane'] if not (o['slug'] == slug and str(o['id']) == eid)]
            if len(stan['obserwowane']) < przed: zmiana = True; tg.wyslij_do(chat, '🔕 Nie obserwuję już tego meczu.')
            continue
        if any(o['slug'] == slug and str(o['id']) == eid for o in stan['obserwowane']):
            tg.wyslij_do(chat, '🔔 Ten mecz już jest obserwowany.'); continue
        if sporty.obserwowany_slug(slug):   # 🎾 tenis / 🥊 MMA
            try: x = sporty.znajdz_po_id(slug, eid)
            except Exception as ex: print('obserwowany (inne):', ex); x = None
            if not x: tg.wyslij_do(chat, '⚠️ Nie znalazłem tego meczu w serwisie wyników.'); continue
            stan['obserwowane'].append(dict(slug=slug, id=eid, dom=x['dom'], gosc=x['gosc'], mecz=f"{x['dom']} – {x['gosc']}", start=x['start'],
                                            liga=x['liga'], kto=(msg.get('from') or {}).get('first_name', '')))
            zmiana = True
            tg.wyslij_do(chat, f"🔔 Obserwuję: {x['dom']} – {x['gosc']} ({x['start'][11:16]}). Start, {'sety' if slug.startswith('t.') else 'wynik walki'} i koniec pojawią się w kanale.")
            continue
        e = None
        for dni in (0, 1):
            e = tablica(slug, (teraz() + pd.Timedelta(days=dni)).tz_convert('America/New_York').strftime('%Y%m%d')).get(eid)
            if e: break
        if not e: tg.wyslij_do(chat, '⚠️ Nie znalazłem tego meczu w serwisie wyników.'); continue
        start = pd.Timestamp(e['start']).tz_convert('Europe/Warsaw').strftime('%Y-%m-%d %H:%M')
        stan['obserwowane'].append(dict(slug=slug, id=eid, dom=e['dom'], gosc=e['gosc'], mecz=f"{pl(e['dom'])} – {pl(e['gosc'])}",
                                        start=start, liga=tg.NAZWY_ESPN.get(slug, slug), kto=(msg.get('from') or {}).get('first_name', '')))
        zmiana = True
        tg.wyslij_do(chat, f"🔔 Obserwuję: {pl(e['dom'])} – {pl(e['gosc'])} ({start[11:16]}). Start, gole i koniec pojawią się w kanale.")
    return zmiana

# ---------------- podsumowanie dnia ----------------
def podsumowanie(sl, stan):
    """Po ostatnim meczu z Pewne i Value: wyniki, trafienia dnia i skuteczność łączna jak w Dzienniku."""
    wiersze, dzien = [], {'pewne': {'🔒': [0, 0], '⚖️': [0, 0], '🎯': [0, 0]}, 'value': [0, 0, 0.0]}
    for m in sorted([m for m in sl.values() if m['wytypowany']], key=lambda m: m['start']):
        s = stan['mecze'].get(m['klucz'], {})
        if s.get('hg') is None: wiersze.append(f"{esc(pl_mecz(m['mecz']))} – brak wyniku"); continue
        opis = []
        for ik, n, f, rodz in m['typy']:
            z = f(s['hg'], s['ag'])
            if rodz == 'pewne': dzien['pewne'][ik][0] += z > 0; dzien['pewne'][ik][1] += 1
            else: dzien['value'][0] += z > 0; dzien['value'][1] += 1; dzien['value'][2] += z
            opis.append(f"{ik}{'✅' if z > 0 else ('↩️' if z == 0 else '❌')}")
        wiersze.append(f"{esc(pl(m['gospodarz']))} <b>{s['hg']}:{s['ag']}</b> {esc(pl(m['gosc']))} {' '.join(opis)}")
    lin = [f"📊 <b>Podsumowanie dnia {wspolne.dzien_programu().strftime('%d.%m')}</b>", ''] + wiersze + ['']
    a, b = dzien['pewne']['🔒']
    if b: lin.append(f"<b>Typy dnia 🔒: {a} z {b}</b> ({round(100 * a / b)}%)")
    for ik, nazwa, cel in (('⚖️', 'wyższy kurs', 'cel ok. 60%'), ('🎯', 'ryzykowne', 'cel ok. 37%')):
        a, b = dzien['pewne'][ik]
        if b: lin.append(f"{ik} {nazwa}: {a}/{b} ({round(100 * a / b)}%, {cel})")
    if dzien['value'][1]: lin.append(f"💰 Value: {dzien['value'][0]}/{dzien['value'][1]}, wynik {dzien['value'][2] * 10:+.2f} zł przy stawce 10 zł")
    lin += ['', '<b>Łącznie (piłka, jak w Dzienniku):</b>'] + skutecznosc_laczna(sl, stan)
    if tg.APLIKACJA: lin.append(f'\n<a href="{tg.APLIKACJA}">Otwórz aplikację →</a>')
    return '\n'.join(lin)

def skutecznosc_laczna(sl, stan):
    """Dziennik typów Pewne + dzisiejsze wyniki (jeszcze nierozliczone w pliku)."""
    out = []
    wyniki = {}
    for m in sl.values():
        s = stan['mecze'].get(m['klucz'], {})
        if m['wytypowany'] and s.get('hg') is not None: wyniki[m['klucz']] = (s['hg'], s['ag'])
    try:
        P = pd.read_csv(os.path.join(KATALOG, 'typy_pewne.csv'), dtype={'event_id': str, 'klucz': str})
        for i, r in P[P.trafiony.isna()].iterrows():
            w = wyniki.get(str(r.event_id))
            if w and r.klucz in MASKI: P.loc[i, 'trafiony'] = float(MASKI[r.klucz][min(w[0], MAXG), min(w[1], MAXG)])
        R = P[P.trafiony.notna()]
        if 'lista' in R: R = R[R.lista.fillna('pewne') == 'pewne']   # bez typów odradzanych przez AI (nie grane)
        niz = R.nizsza.fillna(False).astype(str).str.lower().isin(['true', '1', '1.0']) if 'nizsza' in R else pd.Series(False, index=R.index)
        g = R[(R.poziom == 'najpewniejszy') & ~niz]
        if len(g): out.append(f"<b>🔒 Typy dnia: {round(100 * g.trafiony.mean())}%</b> z {len(g)} (przewidywane {round(100 * g.szansa.mean())}%)")
        for poz, ik, nazwa, cel in (('lepszy_kurs', '⚖️', 'wyższy kurs', 'cel ok. 60%'), ('ryzykowny', '🎯', 'ryzykowne', 'cel ok. 37%')):
            g = R[R.poziom == poz]
            if len(g): out.append(f"{ik} {nazwa}: {round(100 * g.trafiony.mean())}% z {len(g)} ({cel})")
    except Exception as e: print('dziennik Pewne:', e)
    try:
        V = pd.read_csv(os.path.join(KATALOG, 'dziennik.csv'), dtype={'event_id': str})
        for i, r in V[V.zysk_na_1zl.isna()].iterrows():
            w = wyniki.get(str(r.event_id))
            if w and pd.notna(r.kurs_betclic): V.loc[i, 'zysk_na_1zl'] = zysk_zakladu(r.rynek, r.strona, r.linia, float(r.kurs_betclic), *w)
        R = V[V.zysk_na_1zl.notna()]
        if len(R): out.append(f"💰 Value: {len(R)} zakładów, ROI {R.zysk_na_1zl.mean() * 100:+.1f}%, wynik {R.zysk_na_1zl.sum() * 10:+.2f} zł (stawka 10 zł)")
    except FileNotFoundError: pass
    except Exception as e: print('dziennik Value:', e)
    out.append('<i>Przy mniej niż ok. 100 typach różnice to głównie przypadek.</i>')
    return out

# ---------------- główna pętla ----------------
def uruchom_nastepce():
    if not (REPO and GH_TOKEN): return False
    try:
        r = requests.post(f'https://api.github.com/repos/{REPO}/actions/workflows/typer.yml/dispatches', timeout=20,
                          headers={'Authorization': f'Bearer {GH_TOKEN}', 'Accept': 'application/vnd.github+json'},
                          json={'ref': os.environ.get('GITHUB_REF_NAME', 'main'), 'inputs': {'tryb': 'na_zywo'}})
        print('następca:', r.status_code); return r.status_code == 204
    except Exception as e: print('następca:', e); return False

def obieg(stan, sl, pierwszy):
    """Jeden obieg: porównuje wyniki z zapamiętanymi i wysyła wiadomości. Zwraca listę kluczy meczów wciąż w grze/przed startem."""
    _tablice.clear()
    starty, konce, aktywne = [], [], []
    for k, m in sl.items():
        e = espn_meczu(m)
        s = stan['mecze'].setdefault(k, dict(start=m['start'], stan='pre', hg=None, ag=None, gole=0))
        if not e:
            if pd.Timestamp(m['start']).tz_localize('Europe/Warsaw') > teraz() - pd.Timedelta(hours=2.5): aktywne.append(k)
            continue
        if e['stan'] != 'post': aktywne.append(k)
        # mecz zakończył się, zanim strażnik go zobaczył – tylko wynik końcowy, bez odtwarzania goli
        if e['stan'] == 'post' and s['stan'] == 'pre':
            s['stan'] = 'post'; s['hg'], s['ag'], s['gole'] = e['hg'], e['ag'], len(e['gole'])
            if e['hg'] is not None:
                typy = ' · '.join(f"{ik}{ocena_na_zywo(f, e['hg'], e['ag'], True)[0]} {esc(n)}" for ik, n, f, _ in m['typy'])
                konce.append(f"{znak(m)}{linia_wyniku(m, e)}" + (f"\n   {typy}" if typy else ''))
            continue
        # start
        if e['stan'] == 'in' and s['stan'] == 'pre':
            starty.append(f"• {znak(m)}{esc(pl_mecz(m['mecz']))} <i>({esc(m['liga'])})</i>")
            s['stan'] = 'in'; s['hg'] = s['hg'] or 0; s['ag'] = s['ag'] or 0
        # gole / anulowane
        if e['hg'] is not None and s['stan'] != 'pre' and (e['hg'], e['ag']) != (s['hg'], s['ag']):
            if e['hg'] + e['ag'] > (s['hg'] or 0) + (s['ag'] or 0):
                nowe = e['gole'][s.get('gole', 0):]
                g = nowe[-1] if nowe else None
                kto = f", {esc(g['kto'])}{' (k.)' if g['karny'] else ''}{' (sam.)' if g['samob'] else ''}" if g and g['kto'] else ''
                czas = esc(g['min']) if g and g['min'] else esc(e['minuta'])
                lin = [f"⚽ {znak(m)}{linia_wyniku(m, e)} ({czas}{kto})"] + blok_typow(m, e)
            else:
                lin = [f"🚫 {znak(m)}Gol anulowany – {linia_wyniku(m, e)}"] + blok_typow(m, e)
            tg.wyslij('\n'.join(lin))
            s['hg'], s['ag'], s['gole'] = e['hg'], e['ag'], len(e['gole'])
        # koniec
        if e['stan'] == 'post' and s['stan'] != 'post':
            s['stan'] = 'post'; s['hg'], s['ag'] = e['hg'], e['ag']
            typy = ' · '.join(f"{ik}{ocena_na_zywo(f, e['hg'], e['ag'], True)[0]} {esc(n)}" for ik, n, f, _ in m['typy'])
            konce.append(f"{znak(m)}{linia_wyniku(m, e)}" + (f"\n   {typy}" if typy else ''))
    if starty: tg.wyslij('▶️ <b>Rozpoczęły się:</b>\n' + '\n'.join(starty))
    if konce: tg.wyslij('🏁 <b>Koniec meczu:</b>\n' + '\n'.join(konce))
    return aktywne

def main():
    t0 = time.time(); stan = wczytaj_stan(); ostatni_pull = time.time()
    d = dzis_json(); pierwszy = True; inne = sporty.wczytaj_json()
    while True:
        if komendy(stan): zapisz_stan(stan, commit=True, opis='Obserwowane mecze')
        if time.time() - ostatni_pull > 600: odswiez_repo(); d = dzis_json(); inne = sporty.wczytaj_json(); ostatni_pull = time.time()
        dzis = wspolne.dzien_str()
        if d.get('data') != dzis: d = {}
        sl = sledzone(d, stan)
        aktywne = obieg(stan, sl, pierwszy); pierwszy = False
        try: trwa_i, przyszle_i = sporty.obieg_na_zywo(stan, inne)   # 🎾 tenis i 🥊 walki
        except Exception as e: print('tenis/walki na żywo:', e); trwa_i, przyszle_i = False, []
        zapisz_stan(stan)
        # podsumowanie: gdy wszystkie mecze z Pewne i Value się skończyły
        wytyp = [m for m in sl.values() if m['wytypowany']]
        if wytyp and stan.get('podsumowanie') != dzis and not d.get('podsumowanie_wyslane') and not any(m['klucz'] in aktywne for m in wytyp):
            if tg.wyslij_dlugi(podsumowanie(sl, stan)):
                stan['podsumowanie'] = dzis; zapisz_stan(stan, commit=True, opis='Podsumowanie dnia')
        # kiedy kończyć: nic nie trwa i najbliższy start za ponad 75 min (lekkie sprawdzenie uruchomi strażnika ponownie)
        trwa = [k for k in aktywne if stan['mecze'].get(k, {}).get('stan') == 'in']
        przyszle = [pd.Timestamp(sl[k]['start']).tz_localize('Europe/Warsaw') for k in aktywne if k in sl and stan['mecze'].get(k, {}).get('stan') == 'pre']
        przyszle += [pd.Timestamp(t).tz_localize('Europe/Warsaw') for t in przyszle_i]
        najblizszy = min(przyszle) if przyszle else None
        if not trwa and not trwa_i and (najblizszy is None or najblizszy > teraz() + pd.Timedelta(minutes=75)):
            # w nocy harmonogram GitHuba nie działa – strażnik czeka sam na nocne mecze tej doby (do 6:00, walki do 9:00)
            noc = teraz().hour >= 21 or teraz().hour < 9
            if not (noc and najblizszy is not None and najblizszy <= wspolne.koniec_doby('walki')):
                print('Koniec pracy strażnika – nic nie trwa, najbliższy start:', najblizszy); break
            if time.time() - t0 > LIMIT_S:
                print('Limit czasu – uruchamiam następcę'); zapisz_stan(stan, commit=True); uruchom_nastepce(); return
            time.sleep(PRZERWA * 5); continue   # do najbliższego startu daleko – rzadziej sprawdzamy
        if time.time() - t0 > LIMIT_S:
            print('Limit czasu – uruchamiam następcę'); zapisz_stan(stan, commit=True); uruchom_nastepce(); return
        time.sleep(PRZERWA)
    zapisz_stan(stan, commit=True)

if __name__ == '__main__':
    main()
