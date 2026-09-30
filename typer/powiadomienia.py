"""Powiadomienia Telegram i wyniki ESPN (używane przez sprawdzenia w ciągu dnia)."""
import os, json, re, difflib, unicodedata, requests
import pandas as pd

DANE_DIR = os.path.join(os.path.dirname(__file__), '..', 'docs', 'data')
TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
STAN_TG = {'wlaczony': bool(TOKEN), 'chat': None, 'ostatni_blad': None, 'wyslane': 0}
APLIKACJA = os.environ.get('ADRES_APLIKACJI', '')

def _chat_id():
    if os.environ.get('TELEGRAM_CHAT_ID'): return os.environ['TELEGRAM_CHAT_ID']
    plik = os.path.join(DANE_DIR, 'telegram.json')
    try: return json.load(open(plik))['chat_id']
    except Exception: pass
    try:  # automatycznie: pierwsza rozmowa z botem (wystarczy wysłać mu /start)
        r = requests.get(f'https://api.telegram.org/bot{TOKEN}/getUpdates', timeout=20).json()
        for u in reversed(r.get('result', [])):
            ch = (u.get('message') or u.get('my_chat_member') or {}).get('chat', {})
            if ch.get('id'):
                json.dump({'chat_id': ch['id']}, open(plik, 'w')); return ch['id']
    except Exception as e: STAN_TG['ostatni_blad'] = str(e)
    return None

def wyslij(tekst):
    if not TOKEN: return False
    cid = _chat_id(); STAN_TG['chat'] = bool(cid)
    if not cid: STAN_TG['ostatni_blad'] = 'Brak rozmowy z botem – wyślij mu /start w Telegramie'; return False
    try:
        r = requests.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage', timeout=20,
                          data=dict(chat_id=cid, text=tekst[:4000], parse_mode='HTML', disable_web_page_preview='true')).json()
        if not r.get('ok'): STAN_TG['ostatni_blad'] = str(r.get('description')); return False
        STAN_TG['wyslane'] += 1; return True
    except Exception as e:
        STAN_TG['ostatni_blad'] = str(e); return False

def wyslij_dlugi(tekst, limit=3900):
    """Dzieli długą wiadomość na części (Telegram przyjmuje maks. 4096 znaków) – po pustych liniach, potem po liniach."""
    czesci, biez = [], ''
    for blok in tekst.split('\n\n'):
        for kawalek in ([blok] if len(blok) <= limit else [blok[i:i + limit] for i in range(0, len(blok), limit)]):
            if biez and len(biez) + 2 + len(kawalek) > limit: czesci.append(biez); biez = kawalek
            else: biez = f'{biez}\n\n{kawalek}' if biez else kawalek
    if biez: czesci.append(biez)
    ok = True
    for c in czesci: ok = wyslij(c) and ok
    return ok

def wyslij_do(chat_id, tekst):
    """Prywatna odpowiedź bota (np. potwierdzenie obserwowania meczu)."""
    if not TOKEN or not chat_id: return False
    try: return bool(requests.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage', timeout=20,
                                   data=dict(chat_id=chat_id, text=tekst[:4000], disable_web_page_preview='true')).json().get('ok'))
    except Exception: return False

_bot = {}
def nazwa_bota():
    """Nazwa użytkownika bota – aplikacja tworzy z niej link dzwonka 🔔 (t.me/<bot>?start=...)."""
    if 'n' not in _bot:
        _bot['n'] = None
        if TOKEN:
            try: _bot['n'] = requests.get(f'https://api.telegram.org/bot{TOKEN}/getMe', timeout=20).json()['result']['username']
            except Exception: pass
    return _bot['n']

def esc(s): return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
pct = lambda p: f"{round(p * 100)}%"

def kurs(x):
    """Kurs po polsku: 1,85 zamiast 1.85."""
    try: return f"{float(x):.2f}".replace('.', ',')
    except (TypeError, ValueError): return str(x or '')

