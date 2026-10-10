"""Kontrola zdrowia programu (wersja 61). Uruchamiana na końcu KAŻDEGO przebiegu (po kursach) – sprawdza, czy to, co użytkownik ma widzieć,
naprawdę działa, i mówi wprost, co nie działa i dlaczego:
  • AI: Google odrzuca zapytania (brak środków 402 / zły klucz 401) albo dziś nie wykonano żadnej analizy,
  • kursy: dla każdego bukmachera odsetek typów dnia, przy których kurs powinien być, a go brak („?”; „—” i „n/d” nie liczą się),
  • polski serwer kursów: wiek ostatniego odczytu i bukmacherzy, którzy nie odczytali żadnego meczu.
Wynik: docs/data/zdrowie.json (czerwony pasek w aplikacji) + jedna wiadomość na Telegramie na dobę przy każdym NOWYM poważnym problemie
(i jedna „✅ naprawione”, gdy minie). Nic tu nie zmienia typów – tylko mówi prawdę o stanie danych."""
import os, json, sys, datetime as dt
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Warsaw')
KAT = os.environ.get('TYPER_DANE') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'data')
BUK = ('STS', 'Fortuna', 'Superbet', 'Betclic PL')
PLIK = os.path.join(KAT, 'zdrowie.json')

def _wczytaj(nazwa, domyslnie=None):
    try: return json.load(open(os.path.join(KAT, nazwa), encoding='utf-8'))
    except Exception: return domyslnie if domyslnie is not None else {}

def _poziomy(m):
    for k in ('najpewniejszy', 'lepszy_kurs', 'ryzykowny'):
        if isinstance(m.get(k), dict): yield m[k]

