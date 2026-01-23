#!/usr/bin/env bash

# Script to recursively find files with specific extensions and concatenate their contents
# Cross-platform: Linux, macOS, Git Bash on Windows
#
# Usage: concat_files <extension1> [extension2] ... [options]
#
# Options:
#   --dir=PATH        Search directory (default: current directory)
#   --lines=N         Max lines per file (default: unlimited)
#   --max-total=N     Stop after N total lines (default: unlimited)
#   --exclude=PATTERN Exclude pattern (repeatable, e.g., --exclude=test --exclude=vendor)
#   --gitignore       Respect .gitignore rules (requires git)
#   --format=FORMAT   Output format: plain (default), markdown, xml
#   --sort=ORDER      Sort order: alpha (default), mtime, size
#   --dry-run         Show stats without creating output file
#   --stdout          Output to stdout instead of file
#
# Examples:
#   concat_files py                              # All Python files
#   concat_files py js --dir=./src               # Python and JS in src/
#   concat_files py --exclude=test --lines=50    # Skip test dirs, limit per file
#   concat_files py --dry-run                    # Show what would be concatenated
#   concat_files py --stdout | xclip             # Pipe to clipboard (Linux)
#   concat_files py --stdout | pbcopy            # Pipe to clipboard (macOS)
#   concat_files py --format=markdown            # Output with code fences
#   concat_files py --gitignore                  # Respect .gitignore
#   concat_files py --sort=mtime                 # Most recently modified first

set -euo pipefail

# Detect OS
detect_os() {
    case "$(uname -s)" in
        Linux*)     echo "linux" ;;
        Darwin*)    echo "macos" ;;
        CYGWIN*)    echo "cygwin" ;;
        MINGW*)     echo "mingw" ;;
        MSYS*)      echo "msys" ;;
        *)          echo "unknown" ;;
    esac
}

OS_TYPE=$(detect_os)

# Defaults
SEARCH_DIR="."
MAX_LINES=0          # 0 = no limit
MAX_TOTAL=0          # 0 = no limit
DRY_RUN=false
USE_STDOUT=false
USE_GITIGNORE=false
OUTPUT_FORMAT="plain"  # plain, markdown, xml
SORT_ORDER="alpha"     # alpha, mtime, size
EXTENSIONS=()
EXCLUDES=()

# Default exclusions (common non-source directories)
DEFAULT_EXCLUDES=(
    "node_modules"
    ".git"
    "__pycache__"
    ".venv"
    "venv"
    ".tox"
    ".pytest_cache"
    ".mypy_cache"
    ".ruff_cache"
    "dist"
    "build"
    "*.egg-info"
    ".next"
    ".nuxt"
    "coverage"
    ".coverage"
    "htmlcov"
    "target"        # Rust/Java
    "vendor"        # Go/PHP
    # Windows-specific
    "Debug"
    "Release"
    "x64"
    "x86"
    ".vs"
    "packages"
)

