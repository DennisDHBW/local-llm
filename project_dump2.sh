#!/usr/bin/env bash

# ==============================================================================
# KONFIGURATION / VARIABLEN (Hier deine Einstellungen anpassen)
# ==============================================================================

# 1. Dateiendungen, die berücksichtigt werden sollen (durch Leerzeichen getrennt)
# Beispiel: EXTENSIONS=("py" "json" "sh" "md")
EXTENSIONS=("py" "json")

# 2. Unterordner, die rekursiv durchsucht werden sollen (durch Leerzeichen getrennt)
# - Wenn die Liste LEER ist (INCLUDE_SUBDIRS=()), wird NUR der aktuelle Ordner durchsucht.
# - Wenn Ordner eingetragen sind (z. B. INCLUDE_SUBDIRS=("src" "config")), werden diese rekursiv durchsucht.
INCLUDE_SUBDIRS=("src" "config")

# 3. Name der Ausgabedatei
OUTPUT_FILE="output.txt"

# ==============================================================================
# SKRIPT-LOGIK
# ==============================================================================

# Ausgabedatei zurücksetzen/erstellen
> "$OUTPUT_FILE"

# 1. Verzeichnisbaum ganz oben ausgeben
echo "==================================================" >> "$OUTPUT_FILE"
echo "VERZEICHNISBAUM (Gesamtes Verzeichnis)" >> "$OUTPUT_FILE"
echo "==================================================" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"

if command -v tree &> /dev/null; then
    tree -a -I ".git|node_modules|__pycache__|.venv|venv" >> "$OUTPUT_FILE"
else
    # Fallback, falls 'tree' nicht installiert ist
    find . -maxdepth 4 | sed -e 's;[^/]*/;|--;g' -e 's;--|; |;g' >> "$OUTPUT_FILE"
fi

echo "" >> "$OUTPUT_FILE"
echo "==================================================" >> "$OUTPUT_FILE"
echo "DATEIINHALTE" >> "$OUTPUT_FILE"
echo "==================================================" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"

# Find-Suchmuster für Endungen aufbauen
FIND_EXT_ARGS=()
first=true

for ext in "${EXTENSIONS[@]}"; do
    # Führenden Punkt entfernen, falls versehentlich angegeben (z. B. .py -> py)
    ext="${ext#.}"
    if [ "$first" = true ]; then
        first=false
    else
        FIND_EXT_ARGS+=("-o")
    fi
    FIND_EXT_ARGS+=("-name" "*.$ext")
done

# Funktion zum Suchen und Anhängen der Dateien
process_files() {
    local max_depth="$1"
    shift
    local search_paths=("$@")

    if [ ${#FIND_EXT_ARGS[@]} -eq 0 ]; then
        echo "Fehler: Keine Dateiendungen in EXTENSIONS definiert!" >&2
        return
    fi

    find "${search_paths[@]}" $max_depth \( "${FIND_EXT_ARGS[@]}" \) -type f | while read -r file; do
        # Ausgabedatei selbst nicht einlesen
        if [ "$file" == "./$OUTPUT_FILE" ] || [ "$file" == "$OUTPUT_FILE" ]; then
            continue
        fi

        echo "--------------------------------------------------" >> "$OUTPUT_FILE"
        echo "FILE: $file" >> "$OUTPUT_FILE"
        echo "--------------------------------------------------" >> "$OUTPUT_FILE"
        cat "$file" >> "$OUTPUT_FILE"
        echo -e "\n" >> "$OUTPUT_FILE"
    done
}

# 2. Dateien suchen & Inhalte anhängen
if [ ${#INCLUDE_SUBDIRS[@]} -eq 0 ]; then
    # Keine Unterordner angegeben -> Nur im aktuellen Ordner (ohne Unterordner)
    process_files "-maxdepth 1" "."
else
    # Unterordner überprüfen und verarbeiten
    VALID_DIRS=()
    for dir in "${INCLUDE_SUBDIRS[@]}"; do
        if [ -d "$dir" ]; then
            VALID_DIRS+=("$dir")
        else
            echo "Hinweis: Ordner '$dir' existiert nicht und wird übersprungen." >&2
        fi
    done

    if [ ${#VALID_DIRS[@]} -gt 0 ]; then
        process_files "" "${VALID_DIRS[@]}"
    fi
fi

echo "Fertig! Die Inhalte wurden in '$OUTPUT_FILE' gespeichert."