# NFL Calendar

Conteneur autonome qui télécharge le calendrier nflverse, produit `nfl.ics` toutes les six heures et le sert à NGINX Proxy Manager. Il ne contacte ni Google ni un compte tiers.

```text
nflverse games.csv → conteneur Python → /nfl.ics → NGINX Proxy Manager → Google Calendar
```

## Source et limites

La source gratuite est `https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv`. C’est un CSV structuré/versionné sans HTML à parser, mais **ce n’est pas une API NFL officielle**. Toute dépendance à son format est isolée dans [source.py](nfl_calendar/source.py). Le CSV apporte `game_id`, saison, phase, semaine, équipes, lieu, stade et kickoff.

Un `start_time` timezone-aware est conservé comme le même instant UTC. Sinon `gametime` est interprété dans le fuseau nflverse documenté (`America/New_York`), sans mapping stade, ville ou équipe. Un match `TBD` est omis jusqu’à ce qu’un kickoff exploitable soit publié.

`DTEND` respecte toujours : `end_time`, puis `duration`, puis le fallback `EVENT_DURATION_FALLBACK_MINUTES=210`. nflverse ne fournit actuellement pas de fin officielle : c’est donc une limite connue, sans estimation spécifique par match. Une source NFL officielle future s’ajoute seulement dans `source.py`.

## Docker et NGINX Proxy Manager

```bash
mkdir -p data
NFL_SEASON=2026 docker compose up -d --build
```

Le conteneur ne tourne pas en root, conserve le dernier fichier valide dans `./data/nfl.ics` et se synchronise toutes les six heures (`SYNC_INTERVAL_SECONDS=21600`). Il expose :

- `GET /nfl.ics` — `text/calendar; charset=utf-8`, cache 5 min ;
- `GET /healthz` — 200 dès qu’un calendrier valide est disponible.

Dans NGINX Proxy Manager, créez un *Proxy Host* pour `calendar.mondomaine.fr` vers ce conteneur, port `8000`, puis utilisez `https://calendar.mondomaine.fr/nfl.ics`. Si NPM est sur un autre réseau Docker, connectez les deux conteneurs à un réseau Docker commun ; n’ajoutez pas de configuration nginx au projet.

Google Calendar : **Autres agendas → + → À partir de l’URL → `https://calendar.mondomaine.fr/nfl.ics`**. Google choisit lui-même sa fréquence de rafraîchissement.

## Exécution locale

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m nfl_calendar.cli --season 2026 --dry-run
python -m nfl_calendar.cli --season 2026 --output output/nfl.ics
pytest
```

Variables : `NFL_SEASON`, `OUTPUT_FILE`, `EVENT_DURATION_FALLBACK_MINUTES`, `NFLVERSE_URL`, `CALENDAR_DOMAIN`, `LOG_LEVEL`, `SYNC_INTERVAL_SECONDS` et `PORT`.

Le CLI valide les données et l’ICS, écrit via fichier temporaire + `fsync` + remplacement atomique, conserve l’ancien fichier en cas d’erreur et ne réécrit pas un contenu identique. L’UID est toujours `nfl-<game_id>@<CALENDAR_DOMAIN>` : un changement de date, heure, stade ou `DTEND` met à jour le même événement.

## Tests et dépannage

`pytest` couvre le parsing, UID, TBD, priorité de `DTEND`, ICS, écriture atomique, changements, erreurs HTTP/timeout et serveur HTTP. Les erreurs réseau, CSV vide ou invalide conservent le dernier calendrier servi.

La collection [Postman](postman/nflcalendar.postman_collection.json) vérifie l’URL publiée par NGINX Proxy Manager.
# nflcalendar
