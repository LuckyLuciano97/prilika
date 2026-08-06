"""Geografija Hrvatske — županije, gradovi, sudovi.

Izdvojeno iz `normalise.py` jer je ovo referentna tablica, a ne logika.

Izvor podataka: teritorijalni ustroj RH (21 županija uključujući Grad Zagreb)
i mreža sudova prema Zakonu o područjima i sjedištima sudova.

Popunjeno ručno i provjereno protiv 145 nadležnih tijela koja se stvarno
pojavljuju u Očevidniku (v. docs/source-notes.md).
"""
from __future__ import annotations

# --- 21 županija ----------------------------------------------------------
COUNTIES = [
    "Grad Zagreb",
    "Zagrebačka županija",
    "Krapinsko-zagorska županija",
    "Sisačko-moslavačka županija",
    "Karlovačka županija",
    "Varaždinska županija",
    "Koprivničko-križevačka županija",
    "Bjelovarsko-bilogorska županija",
    "Primorsko-goranska županija",
    "Ličko-senjska županija",
    "Virovitičko-podravska županija",
    "Požeško-slavonska županija",
    "Brodsko-posavska županija",
    "Zadarska županija",
    "Osječko-baranjska županija",
    "Šibensko-kninska županija",
    "Vukovarsko-srijemska županija",
    "Splitsko-dalmatinska županija",
    "Istarska županija",
    "Dubrovačko-neretvanska županija",
    "Međimurska županija",
]

# --- Naselje/grad -> županija ---------------------------------------------
# Pokriva svih 127 gradova RH plus općine koje se pojavljuju u Očevidniku.
TOWN_COUNTY: dict[str, str] = {}


def _add(county: str, *towns: str) -> None:
    for t in towns:
        TOWN_COUNTY[t] = county


