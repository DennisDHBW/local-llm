#!/usr/bin/env bash
# ==============================================================================
# Skript: export_project.sh
# ./export_project.sh -x 'tests/*' -x 'scripts/*' . projekt_export.txt
#
#
# Exportiert ein Code-Projekt in EINE Textdatei, die alles enthält, um das
# Projekt zu verstehen (z. B. zum Weitergeben an ein LLM oder für ein Review):
#
#   1. Übersicht   – Pfad, Datum, Git-Stand, erkannte Technologien, Statistik
#   2. Projektbaum – alle Dateien; nicht exportierte sind mit [Grund] markiert
#   3. Inhalte     – jede relevante Textdatei mit Pfad als Überschrift,
#                    README und Konfigurationsdateien zuerst
#
# Standardmäßig ausgelassen: Abhängigkeiten (node_modules, venv, vendor …),
# Build-Artefakte, Caches, Lockfiles, Binär-/Mediendateien, minifizierte
# Dateien, Logs und mögliche Zugangsdaten (.env, Schlüssel). In Git-Repos
# wird zusätzlich die .gitignore beachtet.
#
# Aufruf:
#   ./export_project.sh [Optionen] [Zielordner] [Ausgabedatei]
#
# Optionen:
#   -m KB   Maximale Dateigröße in KB (Standard: 256). Größere Dateien
#           erscheinen nur im Baum.
#   -n N    Zeilen, die von Datendateien (csv, tsv, jsonl) gezeigt werden
#           (Standard: 20).
#   -x MUSTER  Zusätzliche Pfade ausschließen (Glob relativ zum Projekt,
#           mehrfach nutzbar), z. B. -x 'tests/*' -x 'scripts/*'.
#   -G      .gitignore nicht beachten (Dateisystem-Suche statt git ls-files).
#   -h      Hilfe anzeigen.
# ==============================================================================

set -o pipefail

# --- KONFIGURATION ------------------------------------------------------------

# Ordner, deren Inhalt nie exportiert wird (Glob-Muster erlaubt)
EXCLUDE_DIRS=(
  # Versionskontrolle
  ".git" ".hg" ".svn"
  # Abhängigkeiten / virtuelle Umgebungen
  "node_modules" "bower_components" "jspm_packages" "vendor"
  "venv" ".venv" "site-packages" ".eggs" "*.egg-info" "Pods" ".dart_tool" ".pub-cache"
  # Build-Ausgaben
  "build" "dist" "out" "target" ".next" ".nuxt" ".svelte-kit" ".angular" ".output"
  ".gradle" "DerivedData" ".terraform" ".serverless"
  # Caches / Testberichte
  "__pycache__" ".pytest_cache" ".mypy_cache" ".ruff_cache" ".tox" ".nox"
  ".cache" ".parcel-cache" ".turbo" "coverage" "htmlcov" ".nyc_output" ".ipynb_checkpoints"
  # Editor / IDE
  ".vscode" ".idea" ".vs"
)

# Dateiendungen, die nie exportiert werden (ohne Punkt, Groß-/Kleinschreibung egal)
EXCLUDE_EXTS=(
  # Bilder / Grafiken
  "png" "jpg" "jpeg" "gif" "bmp" "tif" "tiff" "webp" "ico" "icns" "svg" "psd"
  # Schriften
  "woff" "woff2" "ttf" "otf" "eot"
  # Audio / Video
  "mp3" "mp4" "wav" "ogg" "flac" "avi" "mov" "mkv" "webm"
  # Archive / Images
  "zip" "tar" "gz" "tgz" "bz2" "xz" "7z" "rar" "jar" "war" "iso" "dmg" "img"
  # Kompilate / Bibliotheken
  "exe" "dll" "so" "dylib" "a" "o" "obj" "class" "pyc" "pyo" "pyd" "wasm" "bin"
  # Office / PDF
  "pdf" "doc" "docx" "xls" "xlsx" "ppt" "pptx" "odt" "ods"
  # Datenbanken / ML-Modelle / Binärdaten
  "db" "sqlite" "sqlite3" "parquet" "feather" "h5" "hdf5" "pkl" "pickle"
  "npy" "npz" "pt" "pth" "onnx" "safetensors" "gguf" "ckpt"
)