# Extension to language mapping for markdown code fences
get_lang_for_ext() {
    local ext="${1,,}"  # lowercase
    case "$ext" in
        py|pyi)         echo "python" ;;
        js|mjs|cjs)     echo "javascript" ;;
        ts|mts|cts)     echo "typescript" ;;
        jsx)            echo "jsx" ;;
        tsx)            echo "tsx" ;;
        rb)             echo "ruby" ;;
        rs)             echo "rust" ;;
        go)             echo "go" ;;
        java)           echo "java" ;;
        c|h)            echo "c" ;;
        cpp|cc|cxx|hpp) echo "cpp" ;;
        cs)             echo "csharp" ;;
        php)            echo "php" ;;
        swift)          echo "swift" ;;
        kt|kts)         echo "kotlin" ;;
        scala)          echo "scala" ;;
        sh|bash)        echo "bash" ;;
        zsh)            echo "zsh" ;;
        fish)           echo "fish" ;;
        ps1|psm1)       echo "powershell" ;;
        bat|cmd)        echo "batch" ;;
        sql)            echo "sql" ;;
        html|htm)       echo "html" ;;
        css)            echo "css" ;;
        scss)           echo "scss" ;;
        sass)           echo "sass" ;;
        less)           echo "less" ;;
        json|jsonc)     echo "json" ;;
        yaml|yml)       echo "yaml" ;;
        toml)           echo "toml" ;;
        xml|xsl|xslt)   echo "xml" ;;
        md|markdown)    echo "markdown" ;;
        lua)            echo "lua" ;;
        r|R)            echo "r" ;;
        pl|pm)          echo "perl" ;;
        ex|exs)         echo "elixir" ;;
        erl|hrl)        echo "erlang" ;;
        clj|cljs)       echo "clojure" ;;
        hs|lhs)         echo "haskell" ;;
        ml|mli)         echo "ocaml" ;;
        fs|fsi|fsx)     echo "fsharp" ;;
        vim)            echo "vim" ;;
        el)             echo "elisp" ;;
        lisp|cl)        echo "lisp" ;;
        scm)            echo "scheme" ;;
        rkt)            echo "racket" ;;
        zig)            echo "zig" ;;
        nim)            echo "nim" ;;
        v)              echo "v" ;;
        d)              echo "d" ;;
        ada|adb|ads)    echo "ada" ;;
        f|f90|f95)      echo "fortran" ;;
        cob|cbl)        echo "cobol" ;;
        asm|s)          echo "asm" ;;
        dockerfile)     echo "dockerfile" ;;
        makefile|mk)    echo "makefile" ;;
        cmake)          echo "cmake" ;;
        gradle|groovy)  echo "groovy" ;;
        tf|tfvars)      echo "terraform" ;;
        proto)          echo "protobuf" ;;
        graphql|gql)    echo "graphql" ;;
        vue)            echo "vue" ;;
        svelte)         echo "svelte" ;;
        *)              echo "$ext" ;;
    esac
}

# Get language for a file path
get_lang_for_file() {
    local file="$1"
    local basename="${file##*/}"
    local ext="${basename##*.}"

    # Handle special filenames
    local basename_lower="${basename,,}"
    if [[ "$basename_lower" == "dockerfile" ]]; then
        echo "dockerfile"
        return
    fi
    if [[ "$basename_lower" == "makefile" || "$basename_lower" == "gnumakefile" ]]; then
        echo "makefile"
        return
    fi

    get_lang_for_ext "$ext"
}

# Colors for output (disabled if not a terminal or stdout mode)
setup_colors() {
    if [[ -t 2 ]] && [[ "$USE_STDOUT" == false ]]; then
        RED='\033[0;31m'
        GREEN='\033[0;32m'
        YELLOW='\033[0;33m'
        BLUE='\033[0;34m'
        NC='\033[0m' # No Color
    else
        RED=''
        GREEN=''
        YELLOW=''
        BLUE=''
        NC=''
    fi
}

# Print to stderr (so it doesn't interfere with --stdout)
log() {
    echo -e "$@" >&2
}

# Check if file is binary (cross-platform)
is_binary() {
    local file="$1"

    # Try 'file' command first (most reliable)
    if command -v file &> /dev/null; then
        if file --mime-encoding "$file" 2>/dev/null | grep -q "binary"; then
            return 0
        fi
        return 1
    fi

    # Fallback: check for null bytes in first 8KB using head and grep
    # This works on Linux, macOS, and Git Bash
    if head -c 8192 "$file" 2>/dev/null | LC_ALL=C grep -q $'[^\t\n\r -~]'; then
        # Has non-printable chars, might be binary - do a more specific check for null
        if head -c 8192 "$file" 2>/dev/null | LC_ALL=C grep -q $'\x00'; then
            return 0
        fi
    fi
    return 1
}

# Get file modification time as epoch seconds (cross-platform)
get_mtime() {
    local file="$1"
    case "$OS_TYPE" in
        macos)
            stat -f '%m' "$file" 2>/dev/null || echo "0"
            ;;
        *)
            stat --format='%Y' "$file" 2>/dev/null || stat -c '%Y' "$file" 2>/dev/null || echo "0"
            ;;
    esac
}