_add("Grad Zagreb", "Zagreb", "Novi Zagreb", "Sesvete", "Sveta Klara", "Stenjevec")
_add(
    "Zagrebačka županija",
    "Velika Gorica", "Samobor", "Zaprešić", "Dugo Selo", "Jastrebarsko",
    "Ivanić-Grad", "Ivanić Grad", "Sveti Ivan Zelina", "Vrbovec", "Sveta Nedelja",
    "Sveta Nedjelja", "Zelina", "Križ", "Rugvica", "Brdovec", "Stupnik",
    "Bistra", "Jakovlje", "Luka", "Klinča Sela", "Pisarovina", "Pokupsko",
    "Kravarsko", "Orle", "Bedenica", "Dubrava", "Farkaševac", "Gradec",
    "Preseka", "Rakovec", "Brckovljani", "Marija Gorica", "Dubravica",
    "Pušća", "Bistra", "Krašić", "Žumberak", "Kloštar Ivanić",
)
_add(
    "Krapinsko-zagorska županija",
    "Krapina", "Zabok", "Zlatar", "Klanjec", "Donja Stubica", "Pregrada",
    "Oroslavje", "Zlatar Bistrica", "Marija Bistrica", "Stubičke Toplice",
    "Krapinske Toplice", "Sveti Križ Začretje", "Bedekovčina", "Konjščina",
    "Zagorska Sela", "Desinić", "Đurmanec", "Hum na Sutli", "Jesenje",
    "Kumrovec", "Lobor", "Mače", "Mihovljan", "Novi Golubovec", "Petrovsko",
    "Radoboj", "Tuhelj", "Veliko Trgovišće", "Budinšćina", "Gornja Stubica",
)
_add(
    "Sisačko-moslavačka županija",
    "Sisak", "Kutina", "Petrinja", "Glina", "Novska", "Hrvatska Kostajnica",
    "Popovača", "Sunja", "Topusko", "Dvor", "Gvozd", "Lekenik", "Martinska Ves",
    "Majur", "Donji Kukuruzari", "Hrvatska Dubica", "Jasenovac", "Lipovljani",
    "Velika Ludina", "Gornja Ploča",
)
_add(
    "Karlovačka županija",
    "Karlovac", "Ogulin", "Duga Resa", "Ozalj", "Slunj", "Vojnić", "Josipdol",
    "Plaški", "Rakovica", "Cetingrad", "Krnjak", "Barilović", "Bosiljevo",
    "Draganić", "Generalski Stol", "Kamanje", "Lasinja", "Netretić", "Ribnik",
    "Saborsko", "Tounj", "Žakanje",
)
_add(
    "Varaždinska županija",
    "Varaždin", "Ivanec", "Ludbreg", "Novi Marof", "Varaždinske Toplice",
    "Lepoglava", "Bednja", "Beretinec", "Breznica", "Cestica", "Donja Voća",
    "Gornji Kneginec", "Jalžabet", "Klenovnik", "Ljubešćica", "Mali Bukovec",
    "Maruševec", "Petrijanec", "Sračinec", "Sveti Đurđ", "Sveti Ilija",
    "Trnovec Bartolovečki", "Vidovec", "Vinica", "Visoko",
)
_add(
    "Koprivničko-križevačka županija",
    "Koprivnica", "Križevci", "Đurđevac", "Drnje", "Gola", "Hlebine",
    "Kalinovac", "Kloštar Podravski", "Koprivnički Bregi", "Koprivnički Ivanec",
    "Legrad", "Molve", "Novigrad Podravski", "Novo Virje", "Peteranec",
    "Podravske Sesvete", "Rasinja", "Sokolovac", "Virje", "Ferdinandovac",
    "Gornja Rijeka", "Kalnik", "Sveti Ivan Žabno", "Sveti Petar Orehovec",
)
_add(
    "Bjelovarsko-bilogorska županija",
    "Bjelovar", "Daruvar", "Garešnica", "Čazma", "Grubišno Polje",
    "Berek", "Dežanovac", "Đulovac", "Hercegovac", "Ivanska", "Kapela",
    "Končanica", "Nova Rača", "Rovišće", "Severin", "Sirač", "Šandrovac",
    "Velika Pisanica", "Velika Trnovitica", "Veliki Grđevac", "Veliko Trojstvo",
    "Zrinski Topolovac", "Štefanje",
)
_add(
    "Primorsko-goranska županija",
    "Rijeka", "Opatija", "Crikvenica", "Krk", "Rab", "Mali Lošinj", "Delnice",
    "Bakar", "Cres", "Čabar", "Kastav", "Kraljevica", "Novi Vinodolski",
    "Vrbovsko", "Kostrena", "Viškovo", "Matulji", "Lovran", "Mošćenička Draga",
    "Omišalj", "Malinska", "Punat", "Baška", "Vrbnik", "Dobrinj", "Fužine",
    "Lokve", "Mrkopalj", "Ravna Gora", "Skrad", "Brod Moravice", "Čavle",
    "Jelenje", "Klana", "Vinodolska općina", "Lopar", "Nerezine", "Rijeka - Sušak",
)
_add(
    "Ličko-senjska županija",
    "Gospić", "Otočac", "Senj", "Novalja", "Karlobag", "Brinje", "Donji Lapac",
    "Lovinac", "Perušić", "Plitvička Jezera", "Udbina", "Vrhovine", "Korenica",
)
_add(
    "Virovitičko-podravska županija",
    "Virovitica", "Slatina", "Orahovica", "Pitomača", "Suhopolje", "Špišić Bukovica",
    "Gradina", "Lukač", "Nova Bukovica", "Sopje", "Voćin", "Crnac", "Čačinci",
    "Čađavica", "Mikleuš", "Zdenci", "Podravska Moslavina",
)
_add(
    "Požeško-slavonska županija",
    "Požega", "Pakrac", "Lipik", "Pleternica", "Kutjevo", "Brestovac",
    "Čaglin", "Jakšić", "Kaptol", "Velika", "Trenkovo",
)
_add(
    "Brodsko-posavska županija",
    "Slavonski Brod", "Nova Gradiška", "Okučani", "Vrpolje", "Donji Andrijevci",
    "Garčin", "Gundinci", "Klakar", "Oprisavci", "Sibinj", "Slavonski Šamac",
    "Velika Kopanica", "Vrbje", "Bebrina", "Brodski Stupnik", "Bukovlje",
    "Cernik", "Davor", "Dragalić", "Gornji Bogićevci", "Nova Kapela",
    "Podcrkavlje", "Rešetari", "Stara Gradiška", "Staro Petrovo Selo",
)
_add(
    "Zadarska županija",
    "Zadar", "Biograd na Moru", "Benkovac", "Obrovac", "Pag", "Nin",
    "Gračac", "Preko", "Sali", "Starigrad", "Posedarje", "Sukošan", "Bibinje",
    "Galovac", "Jasenice", "Kali", "Kolan", "Kukljica", "Lišane Ostrovičke",
    "Novigrad", "Pakoštane", "Pašman", "Poličnik", "Polača", "Povljana",
    "Privlaka", "Ražanac", "Sveti Filip i Jakov", "Škabrnja", "Tkon", "Vir",
    "Vrsi", "Zemunik Donji", "Stankovci", "Turanj",
)
_add(
    "Osječko-baranjska županija",
    "Osijek", "Đakovo", "Našice", "Beli Manastir", "Valpovo", "Belišće",
    "Donji Miholjac", "Bizovac", "Antunovac", "Bilje", "Čeminac", "Darda",
    "Draž", "Erdut", "Ernestinovo", "Jagodnjak", "Kneževi Vinogradi",
    "Koška", "Levanjska Varoš", "Magadenovac", "Marijanci", "Petlovac",
    "Petrijevci", "Podgorač", "Popovac", "Punitovci", "Satnica Đakovačka",
    "Semeljci", "Strizivojna", "Šodolovci", "Trnava", "Viljevo", "Viškovci",
    "Vladislavci", "Vuka", "Drenje", "Feričanci", "Gorjani", "Đurđenovac",
    "Čepin", "Vladimirovac",
)
_add(
    "Šibensko-kninska županija",
    "Šibenik", "Knin", "Drniš", "Skradin", "Vodice", "Tisno", "Murter",
    "Primošten", "Rogoznica", "Pirovac", "Betina", "Jezera", "Tribunj",
    "Bilice", "Biskupija", "Civljane", "Ervenik", "Kijevo", "Kistanje",
    "Promina", "Ružić", "Unešić", "Šibenik - Brodarica",
)
_add(
    "Vukovarsko-srijemska županija",
    "Vukovar", "Vinkovci", "Županja", "Ilok", "Otok", "Ivankovo", "Nijemci",
    "Nuštar", "Andrijaševci", "Babina Greda", "Bogdanovci", "Borovo",
    "Bošnjaci", "Cerna", "Drenovci", "Gradište", "Gunja", "Jarmina",
    "Lovas", "Markušica", "Negoslavci", "Nova Bukovica", "Privlaka",
    "Stari Jankovci", "Stari Mikanovci", "Tompojevci", "Tordinci",
    "Tovarnik", "Trpinja", "Vođinci", "Vrbanja",
)
_add(
    "Splitsko-dalmatinska županija",
    "Split", "Makarska", "Sinj", "Trogir", "Solin", "Omiš", "Imotski",
    "Kaštela", "Supetar", "Hvar", "Stari Grad", "Vis", "Komiža", "Vrgorac",
    "Vrlika", "Bol", "Jelsa", "Postira", "Pučišća", "Selca", "Milna",
    "Sutivan", "Nerežišća", "Baška Voda", "Brela", "Gradac", "Podgora",
    "Tučepi", "Dugi Rat", "Dugopolje", "Klis", "Muć", "Podstrana", "Seget",
    "Marina", "Okrug", "Šolta", "Grohote", "Hrvace", "Otok", "Trilj",
    "Cista Provo", "Lovreć", "Podbablje", "Proložac", "Runovići", "Zmijavci",
    "Zagvozd", "Šestanovac", "Lećevica", "Prgomet", "Primorski Dolac",
    "Kaštel Sućurac", "Kaštel Stari", "Kaštel Novi", "Stobreč",
)
_add(
    "Istarska županija",
    "Pula", "Pola", "Pazin", "Poreč", "Parenzo", "Rovinj", "Rovigno",
    "Umag", "Umago", "Labin", "Buje", "Buie", "Buzet", "Novigrad", "Cittanova",
    "Vodnjan", "Dignano", "Medulin", "Fažana", "Ližnjan", "Marčana",
    "Barban", "Raša", "Sveta Nedelja", "Kršan", "Pićan", "Gračišće",
    "Cerovlje", "Karojba", "Motovun", "Oprtalj", "Grožnjan", "Brtonigla",
    "Tar-Vabriga", "Vrsar", "Funtana", "Kaštelir-Labinci", "Višnjan",
    "Vižinada", "Sveti Lovreč", "Bale", "Kanfanar", "Svetvinčenat",
    "Žminj", "Tinjan", "Sveti Petar u Šumi", "Lanišće", "Lupoglav",
    "Banjole", "Premantura", "Štinjan",
)
_add(
    "Dubrovačko-neretvanska županija",
    "Dubrovnik", "Metković", "Korčula", "Ploče", "Opuzen", "Blato", "Vela Luka",
    "Lastovo", "Mljet", "Ston", "Orebić", "Janjina", "Trpanj", "Konavle",
    "Cavtat", "Župa dubrovačka", "Dubrovačko primorje", "Slivno", "Zažablje",
    "Kula Norinska", "Pojezerje", "Smokvica", "Lumbarda",
)
_add(
    "Međimurska županija",
    "Čakovec", "Prelog", "Mursko Središće", "Nedelišće", "Štrigova",
    "Belica", "Dekanovec", "Domašinec", "Donja Dubrava", "Donji Kraljevec",
    "Donji Vidovec", "Goričan", "Gornji Mihaljevec", "Kotoriba", "Mala Subotica",
    "Orehovica", "Podturen", "Pribislavec", "Selnica", "Strahoninec",
    "Sveta Marija", "Sveti Juraj na Bregu", "Sveti Martin na Muri", "Šenkovec",
    "Vratišinec",
)

