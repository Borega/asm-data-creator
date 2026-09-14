# ASM Generator

Eine Windows-Desktop-Anwendung zur Erstellung von Apple School Manager (ASM) CSV-Exportdateien aus Schulexporten (Schuldock oder Einzelexporte).

![Plattform: Windows](https://img.shields.io/badge/Plattform-Windows-blue)
![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-green)
![GUI: PyQt6](https://img.shields.io/badge/GUI-PyQt6%20Fluent%20Design-orange)

---

## Inhaltsverzeichnis

1. [Was ist der ASM Generator?](#was-ist-der-asm-generator)
2. [⚠️ Bevor Sie starten: Wie ASM Konten identifiziert](#️-bevor-sie-starten-wie-asm-konten-identifiziert)
3. [Schnellstart](#schnellstart)
4. [Installation & Einrichtung](#installation--einrichtung)
5. [Bedienungsanleitung](#bedienungsanleitung)
   - [Die drei Hauptbereiche](#die-drei-hauptbereiche)
   - [Input-Seite – Daten einlesen](#input-seite--daten-einlesen)
   - [Diff Review-Seite – Änderungen prüfen](#diff-review-seite--änderungen-prüfen)
   - [Settings-Seite – Einstellungen](#settings-seite--einstellungen)
6. [Eingabemodi im Detail](#eingabemodi-im-detail)
   - [Legacy-Modus](#legacy-modus)
   - [Schuldock-Modus](#schuldock-modus)
7. [Konfigurationsdateien](#konfigurationsdateien)
   - [teacher_aliases.json](#teacher_aliasesjson)
   - [subject_map.json](#subject_mapjson)
   - [locations.csv](#locationscsv)
8. [Export & Upload](#export--upload)
   - [ZIP-Export](#zip-export)
   - [SFTP-Upload zu Apple](#sftp-upload-zu-apple)
   - [Lokale Backups](#lokale-backups)
9. [Diff-Baselines](#diff-baselines)
10. [Aktivitätslog-Analyse](#aktivitätslog-analyse)
11. [Entwicklung & Build](#entwicklung--build)
12. [Projektstruktur](#projektstruktur)
13. [Tests](#tests)
14. [Fehlerbehebung](#fehlerbehebung)

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

## ⚠️ Bevor Sie starten: Wie ASM Konten identifiziert

Dieser Abschnitt steht vor der Installation, weil er der einzige ist, dessen
Missachtung echte Benutzerkonten zerstört.

**Apple School Manager identifiziert jede Person ausschließlich über
`person_id`.** Daraus folgt alles Weitere:

| Was ASM sieht | Was ASM tut |
|---------------|-------------|
| Bekannte `person_id` | Datensatz wird **aktualisiert** (Name, Klasse, E-Mail ändern sich gefahrlos) |
| Neue `person_id` | Konto wird **neu angelegt** |
| `person_id` fehlt in der Lieferung | Konto wird **deaktiviert** |

Eine geänderte `person_id` ist deshalb kein Rename, sondern **Löschen plus
Neuanlegen**: Das alte Konto wird deaktiviert, ein leeres neues entsteht.
E-Mails, Dateien und Anmeldungen bleiben beim deaktivierten Konto zurück.

### Die wichtigste Fehlerquelle: „ADDED" heißt nicht „nicht in ASM"

Die Diff-Ansicht vergleicht gegen den **lokalen Snapshot des letzten Exports**,
nicht gegen ASM. Ist dieser Snapshot veraltet, dann gilt:

- Eine Zeile mit Status **ADDED** kann längst ein aktives ASM-Konto haben.
  Nimmt man sie heraus, **deaktiviert** man dieses Konto.
- Eine Zeile mit Status **DELETED** kann in ASM nie existiert haben.
  Behält man sie, **erzeugt** man ein Dublettenkonto.

> Ein technisch fehlerfreier Upload — ASM quittiert ihn mit
> `COMPLETED_WITH_SUCCESS` — sagt nichts darüber aus, ob der Inhalt richtig war.
> Der Statusbericht bestätigt nur, dass ASM die Datei verarbeiten konnte.

**Deshalb gibt es die Spalte „In ASM"** in der Diff-Ansicht. Sie beantwortet
die andere Frage — hat ASM diese Person wirklich? — mit drei Zuständen:

| Anzeige | Bedeutung |
|---------|-----------|
| `Ja` | Aktives Konto in ASM. Zeile herausnehmen = Konto deaktivieren. |
| `Nein` | ASM kennt die ID nicht oder hat sie deaktiviert. Zeile behalten = neues Konto. |
| `?` | Keine belastbare Auskunft. **Gilt als gefährlich, nicht als unbedenklich.** |

Belege dafür bezieht die App aus (1) einem ASM-Aktivitätslog — Apples eigenem
Protokoll, das auch außerhalb der App angelegte Konten kennt, aber nur die
Personen nennt, die sich bei diesem Sync geändert haben — und (2) einem
Snapshot, der nachweislich hochgeladen wurde. Ein bloß exportiertes ZIP zählt
nicht: es kann nie bei Apple angekommen sein.

Vor jedem Export prüft die App die getroffenen Entscheidungen und benennt
riskante **namentlich**, bevor irgendetwas ASM erreicht.

### Empfehlungen für den Produktivbetrieb

1. **Erster Lauf ohne Upload.** Exportieren Sie ein ZIP und sehen Sie es an,
   bevor Sie zum ersten Mal hochladen.
2. **Aktivitätslog laden** (Settings → *Load Activity Log as ASM Evidence*),
   bevor Sie Zeilen abwählen.
3. **Bei `?` nichts abwählen.** Ohne Beleg ist jede Abwahl ein Blindflug.
4. **Aktivitätslog nach jedem Upload prüfen** — `CREATED` und `DEACTIVATED`
   bei Personal sind die Zahlen, die zählen.

---

## Schnellstart

### Voraussetzungen

- **Windows 10/11** (64-Bit)
- **Python 3.10 oder neuer** (nur für Entwicklung; die gebaute `.exe` benötigt kein Python)
- Internetzugang für SFTP-Upload

### Als fertige EXE nutzen (Empfohlen)

1. Die ZIP-Datei der neuesten Version von der GitHub-Releases-Seite herunterladen
2. In einen **eigenen, leeren Ordner** entpacken (z. B. `C:\Tools\ASM-Generator`) –
   nur dann kann sich die App später selbst aktualisieren (siehe [Updates](#updates))
3. `ASM-Generator.exe` doppelklicken
4. Beim ersten Start werden die SFTP-Einstellungen abgefragt

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
| **Email Domain** | Domäne Ihrer Managed Apple Accounts | `school.example` |
| **Staff ID source** | *(nur Anzeige)* Wie `person_id` für Personal gebildet wird | siehe unten |
| **Target School Year** | Schuljahr-Filter für Schuldock-Modus – **leer = automatisch** | leer |
| **Teacher Aliases** | Pfad zur Lehrer-Alias-Datei (JSON) | leer |
| **Subject Map** | Pfad zur Fächerzuordnungs-Datei (JSON) | leer |

**Location ID** und **Email Domain** sind Pflicht. Ohne sie verweigert die App
die Erzeugung und nennt beim Klick auf *Run* die fehlenden Felder — jede
erzeugte Adresse und jeder Datensatz trägt beide Werte.

Die Pfade zu `teacher_aliases.json` und `subject_map.json` können leer bleiben –
dann werden die mitgelieferten Standarddateien verwendet.

> **Target School Year leer lassen**, sofern Sie keinen Grund für das Gegenteil
> haben. Ein stehengebliebener Wert importiert nach dem Schuljahreswechsel
> stillschweigend die Kurse des Vorjahres.

#### 1a. Staff ID source — einmalig, nicht änderbar

Bestimmt, woraus die `person_id` einer Lehrkraft gebildet wird. Das Feld ist
**absichtlich schreibgeschützt**: eine Änderung würde jedes vorhandene
Personal-Konto deaktivieren und neu anlegen.

| Wert | Für wen |
|------|---------|
| `interne_id` (SIS-UUID) | **Voreinstellung bei Neuinstallation.** Die ID ändert sich bei Namensänderungen nie. Für Schulen ohne bestehende ASM-Personalkonten. |
| `name` (`vorname.nachname`) | Für Installationen, deren Konten bereits so angelegt sind und die deshalb nicht umgeschlüsselt werden können. |

Schülerkonten nutzen immer die SIS-ID und sind dadurch von Namensänderungen
grundsätzlich nicht betroffen.

Bei `interne_id` bleibt die E-Mail-Adresse namensbasiert
(`vorname.nachname@ihre-domain.de`) — eine UUID als Postfach wäre unbenutzbar.
Lehrkräfte, die nur in einem Kursexport vorkommen und keine SIS-ID mitbringen,
erhalten weiterhin eine namensbasierte ID; ein gemischter Bestand ist in diesem
Modus normal.

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
| 🟢 Grün | **Added** | Nicht im Snapshot — **nicht** zwingend neu in ASM |
| 🟡 Gelb | **Changed** | Geänderter Eintrag |
| 🔴 Rot | **Deleted** | Nicht mehr in den Quelldaten |
| ⚪ Weiß | **Unchanged** | Unveränderter Eintrag (standardmäßig ausgeblendet) |

Der Status beschreibt den Vergleich mit dem **lokalen Snapshot**, nicht mit ASM.
Bei Personen beantwortet die Spalte **In ASM** (`Ja` / `Nein` / `?`) die
eigentlich entscheidende Frage — siehe
[Wie ASM Konten identifiziert](#️-bevor-sie-starten-wie-asm-konten-identifiziert).

#### Spalte „Apply"

Jede Zeile mit Status Added, Changed oder Deleted hat ein Häkchen. Es bedeutet
je nach Status etwas anderes:

| Status | Häkchen gesetzt | Häkchen entfernt |
|--------|-----------------|------------------|
| **Added** | Datensatz wird geliefert (Konto entsteht oder bleibt) | Datensatz fehlt in der Lieferung — **ein vorhandenes Konto wird dadurch deaktiviert** |
| **Changed** | neue Werte werden geliefert | alte Werte aus dem Snapshot werden geliefert |
| **Deleted** | Löschung bestätigt, Datensatz entfällt | Datensatz wird erneut geliefert — **existiert er in ASM nicht, entsteht ein neues Konto** |

Nimmt man eine Person heraus, verlieren Zeilen, die auf sie verweisen, ihr Ziel.
Die App entfernt solche Verweise selbst — ASM lehnt eine Lieferung mit
ungültigen Verweisen sonst komplett ab — und benennt vorher, was betroffen ist:
Kurslehrkraft-Zuordnung wird geleert, Kursbelegungen der Person entfallen.

#### Schaltflächen pro Tab

| Schaltfläche | Funktion |
|-------------|----------|
| **Select All Added** | Alle hinzugefügten Zeilen markieren |
| **Select All Changed** | Alle geänderten Zeilen markieren |
| **Select All Deleted** | Alle gelöschten Zeilen markieren |
| **Show unchanged** | Unveränderte Zeilen ein-/ausblenden |
| **Approve All Changes** | Alle Änderungen (außer Löschungen) genehmigen |
| **Approve All Deletions** | Alle Löschungen bestätigen (mit Rückfrage) |
| **Keep all N deletions** | Alle Löschungen ablehnen, Datensätze behalten |

*Keep all N deletions* erscheint unten neben der Export-Sperre, solange
Löschungen unentschieden sind.

> ⚠️ **Wichtig:** Löschungen (rot) müssen **aktiv entschieden** werden — bestätigt
> oder abgelehnt. Bis dahin bleibt der Export gesperrt.

#### Export-Schaltflächen (unten)

| Schaltfläche | Funktion |
|-------------|----------|
| **Export ZIP** | ZIP-Datei lokal speichern |
| **Export & Upload** | ZIP erstellen und direkt zu Apple hochladen |

### Settings-Seite – Einstellungen

Die Settings-Seite ist in vier Bereiche unterteilt:

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

#### Updates

Die installierte App prüft beim Start im Hintergrund, ob auf GitHub eine neuere
Version veröffentlicht wurde (abschaltbar über *Check for updates when the app
starts*, gespeichert mit *Save Settings*). Ohne Internet bleibt es bei einer
Statuszeile – die App funktioniert normal weiter.

Ist eine neue Version verfügbar, erscheint ein Hinweis mit **Update now** (auch
über **Update Now** in den Settings):

1. Die ZIP-Datei der Version wird heruntergeladen (~115 MB) und gegen die von
   GitHub veröffentlichte SHA-256-Prüfsumme geprüft. Stimmt sie nicht, wird nichts installiert.
2. Die App schließt sich. Ein kleines Hilfsskript ersetzt den Programmordner und
   startet die neue Version.
3. Die bisherige Version bleibt als Ordner `ASM-Generator.old-<Version>` daneben
   liegen (nur die jeweils letzte). Einstellungen, Snapshot und Pins liegen in
   `%LOCALAPPDATA%` und sind nicht betroffen.

Das automatische Update verweigert sich – mit Link zum manuellen Download –, wenn:

- der Programmordner außer `ASM-Generator.exe` und `_internal` weitere Dateien
  enthält (z. B. direkt in *Downloads* entpackt). Legen Sie die App in einen eigenen Ordner.
- der Ordner nicht beschreibbar ist (z. B. unter *Program Files*).
- zu wenig Speicherplatz frei ist.

Versionen bis einschließlich v1.1.7 kennen ihre eigene Versionsnummer noch nicht
und müssen **einmal manuell** aktualisiert werden. Aus dem Quellcode gestartet wird
nie nach Updates gesucht.

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

Optionale Standort-Zuordnungstabelle für `location_id` → `location_name`.
Als Vorlage liegt `locations.example.csv` im Repository:

```csv
location_id,location_name
LOC001,Beispielschule Musterstadt
```

Kopieren Sie die Datei nach `locations.csv` und tragen Sie Ihre Werte ein — die
`location_id` muss der Einstellung *Location ID* entsprechen. Fehlt die Datei,
verwendet der Export die `location_id` auch als Namen; das ist gültig, nur
weniger lesbar.

> `locations.csv` und `teacher_aliases.json` sind bewusst von der
> Versionskontrolle ausgenommen, da sie Ihre Schule bzw. reale Personen
> benennen. Versioniert sind nur die Vorlagen `locations.example.csv` und
> `teacher_aliases.empty.json`.

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
| **Status bleibt auf „Checking SFTP connection…“** | Die Verbindungsprüfung läuft im Hintergrund (max. 15 s) und blockiert das Fenster nicht. Bleibt es bei „Connection timed out“, blockiert das Netzwerk ausgehenden Port 22 – Export und ZIP funktionieren weiterhin, nur der Upload ist deaktiviert. |
| **„paramiko is not installed“** | `pip install paramiko` ausführen |
| **CSV wird nicht erkannt / Encoding-Fehler** | Die App erkennt automatisch UTF-8, UTF-8-SIG und (via chardet) andere Encodings |
| **Snapshot beschädigt** | `%LOCALAPPDATA%\ASMGenerator\snapshot.json` löschen – die App behandelt den nächsten Lauf als Ersteinrichtung |
| **Einstellungen zurücksetzen** | `%LOCALAPPDATA%\ASMGenerator\settings.json` löschen. Nicht zusammen mit `snapshot.json` löschen, wenn es in ASM schon Personalkonten gibt: ohne beide Dateien gilt die Installation als neu, und *Staff ID source* springt auf `interne_id` – das ersetzt beim nächsten Upload jedes Personalkonto |
| **SFTP-Passwort vergessen** | Im Windows-Credential-Manager unter „Windows-Anmeldeinformationen“ nach „asm-generator-sftp“ suchen |
