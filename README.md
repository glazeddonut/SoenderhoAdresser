# Sønderho Adresser

Webapp til at finde og analysere adresser i et område via en redigerbar polygon
på et kort. Beriger hver adresse med BBR-bygningsdata (type, areal, byggeår,
tagmateriale), fredningsstatus (FBB), afstand til nærmeste vand (OSM) og
til-salg-status fra Boligsiden.

## Konfiguration

BBR-data kræver en gratis service-bruger fra
[datafordeler.dk](https://datafordeler.dk/) (Selvbetjening → Brugere → Opret
bruger). Læg credentials i en `.env`-fil i projektroden:

```
DATAFORDELER_USER=dit-brugernavn
DATAFORDELER_PASSWORD=din-adgangskode
```

Uden credentials virker appen stadig, men viser adresser uden bygningstype og
areal.

## Kør lokalt

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Åbn <http://localhost:8000>.

## Kør med Docker

```bash
# Kopiér compose-skabelonen (den lokale version gitignores)
cp docker-compose.yml.example docker-compose.yml

# Byg og start (læser BBR-credentials fra .env)
docker compose up -d --build
```

Appen kører nu på <http://localhost:8000> (eller `http://<server-ip>:8000`).

- Ret host-porten i `docker-compose.yml` under `ports` hvis 8000 er optaget.
- `docker compose logs -f` følger loggen, `docker compose down` stopper den.
- Der er ingen database — søgeresultater caches kun i hukommelsen og nulstilles
  ved genstart.