# Get file size in bytes (cross-platform)
get_size() {
    local file="$1"
    case "$OS_TYPE" in
        macos)
            stat -f '%z' "$file" 2>/dev/null || echo "0"
            ;;
        *)
            stat --format='%s' "$file" 2>/dev/null || stat -c '%s' "$file" 2>/dev/null || echo "0"
            ;;
    esac
}

# Estimate tokens (rough: ~4 chars per token)
estimate_tokens() {
    local chars="$1"
    echo $(( (chars + 3) / 4 ))
}

# XML escape special characters
xml_escape() {
    local text="$1"
    text="${text//&/&amp;}"
    text="${text//</&lt;}"
    text="${text//>/&gt;}"
    text="${text//\"/&quot;}"
    text="${text//\'/&apos;}"
    echo "$text"
}

# Normalize path for display (forward slashes)
normalize_path() {
    local path="$1"
    # Convert backslashes to forward slashes (for Windows)
    echo "${path//\\//}"
}

show_help() {
    cat << 'EOF'
Usage: concat_files <extension1> [extension2] ... [options]

Recursively find files with specific extensions and concatenate their contents.
Cross-platform: Linux, macOS, Git Bash on Windows.

Options:
  --dir=PATH        Search directory (default: current directory)
  --lines=N         Max lines per file (default: unlimited)
  --max-total=N     Stop after N total lines (default: unlimited)
  --exclude=PATTERN Exclude pattern (repeatable)
  --gitignore       Respect .gitignore rules (requires git)
  --format=FORMAT   Output format: plain (default), markdown, xml
  --sort=ORDER      Sort order: alpha (default), mtime, size
  --dry-run         Show stats without creating output file
  --stdout          Output to stdout instead of file
  -h, --help        Show this help message

Examples:
  concat_files py                              # All Python files
  concat_files py js --dir=./src               # Python and JS in src/
  concat_files py --exclude=test --lines=50    # Skip test dirs, limit per file
  concat_files py --dry-run                    # Show what would be concatenated
  concat_files py --stdout | xclip             # Pipe to clipboard (Linux)
  concat_files py --stdout | pbcopy            # Pipe to clipboard (macOS)
  concat_files py --format=markdown            # Output with code fences
  concat_files py --gitignore                  # Respect .gitignore
  concat_files py --sort=mtime                 # Most recently modified first

Output Formats:
  plain     Comment-style headers (default)
  markdown  GitHub-flavored markdown with code fences
  xml       XML structure with CDATA content

Sort Orders:
  alpha     Alphabetical by path (default)
  mtime     Most recently modified first
  size      Largest files first

Default Exclusions:
  node_modules, .git, __pycache__, .venv, venv, .tox, .pytest_cache,
  .mypy_cache, .ruff_cache, dist, build, *.egg-info, .next, .nuxt,
  coverage, .coverage, htmlcov, target, vendor, Debug, Release, .vs
EOF
}

# Process arguments
for arg in "$@"; do
    case "$arg" in
        --dir=*)
            SEARCH_DIR="${arg#--dir=}"
            ;;
        --lines=*)
            MAX_LINES="${arg#--lines=}"
            if ! [[ "$MAX_LINES" =~ ^[0-9]+$ ]]; then
                log "${RED}Error: --lines must be a positive number${NC}"
                exit 1
            fi
            ;;
        --max-total=*)
            MAX_TOTAL="${arg#--max-total=}"
            if ! [[ "$MAX_TOTAL" =~ ^[0-9]+$ ]]; then
                log "${RED}Error: --max-total must be a positive number${NC}"
                exit 1
            fi
            ;;
        --exclude=*)
            EXCLUDES+=("${arg#--exclude=}")
            ;;
        --gitignore)
            USE_GITIGNORE=true
            ;;
        --format=*)
            OUTPUT_FORMAT="${arg#--format=}"
            if [[ ! "$OUTPUT_FORMAT" =~ ^(plain|markdown|xml)$ ]]; then
                log "${RED}Error: --format must be plain, markdown, or xml${NC}"
                exit 1
            fi
            ;;
        --sort=*)
            SORT_ORDER="${arg#--sort=}"
            if [[ ! "$SORT_ORDER" =~ ^(alpha|mtime|size)$ ]]; then
                log "${RED}Error: --sort must be alpha, mtime, or size${NC}"
                exit 1
            fi
            ;;
        --dry-run)
            DRY_RUN=true
            ;;
        --stdout)
            USE_STDOUT=true
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        -*)
            log "${RED}Error: Unknown option: $arg${NC}"
            log "Use --help for usage information"
            exit 1
            ;;
        *)
            EXTENSIONS+=("$arg")
            ;;
    esac
