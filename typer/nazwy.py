"""Polskie nazwy reprezentacji (ten sam słownik co w aplikacji) i powody nieobecności zawodników."""
import re
PL = {
"Poland": "Polska",
"Germany": "Niemcy",
"Spain": "Hiszpania",
"France": "Francja",
"England": "Anglia",
"Italy": "Włochy",
"Netherlands": "Holandia",
"Belgium": "Belgia",
"Portugal": "Portugalia",
"Croatia": "Chorwacja",
"Czech Republic": "Czechy",
"Slovakia": "Słowacja",
"Ukraine": "Ukraina",
"Austria": "Austria",
"Switzerland": "Szwajcaria",
"Denmark": "Dania",
"Sweden": "Szwecja",
"Norway": "Norwegia",
"Finland": "Finlandia",
"Scotland": "Szkocja",
"Wales": "Walia",
"Republic of Ireland": "Irlandia",
"Northern Ireland": "Irlandia Północna",
"Hungary": "Węgry",
"Romania": "Rumunia",
"Serbia": "Serbia",
"Greece": "Grecja",
"Turkey": "Turcja",
"Albania": "Albania",
"Slovenia": "Słowenia",
"Bosnia and Herzegovina": "Bośnia i Hercegowina",
"Iceland": "Islandia",
"Lithuania": "Litwa",
"Latvia": "Łotwa",
"Estonia": "Estonia",
"Georgia": "Gruzja",
"Armenia": "Armenia",
"Bulgaria": "Bułgaria",
"North Macedonia": "Macedonia Północna",
"Montenegro": "Czarnogóra",
"Moldova": "Mołdawia",
"Belarus": "Białoruś",
"Kazakhstan": "Kazachstan",
"Brazil": "Brazylia",
"Argentina": "Argentyna",
"Mexico": "Meksyk",
"United States": "USA",
"Japan": "Japonia",
"South Korea": "Korea Płd.",
"Morocco": "Maroko",
"Colombia": "Kolumbia",
"Uruguay": "Urugwaj",
"Israel": "Izrael",
"Cyprus": "Cypr",
"Luxembourg": "Luksemburg",
"Malta": "Malta",
"Andorra": "Andora",
"San Marino": "San Marino",
"Kosovo": "Kosowo",
"Faroe Islands": "Wyspy Owcze",
"Gibraltar": "Gibraltar",
"Azerbaijan": "Azerbejdżan",
"Liechtenstein": "Liechtenstein",
"Canada": "Kanada",
"Australia": "Australia",
"Egypt": "Egipt",
"Senegal": "Senegal",
"Nigeria": "Nigeria",
"Tunisia": "Tunezja",
"Algeria": "Algieria",
"Iran": "Iran",
"Saudi Arabia": "Arabia Saudyjska",
"Bosnia & Herzegovina": "Bośnia i Hercegowina",
"Bosnia-Herzegovina": "Bośnia i Hercegowina",
"Czechia": "Czechy",
"Türkiye": "Turcja",
"Ireland": "Irlandia",
"Korea Republic": "Korea Płd.",
"USA": "USA",
"Ivory Coast": "Wybrzeże Kości Słoniowej"
}

def pl(n):
    return PL.get(n, n) if n else n

def pl_txt(s, *druzyny):
    """Zamienia angielskie nazwy drużyn w tekście na polskie (najpierw dłuższe, np. 'Northern Ireland' przed 'Ireland')."""
    o = str(s or '')
    for n in sorted([d for d in druzyny if d and d in PL], key=len, reverse=True):
        o = o.replace(n, PL[n])
    return re.sub(r'(\d)\.(\d)', r'\1,\2', o)   # po polsku: 2,5 zamiast 2.5

def pl_mecz(m):
    return ' – '.join(pl(x) for x in str(m).split(' – '))