# Isto naselje, više zapisa. Bez ujednačavanja dva zapisa daju isti URL slug
# (npr. "Ivanić Grad" i "Ivanić-Grad" -> /ivanic-grad/) pa bi se stranice
# međusobno prepisivale. Talijanski nazivi istarskih gradova su službeni, ali
# se za URL i naslov koristi jedan kanonski oblik.
TOWN_CANONICAL = {
    "Ivanić Grad": "Ivanić-Grad",
    "Pola": "Pula",
    "Parenzo": "Poreč",
    "Rovigno": "Rovinj",
    "Buie": "Buje",
    "Umago": "Umag",
    "Cittanova": "Novigrad",
    "Dignano": "Vodnjan",
    "Sveta Nedjelja": "Sveta Nedelja",
    "Novi Zagreb": "Zagreb",
    "Sesvete": "Zagreb",
}

# Imena koja postoje u više županija — bez dodatnog konteksta nesigurna.
AMBIGUOUS_TOWNS = {
    "Novigrad",       # Istarska i Zadarska
    "Otok",           # Vukovarsko-srijemska i Splitsko-dalmatinska
    "Sveta Nedelja",  # Zagrebačka i Istarska
    "Sveta Nedjelja",
    "Privlaka",       # Zadarska i Vukovarsko-srijemska
    "Luka",           # Zagrebačka; ujedno česta imenica
    "Dubrava",
    "Orehovica",
    "Stari Grad",
    "Bistra",
    "Nova Bukovica",
}