done

setup_colors

# Check if at least one extension is provided
if [ ${#EXTENSIONS[@]} -eq 0 ]; then
    show_help
    exit 1
fi

# Check if directory exists
if [ ! -d "$SEARCH_DIR" ]; then
    log "${RED}Error: Directory '$SEARCH_DIR' not found${NC}"
    exit 1
fi

# Check gitignore requirements
if [ "$USE_GITIGNORE" = true ]; then
    if ! command -v git &> /dev/null; then
        log "${RED}Error: --gitignore requires git to be installed${NC}"
        exit 1
    fi
    if ! git -C "$SEARCH_DIR" rev-parse --git-dir &> /dev/null; then
        log "${YELLOW}Warning: --gitignore specified but '$SEARCH_DIR' is not in a git repository${NC}"
        log "${YELLOW}Continuing without gitignore filtering...${NC}"
        USE_GITIGNORE=false
    fi
fi

# Combine default and user excludes
ALL_EXCLUDES=("${DEFAULT_EXCLUDES[@]}" "${EXCLUDES[@]}")

# Build file list based on mode
get_files() {
    local files_tmp
    files_tmp=$(mktemp)

    if [ "$USE_GITIGNORE" = true ]; then
        # Use git ls-files with extension filters
        local git_patterns=()
        for ext in "${EXTENSIONS[@]}"; do
            git_patterns+=("*.$ext")
        done

        # Get tracked + untracked-but-not-ignored files
        (
            cd "$SEARCH_DIR" && {
                git ls-files -z -- "${git_patterns[@]}" 2>/dev/null
                git ls-files -z --others --exclude-standard -- "${git_patterns[@]}" 2>/dev/null
            }
        ) | sort -zu | tr '\0' '\n' | while IFS= read -r file; do
            # Apply manual excludes
            local excluded=false
            for exclude in "${EXCLUDES[@]}"; do
                if [[ "$file" == *"$exclude"* ]]; then
                    excluded=true
                    break
                fi
            done
            if [ "$excluded" = false ]; then
                if [ "$SEARCH_DIR" = "." ]; then
                    echo "$file"
                else
                    echo "$SEARCH_DIR/$file"
                fi
            fi
        done > "$files_tmp"
    else
        # Use find with exclusions (cross-platform)
        local find_args=("$SEARCH_DIR" -type f)

        # Add exclusions
        for exclude in "${ALL_EXCLUDES[@]}"; do
            find_args+=(-not -path "*/$exclude/*" -not -path "*/$exclude" -not -name "$exclude")
        done

        # Add extension pattern with grouping
        find_args+=("(")
        local first=true
        for ext in "${EXTENSIONS[@]}"; do
            if [ "$first" = true ]; then
                find_args+=(-name "*.$ext")
                first=false
            else
                find_args+=(-o -name "*.$ext")
            fi
        done
        find_args+=(")")

        find "${find_args[@]}" 2>/dev/null > "$files_tmp" || true
    fi

    # Sort files based on sort order
    case "$SORT_ORDER" in
        alpha)
            sort < "$files_tmp"
            ;;
        mtime)
            # Sort by modification time, newest first
            while IFS= read -r f; do
                echo "$(get_mtime "$f") $f"
            done < "$files_tmp" | sort -rn | cut -d' ' -f2-
            ;;
        size)
            # Sort by size, largest first
            while IFS= read -r f; do
                echo "$(get_size "$f") $f"
            done < "$files_tmp" | sort -rn | cut -d' ' -f2-
            ;;
    esac

    rm -f "$files_tmp"
}

# Get sorted file list into array
FILES=()
while IFS= read -r line; do
    [ -n "$line" ] && FILES+=("$line")
