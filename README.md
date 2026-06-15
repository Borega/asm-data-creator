# ASM Generator

Eine Windows-Desktop-Anwendung zur Erstellung von Apple School Manager (ASM) CSV-Exportdateien aus Schulexporten (Schuldock oder Einzelexporte).

![Plattform: Windows](https://img.shields.io/badge/Plattform-Windows-blue)
![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-green)
![GUI: PyQt6](https://img.shields.io/badge/GUI-PyQt6%20Fluent%20Design-orange)

---

## Inhaltsverzeichnis

1. [Was ist der ASM Generator?](#was-ist-der-asm-generator)
2. [Schnellstart](#schnellstart)
3. [Installation & Einrichtung](#installation--einrichtung)
4. [Bedienungsanleitung](#bedienungsanleitung)
   - [Die drei Hauptbereiche](#die-drei-hauptbereiche)
   - [Input-Seite – Daten einlesen](#input-seite--daten-einlesen)
   - [Diff Review-Seite – Änderungen prüfen](#diff-review-seite--änderungen-prüfen)
   - [Settings-Seite – Einstellungen](#settings-seite--einstellungen)
5. [Eingabemodi im Detail](#eingabemodi-im-detail)
   - [Legacy-Modus](#legacy-modus)
   - [Schuldock-Modus](#schuldock-modus)
6. [Konfigurationsdateien](#konfigurationsdateien)
   - [teacher_aliases.json](#teacher_aliasesjson)
   - [subject_map.json](#subject_mapjson)
   - [locations.csv](#locationscsv)
7. [Export & Upload](#export--upload)
   - [ZIP-Export](#zip-export)
   - [SFTP-Upload zu Apple](#sftp-upload-zu-apple)
   - [Lokale Backups](#lokale-backups)
8. [Diff-Baselines](#diff-baselines)
9. [Aktivitätslog-Analyse](#aktivitätslog-analyse)
10. [Entwicklung & Build](#entwicklung--build)
11. [Projektstruktur](#projektstruktur)
12. [Tests](#tests)
13. [Fehlerbehebung](#fehlerbehebung)

---

## Was ist der ASM Generator?

Der **ASM Generator** wandelt Schulexport-Daten (Schülerstammdaten, Kursbelegungen, Lehrkräfte) in das von Apple School Manager geforderte CSV-Format um. Die App erzeugt sechs CSV-Dateien – `students.csv`, `staff.csv`, `courses.csv`, `classes.csv`, `rosters.csv` und `locations.csv` – verpackt als ZIP-Archiv.

**Funktionen auf einen Blick:**

| Funktion | Beschreibung |
|----------|-------------|
| 🔄 **Zwei Eingabemodi** | Legacy (Einzelexporte) oder Schuldock (Monolith-CSV) |
| 🎨 **Fluent-Design-GUI** | Moderne Windows-Oberfläche mit Seitenleisten-Navigation |
| 🔍 **Diff-Ansicht** | Farbcodierte Änderungsübersicht (hinzugefügt/geändert/gelöscht/unverändert) |
| ✅ **Freigabe-Workflow** | Änderungen einzeln oder in Gruppen bestätigen/ablehnen |
| 📦 **ZIP-Export** | Alle 6 CSV-Dateien als ZIP-Archiv |
| ☁️ **SFTP-Upload** | Direkter Upload zu `upload.appleschoolcontent.com` |
| 💾 **Lokale Backups** | Automatische Sicherung jedes Uploads in `%LOCALAPPDATA%` |
| 🔐 **Sichere Zugangsdaten** | SFTP-Passwort im Windows-Credential-Manager (Keyring) |
| 📊 **Aktivitätslog-Analyse** | ASM-Aktivitätslogs einlesen und auswerten |
| 📸 **Snapshot-Vergleich** | Automatischer Vergleich mit dem letzten Export |

---

## Schnellstart

### Voraussetzungen

- **Windows 10/11** (64-Bit)
- **Python 3.10 oder neuer** (nur für Entwicklung; die gebaute `.exe` benötigt kein Python)
- Internetzugang für SFTP-Upload

### Als fertige EXE nutzen (Empfohlen)

1. Den Ordner `dist/ASM-Generator/` von einem Administrator erhalten
2. `ASM-Generator.exe` doppelklicken
3. Beim ersten Start werden die SFTP-Einstellungen abgefragt

### Aus dem Quellcode starten (Entwicklung)

```bash
# 1. Repository klonen
git clone <repo-url>
cd appleaccounts

# 2. Virtuelle Umgebung erstellen & aktivieren
python -m venv .venv
.venv\Scripts\activate

# 3. Abhängigkeiten installieren
pip install -r requirements.txt

# 4. Anwendung starten
python main.py
```

---

## Installation & Einrichtung

### Ersteinrichtung

Beim ersten Start öffnet sich automatisch die **Settings**-Seite. Folgende Einstellungen müssen vorgenommen werden:

#### 1. Grundeinstellungen (Configuration)

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| **Location ID** | Eindeutige Standort-Kennung für Apple School Manager | `LOC001` |
| **Email Domain** | E-Mail-Domäne für generierte Adressen | `school.example` |
| **Target School Year** | Schuljahr-Filter für Schuldock-Modus | `2025/2026` |
| **Teacher Aliases** | Pfad zur Lehrer-Alias-Datei (JSON) | `teacher_aliases.json` |
| **Subject Map** | Pfad zur Fächerzuordnungs-Datei (JSON) | `subject_map.json` |

Die Pfade zu `teacher_aliases.json` und `subject_map.json` können leer gelassen werden – dann werden die mitgelieferten Standarddateien verwendet.

#### 2. SFTP-Upload (SFTP Upload)

| Feld | Beschreibung |
|------|-------------|
| **Hostname** | `upload.appleschoolcontent.com` (fest, nicht änderbar) |
| **Port** | `22` (fest, nicht änderbar) |
| **Username** | SFTP-Benutzername (von Apple bereitgestellt) |
| **Password** | SFTP-Passwort (wird sicher im Windows-Credential-Manager gespeichert) |

Nach Eingabe der Zugangsdaten auf **„Test SFTP Connection“** klicken, um die Verbindung zu prüfen.

> ⚠️ **Wichtig:** Das Passwort wird **nicht** in der settings.json gespeichert, sondern im Windows-Credential-Manager (Keyring). Die App fragt das Passwort nur beim ersten Mal ab.

#### 3. Speichern

Auf **„Save Settings“** klicken. Die Einstellungen werden unter `%LOCALAPPDATA%\ASMGenerator\settings.json` gespeichert.

---

## Bedienungsanleitung

### Die drei Hauptbereiche

Die App hat drei Seiten, die über die linke Seitenleiste erreichbar sind:

```
┌──────────────────────────────────────────┐
│  📁 Input         ← Quelldateien auswählen│
│  🔄 Diff Review   ← Änderungen prüfen     │
│                                          │
│                                          │
│                                          │
│  ⚙ Settings       ← Konfiguration        │
└──────────────────────────────────────────┘
```

### Input-Seite – Daten einlesen

Auf der Input-Seite werden die Quelldateien ausgewählt. Je nach gewähltem **Input Mode** (Legacy/Schuldock) erscheinen unterschiedliche Felder.

#### Legacy-Modus

| Feld | Beschreibung | Format |
|------|-------------|--------|
| **Students** | Schülerstammdaten-CSV | Tab-getrennt, mit `externKey`-Spalte |
| **Teachers** | Bestehende `staff.csv` (für E-Mail-Übernahme) | Komma-getrennt |
| **Course Export 1** | Erster Kursbelegungs-Export | Semikolon-getrennt |
| **Course Export 2** | Zweiter Kursbelegungs-Export (optional) | Semikolon-getrennt |

#### Schuldock-Modus

| Feld | Beschreibung | Format |
|------|-------------|--------|
| **Schuldock CSV** | Monolith-CSV mit Schülern, Kursen & Lehrkräften | Semikolon-getrennt |

> 💡 **Tipp:** Im Schuldock-Modus wird das gesamte Datenpaket in einer einzigen CSV-Datei erwartet. Der optionale Filter **Target School Year** in den Settings begrenzt die Ausgabe auf ein bestimmtes Schuljahr.

#### Ausführung

Nach Auswahl aller Dateien auf **„Run“** klicken. Ein Fortschrittsring zeigt die Verarbeitung an. Nach erfolgreicher Generierung erscheint automatisch die Diff-Ansicht.

### Diff Review-Seite – Änderungen prüfen

Die Diff Review-Seite ist das Herzstück der Qualitätskontrolle. Sie zeigt alle Änderungen im Vergleich zur letzten Baseline (Snapshot, Aktivitätslog oder CSV-Export).

#### Tabs & Farbcodierung

| Tab | Inhalt | Schlüssel |
|-----|--------|-----------|
| **Students** | Schüler/-innen | `person_id` |
| **Staff** | Lehrkräfte & Personal | `person_id` |
| **Courses** | Kurse | `course_id` |
| **Classes** | Klassen | `class_id` |
| **Rosters** | Kurszuordnungen | `class_id:student_id` |

Jede Zeile ist farblich markiert:

| Farbe | Status | Bedeutung |
|-------|--------|-----------|
| 🟢 Grün | **Added** | Neuer Eintrag |
| 🟡 Gelb | **Changed** | Geänderter Eintrag |
| 🔴 Rot | **Deleted** | Entfernter Eintrag |
| ⚪ Weiß | **Unchanged** | Unveränderter Eintrag (standardmäßig ausgeblendet) |

#### Schaltflächen pro Tab

| Schaltfläche | Funktion |
|-------------|----------|
| **Select All Added** | Alle hinzugefügten Zeilen markieren |
| **Select All Changed** | Alle geänderten Zeilen markieren |
| **Select All Deleted** | Alle gelöschten Zeilen markieren |
| **Show unchanged** | Unveränderte Zeilen ein-/ausblenden |
| **Approve All Changes** | Alle Änderungen (außer Löschungen) genehmigen |
| **Approve All Deletions** | Alle Löschungen bestätigen |

> ⚠️ **Wichtig:** Gelöschte Einträge (rot) müssen **aktiv bestätigt** werden, indem sie markiert werden! Sie werden nicht automatisch in den Export übernommen.

#### Export-Schaltflächen (unten)

| Schaltfläche | Funktion |
|-------------|----------|
| **Export ZIP** | ZIP-Datei lokal speichern |
| **Export & Upload** | ZIP erstellen und direkt zu Apple hochladen |

### Settings-Seite – Einstellungen

Die Settings-Seite ist in drei Bereiche unterteilt:

#### Configuration

Grundlegende Generator-Einstellungen (siehe [Installation & Einrichtung](#installation--einrichtung)).

#### SFTP Upload

SFTP-Verbindungseinstellungen mit „Test SFTP Connection“-Schaltfläche.

#### Diff Baseline

Steuert, wogegen die aktuelle Generierung verglichen wird:

| Schaltfläche | Beschreibung |
|-------------|-------------|
| **Analyze Activity Log** | ASM-Aktivitätslog einlesen & analysieren |
| **Use Activity Log as Diff Baseline** | Aktivitätslog als Vergleichsbasis setzen |
| **Use CSV/ZIP/Monolith as Diff Baseline** | Früheren Export als Vergleichsbasis setzen |
| **Use Last Export as Diff Baseline** | Letzten Export-Pfad als Vergleichsbasis setzen |
| **Clear Diff Baseline** | Zurücksetzen auf Snapshot-Vergleich |

---

## Eingabemodi im Detail

### Legacy-Modus

Der Legacy-Modus verwendet separate Dateien für Schüler, Lehrkräfte und Kursbelegungen. Dies ist der Modus für den klassischen Schulexport-Workflow mit Einzeldateien.

**Datenfluss:**

```
Student_*.csv  ──→  Schüler-Parser  ──┐
                                       │
Teacher_*.csv  ──→  Lehrer-Parser   ──┼──→  generate()  ──→  ZIP-Export
                                       │
export_*.csv   ──→  Kurs-Parser     ──┘
```

- **Students:** Tab-getrennte CSV mit Spalten wie `externKey`, `foreName`, `longName`, `klasse`
- **Teachers:** Bestehende `staff.csv` (vorheriger Export) zur Übernahme von E-Mail-Adressen
- **Course Exports:** Semikolon-getrennte CSV mit Kursbelegungen und Lehrer-Kürzeln

### Schuldock-Modus

Der Schuldock-Modus verarbeitet eine einzelne, monolithische CSV-Datei, die alle Informationen enthält.

**Datenfluss:**

```
Schuldock.csv  ──→  Monolith-Parser  ──→  generate()  ──→  ZIP-Export
```

Die CSV muss folgende Spalten enthalten (Semikolon-getrennt):
- `Nachname`, `Vorname` – Schülername
- `Rolle` – „Student“ oder „Teacher“
- `Angebote` – Kursbelegungen mit Lehrer-Kürzeln
- `Interne ID` – Eindeutige Schüler-ID
- `Export ID` – ASM-Export-ID

Mit dem **Target School Year**-Filter können Daten auf ein bestimmtes Schuljahr begrenzt werden.

---

## Konfigurationsdateien

### teacher_aliases.json

Diese Datei ordnet abweichende Lehrernamen aus dem Export den kanonischen Namen zu. Format:

```json
[
  [["Export-Vorname", "Export-Nachname"], ["Kanonischer-Vorname", "Kanonischer-Nachname"]],
  [["Maxi", "Mustermann"], ["Maximiliane", "Mustermann"]]
]
```

Jeder Eintrag ist ein Array mit zwei Paaren: `[Export-Name, kanonischer Name]`.

### subject_map.json

Ordnet Fach-Kürzel den vollen Fachnamen zu:

```json
{
  "Sp": "Sport",
  "E": "Englisch",
  "D": "Deutsch",
  "Ma": "Mathematik",
  "BKu": "Bildende Kunst"
}
```

### locations.csv

Optionale Standort-Zuordnungstabelle für `location_id` → `location_name`:

```csv
location_id,location_name
LOC001,Example School
```

---

## Export & Upload

### ZIP-Export

Der Export erzeugt ein ZIP-Archiv mit folgenden Dateien:

| Datei | Inhalt |
|-------|--------|
| `students.csv` | Schüler/-innen mit `person_id`, `first_name`, `last_name`, `grade_level`, `email_address`, … |
| `staff.csv` | Lehrkräfte mit `person_id`, `first_name`, `last_name`, `email_address`, … |
| `courses.csv` | Kurse mit `course_id`, `course_name`, `location_id` |
| `classes.csv` | Klassen mit `class_id`, `course_id`, `instructor_id`, … |
| `rosters.csv` | Kurszuordnungen mit `roster_id`, `class_id`, `student_id` |
| `locations.csv` | Verwendete Standorte mit `location_id`, `location_name` |

**E-Mail-Generierung:** E-Mails werden nach dem Schema `vorname.nachname@domäne.de` generiert. Umlaute und Sonderzeichen werden transliteriert (ä→ae, ö→oe, ü→ue, ß→ss). Bestehende E-Mails aus der Teacher-CSV werden übernommen.

**Personen-ID-Generierung:** IDs folgen dem Schema `vorname.nachname` (z. B. `anna.mueller`). Bei Kollisionen werden IDs automatisch durchnummeriert.

### SFTP-Upload zu Apple

Die App kann ZIP-Dateien direkt zu Apples SFTP-Server hochladen:

- **Host:** `upload.appleschoolcontent.com`
- **Port:** `22`
- **Protokoll:** SFTP (SSH File Transfer Protocol)

**Upload-Workflow:**

1. ZIP wird temporär erstellt
2. Lokales Backup wird in `%LOCALAPPDATA%\ASM-Generator\backups\` abgelegt
3. ZIP wird via SFTP hochgeladen
4. Bei Erfolg: Snapshot wird aktualisiert
5. Bei Fehler: Wiederholung möglich (bei Authentifizierungs- oder Netzwerkfehlern)

### Lokale Backups

Jeder Upload wird automatisch gesichert unter:
```
%LOCALAPPDATA%\ASM-Generator\backups\YYYYMMDD_HHMMSS\asm_export_YYYYMMDD_HHMMSS.zip
```

Standardmäßig werden die **letzten 5 Backups** aufbewahrt, ältere werden automatisch gelöscht.

---

## Diff-Baselines

Der ASM Generator vergleicht jede neue Generierung mit einer **Baseline**, um Änderungen sichtbar zu machen. Es gibt drei Baseline-Modi:

### 1. Snapshot (Standard)

Automatisch nach jedem erfolgreichen Export gespeichert. Gespeichert unter:
```
%LOCALAPPDATA%\ASMGenerator\snapshot.json
```

### 2. Aktivitätslog (Activity Log)

Ein von Apple bereitgestelltes Aktivitätslog-CSV kann als Baseline verwendet werden. Die App extrahiert daraus alle aktiven Einträge und zeigt die Differenz zur neuen Generierung.

**Einrichtung:** Settings → „Use Activity Log as Diff Baseline“ → CSV-Datei auswählen.

### 3. CSV/ZIP-Baseline

Ein früherer Export (ZIP oder entpackter CSV-Ordner) oder eine Schuldock-CSV kann als Baseline dienen. Dies ist nützlich, um z. B. einen früheren Schuljahres-Export mit dem aktuellen zu vergleichen.

**Einrichtung:** Settings → „Use CSV/ZIP/Monolith as Diff Baseline“ → Datei/Ordner auswählen.

---

## Aktivitätslog-Analyse

Über **„Analyze Activity Log“** in den Settings kann ein ASM-Aktivitätslog eingelesen werden. Die Analyse zeigt:

- Erfolgreiche und fehlgeschlagene Einträge pro Kategorie (Personen, Klassen, Kurse, Standorte, Kurszuordnungen)
- Abgleich mit den aktuell generierten Lehrkräften
- Fehlermeldungen und deren Häufigkeit

---

## Entwicklung & Build

### Voraussetzungen

```bash
pip install -r requirements.txt
```

### Start im Entwicklungsmodus

```bash
python main.py
```

### Windows-Executable bauen

```bash
pyinstaller asm_generator.spec
```

Ausgabe: `dist/ASM-Generator/ASM-Generator.exe`

> ⚠️ Der gesamte Ordner `dist/ASM-Generator/` muss verteilt werden – die `.exe` ist nicht standalone.

### Build überprüfen

1. `dist\ASM-Generator\ASM-Generator.exe` ausführen
2. Erwartet: FluentWindow mit „Input“, „Diff Review“, „Settings“ in der Seitenleiste
3. Alle drei Seiten durchklicken
4. Fenster schließen – Exit-Code 0 (kein Absturz)

### Qt-Plugin-Fehler beheben

Falls die Meldung erscheint:
```
This application failed to start because no Qt platform plugin could be initialized.
```

Debug-Ausgabe aktivieren:
```bash
set QT_DEBUG_PLUGINS=1
dist\ASM-Generator\ASM-Generator.exe
```

### Verteilung

Den gesamten Ordner `dist/ASM-Generator/` als ZIP packen und an den Admin-Rechner übergeben. Keine Python-Installation auf dem Zielrechner nötig.

---

## Projektstruktur

```
appleaccounts/
├── main.py                  # Einstiegspunkt (Qt-Fixes + QApplication)
├── pyproject.toml           # Projektkonfiguration (Ruff, Pytest)
├── requirements.txt         # Python-Abhängigkeiten
├── asm_generator.spec       # PyInstaller Build-Spezifikation
│
├── asm_generator/           # Kernbibliothek
│   ├── __init__.py
│   ├── config.py            # GeneratorConfig & GeneratorResult (Dataclasses)
│   ├── generator.py         # generate() Orchestrator – reine Funktion
│   ├── parsers.py           # CSV-Parser (Schüler, Kurse, Schuldock-Monolith)
│   ├── transform.py         # Transformationen (IDs, E-Mails, Umlaute)
│   └── writer.py            # ZIP- & CSV-Ausgabe
│
├── gui/                     # PyQt6 GUI
│   ├── __init__.py
│   ├── main_window.py       # Hauptfenster (FluentWindow)
│   ├── app_controller.py    # Zentraler Controller (verbindet alles)
│   ├── workers.py           # Background-Worker (QRunnable)
│   ├── assets/
│   └── pages/
│       ├── __init__.py
│       ├── input_page.py    # Dateiauswahl & Ausführung
│       ├── diff_review_page.py  # Änderungsansicht mit Tabs
│       └── settings_page.py # Konfiguration & SFTP
│
├── diff_engine.py           # Diff-Berechnung (Added/Changed/Deleted)
├── diff_baseline.py         # Baseline-Ladefunktionen
├── snapshot_store.py        # Snapshot-Persistenz
├── settings_store.py        # Einstellungen-Persistenz
├── activity_log.py          # Aktivitätslog-Parser & Analyse
├── backup_store.py          # Lokale Backup-Verwaltung
├── sftp_client.py           # SFTP-Client (Paramiko)
├── sftp_credentials.py      # Keyring-Credential-Verwaltung
│
├── teacher_aliases.json     # Lehrer-Namensaliase
├── subject_map.json         # Fach-Kürzel → Fach-Namen
├── locations.csv            # Standort-Zuordnung
│
└── tests/                   # Test-Suite (Pytest)
    ├── conftest.py
    ├── test_activity_log.py
    ├── test_app_controller_sftp.py
    ├── test_backup_store.py
    ├── test_diff_baseline.py
    ├── test_diff_engine.py
    ├── test_parsers.py
    ├── test_settings_store.py
    ├── test_sftp_client.py
    ├── test_sftp_credentials.py
    ├── test_snapshot_store.py
    ├── test_transform.py
    └── ...
```

---

## Tests

```bash
# Alle Tests ausführen
python -m pytest tests/ -v

# Einzelne Testdatei
python -m pytest tests/test_diff_engine.py -v

# Mit Coverage
python -m pytest tests/ -v --cov=asm_generator --cov=gui --cov-report=html
```

---

## Fehlerbehebung

| Problem | Lösung |
|---------|--------|
| **„No Qt platform plugin could be initialized“** | `set QT_DEBUG_PLUGINS=1` setzen und Pfad prüfen |
| **„Authentication failed“ beim SFTP** | Zugangsdaten in Settings prüfen, „Test SFTP Connection“ ausführen |
| **„paramiko is not installed“** | `pip install paramiko` ausführen |
| **CSV wird nicht erkannt / Encoding-Fehler** | Die App erkennt automatisch UTF-8, UTF-8-SIG und (via chardet) andere Encodings |
| **Snapshot beschädigt** | `%LOCALAPPDATA%\ASMGenerator\snapshot.json` löschen – die App behandelt den nächsten Lauf als Ersteinrichtung |
| **Einstellungen zurücksetzen** | `%LOCALAPPDATA%\ASMGenerator\settings.json` löschen |
| **SFTP-Passwort vergessen** | Im Windows-Credential-Manager unter „Windows-Anmeldeinformationen“ nach „asm-generator-sftp“ suchen |