# --- Sud / nadležno tijelo -> županija -------------------------------------
# Ključ je grad iz naziva suda. Kod "Stalna služba u X" prednost ima X,
# jer je uže i bliže lokaciji nekretnine.
COURT_TOWN_COUNTY = {
    "Zagrebu": "Grad Zagreb",
    "Novom Zagrebu": "Grad Zagreb",
    "Sesvetama": "Grad Zagreb",
    "Velikoj Gorici": "Zagrebačka županija",
    "Zaprešiću": "Zagrebačka županija",
    "Samoboru": "Zagrebačka županija",
    "Ivanić-Gradu": "Zagrebačka županija",
    "Vrbovcu": "Zagrebačka županija",
    "Svetom Ivanu Zelini": "Zagrebačka županija",
    "Dugom Selu": "Zagrebačka županija",
    "Jastrebarskom": "Zagrebačka županija",
    "Zlataru": "Krapinsko-zagorska županija",
    "Zaboku": "Krapinsko-zagorska županija",
    "Krapini": "Krapinsko-zagorska županija",
    "Klanjcu": "Krapinsko-zagorska županija",
    "Donjoj Stubici": "Krapinsko-zagorska županija",
    "Pregradi": "Krapinsko-zagorska županija",
    "Sisku": "Sisačko-moslavačka županija",
    "Kutini": "Sisačko-moslavačka županija",
    "Glini": "Sisačko-moslavačka županija",
    "Karlovcu": "Karlovačka županija",
    "Ogulinu": "Karlovačka županija",
    "Varaždinu": "Varaždinska županija",
    "Ivancu": "Varaždinska županija",
    "Koprivnici": "Koprivničko-križevačka županija",
    "Đurđevcu": "Koprivničko-križevačka županija",
    "Križevcima": "Koprivničko-križevačka županija",
    "Bjelovaru": "Bjelovarsko-bilogorska županija",
    "Čazmi": "Bjelovarsko-bilogorska županija",
    "Daruvaru": "Bjelovarsko-bilogorska županija",
    "Garešnici": "Bjelovarsko-bilogorska županija",
    "Grubišnom Polju": "Bjelovarsko-bilogorska županija",
    "Pakracu": "Požeško-slavonska županija",
    "Rijeci": "Primorsko-goranska županija",
    "Opatiji": "Primorsko-goranska županija",
    "Crikvenici": "Primorsko-goranska županija",
    "Krku": "Primorsko-goranska županija",
    "Rabu": "Primorsko-goranska županija",
    "Malom Lošinju": "Primorsko-goranska županija",
    "Delnicama": "Primorsko-goranska županija",
    "Gospiću": "Ličko-senjska županija",
    "Virovitici": "Virovitičko-podravska županija",
    "Slatini": "Virovitičko-podravska županija",
    "Požegi": "Požeško-slavonska županija",
    "Slavonskom Brodu": "Brodsko-posavska županija",
    "Novoj Gradiški": "Brodsko-posavska županija",
    "Zadru": "Zadarska županija",
    "Pagu": "Zadarska županija",
    "Osijeku": "Osječko-baranjska županija",
    "Belom Manastiru": "Osječko-baranjska županija",
    "Valpovu": "Osječko-baranjska županija",
    "Đakovu": "Osječko-baranjska županija",
    "Našicama": "Osječko-baranjska županija",
    "Šibeniku": "Šibensko-kninska županija",
    "Kninu": "Šibensko-kninska županija",
    "Vukovaru": "Vukovarsko-srijemska županija",
    "Vinkovcima": "Vukovarsko-srijemska županija",
    "Županji": "Vukovarsko-srijemska županija",
    "Otoku": "Vukovarsko-srijemska županija",
    "Splitu": "Splitsko-dalmatinska županija",
    "Supetru": "Splitsko-dalmatinska županija",
    "Sinju": "Splitsko-dalmatinska županija",
    "Trogiru": "Splitsko-dalmatinska županija",
    "Makarskoj": "Splitsko-dalmatinska županija",
    "Imotskom": "Splitsko-dalmatinska županija",
    "Puli": "Istarska županija",
    "Puli-Pola": "Istarska županija",
    "Puli - Pola": "Istarska županija",
    "Pazinu": "Istarska županija",
    "Bujama": "Istarska županija",
    "Bujama-Buie": "Istarska županija",
    "Bujama - Buie": "Istarska županija",
    "Poreču": "Istarska županija",
    "Poreču-Parenzo": "Istarska županija",
    "Poreču - Parenzo": "Istarska županija",
    "Labinu": "Istarska županija",
    "Rovinju": "Istarska županija",
    "Rovinju-Rovigno": "Istarska županija",
    "Dubrovniku": "Dubrovačko-neretvanska županija",
    "Metkoviću": "Dubrovačko-neretvanska županija",
    "Korčuli": "Dubrovačko-neretvanska županija",
    "Čakovcu": "Međimurska županija",
}

