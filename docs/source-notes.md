# Phase 0 — Recon & legal confirmation

**Datum recona:** 2026-08-05
**Izvor:** FINA — Očevidnik nekretnina i pokretnina, `ponip.fina.hr`

Sve tvrdnje u ovom dokumentu potkrijepljene su HTTP odgovorom ili brojanjem nad
stvarno preuzetom datotekom. Ništa nije pretpostavljeno.

---

## 1. Službeni CSV export — potvrđen

| Stavka | Nalaz |
|---|---|
| URL | `https://ponip.fina.hr/ocevidnik-web/preuzmi/csv` |
| HTTP status | `200 OK` |
| Content-Type | `text/csv;charset=UTF-8` |
| Content-Disposition | `attachment; filename="ponip_ocevidnik.csv"` |
| Veličina | **10 329 500 bajtova** (10,3 MB) |
| Vrijeme preuzimanja | 0,46 s |
| Autentikacija | **nema** — običan GET, bez kolačića, bez tokena |
| CAPTCHA | **nema** na ovoj ruti |
| Kodiranje | UTF-8 **s BOM-om** (`EF BB BF`) |
| Delimiter | `;` (točka-zarez), sva polja pod dvostrukim navodnicima |
| Redaka | **11 091** (bez zaglavlja) |
| Stupaca | **26** |
| Server | `IBM_HTTP_Server` |

**Zaključak:** CSV export je primarni i jedini potreban put do podataka.
Interaktivna tražilica (s reCAPTCHA-om i limitom od 100 rezultata) **nije
potrebna** i ne dira se.

### Ažurnost
Stupac `Stanje na dan` ima **jednu jedinu vrijednost u svih 11 091 redaka:
`2026-08-05`** — dan preuzimanja. Export je dakle **dnevni snimak (snapshot)
cijelog očevidnika**, a ne inkrementalni feed. Datumi završetka nadmetanja idu
od `2016-02-17` do `2026-10-28`, što potvrđuje da snimak sadrži i **povijesne
(završene) predmete**, ne samo aktivne.

> **Ispravak pretpostavke iz specifikacije.** Specifikacija navodi „~1.000
> aktivnih stavki". To je točno samo za *trenutno otvorena* nadmetanja. Puni
> export sadrži 11 091 stavku. Izvedeni status (v. §5) daje: 136 u tijeku,
> 551 najavljeno, 8 627 završeno, 1 777 bez prozora nadmetanja.

---

## 2. Pravni status i dozvola za ponovnu uporabu — potvrđeno

Skup podataka je službeno objavljen na **data.gov.hr** (Portal otvorenih
podataka Republike Hrvatske):

- Dataset: `https://data.gov.hr/ckan/hr/dataset/ocevidnik-nekretnina-i-pokretnina`
- **Nakladnik:** Financijska agencija (FINA)
- **Licenca:** **„Otvorena dozvola (OD)"** — `http://data.gov.hr/otvorena-dozvola`
- **Klasifikacija:** javni podaci; označeni kao **skup podataka visoke
  vrijednosti (high-value dataset)** prema EU standardu
- Zadnja izmjena zapisa: 15. travnja 2026.

FINA na svojim stranicama potvrđuje javnost i besplatnost:

> „Aplikaciji može pristupiti svaki korisnik koji želi dobiti informaciju."
> — fina.hr, Očevidnik nekretnina i pokretnina

> „svim zainteresiranim osobama bez naknade"
> — fina.hr, FAQ Očevidnik

> „Za pristup aplikaciji Očevidnik nije potreban digitalni certifikat."
> — fina.hr, FAQ Očevidnik

Prag vrijednosti potvrđen na izvoru: „ako je njihova procijenjena vrijednost
veća od **6.630,00 EUR**".

**Zaključak: ponovna uporaba je dopuštena.** Ništa u uvjetima ne ograničava
ponovnu uporabu ni komercijalnu primjenu. Uvjet je navođenje izvora, što ovaj
projekt radi na svakoj generiranoj stranici.

### robots.txt
`https://ponip.fina.hr/robots.txt` → **HTTP 404**. Nema deklariranih
ograničenja za automatizirani pristup. Unatoč tome, projekt radi jedan
zahtjev dnevno na jednu rutu.

---

## 3. ⚠ KRITIČAN NALAZ: osobni podaci JESU prisutni u exportu