# Lockfiles (automatisch erzeugt, lang, für das Verständnis unnötig)
LOCK_PATTERNS=(
  "package-lock.json" "npm-shrinkwrap.json" "yarn.lock" "pnpm-lock.yaml" "bun.lockb"
  "poetry.lock" "Pipfile.lock" "uv.lock" "pdm.lock" "Cargo.lock" "composer.lock"
  "Gemfile.lock" "go.sum" "flake.lock" "packages.lock.json"
)

# Generierte oder irrelevante Dateien
EXCLUDE_PATTERNS=(
  "*.min.js" "*.min.css" "*.map" "*.bundle.js" "*.chunk.js"
  "*.log" ".DS_Store" "Thumbs.db" "desktop.ini"
)

# Mögliche Zugangsdaten – werden NIE exportiert …
SECRET_PATTERNS=(
  ".env" ".env.*" "*.pem" "*.key" "*.p12" "*.pfx" "*.jks" "*.keystore" "*.kdbx"
  "id_rsa*" "id_ed25519*" "id_ecdsa*" ".netrc" ".pypirc" ".npmrc"
)
# … außer es sind offensichtlich Vorlagen
SECRET_ALLOW_PATTERNS=("*.example" "*.sample" "*.template" "*.dist")

# Datendateien: nur die ersten N Zeilen als Beispiel zeigen
DATA_EXTS=("csv" "tsv" "jsonl" "ndjson")

# Wichtige Dateien im Projektstamm, die zuerst gezeigt werden (in dieser Reihenfolge)
PRIORITY_PATTERNS=(
  "README*" "*.md" "*.rst" "pyproject.toml" "setup.py" "setup.cfg" "requirements*.txt" "Pipfile" "environment.yml"
  "package.json" "tsconfig.json" "go.mod" "Cargo.toml" "pom.xml" "build.gradle*" "settings.gradle*"
  "composer.json" "Gemfile" "*.csproj" "*.sln" "CMakeLists.txt" "Makefile" "Dockerfile*"
  "docker-compose*.y*ml" "compose*.y*ml" ".env.example" ".env.sample" ".gitignore"
)

MAX_KB=256
DATA_LINES=20
USE_GITIGNORE=1
USER_EXCLUDES=()

# Pfad dieses Skripts (es soll sich nicht selbst exportieren)
SELF_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

# --- ARGUMENTE ----------------------------------------------------------------

usage() {
  cat <<'EOF'
Aufruf: ./export_project.sh [Optionen] [Zielordner] [Ausgabedatei]

  Zielordner     Projektordner (Standard: aktueller Ordner)
  Ausgabedatei   Exportdatei   (Standard: projekt_export.txt)

Optionen:
  -m KB   Maximale Dateigröße in KB (Standard: 256)
  -n N    Zeilen, die von Datendateien gezeigt werden (Standard: 20)
  -x MUSTER  Zusätzliche Pfade ausschließen, mehrfach nutzbar
          (Glob relativ zum Projekt, z. B. -x 'tests/*' -x 'scripts/*')
  -G      .gitignore nicht beachten
  -h      Diese Hilfe anzeigen
EOF
}

while getopts ":m:n:x:Gh" opt; do
  case "$opt" in
    m) MAX_KB="$OPTARG" ;;
    n) DATA_LINES="$OPTARG" ;;
    x) USER_EXCLUDES+=("$OPTARG") ;;
    G) USE_GITIGNORE=0 ;;
    h) usage; exit 0 ;;
    :)  echo "[FEHLER] Option -$OPTARG braucht einen Wert." >&2; exit 1 ;;
    \?) echo "[FEHLER] Unbekannte Option -$OPTARG." >&2; usage >&2; exit 1 ;;
  esac
done
shift $((OPTIND - 1))