done < <(get_files)
FILE_COUNT=${#FILES[@]}

if [ "$FILE_COUNT" -eq 0 ]; then
    log "${YELLOW}No files with extensions (${EXTENSIONS[*]}) found in '$SEARCH_DIR'${NC}"
    exit 0
fi

# Dry run: collect and display stats
if [ "$DRY_RUN" = true ]; then
    total_lines=0
    total_chars=0
    skipped_binary=0
    file_details=()

    log "${BLUE}Dry run - analyzing ${FILE_COUNT} files...${NC}"
    log ""

    for file in "${FILES[@]}"; do
        if is_binary "$file"; then
            ((skipped_binary++)) || true
            continue
        fi

        file_lines=$(wc -l < "$file" 2>/dev/null | tr -d ' ' || echo 0)
        file_chars=$(wc -c < "$file" 2>/dev/null | tr -d ' ' || echo 0)
        original_lines=$file_lines

        # Apply per-file limit
        if [ "$MAX_LINES" -gt 0 ] && [ "$file_lines" -gt "$MAX_LINES" ]; then
            # Estimate chars for limited lines (rough approximation)
            if [ "$file_lines" -gt 0 ]; then
                avg_chars_per_line=$(( file_chars / file_lines ))
            else
                avg_chars_per_line=0
            fi
            file_lines=$MAX_LINES
            file_chars=$(( avg_chars_per_line * MAX_LINES ))
        fi

        # Check total limit
        if [ "$MAX_TOTAL" -gt 0 ] && [ $((total_lines + file_lines)) -gt "$MAX_TOTAL" ]; then
            remaining=$((MAX_TOTAL - total_lines))
            if [ "$remaining" -le 0 ]; then
                log "${YELLOW}  ... (budget exhausted, remaining files skipped)${NC}"
                break
            fi
            file_lines=$remaining
        fi

        total_lines=$((total_lines + file_lines))
        total_chars=$((total_chars + file_chars))

        # Store file details for verbose output
        normalized_file=$(normalize_path "$file")
        if [ "$original_lines" -ne "$file_lines" ]; then
            file_details+=("  $normalized_file ($original_lines lines, truncated to $file_lines)")
        else
            file_details+=("  $normalized_file ($file_lines lines)")
        fi
    done

    # Add estimated overhead for headers
    case "$OUTPUT_FORMAT" in
        plain)    header_overhead=$((FILE_COUNT * 200 + 500)) ;;
        markdown) header_overhead=$((FILE_COUNT * 150 + 300)) ;;
        xml)      header_overhead=$((FILE_COUNT * 250 + 400)) ;;
    esac
    total_chars=$((total_chars + header_overhead))

    tokens=$(estimate_tokens $total_chars)

    log "${GREEN}=== Dry Run Results ===${NC}"
    log ""
    log "Files found:      $FILE_COUNT"
    [ "$skipped_binary" -gt 0 ] && log "Binary (skipped): $skipped_binary"
    log "Extensions:       ${EXTENSIONS[*]}"
    log "Search dir:       $(normalize_path "$SEARCH_DIR")"
    log "Sort order:       $SORT_ORDER"
    log "Output format:    $OUTPUT_FORMAT"
    [ "$USE_GITIGNORE" = true ] && log "Using .gitignore: yes"
    log ""
    log "${BLUE}Estimated output:${NC}"
    log "  Lines:          $total_lines"
    log "  Characters:     $total_chars"
    log "  Tokens (est):   ~$tokens"
    log ""

    if [ "$MAX_LINES" -gt 0 ]; then
        log "Per-file limit:   $MAX_LINES lines"
    fi
    if [ "$MAX_TOTAL" -gt 0 ]; then
        log "Total limit:      $MAX_TOTAL lines"
    fi
    if [ ${#EXCLUDES[@]} -gt 0 ]; then
        log "User excludes:    ${EXCLUDES[*]}"
    fi

    log ""
    log "${BLUE}Files to include:${NC}"
    for detail in "${file_details[@]}"; do
        log "$detail"
    done

    exit 0
fi

# Determine output destination
if [ "$USE_STDOUT" = true ]; then
    OUTPUT_FILE="/dev/stdout"
else
    # Build output filename
    if [ "$SEARCH_DIR" = "." ]; then
        DIR_NAME=$(basename "$(pwd)")
    else
        DIR_NAME=$(basename "$SEARCH_DIR")
    fi

    EXT_STRING=$(IFS=_ ; echo "${EXTENSIONS[*]}")

    # Choose extension based on format
    case "$OUTPUT_FORMAT" in
        plain)    file_ext="txt" ;;
        markdown) file_ext="md" ;;
        xml)      file_ext="xml" ;;
    esac

    if [ "$MAX_LINES" -gt 0 ]; then
        OUTPUT_FILE="${DIR_NAME}_${EXT_STRING}_${MAX_LINES}lines.${file_ext}"
    else
        OUTPUT_FILE="${DIR_NAME}_${EXT_STRING}_files.${file_ext}"
    fi

    # Check write permission
    if ! touch "$OUTPUT_FILE" 2>/dev/null; then
        log "${RED}Error: Cannot write to '$OUTPUT_FILE'${NC}"
        exit 1
    fi
