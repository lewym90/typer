#!/usr/bin/env bash
# PRZEŁĄCZENIE ze STAREGO serwera (188.68.247.55) na NOWY (188.68.247.201).
# Uruchom na NOWYM serwerze jako root (zakładka "NOWY lewym90", znak zachęty root@lewym90).
# Wymaga otwartego połączenia ze starym serwerem (/tmp/ssh-old).
# Co robi: wstrzymuje zadania i usługi push na starym, kopiuje końcowe dane, włącza wszystko na nowym.
# Zadania, które wysyłają dane na zewnątrz (kursy, egida, powiadomienia), działają zawsze tylko na jednym serwerze.
set -u
OLD=root@188.68.247.55
CP=/tmp/ssh-old
DOM=188-68-247-201.sslip.io
COFNIJ="bash <(curl -fsSL https://raw.githubusercontent.com/lewym90/typer/migracja-skrypty/cofnij.sh)"

so() { ssh -o ControlPath="$CP" -o BatchMode=yes "$OLD" "$@"; }
rs() { rsync -a -e "ssh -o ControlPath=$CP" "$@"; }
say() { printf '\n== %s\n' "$*"; }
die() { printf '\nPRZERWANO: %s\n' "$*" >&2; printf 'Żeby wrócić do stanu sprzed zmian, wklej:\n  %s\n' "$COFNIJ" >&2; exit 1; }

# --- Kontrole przed startem (nic jeszcze nie zmieniają) ---
[ "$(id -u)" = 0 ] || die "uruchom jako root"
[ "$(hostname)" = "lewym90" ] || { echo "PRZERWANO: to nie jest NOWY serwer (znak zachęty ma być root@lewym90). Nic nie zmieniłem."; exit 1; }
so true 2>/dev/null || { echo "PRZERWANO: brak połączenia ze starym serwerem. Otwórz je poleceniem:"; echo "  ssh -fN -o ControlMaster=yes -o ControlPath=/tmp/ssh-old -o ControlPersist=3h $OLD"; echo "Nic nie zmieniłem."; exit 1; }
[ "$(so hostname)" != "$(hostname)" ] || { echo "PRZERWANO: stary i nowy serwer mają tę samą nazwę. Nic nie zmieniłem."; exit 1; }
KL="$(so "crontab -l 2>/dev/null | grep '# typer_kursy'")"
[ -n "$KL" ] || { echo "PRZERWANO: na starym serwerze nie widzę zadania typer_kursy (może przełączenie już było?). Nic nie zmieniłem."; exit 1; }
curl -fsS -m 10 "https://$DOM/zdrowie" >/dev/null 2>&1 || { echo "PRZERWANO: nowy serwer AI nie odpowiada pod https://$DOM. Nic nie zmieniłem."; exit 1; }

echo "Za chwilę:"
echo "  1) wstrzymam zadania i usługi push na STARYM serwerze,"
echo "  2) skopiuję końcowe dane na NOWY serwer,"
echo "  3) włączę wszystko na NOWYM serwerze."
echo "Powiadomienia mogą być wstrzymane przez ok. 1-2 minuty."
read -r -p "Wpisz TAK i naciśnij Enter, aby kontynuować (cokolwiek innego anuluje): " A </dev/tty
[ "$A" = "TAK" ] || { echo "Anulowano. Nic nie zmieniłem."; exit 0; }

say "1/6 Kopie zapasowe zadań cron na starym serwerze (/root/crontab-*.przed-migracja)"
so '[ -e /root/crontab-root.przed-migracja ] || crontab -l > /root/crontab-root.przed-migracja 2>/dev/null; [ -e /root/crontab-egida.przed-migracja ] || crontab -u egida -l > /root/crontab-egida.przed-migracja 2>/dev/null; true'

say "2/6 Wstrzymuję zadania i usługi push na STARYM serwerze"
so "crontab -l 2>/dev/null | grep -v '# typer_kursy' | crontab -" || die "nie udało się wyłączyć zadania typer_kursy na starym serwerze"
so 'crontab -u egida -r 2>/dev/null; true'
echo "   czekam, aż zakończą się uruchomione właśnie zadania…"
for i in $(seq 1 18); do
  so "! pgrep -f '[k]\\.py --cron' >/dev/null && ! pgrep -u egida >/dev/null" && break
  sleep 5
done
so 'systemctl disable --now kalendarz-push forge-push poczta 2>&1 | grep -v "^Removed"; true'

say "3/6 Końcowa synchronizacja danych"
{ rs "$OLD:/opt/kalendarz/data/" /opt/kalendarz/data/ \
  && rs "$OLD:/opt/forge-push/data/" /opt/forge-push/data/ \
  && rs "$OLD:/opt/poczta/data/" /opt/poczta/data/ \
  && rs --exclude=/node --exclude=/repo --exclude=/env --exclude=/.npm "$OLD:/opt/egida/" /opt/egida/ \
  && rs --exclude=/ai/venv --exclude=/ai/start.sh "$OLD:/opt/typer/" /opt/typer/; } || die "kopiowanie danych nie powiodło się"
chown -R kalendarz:kalendarz /opt/kalendarz/data
chown -R forgepush:forgepush /opt/forge-push/data
chown -R poczta:poczta /opt/poczta/data
chown -R egida:egida /opt/egida
echo "   dane skopiowane"

say "4/6 Uruchamiam usługi na NOWYM serwerze"
systemctl enable --now kalendarz-push forge-push poczta 2>&1 | grep -v '^Created'
systemctl restart typer-ai

say "5/6 Włączam zadania automatyczne na NOWYM serwerze"
( crontab -l 2>/dev/null | grep -v '# typer_kursy'; echo "$KL" ) | crontab -
for f in --cron --neptun-cron --watchdog-cron --neptun-tg-cron; do
  bash /opt/egida/repo/server/install.sh "$f" 2>&1 | tail -n 1 | cut -c1-110
done

say "6/6 Sprawdzam, czy wszystko odpowiada"
chk() { local c i; for i in 1 2 3 4 5 6 7 8; do c=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$1"); [ "$c" = 200 ] && { echo "OK      $1"; return 0; }; sleep 3; done; echo "BŁĄD    $1 (kod $c)"; return 1; }
bad=0
chk "https://$DOM/zdrowie" || bad=1
chk "https://$DOM/kalendarz-push/health" || bad=1
chk "https://$DOM/forge-push/health" || bad=1
chk "https://$DOM/poczta/zdrowie" || bad=1
echo "Usługi (kalendarz-push forge-push poczta typer-ai kalendarz-stt caddy):"
systemctl is-active kalendarz-push forge-push poczta typer-ai kalendarz-stt caddy | paste -sd' '
echo "Zadania roota na nowym serwerze:"; crontab -l | cut -c1-70
echo "Liczba zadań egida na nowym serwerze: $(crontab -u egida -l 2>/dev/null | wc -l) (ma być 4)"
echo
if [ "$bad" = 0 ]; then
  echo "GOTOWE: nowy serwer działa i przejął wszystkie zadania."
else
  echo "UWAGA: część adresów nie odpowiada. Napisz mi, co jest powyżej. Cofnięcie: $COFNIJ"
fi