# ---------- powody nieobecności (BSD, Big Balls, API-Football) po polsku ----------
_POWODY = {
    'national_team': 'powołanie do reprezentacji', 'national team': 'powołanie do reprezentacji', 'international duty': 'powołanie do reprezentacji',
    'injured': 'kontuzja', 'injury': 'kontuzja', 'injured list': 'kontuzja', 'missing fixture': 'nie zagra', 'missing': 'nie zagra',
    'out': 'nie zagra', 'out for season': 'nie zagra do końca sezonu', 'season ending': 'nie zagra do końca sezonu',
    'suspended': 'zawieszenie', 'suspension': 'zawieszenie', 'red card': 'czerwona kartka', 'yellow cards': 'kartki', 'yellow card suspension': 'kartki',
    'doubtful': 'niepewny', 'questionable': 'niepewny', 'day-to-day': 'niepewny', 'game time decision': 'niepewny', 'probable': 'raczej zagra',
    'illness': 'choroba', 'ill': 'choroba', 'sick': 'choroba', 'virus': 'choroba', 'flu': 'grypa', 'covid-19': 'COVID-19',
    'personal reasons': 'sprawy osobiste', 'personal': 'sprawy osobiste', 'family reasons': 'sprawy rodzinne', 'rest': 'odpoczynek',
    'fitness': 'brak formy fizycznej', 'lack of fitness': 'brak formy fizycznej', 'knock': 'stłuczenie', 'concussion': 'wstrząśnienie mózgu',
    'coach decision': 'decyzja trenera', "coach's decision": 'decyzja trenera', 'inactive': 'nieaktywny', 'unknown': 'powód nieznany',
    'not in squad': 'poza kadrą meczową', 'loan': 'wypożyczenie', 'transfer': 'transfer', 'surgery': 'operacja', 'fracture': 'złamanie',
    'broken': 'złamanie', 'bruise': 'stłuczenie', 'strain': 'naciągnięcie', 'sprain': 'skręcenie', 'tear': 'naderwanie', 'rupture': 'zerwanie',
}
_CZESCI = {'hamstring': 'ścięgna podkolanowego', 'knee': 'kolana', 'ankle': 'kostki', 'groin': 'pachwiny', 'muscle': 'mięśnia', 'calf': 'łydki',
           'thigh': 'uda', 'foot': 'stopy', 'back': 'pleców', 'shoulder': 'barku', 'hip': 'biodra', 'head': 'głowy', 'achilles': 'ścięgna Achillesa',
           'acl': 'więzadła krzyżowego', 'cruciate ligament': 'więzadła krzyżowego', 'ligament': 'więzadła', 'adductor': 'przywodziciela',
           'quadriceps': 'mięśnia czworogłowego', 'toe': 'palca u stopy', 'finger': 'palca', 'hand': 'dłoni', 'wrist': 'nadgarstka', 'arm': 'ręki',
           'elbow': 'łokcia', 'leg': 'nogi', 'neck': 'szyi', 'rib': 'żebra', 'ribs': 'żeber', 'chest': 'klatki piersiowej', 'face': 'twarzy',
           'nose': 'nosa', 'eye': 'oka', 'jaw': 'szczęki', 'abdominal': 'brzucha', 'pelvis': 'miednicy', 'heel': 'pięty', 'shin': 'goleni',
           'meniscus': 'łąkotki', 'collarbone': 'obojczyka', 'metatarsal': 'kości śródstopia', 'lower back': 'dolnej części pleców'}
_RODZAJ = {'injury': 'uraz', 'problem': 'uraz', 'issue': 'uraz', 'fracture': 'złamanie', 'strain': 'naciągnięcie', 'sprain': 'skręcenie',
           'tear': 'naderwanie', 'surgery': 'operacja', 'bruise': 'stłuczenie', 'knock': 'stłuczenie', 'rupture': 'zerwanie', 'pain': 'ból'}

def pl_powod(s):
    """'national_team' -> 'powołanie do reprezentacji', 'Hip Injury' -> 'uraz biodra'. Nieznane zostawia bez zmian."""
    t = str(s or '').strip()
    if not t: return t
    k = t.lower().replace('_', ' ').strip()
    if k in _POWODY: return _POWODY[k]
    if k.replace(' ', '_') in _POWODY: return _POWODY[k.replace(' ', '_')]
    slowa = k.replace('-', ' ').split()
    for czesc in sorted(_CZESCI, key=len, reverse=True):   # np. 'hamstring injury', 'left knee surgery', 'broken foot'
        if re.search(r'\b' + re.escape(czesc) + r's?\b', k):
            rodz = next((_RODZAJ[w] for w in slowa if w in _RODZAJ), None) or next((_POWODY[w] for w in slowa if w in _POWODY), 'uraz')
            return f'{rodz} {_CZESCI[czesc]}'
    for w in slowa:
        if w in _POWODY: return _POWODY[w]
    return t