if ! [[ "$MAX_KB" =~ ^[0-9]+$ && "$DATA_LINES" =~ ^[0-9]+$ ]]; then
  echo "[FEHLER] -m und -n erwarten ganze Zahlen." >&2
  exit 1
fi

TARGET_DIR="${1:-.}"
OUTPUT_FILE="${2:-projekt_export.txt}"

if [ ! -d "$TARGET_DIR" ]; then
  echo "[FEHLER] Ordner '$TARGET_DIR' existiert nicht." >&2
  exit 1
fi

ABS_TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
PROJECT_NAME="$(basename "$ABS_TARGET_DIR")"

# Ausgabedatei anlegen und absoluten Pfad bestimmen (damit sie sich nicht selbst einliest)
if ! : > "$OUTPUT_FILE"; then
  echo "[FEHLER] Ausgabedatei '$OUTPUT_FILE' kann nicht geschrieben werden." >&2
  exit 1
fi
ABS_OUTPUT_FILE="$(cd "$(dirname "$OUTPUT_FILE")" && pwd)/$(basename "$OUTPUT_FILE")"

# Git verwenden, wenn möglich (beachtet .gitignore)
USE_GIT=0
if [ "$USE_GITIGNORE" -eq 1 ] && command -v git >/dev/null 2>&1 \
   && git -C "$ABS_TARGET_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  USE_GIT=1
fi

MAX_BYTES=$((MAX_KB * 1024))
SEP="================================================================================"
SUBSEP="--------------------------------------------------------------------------------"

info() { echo "[INFO] $*"; }

info "Starte Projekt-Export..."
info "Quellverzeichnis (Absolut): $ABS_TARGET_DIR"
info "Ausgabedatei:              $ABS_OUTPUT_FILE"
if [ "$USE_GIT" -eq 1 ]; then
  info "Dateiauswahl:              git ls-files (.gitignore wird beachtet)"
else
  info "Dateiauswahl:              Dateisystem-Suche"
fi
echo "$SUBSEP"

# --- HILFSFUNKTIONEN ----------------------------------------------------------

# Prüft, ob $1 auf eines der folgenden Glob-Muster passt (ohne Groß-/Kleinschreibung)
matches_any() {
  local s="$1" p
  shift
  shopt -s nocasematch
  for p in "$@"; do
    if [[ "$s" == $p ]]; then shopt -u nocasematch; return 0; fi
  done
  shopt -u nocasematch
  return 1
}

