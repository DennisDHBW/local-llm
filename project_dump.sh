#!/bin/bash

# Konfiguration
# 1. Argument: Zielverzeichnis (Standard: aktuelles Verzeichnis)
# 2. Argument: Name der Ausgabedatei (Standard: project_content.txt)
TARGET_DIR="${1:-.}"
OUTPUT_FILE="${2:-project_content.txt}"

# Hier kannst du die gewünschten Dateiendungen anpassen
EXTENSIONS=("py" "json")

echo "Starte Zusammenstellung für: $TARGET_DIR"

{
    echo "=================================================="
    echo "PROJEKTSTRUKTUR"
    echo "=================================================="
    echo "Verzeichnis: $(realpath "$TARGET_DIR")"
    echo ""

    # Projektstruktur ausgeben (nutzt 'tree', falls vorhanden, sonst Fallback)
    if command -v tree &> /dev/null; then
        tree "$TARGET_DIR" -I ".git|venv|__pycache__|node_modules|.env"
    else
        find "$TARGET_DIR" -not -path '*/.*' -not -path '*/venv*' -print | sed -e 's;[^/]*/;|-- ;g;s;-- |;  |;g'
    fi

    echo ""
    echo "=================================================="
    echo "DATEINHALTE"
    echo "=================================================="
    echo ""

    # Dynamischen Suchfilter für die Dateiendungen zusammenbauen
    find_args=()
    first=true
    for ext in "${EXTENSIONS[@]}"; do
        if [ "$first" = true ]; then
            find_args+=( -name "*.$ext" )
            first=false
        else
            find_args+=( -o -name "*.$ext" )
        fi
    done

    # Dateien finden (unter Ausschluss von Ordnern wie .git, venv, etc.) und Inhalte anhängen
    find "$TARGET_DIR" \
        \( -name ".git" -o -name "venv" -o -name "__pycache__" -o -name "node_modules" -o -name ".env" \) -prune \
        -o -type f \( "${find_args[@]}" \) -print | sort | while read -r file; do

        if [ -f "$file" ]; then
            echo "--------------------------------------------------"
            echo "DATEI: $file"
            echo "--------------------------------------------------"
            cat "$file"
            echo -e "\n\n"
        fi
    done

} > "$OUTPUT_FILE"

echo "Fertig! Alle Inhalte wurden erfolgreich in '$OUTPUT_FILE' gespeichert."