# Trgovački sudovi pokrivaju više županija i stečajna masa može držati
# nekretnine bilo gdje u RH. Zato njihov grad NIJE pouzdan pokazatelj
# lokacije nekretnine i koristi se samo kao zadnja, označena pretpostavka.
LOW_CONFIDENCE_ISSUERS = ("trgovacki_sud", "javni_biljeznik", "ostalo", "nepoznato")


# Približna središta županija. Dvije namjene: mjehurići na karti i provjera
# udaljenosti pri vezanju k.o. točke uz predmet (istoimene k.o. postoje u
# više dijelova zemlje). Navigacijska preciznost, ne katastarska.
COUNTY_CENTROIDS = {
    "Grad Zagreb": (45.815, 15.98),
    "Zagrebačka županija": (45.85, 16.10),
    "Krapinsko-zagorska županija": (46.10, 15.87),
    "Sisačko-moslavačka županija": (45.35, 16.55),
    "Karlovačka županija": (45.30, 15.55),
    "Varaždinska županija": (46.25, 16.25),
    "Koprivničko-križevačka županija": (46.10, 16.75),
    "Bjelovarsko-bilogorska županija": (45.85, 16.95),
    "Primorsko-goranska županija": (45.35, 14.55),
    "Ličko-senjska županija": (44.75, 15.30),
    "Virovitičko-podravska županija": (45.75, 17.55),
    "Požeško-slavonska županija": (45.35, 17.75),
    "Brodsko-posavska županija": (45.15, 17.85),
    "Zadarska županija": (44.10, 15.55),
    "Osječko-baranjska županija": (45.55, 18.55),
    "Šibensko-kninska županija": (43.85, 16.05),
    "Vukovarsko-srijemska županija": (45.20, 18.85),
    "Splitsko-dalmatinska županija": (43.55, 16.55),
    "Istarska županija": (45.15, 13.85),
    "Dubrovačko-neretvanska županija": (42.85, 17.65),
    "Međimurska županija": (46.40, 16.45),
}