# Liegt der relative Pfad in einem ausgeschlossenen Ordner?
in_excluded_dir() {
  local -a parts
  local i
  IFS='/' read -r -a parts <<< "$1"
  for (( i = 0; i < ${#parts[@]} - 1; i++ )); do
    matches_any "${parts[$i]}" "${EXCLUDE_DIRS[@]}" && return 0
  done
  return 1
}

# Reine Textdatei? (NUL-Bytes => binär)
is_text_file() {
  LC_ALL=C grep -Iq '' "$1" 2>/dev/null
}

file_size() {
  wc -c < "$1" | tr -d ' '
}

fmt_size() {
  awk -v b="$1" 'BEGIN {
    if (b < 1024) printf "%d B", b
    else if (b < 1048576) printf "%.1f KB", b / 1024
    else printf "%.1f MB", b / 1048576
  }'
}

file_ext() {
  local name="${1##*/}"
  name="${name#.}"                       # ".gitignore" hat keine Endung
  if [[ "$name" == *.* ]]; then
    printf '%s' "${name##*.}" | tr '[:upper:]' '[:lower:]'
  fi
}

# Entscheidet, ob/wie eine Datei exportiert wird.
# Setzt REASON (leer = exportieren) und MODE (full | empty | sample | notebook)
classify_file() {
  local abs="$1" rel="$2" name ext size
  name="${abs##*/}"
  ext="$(file_ext "$abs")"
  REASON=""
  MODE="full"

  if [ "$abs" -ef "$SELF_PATH" ] \
     || head -n 5 "$abs" 2>/dev/null | grep -q '^# Skript: export_project.sh'; then
    REASON="dieses Export-Skript"; return
  fi
  if [ ${#USER_EXCLUDES[@]} -gt 0 ] && matches_any "$rel" "${USER_EXCLUDES[@]}"; then
    REASON="per -x ausgeschlossen"; return
  fi

  if matches_any "$name" "${SECRET_PATTERNS[@]}" \
     && ! matches_any "$name" "${SECRET_ALLOW_PATTERNS[@]}"; then
    REASON="mögliche Zugangsdaten"; return
  fi
  if matches_any "$name" "${LOCK_PATTERNS[@]}"; then
    REASON="Lockfile"; return
  fi
  if matches_any "$name" "${EXCLUDE_PATTERNS[@]}"; then
    REASON="generiert/irrelevant"; return
  fi
  if [ -n "$ext" ] && matches_any "$ext" "${EXCLUDE_EXTS[@]}"; then
    REASON="binär/Medien"; return
  fi

  size="$(file_size "$abs")"
  if [ "$size" -eq 0 ]; then
    REASON="leer"; MODE="empty"; return
  fi
  if [ "$ext" = "ipynb" ] && command -v python3 >/dev/null 2>&1; then
    MODE="notebook"; return
  fi
  if ! is_text_file "$abs"; then
    REASON="binär"; return
  fi
  if head -n 2 "$abs" 2>/dev/null | grep -q '^PROJEKT-EXPORT: '; then
    REASON="früherer Export"; return
  fi
  if [ -n "$ext" ] && matches_any "$ext" "${DATA_EXTS[@]}"; then
    MODE="sample"; return
  fi
  if [ "$size" -gt "$MAX_BYTES" ]; then
    REASON="zu groß, $(fmt_size "$size")"; return
  fi
}

# Sprache/Art einer Datei für die Überschrift
lang_of() {
  local name="${1##*/}"
  case "$name" in
    Dockerfile*) echo "Dockerfile"; return ;;
    Makefile|makefile|GNUmakefile) echo "Makefile"; return ;;
    CMakeLists.txt) echo "CMake"; return ;;
  esac
  case "$(file_ext "$1")" in
    py) echo "Python" ;;            ipynb) echo "Jupyter-Notebook" ;;
    js|mjs|cjs) echo "JavaScript" ;; jsx) echo "JavaScript/React" ;;
    ts|mts|cts) echo "TypeScript" ;; tsx) echo "TypeScript/React" ;;
    java) echo "Java" ;;            kt|kts) echo "Kotlin" ;;
    go) echo "Go" ;;                rs) echo "Rust" ;;
    c|h) echo "C" ;;                cpp|cc|cxx|hpp|hh) echo "C++" ;;
    cs) echo "C#" ;;                php) echo "PHP" ;;
    rb) echo "Ruby" ;;              swift) echo "Swift" ;;
    r) echo "R" ;;                  scala) echo "Scala" ;;
    sh|bash|zsh) echo "Shell" ;;    ps1) echo "PowerShell" ;;
    sql) echo "SQL" ;;              html|htm) echo "HTML" ;;
    css) echo "CSS" ;;              scss|sass|less) echo "SCSS/Less" ;;
    vue) echo "Vue" ;;              svelte) echo "Svelte" ;;
    md|markdown) echo "Markdown" ;; rst) echo "reStructuredText" ;;
    json) echo "JSON" ;;            yml|yaml) echo "YAML" ;;
    toml) echo "TOML" ;;            ini|cfg|conf) echo "Konfiguration" ;;
    xml) echo "XML" ;;              csv|tsv) echo "Tabellendaten" ;;
    jsonl|ndjson) echo "JSON Lines" ;;
    *) echo "" ;;
  esac
}

# Jupyter-Notebook ohne Ausgaben (Bilder, Tabellen …) als Text
notebook_to_text() {
  python3 - "$1" 2>/dev/null <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    nb = json.load(f)
for i, cell in enumerate(nb.get("cells", []), 1):
    src = cell.get("source", "")
    if isinstance(src, list):
        src = "".join(src)
    print(f"# ---- Zelle {i} [{cell.get('cell_type', '?')}] ----")
    print(src.rstrip("\n"))
    print()
PY
}

