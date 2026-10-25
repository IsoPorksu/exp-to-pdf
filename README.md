# EXP timetable PDF generator

This Python program reads EXP timetable files, builds route tables, and writes them to a PDF. It supports two known EXP file formats: that used by HSL for trams (English file, HASTUS 2017) and that used by HSL for bus tenders (Finnish file).

This project uses lazy imports and thus requires Python 3.15.

## English

### Run the program

Install the dependencies:

```text
python -m pip install -r requirements.txt
```

Run the program from any directory:

```text
python exptranslator.py
```

The program currently loads `config-files/config_kohde_321_talvi_2028.json`, as set by `CONFIG_PATH` in `exptranslator.py`. To generate a different timetable, change `CONFIG_PATH` to one of the other configuration files:

- `config-files/config_11_13_9.11.2026.json` — tram lines 11 and 13; uses `file_format: "tram"`.
- `config-files/config_kohde_320b_talvi_2028.json` — bus 600; uses `file_format: "bus_tender"`.
- `config-files/config_kohde_321_talvi_2028.json` — bus 623; uses `file_format: "bus_tender"`.

Paths in the configuration are relative to the repository folder. EXP files are read from `data-files/`; generated PDFs are written to `output-pdfs/` unless `output_pdf` is an absolute path.

### Configuration options

Each configuration file describes one PDF:

- `output_pdf`: output PDF filename.
- `font_name`: installed Windows font family or face name. The program searches system and per-user font locations. ReportLab supports TrueType fonts and OpenType fonts with TrueType outlines; PostScript-outline OpenType fonts cannot be embedded.
- `font_size`: font size in points. The selected font must have equal-width digits so timetable times use tabular numerals.
- `file_format`: `tram` for the tram EXP records or `bus_tender` for the bus-tender records.
- `page_header` and `page_footer`: optional text repeated on every page. `{page}` and `{day_type}` are available as placeholders.
- `day_types`: list of service days to include, in PDF order. Each item has:
  - `name`: heading for that service day.
  - `exp_file`: source EXP file.
  - `page_color`: optional page background color, such as a hex color. Pages for each day type start on a fresh page.
- `routes`: list of route tables to produce. Each route has:
  - `name`: table title.
  - `route_shape`: EXP stop codes in display order. Repeat the pivot stop to show both sides of a loop.
  - `pivot_stop`: stop code used to split/map a route around its pivot.
  - `match_patterns`: optional list of stop-code sequences used to select trips. A trip is included if its timing points contain any listed sequence in order.
  - `shaded_stops`: stop codes whose table columns should be shaded.
  - `stop_labels`: optional mapping from an EXP stop code to a displayed column heading.
  - `show_following_line`: when true, adds the following trip’s line number in the `Linjalle` column.
  - `side_by_side_with`: optional title of the next route table to place beside this one when both fit.

Column widths are based on the widest header or cell value plus padding. Cell contents are centered; tables and titles are left-aligned. Pagination keeps groups of up to three data rows together.

## Suomeksi

### Ohjelman suorittaminen

Asenna riippuvuudet:

```text
python -m pip install -r requirements.txt
```

Suorita ohjelma mistä tahansa työhakemistosta:

```text
python exptranslator.py
```

Ohjelma käyttää tällä hetkellä tiedostoa `config-files/config_kohde_321_talvi_2028.json`. Käytettävä tiedosto määritellään `exptranslator.py`-tiedoston `CONFIG_PATH`-muuttujassa. Jos haluat tuottaa toisen aikataulun, vaihda muuttuja osoittamaan johonkin seuraavista asetustiedostoista:

- `config-files/config_11_13_9.11.2026.json` — raitiolinjat 11 ja 13; `file_format: "tram"`.
- `config-files/config_kohde_320b_talvi_2028.json` — bussilinja 600; `file_format: "bus_tender"`.
- `config-files/config_kohde_321_talvi_2028.json` — bussilinja 623; `file_format: "bus_tender"`.

Asetustiedostojen polut ovat suhteessa projektin kansioon. EXP-tiedostot luetaan `data-files/`-kansiosta. PDF-tiedosto tallennetaan `output-pdfs/`-kansioon, ellei `output_pdf`-asetuksessa anneta absoluuttista polkua.

### Asetusten kuvaus

Kukin asetustiedosto määrittää yhden tuotettavan PDF-tiedoston:

- `output_pdf`: tuotettavan PDF-tiedoston nimi.
- `font_name`: Windowsiin asennetun fonttiperheen tai fonttileikkauksen nimi. Ohjelma etsii fontteja järjestelmän ja käyttäjän fonttikansioista. ReportLab tukee TrueType-fontteja ja TrueType-muotoisia OpenType-fontteja; PostScript-muotoisia OpenType-fontteja ei voi upottaa PDF-tiedostoon.
- `font_size`: fonttikoko pisteinä. Valitussa fontissa numeroiden leveyksien on oltava samat, jotta aikataulun kellonajat näkyvät tasalevyisin numeroin.
- `file_format`: raitiovaunun EXP-tiedostolle `tram` tai bussiliikenteen tarjousaineistolle `bus_tender`.
- `page_header` ja `page_footer`: valinnaiset tekstit, jotka tulostetaan jokaiselle sivulle. Paikkamerkit `{page}` ja `{day_type}` ovat käytettävissä.
- `day_types`: PDF-tiedostoon tulevat liikennöintipäivät halutussa järjestyksessä. Jokaisella kohteella on:
  - `name`: liikennöintipäivän otsikko.
  - `exp_file`: lähteen EXP-tiedosto.
  - `page_color`: valinnainen sivun taustaväri, esimerkiksi heksadesimaalinen väriarvo. Kukin liikennöintipäivä aloitetaan uudelta sivulta.
- `routes`: tuotettavat reittitaulukot. Jokaisella reitillä on:
  - `name`: taulukon otsikko.
  - `route_shape`: EXP-pysäkkikoodit näyttöjärjestyksessä. Toista kääntöpysäkki, jos haluat näyttää lenkin molemmat puolet.
  - `pivot_stop`: kääntöpysäkkinä käytettävä reitin pysäkkikoodi.
  - `match_patterns`: valinnainen lista pysäkkikoodien sarjoja, joiden perusteella vuorot valitaan. Vuoro otetaan mukaan, jos sen ajoaikapisteissä esiintyy mikä tahansa sarjoista oikeassa järjestyksessä.
  - `shaded_stops`: pysäkkikoodit, joiden sarakkeet varjostetaan.
  - `stop_labels`: valinnainen määritys, jolla EXP-pysäkkikoodille annetaan tulosteessa käytettävä sarakeotsikko.
  - `show_following_line`: lisää seuraavan vuoron linjanumeron `Linjalle`-sarakkeeseen, kun arvo on `true`.
  - `side_by_side_with`: valinnainen seuraavan reittitaulukon otsikko. Taulukot asetetaan vierekkäin, jos ne mahtuvat sivulle.

Sarakkeen leveys määräytyy sen pisimmän otsikon tai soluarvon mukaan, ja siihen lisätään täyte. Solujen sisältö keskitetään, taulukot ja otsikot tasataan vasemmalle. Sivunvaihdot säilyttävät enintään kolmen lähtörivin ryhmät samalla sivulla.