# --- Referentne točke katastarskih općina (DGU INSPIRE WFS) ----------------
# data/ko_tocke.csv generira tools/build_ko_tocke.py — službene cp:referencePoint
# koordinate svih k.o., Otvorena dozvola (provenijencija u zaglavlju skripte).

_KO_POINTS: tuple[dict, dict] | None = None


def ko_points() -> tuple[dict[str, tuple[str, float, float]],
                         dict[str, list[tuple[str, str, float, float]]]]:
    """(po_maticnom_broju, po_imenu) — lijeno učitano.

    po_maticnom_broju: "329525" -> (naziv, lat, lon)
    po_imenu:          fold(naziv) -> [(maticni, naziv, lat, lon), ...]
    """
    global _KO_POINTS
    if _KO_POINTS is None:
        import csv
        import unicodedata
        from pathlib import Path

        def _fold(s: str) -> str:
            s = s.replace("đ", "d").replace("Đ", "D").lower()
            return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()

        by_code: dict[str, tuple[str, float, float]] = {}
        by_name: dict[str, list[tuple[str, str, float, float]]] = {}
        path = Path(__file__).resolve().parent / "data" / "ko_tocke.csv"
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                for row in csv.DictReader(fh, delimiter=";"):
                    code, name = row["maticni_broj"], row["naziv"]
                    lat, lon = float(row["lat"]), float(row["lon"])
                    by_code[code] = (name, lat, lon)
                    by_name.setdefault(_fold(name), []).append((code, name, lat, lon))
        _KO_POINTS = (by_code, by_name)
    return _KO_POINTS


# --- Službeni registar naselja (DZS, Popis 2021) ---------------------------
# data/naselja.csv generira tools/build_naselja.py iz DZS-ove tablice
# objavljene pod Otvorenom dozvolom (v. zaglavlje te skripte za provenijenciju).
# 6 357 naselja; ime koje postoji u više jedinica rješava se korovoracijom
# u normalise.py, nikad pogađanjem.

_SETTLEMENTS: dict[str, list[tuple[str, str, str, int]]] | None = None


def settlements() -> dict[str, list[tuple[str, str, str, int]]]:
    """fold(ime) -> [(ime, grad/općina, županija, stanovništvo), ...]."""
    global _SETTLEMENTS
    if _SETTLEMENTS is None:
        import csv
        from pathlib import Path

        # lokalni fold — croatia.py ne smije ovisiti o normalise.py (ciklus)
        import unicodedata

        def _fold(s: str) -> str:
            s = s.replace("đ", "d").replace("Đ", "D").lower()
            return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()

        table: dict[str, list[tuple[str, str, str, int]]] = {}
        path = Path(__file__).resolve().parent / "data" / "naselja.csv"
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                key = _fold(row["naselje"])
                table.setdefault(key, []).append(
                    (row["naselje"], row["grad_opcina"], row["zupanija"],
                     int(row.get("stanovnistvo") or 0))
                )
        _SETTLEMENTS = table
    return _SETTLEMENTS