def _start(m, teraz):
    try: return dt.datetime.strptime(str(m.get('start'))[:16], '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
    except Exception: return None

def _karty(dzis, inne):
    """[(sport, karta, [poziomy typu])] – tylko karty z listy typów dnia (Pewne), mecze jeszcze niezaczęte."""
    out = []
    for m in dzis.get('pewne') or []:
        if isinstance(m, dict): out.append(('pilka', m, [m] + [m[k] for k in ('lepszy_kurs', 'ryzykowny') if isinstance(m.get(k), dict)]))
    for sp in ('tenis', 'walki'):
        s = inne.get(sp) or {}
        wybrane = set(s.get('pewne') or [])
        for m in s.get('mecze') or []:
            if m.get('event_id') in wybrane: out.append((sp, m, list(_poziomy(m))))
    return out

def pokrycie_kursow(dzis, inne, teraz=None):
    """{bukmacher: {'ok': n, 'brak': n, 'nd': n, 'kreska': n}} dla typów dnia z meczami, które się jeszcze nie zaczęły."""
    teraz = teraz or dt.datetime.now(TZ)
    wyn = {b: dict(ok=0, brak=0, nd=0, kreska=0) for b in BUK}
    for sp, m, poziomy in _karty(dzis, inne):
        s = _start(m, teraz)
        if s and s <= teraz: continue
        for t in poziomy:
            kp = t.get('kursy_pl') or {}; odczyt = set(t.get('kursy_odczyt') or []); nd = set(t.get('kursy_nd') or [])
            for b in BUK:
                if b in kp: wyn[b]['ok'] += 1
                elif b in odczyt: wyn[b]['kreska'] += 1
                elif b in nd: wyn[b]['nd'] += 1
                else: wyn[b]['brak'] += 1
    return wyn

def ocen(teraz=None):
    """Lista problemów [{id, poziom, tytul, tekst}] + stan AI."""
    teraz = teraz or dt.datetime.now(TZ)
    st = _wczytaj('status.json'); dzis = _wczytaj('dzis.json'); inne = _wczytaj('inne.json'); vps = _wczytaj('kursy_vps.json')
    problemy = []; godz = teraz.hour + teraz.minute / 60
    # --- AI
    ai = dict(dziala=True)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import ai_raport
        b = ai_raport.blokada()
        if b:
            ai = dict(dziala=False, kod=b.get('kod'), od=b.get('od'), powod=b.get('opis'))
            problemy.append(dict(id='ai_blokada', poziom='krytyczne', tytul='AI nie działa – brak ocen i analiz',
                                 tekst=(b.get('opis') or 'Google odrzuca zapytania.') + ' Dopóki to trwa, typy dnia pokazują się bez oceny AI.'))
    except Exception as e: print('zdrowie – AI:', e)
    g = st.get('gemini') or {}
    if ai.get('dziala') and godz >= 10 and (dzis.get('pewne') or []) and not g.get('analiz_dzis') and not g.get('z_pamieci') \
            and (g.get('koszt_miesiac_zl') or 0) < (g.get('budzet_zl') or 1e9) and g.get('klucz'):
        problemy.append(dict(id='ai_zero', poziom='uwaga', tytul='Dziś nie wykonano żadnej analizy AI',
                             tekst='Klucz jest, budżet jest, a analiz brak – sprawdź w Ustawieniach błędy Gemini.'))
    if (g.get('koszt_miesiac_zl') or 0) >= (g.get('budzet_zl') or 1e9) > 0 and ai.get('dziala'):
        problemy.append(dict(id='ai_budzet', poziom='uwaga', tytul='Wyczerpany miesięczny budżet AI w programie',
                             tekst=f"Wydano {g.get('koszt_miesiac_zl')} zł z {g.get('budzet_zl')} zł – podnieś AI_BUDZET_ZL albo poczekaj do 1. dnia miesiąca."))
    # --- kursy bukmacherów przy typach dnia
    pok = pokrycie_kursow(dzis, inne, teraz)
    for b, p in pok.items():
        n = p['ok'] + p['brak']
        if n < 4: continue
        if p['ok'] == 0:
            problemy.append(dict(id=f'kursy_{b}', poziom='krytyczne', tytul=f'{b}: brak kursów przy typach dnia',
                                 tekst=f'Przy żadnym z {n} zakładów nie ma kursu {b}, a powinien być (to awaria odczytu, nie brak w ofercie).'))
        elif p['ok'] / n < 0.6:
            problemy.append(dict(id=f'kursy_{b}_czesc', poziom='uwaga', tytul=f'{b}: brakuje części kursów',
                                 tekst=f"Kurs jest przy {p['ok']} z {n} zakładów (reszta „?” = nie odczytano)."))
    # --- polski serwer kursów
    try:
        czas = dt.datetime.strptime(vps.get('czas'), '%Y-%m-%d %H:%M UTC').replace(tzinfo=dt.timezone.utc)
        wiek_h = (teraz.astimezone(dt.timezone.utc) - czas).total_seconds() / 3600
        if 8 <= godz < 23 and wiek_h > 6:
            problemy.append(dict(id='vps_stary', poziom='krytyczne', tytul='Polski serwer kursów nie odświeża danych',
                                 tekst=f'Ostatni odczyt sprzed {wiek_h:.0f} h – sprawdź serwer (cron, token GitHub).'))
        elif 8 <= godz < 23 and wiek_h > 3:
            problemy.append(dict(id='vps_wolny', poziom='uwaga', tytul='Kursy z polskiego serwera są nieświeże', tekst=f'Ostatni odczyt sprzed {wiek_h:.1f} h.'))
        nasze = (vps.get('diag') or {}).get('nasze_mecze') or 0
        for kl, nazwa in (('fortuna', 'Fortuna'), ('sts', 'STS'), ('betclic', 'Betclic PL')):
            d = (vps.get('bukmacherzy') or {}).get(kl) or {}
            if nasze >= 6 and d.get('dopasowane', 0) == 0:
                problemy.append(dict(id=f'vps_{kl}', poziom='krytyczne', tytul=f'Serwer nie odczytał żadnego meczu u bukmachera {nazwa}',
                                     tekst='Strona bukmachera mogła zmienić format albo zablokować odczyt – kursy tego bukmachera nie będą się pojawiać.'))
    except Exception as e: print('zdrowie – serwer:', e)
    return problemy, ai, pok

def uruchom(wyslij=True):
    teraz = dt.datetime.now(TZ)
    problemy, ai, pok = ocen(teraz)
    stare = _wczytaj('zdrowie.json')
    doba = (teraz - dt.timedelta(hours=6)).strftime('%Y-%m-%d')
    wyslane = {k: v for k, v in (stare.get('wyslane') or {}).items() if v == doba}   # co dobę od nowa
    krytyczne = [p for p in problemy if p['poziom'] == 'krytyczne']
    nowe = [p for p in krytyczne if p['id'] not in wyslane and p['id'] != 'ai_blokada']   # v62: o braku środków/AI Telegram milczy (tylko pasek w aplikacji)
    ai_bylo_zle = (stare.get('ai') or {}).get('dziala') is False
    naprawione = ai_bylo_zle and ai.get('dziala') and stare.get('ai_alarm_wyslany')
    wiad = []
    if nowe:
        wiad.append('⚠️ <b>Typer – coś nie działa</b>\n' + '\n'.join(f"• <b>{p['tytul']}</b> – {p['tekst']}" for p in nowe))
    wys = False
    if wiad and wyslij:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import powiadomienia as tg
            wys = tg.wyslij('\n\n'.join(wiad))
        except Exception as e: print('zdrowie – Telegram:', e)
    if wys:
        for p in nowe: wyslane[p['id']] = doba
    ai_alarm = bool(stare.get('ai_alarm_wyslany')) if not naprawione else False
    if wys and any(p['id'] == 'ai_blokada' for p in nowe): ai_alarm = True
    out = dict(czas=teraz.strftime('%Y-%m-%d %H:%M'), problemy=problemy, ai=ai, pokrycie_kursow=pok, wyslane=wyslane, ai_alarm_wyslany=ai_alarm)
    tmp = PLIK + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: json.dump(out, f, ensure_ascii=False)
    os.replace(tmp, PLIK)
    print('Zdrowie:', 'OK' if not problemy else '; '.join(f"{p['poziom']}: {p['tytul']}" for p in problemy))
    return out

if __name__ == '__main__':
    try: uruchom()
    except Exception as e: print('Kontrola zdrowia – błąd (reszta programu działa):', type(e).__name__, e)
