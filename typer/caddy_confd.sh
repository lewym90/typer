#!/usr/bin/env bash
# Włącza w Caddy folder /etc/caddy/conf.d, w którym inne aplikacje na tym serwerze (np. kalendarz)
# mogą trzymać własne trasy BEZ edytowania pliku Caddyfile należącego do Typera.
# Bezpieczeństwo:
#  - trasa Typera zostaje dokładnie taka sama (dopisujemy tylko jedną linię „import”),
#  - nową wersję pliku sprawdza prawdziwe „caddy validate” PRZED podmianą,
#  - kopia zapasowa pliku, łagodne przeładowanie (reload, bez przerwy w działaniu),
#  - jeśli Typer po zmianie przestanie odpowiadać, poprzednia konfiguracja wraca sama.
# Można uruchamiać wielokrotnie (nic nie zrobi, jeśli już skonfigurowane).
# Użycie (jako root):  bash <(curl -fsSL https://raw.githubusercontent.com/lewym90/typer/main/typer/caddy_confd.sh)
set -uo pipefail
CF="${CADDYFILE:-/etc/caddy/Caddyfile}"
CD="${CONFD:-$(dirname "$CF")/conf.d}"
say() { printf '== %s\n' "$*"; }
die() { printf 'PRZERWANO (nic nie zmieniłem): %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "uruchom jako root"
command -v caddy >/dev/null || die "nie widzę programu caddy"
[ -f "$CF" ] || die "brak pliku $CF"
grep -qF "$CD" "$CF" && { say "Już skonfigurowane ($CD jest w Caddyfile). Nic do zrobienia."; exit 0; }

# Pierwsza linia otwierająca blok strony, np. „1-2-3-4.sslip.io {”
SITE_LINE="$(grep -nE '^[^[:space:]{#(][^{]*\{[[:space:]]*$' "$CF" | head -n1 | cut -d: -f1)"
[ -n "$SITE_LINE" ] || die "nie rozpoznaję układu pliku $CF (brak bloku strony)"
DOM="$(sed -n "${SITE_LINE}p" "$CF" | sed -E 's/[[:space:]]*\{.*$//; s/[[:space:]].*$//')"

health() { [ -n "${SKIP_HEALTH:-}" ] && return 0; curl -fsS -m 10 "https://$DOM/zdrowie" >/dev/null 2>&1; }
HEALTH_BEFORE=0; health && HEALTH_BEFORE=1
say "Typer przed zmianą: $([ $HEALTH_BEFORE = 1 ] && echo odpowiada || echo 'nie odpowiada (nie będę tego wymagać po zmianie)')"

mkdir -p "$CD" || die "nie mogę utworzyć $CD"
[ -e "$CD/00-puste.caddy" ] || printf '# Tu trafiają dodatkowe trasy innych aplikacji na tym serwerze. Pliki *.caddy z tego folderu są wczytywane do strony Typera.\n' > "$CD/00-puste.caddy"

BAK="$CF.przed-confd-$(date +%Y%m%d-%H%M%S)"
cp -p "$CF" "$BAK" || die "nie mogę zrobić kopii zapasowej"
NEW="$(mktemp "${CF}.XXXXXX")" || die "nie mogę utworzyć pliku tymczasowego"
# Dopisujemy JEDNĄ linię import zaraz po otwarciu bloku strony; reszta pliku bez zmian.
awk -v n="$SITE_LINE" -v imp="	import $CD/*.caddy" '{print} NR==n{print imp}' "$CF" > "$NEW"
chmod --reference="$CF" "$NEW" 2>/dev/null || true
if ! caddy validate --config "$NEW" --adapter caddyfile >/dev/null 2>"$NEW.err"; then
  cat "$NEW.err" >&2; rm -f "$NEW" "$NEW.err"
  die "Caddy odrzucił nową konfigurację; plik $CF jest nietknięty"
fi
rm -f "$NEW.err"
mv "$NEW" "$CF" || die "nie mogę podmienić pliku"

restore() {
  say "PRZYWRACAM poprzednią konfigurację"
  cp -p "$BAK" "$CF" && { systemctl reload caddy 2>/dev/null || systemctl restart caddy; }
  exit 1
}
say "Przeładowuję Caddy (łagodnie)"
systemctl reload caddy || restore
sleep "${WAIT:-3}"
systemctl is-active --quiet caddy || restore
if [ $HEALTH_BEFORE = 1 ]; then
  ok=0
  for _ in 1 2 3 4 5 6; do health && { ok=1; break; }; sleep "${WAIT:-3}"; done
  [ $ok = 1 ] || { echo "Typer nie odpowiada po zmianie." >&2; restore; }
fi
say "GOTOWE. Typer działa jak wcześniej. Kopia: $BAK"
say "Dodatkowe trasy wrzucaj jako pliki *.caddy do $CD i wykonaj: systemctl reload caddy"