# Liefert alle Kandidaten-Dateien (relativ, NUL-getrennt)
NAME_EXPR=()
for i in "${!EXCLUDE_DIRS[@]}"; do
  [ "$i" -gt 0 ] && NAME_EXPR+=("-o")
  NAME_EXPR+=("-name" "${EXCLUDE_DIRS[$i]}")
done

list_files() {
  if [ "$USE_GIT" -eq 1 ]; then
    git -C "$ABS_TARGET_DIR" ls-files -z --cached --others --exclude-standard
  else
    (cd "$ABS_TARGET_DIR" && find . -type d \( "${NAME_EXPR[@]}" \) -prune -o -type f -print0)
  fi
}

# Ausgelassene Ordner (nur bei Dateisystem-Suche), damit sie im Baum sichtbar sind
list_pruned_dirs() {
  (cd "$ABS_TARGET_DIR" && find . -mindepth 1 -type d \( "${NAME_EXPR[@]}" \) -prune -print0)
}

# --- 1. DATEIEN SAMMELN UND EINORDNEN ----------------------------------------

info "Sammle und prüfe Dateien..."

TREE_LIST="$(mktemp)" || exit 1
BODY_FILE="$(mktemp)" || exit 1
trap 'rm -f "$TREE_LIST" "$BODY_FILE"' EXIT

EXPORT_FILES=()
skipped=0
empty_files=0
pruned_dirs=0

while IFS= read -r -d '' rel; do
  rel="${rel#./}"
  abs="$ABS_TARGET_DIR/$rel"
  [ -f "$abs" ] || continue
  [ "$abs" -ef "$ABS_OUTPUT_FILE" ] && continue
  in_excluded_dir "$rel" && continue

  classify_file "$abs" "$rel"
  if [ "$MODE" = "empty" ]; then
    printf '%s\t  [leer]\n' "$rel" >> "$TREE_LIST"
    empty_files=$((empty_files + 1))
  elif [ -n "$REASON" ]; then
    printf '%s\t  [nicht exportiert: %s]\n' "$rel" "$REASON" >> "$TREE_LIST"
    skipped=$((skipped + 1))
  else
    printf '%s\t\n' "$rel" >> "$TREE_LIST"
    EXPORT_FILES+=("$rel")
  fi
done < <(list_files)

if [ "$USE_GIT" -eq 0 ]; then
  while IFS= read -r -d '' rel; do
    rel="${rel#./}"
    [ "${rel##*/}" = ".git" ] && continue
    printf '%s\t/  [Ordner nicht exportiert]\n' "$rel" >> "$TREE_LIST"
    pruned_dirs=$((pruned_dirs + 1))
  done < <(list_pruned_dirs)
fi

# --- AUSWERTUNG FÜR DIE ÜBERSICHT --------------------------------------------

# Gibt es irgendwo im Projekt eine Datei, deren Name auf die Regex $1 passt?
has_file() {
  grep -qE "(^|/)$1"$'\t' "$TREE_LIST"
}