fi

# Helper to write to output
out() {
    if [ "$USE_STDOUT" = true ]; then
        printf '%s\n' "$@"
    else
        printf '%s\n' "$@" >> "$OUTPUT_FILE"
    fi
}

# Clear output file if not stdout
if [ "$USE_STDOUT" = false ]; then
    : > "$OUTPUT_FILE"
fi

# Build limit message
LIMIT_MSG=""
[ "$MAX_LINES" -gt 0 ] && LIMIT_MSG+="max $MAX_LINES lines/file "
[ "$MAX_TOTAL" -gt 0 ] && LIMIT_MSG+="max $MAX_TOTAL total lines"

log "${GREEN}Found $FILE_COUNT files with extensions (${EXTENSIONS[*]})${NC}"
[ -n "$LIMIT_MSG" ] && log "${YELLOW}Limits: $LIMIT_MSG${NC}"
log "Format: $OUTPUT_FORMAT, Sort: $SORT_ORDER"
[ "$USE_GITIGNORE" = true ] && log "Using .gitignore rules"
[ "$USE_STDOUT" = false ] && log "Writing to: $OUTPUT_FILE"

# Write header based on format
write_header() {
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date)
    local search_dir_display
    search_dir_display=$(normalize_path "$SEARCH_DIR")

    case "$OUTPUT_FORMAT" in
        plain)
            out "# Concatenated files with extensions: ${EXTENSIONS[*]}"
            out "# From directory: '$search_dir_display'"
            out "# Created on $timestamp"
            out "# Contains $FILE_COUNT files"
            out "# Sort order: $SORT_ORDER"
            [ "$MAX_LINES" -gt 0 ] && out "# Limited to maximum $MAX_LINES lines per file"
            [ "$MAX_TOTAL" -gt 0 ] && out "# Limited to maximum $MAX_TOTAL total lines"
            [ ${#EXCLUDES[@]} -gt 0 ] && out "# User excludes: ${EXCLUDES[*]}"
            [ "$USE_GITIGNORE" = true ] && out "# Respecting .gitignore rules"
            out "# =========================================================="
            out ""
            ;;
        markdown)
            out "# Concatenated Files"
            out ""
            out "- **Extensions:** ${EXTENSIONS[*]}"
            out "- **Directory:** \`$search_dir_display\`"
            out "- **Created:** $timestamp"
            out "- **Files:** $FILE_COUNT"
            out "- **Sort:** $SORT_ORDER"
            [ "$MAX_LINES" -gt 0 ] && out "- **Per-file limit:** $MAX_LINES lines"
            [ "$MAX_TOTAL" -gt 0 ] && out "- **Total limit:** $MAX_TOTAL lines"
            [ ${#EXCLUDES[@]} -gt 0 ] && out "- **Excludes:** ${EXCLUDES[*]}"
            [ "$USE_GITIGNORE" = true ] && out "- **Gitignore:** enabled"
            out ""
            out "---"
            out ""
            ;;
        xml)
            out '<?xml version="1.0" encoding="UTF-8"?>'
            out '<concatenation>'
            out "  <metadata>"
            out "    <extensions>${EXTENSIONS[*]}</extensions>"
            out "    <directory>$(xml_escape "$search_dir_display")</directory>"
            out "    <created>$timestamp</created>"
            out "    <file_count>$FILE_COUNT</file_count>"
            out "    <sort_order>$SORT_ORDER</sort_order>"
            [ "$MAX_LINES" -gt 0 ] && out "    <max_lines_per_file>$MAX_LINES</max_lines_per_file>"
            [ "$MAX_TOTAL" -gt 0 ] && out "    <max_total_lines>$MAX_TOTAL</max_total_lines>"
            [ ${#EXCLUDES[@]} -gt 0 ] && out "    <excludes>${EXCLUDES[*]}</excludes>"
            [ "$USE_GITIGNORE" = true ] && out "    <gitignore>true</gitignore>"
            out "  </metadata>"
            out "  <files>"
            ;;
    esac
}

# Write tree structure (plain and markdown only)
write_tree() {
    if [ "$USE_STDOUT" = true ]; then
        return
    fi

    if ! command -v tree &> /dev/null; then
        [ "$OUTPUT_FORMAT" = "plain" ] && out "# Note: 'tree' command not available for directory structure"
        return
    fi

    # Build tree pattern
    local tree_pattern=""
    for ext in "${EXTENSIONS[@]}"; do
        [ -n "$tree_pattern" ] && tree_pattern+="|"
        tree_pattern+="*.$ext"
    done

    # Build tree ignore pattern
    local tree_ignore
    tree_ignore=$(IFS=\| ; echo "${ALL_EXCLUDES[*]}")

    case "$OUTPUT_FORMAT" in
        plain)
            out "# Directory Structure:"
            out "#"
            tree -P "$tree_pattern" --prune -I "$tree_ignore" "$SEARCH_DIR" 2>/dev/null | while IFS= read -r line; do
                out "# $line"
            done
            out "#"
            out "# =========================================================="
            out ""
            ;;
        markdown)
            out "## Directory Structure"
            out ""
            out '```'
            tree -P "$tree_pattern" --prune -I "$tree_ignore" "$SEARCH_DIR" 2>/dev/null | while IFS= read -r line; do
                out "$line"
            done
            out '```'
            out ""
            out "---"
            out ""
            ;;
    esac
}

# Write file header
write_file_header() {
    local file="$1"
    local line_count="$2"
    local showing="$3"
    local lang
    lang=$(get_lang_for_file "$file")
    local file_display
    file_display=$(normalize_path "$file")

    case "$OUTPUT_FORMAT" in
        plain)
            out ""
            out "# =========================================="
            out "# File: $file_display"
            out "# Lines: $line_count"
            [ "$showing" -lt "$line_count" ] && out "# NOTE: Showing only first $showing of $line_count lines"
            out "# =========================================="
            out ""
            ;;
        markdown)
            out "## \`$file_display\`"
            out ""
            if [ "$showing" -lt "$line_count" ]; then
                out "_Lines: $line_count (showing first $showing)_"
            else
                out "_Lines: $line_count_"
            fi
            out ""
            out "\`\`\`$lang"
            ;;
        xml)
            out "    <file>"
            out "      <path>$(xml_escape "$file_display")</path>"
            out "      <lines>$line_count</lines>"
            [ "$showing" -lt "$line_count" ] && out "      <truncated_to>$showing</truncated_to>"
            out "      <content><![CDATA["
            ;;
    esac
}

