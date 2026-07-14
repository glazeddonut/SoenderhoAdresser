# CLAUDE.md — Sønderho Adresser

Kontekst til fremtidige sessioner. Læs denne før du arbejder på projektet.
Sproget i UI og kommentarer er **dansk** — match det.

## Hvad er det

Lokal webapp til at finde og analysere adresser i et geografisk område. Man tegner
(eller flytter) en **polygon** på et kort, søger, og får alle adresser inden for den —
beriget med bygnings- og salgsdata. Oprindeligt bygget til **Sønderho** på Fanø, men
virker nu i hele Danmark via postnummer-opslag.

Hver adresse beriges med:
- **BBR-bygningsdata:** type (helårshus/fritidshus/andet), samlet boligareal, bebygget
  areal, byggeår, tagdækningsmateriale.
- **Fredningsstatus** fra Slots- og Kulturstyrelsen (FBB).
- **Afstand til nærmeste vand** (kyst, søer, åer) beregnet fra OSM-data.
- **Til-salg-status + udbudspris** fra Boligsiden.dk (auto-tjekkes når den filtrerede
  liste er ≤ 250 adresser).
- **Markedspris-estimat** ud fra tidligere frie handler (familiehandler ekskluderet),
  korreleret med salgsdato og m² — plus offentlig vurdering pr. adresse.

Resultater vises i en filtrerbar, sorterbar tabel og som farvede markører på kortet.

- **Backend:** Python + **FastAPI** (`main.py`), API-integrationer i `api/`.
- **Frontend:** vanilla JS + **Leaflet** (`static/`), ingen build-step.
- **Ingen database** — søgeresultater caches kun **in-memory** (polygon-hash → resultat)
  og nulstilles ved genstart.
- **GitHub:** https://github.com/glazeddonut/SoenderhoAdresser (main).

## Sådan kører du det

- **Lokalt:** `pip install -r requirements.txt` → `uvicorn main:app --reload` → <http://localhost:8000>.
- **Docker:** `cp docker-compose.yml.example docker-compose.yml` → `docker compose up -d --build`.
  Ingen volume (ingen DB); BBR-credentials læses fra `.env` via `env_file`.
- **Preview under udvikling:** `.claude/launch.json` definerer serveren `soenderho`
  (system-`uvicorn` på 8000, **uden** `--reload`). Efter backend-ændringer skal serveren
  **genstartes** for at rydde in-memory cachen og indlæse ny kode.

## Konfiguration (.env — git-ignored, committes ALDRIG)

```
DATAFORDELER_USER=...
DATAFORDELER_PASSWORD=...
```

Gratis service-bruger fra <https://datafordeler.dk> (Selvbetjening → Brugere → Opret bruger).
Uden credentials virker appen, men adresser vises uden bygningstype/areal (`/api/config`
melder `bbr_enabled: false`, og UI viser en hjælpetekst).

## Filoversigt

| Fil | Ansvar |
|-----|--------|
| `main.py` | FastAPI-app, endpoints, berigelse (`enrich`), in-memory cache, no-cache static |
| `api/dawa.py` | Adresser inden for polygon fra DAWA (`fetch_addresses_in_polygon`) |
| `api/bbr.py` | Bygningsdata pr. adgangsadresse fra Datafordeler BBR (`fetch_buildings`) |
| `api/fbb.py` | Fredede bygninger i bbox fra Slots- og Kulturstyrelsen WFS (`fetch_listed_buildings`) |
| `api/water.py` | Vanddata fra OSM Overpass + `WaterIndex` (spatial grid til afstandsberegning) |
| `api/boligsiden.py` | Til-salg-tjek via `curl_cffi` (`check_for_sale`) + salgshistorik via `httpx` (`fetch_registrations`) |
| `api/prisindeks.py` | Markedspris-model: log-lineær kr/m²-trend + estimat pr. bolig (`build_model`, `estimate`) |
| `static/index.html` | UI: kontroller, filtre, tabel |
| `static/app.js` | Kort, polygon, søgning, filtrering, auto-tjek af Boligsiden |
| `static/style.css` | Styling |

## Endpoints (main.py)

- `GET /api/config` → `{bbr_enabled}` (bruges også som healthcheck i Docker).
- `POST /api/search` `{polygon: [[lon,lat],...]}` → liste af berigede adresser (cachet på polygon-hash).
- `GET /api/postnummer/{nr}` → `{nr, navn, bbox:[minLon,minLat,maxLon,maxLat], center, antal}`
  — bruges til at flytte polygonen til et postnummer.
