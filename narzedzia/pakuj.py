#!/usr/bin/env python3
"""Pakuje aplikację do .github/workflows/typer.yml (workflow rozpakowuje ją przy każdym uruchomieniu i nadpisuje pliki w repo).
Użycie: python narzedzia/pakuj.py <numer wersji> "<opis wersji>"  – uruchom po każdej zmianie w typer/ albo docs/index.html."""
import base64, glob, io, os, re, sys, tarfile
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
W = '.github/workflows/typer.yml'
pliki = sorted(f for f in glob.glob('typer/*') if f.endswith(('.py', '.sh')) and not f.endswith('caddy_confd.sh'))
pliki += ['docs/index.html', 'docs/manifest.json', 'docs/data/dzis.json', 'docs/data/dziennik.json', 'requirements.txt', 'README.md']
pliki += sorted(glob.glob('docs/*.png'))
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode='w:gz', compresslevel=9) as t:
    for f in pliki:
        ti = tarfile.TarInfo(f); b = open(f, 'rb').read(); ti.size = len(b); ti.mode = 0o644
        if f.startswith('docs/data/'): b = b'{}'; ti.size = 2        # dane startowe – w repo są prawdziwe
        t.addfile(ti, io.BytesIO(b))
b64 = base64.b64encode(buf.getvalue()).decode()
linie = '\n'.join('          ' + b64[i:i + 76] for i in range(0, len(b64), 76))
s = open(W, encoding='utf-8').read()
s, n = re.subn(r"(<<'KONIEC'\n).*?(\n\s+KONIEC)", lambda m: m.group(1) + linie + m.group(2), s, count=1, flags=re.S)
assert n == 1
if len(sys.argv) > 2:
    s = re.sub(r'^# Typer – aplikacja z typami \(wersja .*$', f'# Typer – aplikacja z typami (wersja {sys.argv[1]}: {sys.argv[2]})', s, count=1, flags=re.M)
open(W, 'w', encoding='utf-8').write(s)
print('typer.yml:', len(s) // 1024, 'KB,', len(pliki), 'plików')