# Write file footer
write_file_footer() {
    local file="$1"
    local line_count="$2"
    local showing="$3"

    case "$OUTPUT_FORMAT" in
        plain)
            if [ "$showing" -lt "$line_count" ]; then
                out ""
                out "# ... ($((line_count - showing)) more lines) ..."
            fi
            ;;
        markdown)
            out '```'
            if [ "$showing" -lt "$line_count" ]; then
                out ""
                out "_... ($((line_count - showing)) more lines) ..._"
            fi
            out ""
            ;;
        xml)
            out "]]></content>"
            out "    </file>"
            ;;
    esac
}

# Write overall footer
write_footer() {
    case "$OUTPUT_FORMAT" in
        xml)
            out "  </files>"
            out "</concatenation>"
            ;;
    esac
}

# Write budget exhausted message
write_budget_exhausted() {
    case "$OUTPUT_FORMAT" in
        plain)
            out ""
            out "# =========================================="
            out "# NOTE: Total line budget ($MAX_TOTAL) exhausted"
            out "# Remaining files skipped"
            out "# =========================================="
            ;;
        markdown)
            out ""
            out "> **Note:** Total line budget ($MAX_TOTAL) exhausted. Remaining files skipped."
            out ""
            ;;
        xml)
            out "    <!-- Total line budget ($MAX_TOTAL) exhausted. Remaining files skipped. -->"
            ;;
    esac
}

