#!/usr/bin/env bash
# COFNIĘCIE przełączenia: praca wraca na STARY serwer (188.68.247.55).
# Uruchom na NOWYM serwerze jako root (znak zachęty root@lewym90). Wymaga połączenia /tmp/ssh-old.
# Dane zapisane na nowym serwerze od chwili przełączenia nie są przenoszone z powrotem.
set -u
OLD=root@188.68.247.55
CP=/tmp/ssh-old
so() { ssh -o ControlPath="$CP" -o BatchMode=yes "$OLD" "$@"; }
say() { printf '\n== %s\n' "$*"; }

[ "$(id -u)" = 0 ] || { echo "uruchom jako root"; exit 1; }
[ "$(hostname)" = "lewym90" ] || { echo "To nie jest NOWY serwer (ma być root@lewym90). Nic nie zmieniłem."; exit 1; }
so true 2>/dev/null || { echo "Brak połączenia ze starym serwerem. Otwórz je: ssh -fN -o ControlMaster=yes -o ControlPath=/tmp/ssh-old -o ControlPersist=3h $OLD"; exit 1; }
so '[ -s /root/crontab-root.przed-migracja ]' || { echo "Na starym serwerze nie ma kopii /root/crontab-root.przed-migracja. Nic nie zmieniłem."; exit 1; }

say "1/3 Wyłączam zadania i usługi push na NOWYM serwerze"
systemctl disable --now kalendarz-push forge-push poczta 2>&1 | grep -v '^Removed'
( crontab -l 2>/dev/null | grep -v '# typer_kursy' ) | crontab -
crontab -u egida -r 2>/dev/null

say "2/3 Przywracam zadania i usługi na STARYM serwerze"
so 'crontab /root/crontab-root.przed-migracja'
so '[ -s /root/crontab-egida.przed-migracja ] && crontab -u egida /root/crontab-egida.przed-migracja; true'
so 'systemctl enable --now kalendarz-push forge-push poczta 2>&1 | grep -v "^Created"; true'

say "3/3 Sprawdzam stary serwer"
so 'systemctl is-active kalendarz-push forge-push poczta typer-ai caddy | paste -sd" "; crontab -l | cut -c1-70; echo "zadań egida: $(crontab -u egida -l 2>/dev/null | wc -l)"'
echo
echo "GOTOWE: praca wróciła na stary serwer."