# ---------- wyniki ESPN (publiczne dane, bez klucza i bez kredytów) ----------
ESPN = {'soccer_epl': 'eng.1', 'soccer_efl_champ': 'eng.2', 'soccer_spain_la_liga': 'esp.1', 'soccer_germany_bundesliga': 'ger.1',
 'soccer_germany_bundesliga2': 'ger.2', 'soccer_italy_serie_a': 'ita.1', 'soccer_france_ligue_one': 'fra.1', 'soccer_netherlands_eredivisie': 'ned.1',
 'soccer_portugal_primeira_liga': 'por.1', 'soccer_poland_ekstraklasa': 'pol.1', 'soccer_turkey_super_league': 'tur.1', 'soccer_belgium_first_div': 'bel.1',
 'soccer_spl': 'sco.1', 'soccer_uefa_champs_league': 'uefa.champions', 'soccer_uefa_europa_league': 'uefa.europa',
 'soccer_uefa_europa_conference_league': 'uefa.europa.conf', 'soccer_uefa_nations_league': 'uefa.nations', 'soccer_fifa_world_cup': 'fifa.world',
 'soccer_fifa_world_cup_qualifiers_europe': 'fifa.worldq.uefa', 'soccer_uefa_european_championship': 'uefa.euro', 'soccer_uefa_euro_qualification': 'uefa.euroq',
 'soccer_international_friendlies': 'fifa.friendly', 'soccer_usa_mls': 'usa.1', 'soccer_brazil_campeonato': 'bra.1',
 'soccer_argentina_primera_division': 'arg.1', 'soccer_mexico_ligamx': 'mex.1', 'soccer_japan_j_league': 'jpn.1', 'soccer_china_superleague': 'chn.1'}
_cache = {}

ALIASY = {'turkiye': 'turkey', 'czechia': 'czech republic', 'korea republic': 'south korea', 'republic of korea': 'south korea',
 'usa': 'united states', 'us': 'united states', 'bosnia herzegovina': 'bosnia and herzegovina', 'bosnia': 'bosnia and herzegovina',
 'cote d ivoire': 'ivory coast', 'republic of ireland': 'ireland', 'rep of ireland': 'ireland', 'north macedonia': 'macedonia',
 'cabo verde': 'cape verde', 'kyrgyz republic': 'kyrgyzstan', 'dr congo': 'congo dr', 'ir iran': 'iran', 'china pr': 'china',
 'chinese taipei': 'taiwan', 'curacao': 'curacao', 'holland': 'netherlands'}

def _nrm(s):
    s = unicodedata.normalize('NFKD', str(s).replace('ø', 'o').replace('&', ' and ')).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\b(fc|cf|afc|sc|ac|fk|sk|club|de|the)\b', ' ', s)
    s = re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', ' ', s)).strip()
    return ALIASY.get(s, s)

def podob(a, b):
    a, b = _nrm(a), _nrm(b)
    if a == b: return 1.0
    if a and b and (a in b or b in a) and min(len(a), len(b)) >= 4: return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()

def _mecze_espn(sport_key, start):
    slug = ESPN.get(sport_key)
    if not slug: return slug, []
    data = pd.Timestamp(start).tz_localize('Europe/Warsaw').tz_convert('America/New_York').strftime('%Y%m%d')
    k = (slug, data)
    if k not in _cache:
        try: j = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard', params={'dates': data}, timeout=20).json()
        except Exception as e: print('ESPN:', slug, e); j = {}
        _cache[k] = []
        for e in j.get('events', []):
            c = (e.get('competitions') or [{}])[0]; t = c.get('competitors', [])
            H = next((x for x in t if x.get('homeAway') == 'home'), None); A = next((x for x in t if x.get('homeAway') == 'away'), None)
            if not H or not A: continue
            st = ((e.get('status') or {}).get('type') or {}).get('state', 'pre')
            _cache[k].append(dict(id=e.get('id'), start=e.get('date'), dom=H['team'].get('displayName', ''), gosc=A['team'].get('displayName', ''),
                                  dom_id=H['team'].get('id'), gosc_id=A['team'].get('id'), hg=H.get('score'), ag=A.get('score'), stan=st))
    return slug, _cache[k]

def znajdz_espn(sport_key, dom, gosc, start):
    """Mecz ESPN pasujący do naszego: obie nazwy podobne, albo jedna bardzo podobna i ta sama godzina rozpoczęcia."""
    slug, lista = _mecze_espn(sport_key, start)
    t0 = pd.Timestamp(start).tz_localize('Europe/Warsaw')
    najl, out = 0, None
    for m in lista:
        a, b = podob(dom, m['dom']), podob(gosc, m['gosc'])
        try: dt = abs((pd.Timestamp(m['start']) - t0).total_seconds()) / 60
        except Exception: dt = 999
        ok = (a >= 0.6 and b >= 0.6) or (max(a, b) >= 0.8 and dt <= 20)
        if ok and a + b > najl: najl, out = a + b, m
    return slug, out