# Main output generation
write_header
write_tree

# Process files
total_lines_written=0
skipped_binary=0
budget_exhausted=false

for file in "${FILES[@]}"; do
    # Check if budget exhausted
    if [ "$budget_exhausted" = true ]; then
        break
    fi

    # Skip binary files
    if is_binary "$file"; then
        ((skipped_binary++)) || true
        continue
    fi

    # Get file stats
    file_line_count=$(wc -l < "$file" 2>/dev/null | tr -d ' ' || echo 0)

    # Calculate how many lines to include
    lines_to_include=$file_line_count

    # Apply per-file limit
    if [ "$MAX_LINES" -gt 0 ] && [ "$lines_to_include" -gt "$MAX_LINES" ]; then
        lines_to_include=$MAX_LINES
    fi

    # Apply total limit
    if [ "$MAX_TOTAL" -gt 0 ]; then
        remaining=$((MAX_TOTAL - total_lines_written))
        if [ "$remaining" -le 0 ]; then
            budget_exhausted=true
            write_budget_exhausted
            break
        fi
        if [ "$lines_to_include" -gt "$remaining" ]; then
            lines_to_include=$remaining
            budget_exhausted=true
        fi
    fi

    # Write file
    write_file_header "$file" "$file_line_count" "$lines_to_include"

    # Write file content
    if [ "$lines_to_include" -lt "$file_line_count" ]; then
        head -n "$lines_to_include" "$file" | while IFS= read -r line || [ -n "$line" ]; do
            out "$line"
        done
    else
        while IFS= read -r line || [ -n "$line" ]; do
            out "$line"
        done < "$file"
    fi

    write_file_footer "$file" "$file_line_count" "$lines_to_include"

    total_lines_written=$((total_lines_written + lines_to_include))
done

write_footer

# Print stats (to stderr so they don't interfere with stdout mode)
if [ "$USE_STDOUT" = false ]; then
    TOTAL_LINES=$(wc -l < "$OUTPUT_FILE" | tr -d ' ')
    TOTAL_CHARS=$(wc -c < "$OUTPUT_FILE" | tr -d ' ')
    TOKENS=$(estimate_tokens "$TOTAL_CHARS")

    # Get human-readable size (cross-platform)
    if [ "$TOTAL_CHARS" -lt 1024 ]; then
        TOTAL_SIZE="${TOTAL_CHARS}B"
    elif [ "$TOTAL_CHARS" -lt 1048576 ]; then
        TOTAL_SIZE="$((TOTAL_CHARS / 1024))K"
    else
        TOTAL_SIZE="$((TOTAL_CHARS / 1048576))M"
    fi

    log ""
    log "${GREEN}Concatenation complete: $OUTPUT_FILE${NC}"
    log "  Lines:        $TOTAL_LINES"
    log "  Size:         $TOTAL_SIZE ($TOTAL_CHARS chars)"
    log "  Tokens (est): ~$TOKENS"
    [ "$skipped_binary" -gt 0 ] && log "  ${YELLOW}Skipped $skipped_binary binary file(s)${NC}"
else
    log ""
    log "${GREEN}Output complete${NC}"
    [ "$skipped_binary" -gt 0 ] && log "${YELLOW}Skipped $skipped_binary binary file(s)${NC}"
fi
