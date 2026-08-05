# Pogon: koliko često pokretati i koliko podatak smije biti star

Sve brojke ovdje izmjerene su nad stvarnim izvozom od 2026-08-05
(11 091 redak), ne procijenjene.

---

## 1. Izvor je DNEVNI snimak — to određuje sve ostalo

Stupac `Stanje na dan` ima jednu jedinu vrijednost u svih 11 091 redaka.
Dva dohvata unutar istog dana vraćaju **bajt-identičnu datoteku**; provjereno
usporedbom sha256 (`06013bb9c325…` oba puta) i nulom zabilježenih promjena.

**Posljedica: dohvaćati izvor češće od jednom dnevno ne donosi ništa,** a
opterećuje FINA-u bez razloga.

| Posao | Učestalost | Zašto |
|---|---|---|
| `python run.py` | **jednom dnevno**, ujutro | prati ritam izvora |
| `python run.py --rebuild-only` | svakih 2–4 h (neobavezno) | osvježi STATUS bez dohvata izvora |
| `python validate.py` | **uz svako pokretanje** | provjera br. 4 (osobni podaci) je tvrdi prekid |

Objava se veže uz izlazni kod: `validate.py` koji ne vrati 0 znači da se
stranice ne objavljuju.

### Zašto `--rebuild-only` uopće postoji

Status (`najavljeno` → `u tijeku` → `završeno`) **ne dolazi iz izvora** — računa
se iz `auction_start` / `auction_end` u odnosu na trenutak generiranja. Zato
ponovno generiranje nekoliko sati kasnije daje točniji status i bez ijednog
novog podatka, i bez ijednog zahtjeva prema izvoru.

```bash
python run.py                 # jednom dnevno: dohvat + obrada + stranice
python run.py --rebuild-only  # kroz dan: samo status + stranice, bez dohvata
```

---

## 2. Koliko podatak smije biti star

**Tvrda granica: 48 h** (`LICITA_MAX_SNAPSHOT_AGE_H`, zadano 48).
Preko toga `run.py` izlazi s kodom **3** i **ne generira stranice**.

Granica nije proizvoljna. Iz istog izvoza:

| Mjerenje | Vrijednost |
|---|---|
| nadmetanja koja tek završavaju | 687 |
| prosječno završetaka po danu | **19** |
| najgori pojedinačni dan (13.8.2026.) | **76** |
| stavki koje postanu netočne pri starosti 48 h | 15 |
| stavki koje postanu netočne pri starosti 72 h | 28 |

Zastarjela stranica ne izgleda zastarjelo — izgleda **pogrešno**: prikazuje
zatvorenu dražbu kao otvorenu. Za stranicu koja se predstavlja kao pregled
aktualnih dražbi to je najskuplja moguća greška.

Zato:

- svaka stranica u podnožju piše `Podaci su preuzeti {datum}` — to ostaje;
- preko 48 h radije **nema objave** nego netočni rokovi;
- `--allow-stale` postoji, ali ga treba upisati svjesno.

```bash
python run.py --rebuild-only                 # stane ako je snimak prestar
python run.py --rebuild-only --allow-stale   # svjesno dopusti zastarjelo
```

**Napomena o satu:** izvoz se ne osvježava u ponoć. Provjereno 6.8.2026. oko
01:00 — izvor je još vraćao snimak od 5.8. Cron zato treba postaviti kasnije
ujutro, a ne odmah iza ponoći; točan sat prevrtanja tek treba izmjeriti.

---

## 3. Traženje onoga što ljudi doista traže

Redoslijed je namjeran: prvo ono što podaci već dokazuju, pa tek onda nagađanje.

**a) Količina je pokazatelj potražnje — i besplatna je.**
Grad Zagreb (150 aktivnih), Osječko-baranjska (118), Istarska (115) zaslužuju
ručno pisan uvod na stranici županije. Županije s 16 predmeta ne zaslužuju.

**b) Oblici upita koje vrijedi držati:**
`kuća na dražbi [grad]`, `stan ovrha [grad]`, `zemljište dražba [županija]`,
`kako kupiti nekretninu na dražbi`, `e-dražba jamčevina`.
Prva tri već pokrivaju stranice po županiji, gradu i vrsti; zadnja dva pokriva
vodič `/kako-sudjelovati/`, koji je zasad jedini pravi urednički sadržaj.

**c) Provjeri stvarnost prije nego što se piše još sadržaja.**
Google Search Console (kad domena proradi) i Google Trends za `ovrha`,
`dražba`, `e-dražba` — zbog sezonalnosti. Ne izmišljati brojke o pretragama;
zasad ih nemamo nijednu.

**d) Najveći SEO dobitak trenutno nije SEO.**
Lokacija nije utvrđena za **44,8 % aktivnih predmeta**. Svaki predmet koji
dobije županiju dobiva i stranicu koja može odgovoriti na lokalni upit s
visokom namjerom. Rješavanje k.o. → županija mapiranja *jest* SEO posao.

---

## 4. Otvoreno

- **k.o. → županija:** 879 neriješenih predmeta ima naziv katastarske općine
  koji nije naziv naselja (324 različita naziva). Potreban je službeni registar
  s dopuštenom ponovnom uporabom. DGU objavljuje RPJ pod Otvorenom dozvolom,
  ali kao WFS s geometrijom i bez atributa županije; jedini gotov CSV koji je
  nađen (Grad Zagreb) ima `license_id: ""` i `isopen: false` pa **nije korišten**.
- **Provjera br. 12** (promjena cijene između dva RAZLIČITA dnevna snimka)
  ostaje WARN dok se pipeline ne pokrene dva dana zaredom.
