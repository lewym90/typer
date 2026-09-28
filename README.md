# ⚽ Typer – aplikacja z typami piłkarskimi

Program codziennie rano sam liczy typy (Value w Betclic, 5 najpewniejszych, dziennik),
a aplikacja na telefonie pokazuje wyniki i pozwala przeanalizować dowolny mecz.

## Instalacja (z telefonu)
Cała aplikacja mieści się w jednym pliku: `.github/workflows/typer.yml`.
1. Sekret `ODDS_API_KEY` (Settings → Secrets and variables → Actions). Opcjonalnie `API_FOOTBALL_KEY` (darmowe konto na api-football.com) – kontuzje, zawieszenia i rotacje w raporcie przedmeczowym.
2. Settings → Pages → Source: **GitHub Actions**.
3. Add file → Create new file → `.github/workflows/typer.yml` → wklej zawartość → Commit.
4. Po ok. 10 minutach aplikacja działa pod adresem `https://TWÓJ-LOGIN.github.io/typer/`.

Typy odświeżają się same codziennie o 12:00. Ręcznie: Actions → Typer → Run workflow.
Aktualizacja programu = podmiana pliku `typer.yml` na nowy.

## Pliki
- `typer/core.py` – model, pobieranie danych, kursy, dziennik
- `typer/run_daily.py` – codzienne uruchomienie, zapis do `docs/data/`
- `docs/index.html` – aplikacja
- `.github/workflows/typer.yml` – instalator i harmonogram (zawiera wszystkie pliki)

## Plan płatny The Odds API (opcjonalnie)
Settings → Secrets and variables → Actions → zakładka Variables → „New repository variable”:
`PLATNY_PLAN` = `1`. Włącza pomiar CLV w dzienniku.

⚠ Repozytorium jest publiczne: każdy z linkiem zobaczy aplikację i kod (ale **nie** Twój klucz API).
Tylko dla osób pełnoletnich. Program liczy prawdopodobieństwa – nie daje pewnych typów.