- `GET /api/boligsiden?vejnavn&husnr&postnr&postnrnavn` → `{til_salg, pris, url}`.
- `POST /api/prisindeks` `{addresses:[{id, m2}]}` → `{model, estimater:{id:{...}}}`. Bygger
  områdets kr/m²-indeks af tidligere frie handler og estimerer markedspris pr. bolig.
  Cacher salgshistorik pr. adresse til `data/salgshistorik.json` (overlever genstart).
- `GET /` → `static/index.html`. `/static/*` serveres med `no-cache` (se nedenfor).

## Resultat-objektet (pr. adresse)

`id, adresse, vejnavn, husnr, postnr, postnrnavn, x (lon), y (lat), type, anvend_kode,
boligareal, bebygget_areal, opfoerelse_aar, tagmateriale, fredet, vand_afstand`.
`til_salg`/`pris` sættes først når Boligsiden auto-tjekkes i frontenden.

## Datakilder — vigtige (ikke-oplagte) fakta

### DAWA (`api.dataforsyningen.dk`)
- **Polygon-format:** triple-nested lukket GeoJSON-ring: `[[[lon,lat],...]]` (første = sidste).
  Brug `struktur=mini` for let svar (giver bl.a. `adgangsadresseid`, `x`=lon, `y`=lat i WGS84).
- **Dyb paginering afvises med HTTP 400** ved ca. `per_side*side > 25000`. `/api/postnummer`
  capper derfor ved 25 sider; adresser kommer i id-rækkefølge (rumligt tilfældigt), så
  udstrækningen er stadig præcis.
- **Postnummer-bbox er ubrugelig for kyst-postnumre** — den inkluderer havterritorium
  (Fanø 6720 → bbox 2° bred, center ude i Nordsøen). Derfor bruger `/api/postnummer`
  **adressernes faktiske x/y-udstrækning**, ikke DAWA's bbox/visueltcenter.

### BBR — Datafordeler (`services.datafordeler.dk/BBR/BBRPublic/1/rest/bygning`)
- Det gamle `bbrlight`-API er **nedlagt**; brug Datafordeler med username+password.
- Query-parameter `husnummer` = DAWA's `adgangsadresseid`. Format `JSON`.
- Feltnavne: `byg021BygningensAnvendelse` (anvendelseskode), `byg039BygningensSamledeBoligAreal`
  (samlet boligareal inkl. tag — **brug denne**), `byg041BebyggetAreal` (fodaftryk),
  `byg038SamletBygningsareal` (fodaftryk — **IKKE** samlet boligareal), `byg026Opførelsesår`,
  `byg033Tagdækningsmateriale`, `id_lokalId` (BBR-bygningens UUID).
- Anvendelseskoder: 110/120/121/122 = helårshus; 510/520 = fritidshus/sommerhus; ellers "andet".
- `primary_building()` vælger den beboelsesbygning med størst `byg038SamletBygningsareal`.

### FBB — fredede bygninger (`www.kulturarv.dk/geoserver/fbb/wfs`)
- Offentligt WFS, ingen auth. Layer `fbb:view_bygning_fredede`, `outputFormat=application/json`.
- **BBOX-rækkefølge er lat,lon** i EPSG:4326: `minLat,minLon,maxLat,maxLon,urn:ogc:def:crs:EPSG::4326`
  (lon,lat gav 0 resultater). `properties.ois_id` matcher BBR `id_lokalId`.
- Bevaringsværdi findes ikke for Fanø (intet kommuneatlas) — kun `fredet` (boolean) er meningsfuldt.

### Afstand til vand — OSM Overpass (`overpass-api.de/api/interpreter`)
- **Kræver `User-Agent`-header**, ellers HTTP 406.
- Query henter bredt: `natural=coastline`, `natural=water`, `waterway~"^(river|canal|stream)$"`,
  og `relation[natural=water]` — alle med `out geom;`. Relationer har `members[].geometry`
  (iterér dem som polylinjer); ways har top-level `geometry`.
- Afstand = nærmeste punkt-til-segment over alle vand-polylinjer, projiceret til lokale meter
  (equirektangulær, cos(lat0)). `WaterIndex` er et **spatial grid** (300 m celler,
  ekspanderende ring-søgning) så det skalerer — testet med 13.4k adresser i Silkeborg.
- bbox-margin 0.06° omkring polygonen; adresser længere væk end det får `vand_afstand = null`.

### Boligsiden.dk (`api/boligsiden.py`)
- Beskyttet af Cloudflare → server-side requests blokeres. Løst med **`curl_cffi`**
  (`impersonate="chrome"`, efterligner Chrome TLS-fingerprint).