def wynik(sport_key, dom, gosc, start):
    """(gole gosp., gole gości, stan: pre/in/post) albo None."""
    slug, m = znajdz_espn(sport_key, dom, gosc, start)
    if not m: return None
    try: return int(m['hg']), int(m['ag']), m['stan']
    except (TypeError, ValueError): return None

def _starterzy(slug, event_id):
    """Pierwsze jedenastki z ESPN: {team_id: [nazwiska]} (puste, gdy składy nieogłoszone)."""
    try: j = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary', params={'event': event_id}, timeout=20).json()
    except Exception as e: print('ESPN skład:', e); return {}
    out = {}
    for r in j.get('rosters', []) or []:
        tid = (r.get('team') or {}).get('id')
        xi = [((p.get('athlete') or {}).get('displayName') or '') for p in (r.get('roster') or []) if p.get('starter')]
        if tid and len(xi) >= 7: out[str(tid)] = xi
    return out

def _poprzedni_mecz(slug, team_id, przed):
    try: j = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams/{team_id}/schedule', timeout=20).json()
    except Exception: return None
    best = None
    for e in j.get('events', []) or []:
        try: t = pd.Timestamp(e['date'])
        except Exception: continue
        done = (((e.get('competitions') or [{}])[0].get('status') or {}).get('type') or {}).get('completed')
        if done and t < przed and (best is None or t > best[0]): best = (t, e.get('id'))
    return best[1] if best else None

def sklady_espn(sport_key, dom, gosc, start):
    """Składy z ESPN + liczba zmian w pierwszej jedenastce względem poprzedniego meczu (wskaźnik rotacji)."""
    slug, m = znajdz_espn(sport_key, dom, gosc, start)
    if not m or not m.get('id'): return None
    xi = _starterzy(slug, m['id'])
    if not xi: return None
    out = {'gosp': xi.get(str(m['dom_id']), []), 'gosc': xi.get(str(m['gosc_id']), []), 'zmiany': {}, 'zrodlo': 'ESPN'}
    t0 = pd.Timestamp(m['start']) if m.get('start') else pd.Timestamp(start).tz_localize('Europe/Warsaw')
    for strona, tid in (('gosp', m['dom_id']), ('gosc', m['gosc_id'])):
        if not out[strona]: continue
        prev = _poprzedni_mecz(slug, tid, t0)
        if not prev: continue
        stare = _starterzy(slug, prev).get(str(tid), [])
        if stare: out['zmiany'][strona] = len(set(out[strona]) - set(stare))
    return out

NAZWY_ESPN = {'uefa.champions': 'Liga Mistrzów', 'uefa.europa': 'Liga Europy', 'uefa.europa.conf': 'Liga Konferencji', 'uefa.nations': 'Liga Narodów',
 'fifa.world': 'Mistrzostwa świata', 'fifa.worldq.uefa': 'El. MŚ (Europa)', 'uefa.euro': 'Mistrzostwa Europy', 'uefa.euroq': 'El. ME', 'fifa.friendly': 'Mecze towarzyskie',
 'eng.1': 'Premier League', 'eng.2': 'Championship', 'eng.3': 'League One', 'eng.4': 'League Two', 'eng.5': 'National League', 'esp.1': 'La Liga', 'esp.2': 'LaLiga 2',
 'ger.1': 'Bundesliga', 'ger.2': '2. Bundesliga', 'ita.1': 'Serie A', 'ita.2': 'Serie B', 'fra.1': 'Ligue 1', 'fra.2': 'Ligue 2', 'ned.1': 'Eredivisie', 'por.1': 'Liga Portugal',
 'pol.1': 'Ekstraklasa', 'sco.1': 'Premiership (SCO)', 'sco.2': 'Championship (SCO)', 'bel.1': 'Jupiler Pro League', 'tur.1': 'Süper Lig', 'gre.1': 'Super League (GRE)',
 'aut.1': 'Bundesliga (AUT)', 'den.1': 'Superliga (DEN)', 'nor.1': 'Eliteserien', 'swe.1': 'Allsvenskan', 'sui.1': 'Super League (SUI)', 'irl.1': 'League of Ireland',
 'rou.1': 'Liga I (ROU)', 'fin.1': 'Veikkausliiga', 'usa.1': 'MLS (USA)', 'bra.1': 'Brasileirão', 'arg.1': 'Liga Profesional (ARG)',
 'mex.1': 'Liga MX', 'jpn.1': 'J1 League', 'chn.1': 'Super League (CHN)'}
