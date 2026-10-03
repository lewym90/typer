#!/bin/bash
# Instalacja serwera analizy AI (ręczna analiza meczu w aplikacji) na polskim VPS.
# Uruchom jako root:  bash <(curl -fsSL https://raw.githubusercontent.com/lewym90/typer/main/typer/instaluj_ai.sh)
set -e
REPO=https://raw.githubusercontent.com/lewym90/typer/main
IP=$(curl -fsS -4 https://api.ipify.org || hostname -I | awk '{print $1}')
DOMENA="$(echo "$IP" | tr . -).sslip.io"
echo "== Serwer AI Typera – adres: https://$DOMENA"

echo "== 1/6 Pakiety (Caddy – HTTPS, Python)"
apt-get update -qq
apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gnupg python3-venv >/dev/null
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi

echo "== 2/6 Biblioteki Pythona"
mkdir -p /opt/typer/ai/typer /opt/typer/ai/docs/data
[ -x /opt/typer/ai/venv/bin/python ] || python3 -m venv /opt/typer/ai/venv
/opt/typer/ai/venv/bin/pip install -q --upgrade pip
/opt/typer/ai/venv/bin/pip install -q numpy pandas scipy requests json-repair

echo "== 3/6 Klucz Gemini"
if [ ! -s /opt/typer/gemini_key ]; then
  read -r -s -p "Wklej klucz Gemini (ten sam co w GitHubie, sekret GEMINI_API_KEY) i naciśnij Enter: " K < /dev/tty; echo
  [ -n "$K" ] || { echo "Brak klucza – przerwano."; exit 1; }
  printf '%s' "$K" > /opt/typer/gemini_key; chmod 600 /opt/typer/gemini_key
else echo "   klucz już jest (/opt/typer/gemini_key)"; fi

echo "== 4/6 Skrypt startowy (zawsze najnowszy kod z repozytorium)"
cat > /opt/typer/ai/start.sh <<'S'
#!/bin/bash
cd /opt/typer/ai
for f in serwer_ai ai_raport sporty core tenis walki powiadomienia wspolne nazwy; do
  curl -fsSL "https://raw.githubusercontent.com/lewym90/typer/main/typer/$f.py" -o "typer/$f.py.new" && mv "typer/$f.py.new" "typer/$f.py"
done
export GEMINI_API_KEY="$(cat /opt/typer/gemini_key)"
exec /opt/typer/ai/venv/bin/python typer/serwer_ai.py
S
chmod +x /opt/typer/ai/start.sh

echo "== 5/6 Usługa systemowa"
cat > /etc/systemd/system/typer-ai.service <<S
[Unit]
Description=Typer – serwer analizy AI
After=network-online.target
[Service]
ExecStart=/opt/typer/ai/start.sh
Restart=always
RestartSec=10
Environment=AI_BUDZET_ZL=15
Environment=RECZNE_DZIENNIE=40
[Install]
WantedBy=multi-user.target
S
systemctl daemon-reload
systemctl enable -q typer-ai
systemctl restart typer-ai
( crontab -l 2>/dev/null | grep -v typer_ai_restart; echo "30 5 * * * systemctl restart typer-ai # typer_ai_restart" ) | crontab -

echo "== 6/6 HTTPS (Caddy)"
cat > /etc/caddy/Caddyfile <<S
$DOMENA {
	reverse_proxy 127.0.0.1:8787
}
S
command -v ufw >/dev/null && ufw status | grep -q active && { ufw allow 80/tcp; ufw allow 443/tcp; } || true
systemctl restart caddy

echo "== Sprawdzam (do 60 s)…"
for i in $(seq 1 12); do
  sleep 5
  if curl -fsS "https://$DOMENA/zdrowie" 2>/dev/null; then echo; echo "GOTOWE: serwer AI działa pod https://$DOMENA"; exit 0; fi
done
echo "Serwer jeszcze nie odpowiada przez HTTPS. Stan usług:"
systemctl --no-pager -l status typer-ai | tail -5
journalctl -u caddy --no-pager -n 8