- **Til salg** = sidens `<title>` starter med "Til salg:". **Pris** fra JSON-LD
  `schema.org/Product` → `offers.price`.
- **URL-slug:** `vejnavn-husnr-postnr-postnrnavn`, æ→ae ø→oe å→aa, mellemrum→bindestreg, lowercase.
  I frontenden: brug `data-`-attributter (IKKE `encodeURIComponent` i onclick → dobbelt-encoding).

### Boligsiden API — salgshistorik + offentlig vurdering (`api/boligsiden.py`)
- **`api.boligsiden.dk` er tilgængeligt med almindelig `httpx`** (User-Agent-header, ingen
  Cloudflare/`curl_cffi` nødvendig) og tåler bursts — crawles server-side med semaphore.
- **`GET /addresses/{id}` hvor `{id}` = DAWA's enhedsadresse-`id`** (matcher Boligsidens
  `addressID`; `adgangsadresseid` giver 404). Returnerer `registrations[]`, `latestValuation`
  (offentlig vurdering), `livingArea`.
- Hver registrering: `amount`, `area`, `date`, `perAreaPrice`, **`type`** = `normal` (fri handel),
  `family` (familiehandel — **ekskluderes**, kunstigt lav), `other` (auktion/andet, ofte uden areal).
- `search/cases`-bulk-API'et er **ubrugeligt** til dette (mangler handelstype og salgsdato).

### Markedspris-estimat (`api/prisindeks.py`)
- Model: kun `normal`-handler med areal+dato, nyere end 25 år. Log-lineær regression af
  ln(kr/m²) mod tid → årlig vækst (klampet til [-3%, +15%]). Områdets kr/m² i dag = **median**
  af de til-i-dag-fremskrevne kr/m². Estimat = vægtet snit af (områdets kr/m² × boligens m²)
  og (boligens egen sidste frie handel, fremskrevet); egen-handel vejer mest når den er ny.
- **Segmenteret på boligtype (VIGTIGT):** helårshuse og fritidshuse har vidt forskelligt
  prisniveau OG udvikling (Sønderho: fritidshuse ~22.400 kr/m² vs. helårshuse ~12.600 kr/m²),
  så der bygges en separat model pr. BBR-type. Frontenden sender `type` med hver adresse;
  typer med < 8 frie handler falder tilbage til den samlede model (`indeks_basis` viser hvilken).
- Frontenden: knap "Beregn markedspriser" crawler alle adresser i resultatet (up front, cachet),
  viser ét indeks pr. type + kolonner "Markedsestimat"/"Off. vurdering" + nedbrydning i popup.

## Frontend-adfærd (static/app.js)

- Default-polygon dækker Sønderho ved load og søger automatisk.
- **Filtre:** boligtype, min/maks samlet boligareal, min/maks bebygget areal, byggeår fra/til,
  min/maks afstand til vand, tagdækningsmateriale (dropdown udfyldes dynamisk fra resultater),
  til salg (skjult indtil auto-tjek kører), fredning. Alle kører via `applyFilters()`.
- **Flyt polygon til postnummer:** felt + "Placer"-knap → `placePostnr()` henter
  `/api/postnummer/{nr}`, laver et rektangel af bbox'en, zoomer, rydder gamle resultater.
- **Auto-tjek af Boligsiden:** `autocheckBoligsiden()` kører fra `applyFilters()` når den
  **filtrerede** liste er ≤ **250** adresser; kun ikke-tjekkede (`til_salg === undefined`);
  5 samtidige; cacher på resultat-objektet så re-filtrering ikke gentjekker. Til-salg-adresser
  får grøn ring på kortet + pris i tabel/popup.
- `TAG_LABELS`, `TYPE_COLORS`, `TYPE_LABELS` mapper koder → danske labels/farver.

## Faldgruber / vaner

- **In-memory cache:** når du tilføjer/ændrer et felt i berigelsen, ryd cachen ved at
  **genstarte serveren** — ellers serveres gamle resultater uden det nye felt.
- **Browser-cache på statiske filer:** løst permanent — `/`, `app.js`, `style.css` serveres
  med `Cache-Control: no-cache, must-revalidate` (`NoCacheStaticFiles` i `main.py`), så browseren
  altid revaliderer. (Tidligere krævede ændringer et hard reload.)
- **`.env` og `docker-compose.yml`** er git-ignored. Committ dem aldrig.
- Alle eksterne kald pakkes "blødt" (fejl → tomt/None), så én kilde der er nede ikke
  vælter en søgning (se `safe_fetch_listed`, `safe_fetch_water`).