detect_tech() {
  local t=()
  has_file 'package\.json'                                   && t+=("JavaScript/Node.js")
  has_file 'tsconfig\.json'                                  && t+=("TypeScript")
  has_file '(pyproject\.toml|requirements[^/]*\.txt|setup\.py|Pipfile|environment\.ya?ml)' && t+=("Python")
  has_file '[^/]*\.ipynb'                                    && t+=("Jupyter")
  has_file 'go\.mod'                                         && t+=("Go")
  has_file 'Cargo\.toml'                                     && t+=("Rust")
  has_file '(pom\.xml|build\.gradle(\.kts)?)'                && t+=("Java/Kotlin (JVM)")
  has_file '[^/]*\.(csproj|sln)'                             && t+=(".NET")
  has_file 'composer\.json'                                  && t+=("PHP")
  has_file 'Gemfile'                                         && t+=("Ruby")
  has_file 'CMakeLists\.txt'                                 && t+=("C/C++ (CMake)")
  has_file '(Dockerfile[^/]*|(docker-)?compose[^/]*\.ya?ml)' && t+=("Docker")
  if [ ${#t[@]} -eq 0 ]; then
    echo "(keine erkannt)"
  else
    local IFS=","
    echo "${t[*]}" | sed 's/,/, /g'
  fi
}

type_stats() {
  [ ${#EXPORT_FILES[@]} -eq 0 ] && { echo "-"; return; }
  local f e
  for f in "${EXPORT_FILES[@]}"; do
    e="$(file_ext "$f")"
    echo "${e:-${f##*/}}"
  done | sort | uniq -c | sort -rn | head -10 \
    | awk '{ printf "%s%s (%d)", (NR > 1 ? ", " : ""), $2, $1 } END { print "" }'
}

# Exportierte Dateien sortieren: Stamm-Prioritätsdateien, dann READMEs, dann alphabetisch
ordered_export_files() {
  local f i rank
  for f in "${EXPORT_FILES[@]}"; do
    rank=9999
    if [[ "$f" != */* ]]; then
      for i in "${!PRIORITY_PATTERNS[@]}"; do
        if matches_any "$f" "${PRIORITY_PATTERNS[$i]}"; then rank=$i; break; fi
      done
    fi
    if [ "$rank" -eq 9999 ] && matches_any "${f##*/}" "README*"; then
      rank=5000
    fi
    printf '%04d\t%s\n' "$rank" "$f"
  done | LC_ALL=C sort | cut -f2-
}

# Projektbaum aus der sortierten Pfadliste zeichnen
render_tree() {
  echo "$PROJECT_NAME/"
  LC_ALL=C sort -t $'\t' -k1,1 "$TREE_LIST" | awk -F'\t' '
    function ind(d,   s, x) { s = "  "; for (x = 1; x < d; x++) s = s "  "; return s }
    {
      n = split($1, p, "/")
      i = 1
      while (i < n && i <= pn && p[i] == prev[i]) i++
      for (j = i; j < n; j++) print ind(j) p[j] "/"
      print ind(n) p[n] $2
      for (k = 1; k < n; k++) prev[k] = p[k]
      pn = n - 1
    }'
}

write_file_block() {
  local rel="$1" abs="$ABS_TARGET_DIR/$1" lang size lines meta
  classify_file "$abs" "$rel"
  lang="$(lang_of "$rel")"
  size="$(file_size "$abs")"
  lines="$(wc -l < "$abs" | tr -d ' ')"
  [ -n "$(tail -c1 "$abs")" ] && lines=$((lines + 1))   # letzte Zeile ohne Zeilenumbruch

  if [ "$MODE" = "notebook" ]; then
    meta="$(fmt_size "$size")"
  else
    meta="$lines Zeilen, $(fmt_size "$size")"
  fi
  [ -n "$lang" ] && meta="$lang, $meta"

  echo
  echo "$SUBSEP"
  echo "DATEI: $rel  ($meta)"
  echo "$SUBSEP"

  case "$MODE" in
    notebook)
      echo "(Jupyter-Notebook: nur Zellinhalte, Ausgaben entfernt)"
      echo
      notebook_to_text "$abs" || cat "$abs"
      ;;
    sample)
      if [ "$lines" -gt "$DATA_LINES" ]; then
        echo "(Datendatei: erste $DATA_LINES von $lines Zeilen)"
        echo
      fi
      head -n "$DATA_LINES" "$abs"
      [ -n "$(head -n "$DATA_LINES" "$abs" | tail -c1)" ] && echo
      [ "$lines" -gt "$DATA_LINES" ] && echo "[… gekürzt …]"
      ;;
    *)
      cat "$abs"
      [ -n "$(tail -c1 "$abs")" ] && echo
      ;;
  esac
}

# --- 2. AUSGABEDATEI SCHREIBEN -----------------------------------------------

info "Schreibe Übersicht, Projektbaum und Dateiinhalte..."

# Baum und Inhalte zuerst in eine Temp-Datei, damit der Kopf die Gesamtgröße kennt
{
  echo "$SEP"
  echo "1. PROJEKTBAUM"
  echo "$SEP"
  render_tree
  echo
  echo "$SEP"
  echo "2. DATEIINHALTE"
  echo "$SEP"
  while IFS= read -r rel; do
    [ -n "$rel" ] && write_file_block "$rel"
  done < <(ordered_export_files)
  echo
  echo "$SEP"
  echo "ENDE DES EXPORTS"
  echo "$SEP"
} > "$BODY_FILE"

BODY_BYTES="$(file_size "$BODY_FILE")"
TOKEN_ESTIMATE=$(( (BODY_BYTES + 3) / 4 ))   # Faustregel: ~4 Zeichen pro Token

{
  echo "$SEP"
  echo "PROJEKT-EXPORT: $PROJECT_NAME"
  echo "$SEP"
  echo "Quellverzeichnis : $ABS_TARGET_DIR"
  echo "Erstellt am      : $(date '+%Y-%m-%d %H:%M')"
  if [ "$USE_GIT" -eq 1 ]; then
    echo "Dateiauswahl     : git ls-files (.gitignore beachtet)"
    branch="$(git -C "$ABS_TARGET_DIR" symbolic-ref --short -q HEAD 2>/dev/null \
              || git -C "$ABS_TARGET_DIR" rev-parse --short HEAD 2>/dev/null)"
    last_commit="$(git -C "$ABS_TARGET_DIR" log -1 --format='%h – %s (%ad)' --date=short 2>/dev/null)"
    [ -n "$branch" ]      && echo "Git-Branch       : $branch"
    [ -n "$last_commit" ] && echo "Letzter Commit   : $last_commit"
  else
    echo "Dateiauswahl     : Dateisystem-Suche"
  fi
  if [ ${#USER_EXCLUDES[@]} -gt 0 ]; then
    echo "Zusätzlich aus.  : ${USER_EXCLUDES[*]}"
  fi
  echo "Technologien     : $(detect_tech)"
  echo "Dateien          : ${#EXPORT_FILES[@]} exportiert, $empty_files leer, $skipped nur im Baum gelistet"
  echo "Dateitypen       : $(type_stats)"
  echo "Umfang           : $(fmt_size "$BODY_BYTES"), ca. $TOKEN_ESTIMATE Tokens (grobe Schätzung)"
  echo
  echo "Aufbau dieser Datei:"
  echo "  1. PROJEKTBAUM  – alle Dateien des Projekts. Einträge mit [nicht exportiert: …]"
  echo "                    existieren, ihr Inhalt fehlt hier aber (Grund in Klammern)."
  echo "                    [leer] = leere Datei. Abhängigkeits-, Build- und Cache-Ordner"
  echo "                    sind ausgelassen."
  echo "  2. DATEIINHALTE – jede Datei beginnt mit 'DATEI: <Pfad relativ zum Projekt>'."
  echo "                    README und Projektdokumentation zuerst, dann Konfiguration,"
  echo "                    danach alphabetisch. Datendateien sind gekürzt, Notebooks"
  echo "                    ohne Zellausgaben."
  echo
  cat "$BODY_FILE"
} > "$ABS_OUTPUT_FILE"

# --- ABSCHLUSS ---------------------------------------------------------------

echo "$SUBSEP"
info "Fertig!"
info "${#EXPORT_FILES[@]} Textdatei(en) exportiert, $empty_files leer, $skipped nur im Baum gelistet."
info "Umfang: ca. $TOKEN_ESTIMATE Tokens (grobe Schätzung)."
[ "$pruned_dirs" -gt 0 ] && info "$pruned_dirs Ordner ausgelassen (Abhängigkeiten, Build, Cache …)."
info "Datei erfolgreich erstellt: $ABS_OUTPUT_FILE ($(fmt_size "$(file_size "$ABS_OUTPUT_FILE")"))"