Specifikacija je pretpostavljala da očevidnik ne sadrži osobne podatke
(„Confirm no personal/debtor-identifying data is present in the export").

**Ta pretpostavka je netočna.** Skeniranje svih 26 stupaca × 11 091 redak
daje sljedeće pogotke:

| Uzorak | Pogodaka (ćelija) | Najgori stupci |
|---|---|---|
| **OIB** (11 znamenki) | **222** | `Opis` (79), `Napomena uz uvjete prodaje` (68), `Napomena uz detalje` (54) |
| **IBAN (HR…)** | **728** | `Ostali uvjeti za jamčevinu` (292), `Napomena uz uvjete prodaje` (152) |
| **E-mail adrese** | **1 136** | `Razgledavanje` (1 074) |
| **Telefoni** (09x / +385) | **2 505** | `Razgledavanje` (2 480) |

Oblik zapisa koji se stvarno pojavljuje u datoteci. **Vrijednosti su ovdje
maskirane.** Nalaz dokazuje *struktura* zapisa, a ne same znamenke — a ovaj
dokument ne smije biti mjesto na kojem osobni podaci ipak procure:

- `Založni vjerovnik - [Ime Prezime], OIB: [11 znamenki], iz [Grad], [Ulica i kbr.]`
  → **ime + OIB + kućna adresa fizičke osobe**
- `stečajnim upraviteljem: [Ime Prezime], [11 znamenki], e-mail: [ime.prezime]@gmail.com`
  → **ime + OIB + privatni e-mail na javnom servisu**
- `stečajnim upraviteljem [Ime Prezime], OIB: [11 znamenki], [Ulica i kbr.], [Grad]`
  → **ime + OIB + kućna adresa**

Tko želi provjeriti nalaz, reproducira ga nad svježim izvozom:

```bash
python -c "import csv,io,sanitise as S; \
rows=list(csv.DictReader(io.StringIO(open('cache/raw/ponip_ocevidnik.csv','rb') \
.read().decode('utf-8-sig')),delimiter=';')); \
print(sum(len(S.scan(v or '')) for r in rows for v in r.values()))"
```

Dodatno, stupac `Nadležno tijelo` — koji je specifikacija opisala kao
„institution, not a person" — sadrži **46 različitih javnih bilježnika
imenom i prezimenom** (npr. `Javni bilježnik Strinavić Domagoj`), na
**120 redaka**.

### Posljedica za arhitekturu

Zahtjev „nula osobnih podataka" **ne zadovoljava se sam od sebe** — mora se
aktivno provoditi. Zato projekt uvodi sloj kojeg specifikacija nije
predviđala: **`sanitise.py`**, koji se izvršava *prije* upisa u bazu.

Pravilo je **whitelist, ne blacklist**: u bazu i na stranice ulaze samo
izrijekom dopuštena polja, a i ona prolaze kroz redakciju.

| Izvorni stupac | Postupak | Razlog |
|---|---|---|
| `Opis` | **redigira se**, pa objavljuje | jedini izvor lokacije i površine — nužan |
| `Razgledavanje` | **odbacuje se**; zadržava se samo izvedeni obrazac termina | 1 074 e-mailova + 2 480 telefona osobnih kontakata |
| `Napomena uz uvjete prodaje` | **odbacuje se u cijelosti** | 68 OIB-a, 152 IBAN-a; nije nužna za proizvod |
| `Napomena uz detalje predmeta prodaje` | **odbacuje se u cijelosti** | 54 OIB-a, 68 IBAN-a |
| `Ostali uvjeti prodaje` | **odbacuje se u cijelosti** | OIB-i, IBAN-i, kontakti |
| `Ostali uvjeti za jamčevinu` | **odbacuje se u cijelosti** | 292 IBAN-a |
| `Nadležno tijelo` | ime bilježnika **zamjenjuje se** ulogom „Javni bilježnik" | fizička osoba imenom; izvor uz bilježnika ne navodi grad, pa se grad ne dodaje |

`validate.py` provjeru broj 4 tretira kao **tvrdi prekid (hard fail)**: ako se
bilo koji uzorak osobnog podatka pojavi u bazi ili u generiranom HTML-u,
proces izlazi s ne-nultim kodom.

---

## 4. Struktura CSV-a — svih 26 stupaca

Popunjenost mjerena nad svih 11 091 redaka.

| # | Stupac | Popunjeno | Uniq | Objavljuje se? |
|---|---|---|---|---|
| 0 | `Nadležno tijelo` | 100,0 % | 145 | da (redigirano) |
| 1 | `Poslovni broj spisa` | 100,0 % | 4 636 | da |
| 2 | `Opis` | 100,0 % | 10 929 | da (redigirano) |
| 3 | `Vrsta predmeta prodaje` | 100,0 % | 4 | da |
| 4 | `Složenost PP / opseg imovine` | 100,0 % | 5 | da |
| 5 | `Utvrđena vrijednost` | 100,0 % | 7 967 | da |
| 6 | `Napomena uz detalje predmeta prodaje` | 61,7 % | 2 014 | **ne** |
| 7 | `Način prodaje` | 100,0 % | 5 | da |
| 8 | `ID nadmetanja` | 84,0 % | 9 304 | da |
| 9 | `Oznaka EJD` | 87,2 % | 4 | da |
| 10 | `Datum odluke o prodaji` | 100,0 % | 1 925 | da |
| 11 | `Datum i vrijeme početka` | 95,1 % | 2 316 | da |
| 12 | `Datum i vrijeme početka nadmetanja` | 84,0 % | 3 594 | da |
| 13 | `Datum i vrijeme završetka nadmetanja` | 84,0 % | 3 596 | da |
| 14 | `Mogućnost produljenja nadmetanja` | 84,0 % | 2 | da |
| 15 | `Ostali uvjeti prodaje` | 27,1 % | 772 | **ne** |
| 16 | `Minimalna zakonska cijena…` | 100,0 % | 9 019 | da |
| 17 | `Početna cijena za nadmetanje` | 87,2 % | 7 752 | da |
| 18 | `Iznos dražbenog koraka` | 84,0 % | 20 | da |
| 19 | `Rok u kojem je kupac dužan položiti kupovninu` | 99,3 % | 1 598 | **ne** (47 IBAN-a) |
| 20 | `Iznos jamčevine` | 98,4 % | 7 708 | da |
| 21 | `Ostali uvjeti za jamčevinu` | 6,0 % | 359 | **ne** |
| 22 | `Razgledavanje` | 96,2 % | 4 980 | **ne** (samo izvedeni termin) |
| 23 | `Napomena uz uvjete prodaje` | 36,0 % | 1 496 | **ne** |
| 24 | `Stanje na dan` | 100,0 % | 1 | da (kao datum snimka) |
| 25 | `Datum valute jamčevine` | 84,0 % | 1 005 | da |

### Vrijednosti šifrarnika

`Vrsta predmeta prodaje`: nekretnina 10 282 · pokretnina 689 · imovina 62 · pravo 58

`Način prodaje`: Sudska e-Dražba 9 672 · Prikupljanje pisanih ponuda 938 ·
Neposredna pogodba 220 · Usmena javna dražba 205 · „Nadležno tijelo nije
dostavilo podatke" 56

`Oznaka EJD` (redni broj dražbe): Prva 5 131 · Druga 3 841 · Treća 461 ·
Četvrta 239 · prazno 1 419

`Složenost`: Pojedinačni 6 884 · Skupni 4 088 · Pojedinačan *(sic — varijanta
pisanja, normalizira se)* 57 · Dio imovine 45 · Cjelokupna imovina 17

---

## 5. Polja koja specifikacija traži, a CSV ih NEMA

Ovo je drugi bitan nalaz. Pet polja iz specifikacije ne postoji u exportu i
mora se izvesti — ili se pošteno prijaviti kao nedostupno.

| Traženo polje | Status | Kako se rješava |
|---|---|---|
| `county` / `city` / `settlement` | **ne postoji** — nijedan stupac ne sadrži županiju, grad ni naselje | izvodi se: (a) naselje/k.o. iz teksta `Opis` (pouzdanost visoka, 4 547), (b) županija iz **općinskog** suda (srednja, 4 363); trgovački sud se NE koristi; neriješeno **2 179** ostaje `Nepoznato` i prijavljuje se poimence |
| `area_m2` | **ne postoji** kao stupac | parsira se iz `Opis`, uz pretvorbu `čhv` (×3,5966) i `ha` (×10 000); popunjeno **9 834 / 11 089 (88,7 %)** |
| `status` | **ne postoji** | izvodi se iz datuma nadmetanja vs. datum snimka |
| `current_bid_eur` | **nije u exportu** | vidljivo samo u živoj aplikaciji tijekom nadmetanja; **prijavljuje se kao nedostupno**, ne izmišlja se |
| `source_url` (dubinski link po stavci) | **ne postoji** | testirane 4 sheme URL-a (`/predmet/{id}`, `/nadmetanje/{id}`, `/pretrazivanje/detalji/{id}`, `/pregled/{id}`) → **sve HTTP 404**. Aplikacija je stateful (JSESSIONID), nema stabilnih dubinskih linkova. Link vodi na tražilicu + navodi se `ID nadmetanja` za ručnu provjeru |

`opening_price_eur` postoji (`Početna cijena za nadmetanje`), ali je popunjen
u 87,2 % redaka — popust se računa samo gdje postoje obje brojke.

---

## 5a. Novčani stupci nisu dosljedno numerički

Otkriveno tek pri validaciji, pa se ovdje bilježi kao svojstvo izvora.

Četiri od pet novčanih stupaca (`Utvrđena vrijednost`, `Početna cijena`,
`Iznos jamčevine`, `Iznos dražbenog koraka`) uredni su: `39816.84`, točka kao
decimalni separator.

**`Minimalna zakonska cijena` nije.** U istom stupcu supostoje najmanje četiri
oblika (mjereno nad svih 11 091 redaka):

| Oblik | Pojava | Primjer |
|---|---|---|
| točka = decimalna | 50 670 (svi stupci) | `39816.84` |
| hrvatski zapis + dvije valute | **1 103** | `59.725,26 EUR (449.999,97 HRK)` |
| zarez = decimalni | **164** | `30,31 EUR (228,37 HRK)` |
| više točaka kao tisućice | 12 | `1.102.500,03` |
| proza, uopće nije iznos | — | `3/4, 1/2, 1/4 procijenjene vrijednosti…` |

Posljedica je bila ozbiljna: naivno brisanje zareza pretvara `32.805,00` u
**32,805 €** umjesto **32 805,00 €**. Provjera je pokazala **122 vrijednosti
pogrešne za tri reda veličine** i **1 112 tiho izgubljenih** (parser je vraćao
`None`).

Pravilo koje sada vrijedi: ako se spominje EUR, uzima se iznos **ispred** riječi
„EUR" (nikad iznos u kunama iz zagrade); decimalni separator je onaj koji se
pojavljuje **posljednji**; ono što nakon čišćenja nije čist broj vraća se kao
`None`, nikad kao nula.

---

## 6. Izvedeni signali — provjera izvodljivosti

**Popust vs. procijenjena vrijednost.** 9 672 / 11 091 redaka ima i utvrđenu
vrijednost i početnu cijenu > 0. Samo **1 redak** ima početnu cijenu *iznad*
procjene, što potvrđuje da je smjer računa ispravan.

Uočen je i izražen podatkovni izuzetak: `ST-13/2016` ima procjenu
523 856,92 € i početnu cijenu **0,13 €** (popust 100,0 %). To je pogreška u
izvoru, ne prilika. `validate.py` takve slučajeve označava i pipeline ih
izdvaja umjesto da ih prikaže kao „najveći popust".

**Ponovljene dražbe.** 4 636 različitih poslovnih brojeva spisa; **1 558 ih
ima više od jednog retka**. Najviše redaka na jednom spisu: 150
(`ST-6578/2016` — stečaj s mnogo zasebnih predmeta prodaje).

> Bitna nijansa: više redaka na istom `Poslovni broj spisa` **ne znači nužno
> ponovljenu dražbu** — veliki stečaj ima mnogo *različitih* nekretnina pod
> istim spisom. Zato se ponovljena dražba detektira po kombinaciji spisa,
> potpisa predmeta i **rastuće `Oznaka EJD`** (Prva → Druga → Treća →
> Četvrta), a ne po samom broju spisa. Ordinal EJD je izravan signal koji
> izvor sam daje.

---

## 7. Poštivanje izvora

- Jedan GET dnevno na jednu rutu (`/preuzmi/csv`), 10,3 MB.
- Opisni User-Agent: `LicitaBot/0.1 (+https://licita.hr; kontakt: support@nexistudio.dev)`
- Lokalni cache; ponovno preuzimanje se ne radi bez potrebe.
- **Bez rješavanja CAPTCHA-e, bez zaobilaženja zaštita, bez pristupa
  interaktivnoj tražilici.**
- Na blokadu (403/429) pipeline staje i prijavljuje, ne pokušava ponovno
  agresivno.

---

## 8. Sažetak Phase 0

| Pitanje iz specifikacije | Odgovor |
|---|---|
| Postoji li službeni CSV export? | **Da** — potvrđen, 10 329 500 B, HTTP 200, bez autentikacije |
| Je li ponovna uporaba dopuštena? | **Da** — Otvorena dozvola (OD), data.gov.hr, HVD klasifikacija |
| Pokriva li CSV sve potrebno? | **Ne u potpunosti** — nedostaju lokacija, površina, status, trenutna ponuda, dubinski link |
| Ima li osobnih podataka? | **DA — i to mnogo.** 222 OIB-a, 728 IBAN-a, 1 136 e-mailova, 2 505 telefona. Zahtijeva aktivnu redakciju |
| Treba li dirati interaktivnu tražilicu? | **Ne** |

Nijedan nalaz ne zaustavlja projekt. Nalaz o osobnim podacima **mijenja
arhitekturu** — dodaje obavezni sloj redakcije prije baze.
