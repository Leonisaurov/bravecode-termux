#!/usr/bin/env bash
# Verifica que un libopentui.so sirva para cargarse con bun:ffi en Termux/Android
# y para responder a la tabla FFI de @opentui/core 0.5.9.
#
# Uso:
#   ci/verify-libopentui.sh <ruta/libopentui.so> [ruta/required-symbols.txt]
#
# Salidas:
#   0 -> todo OK (ELF AArch64 DYN + NEEDED libc.so + los 397 símbolos FFI)
#   1 -> uso incorrecto
#   2 -> el archivo no existe
#   3 -> no es un ELF AArch64 shared object
#   4 -> no declara NEEDED libc.so (dlopen de Android no la resolvería)
#   5 -> faltan símbolos FFI requeridos por @opentui/core 0.5.9
#
# Sin dependencias fuera de binutils (readelf). No usa `file`, que no está
# garantizado en todos los runners.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="${1:-}"
REQUIRED="${2:-${SCRIPT_DIR}/required-symbols.txt}"

if [ -z "$LIB" ]; then
    echo "uso: $0 <ruta/libopentui.so> [ruta/required-symbols.txt]" >&2
    exit 1
fi

if [ ! -f "$LIB" ]; then
    echo "error: no existe la librería '$LIB'" >&2
    exit 2
fi

if ! command -v readelf >/dev/null 2>&1; then
    echo "error: readelf no está disponible (instala binutils)" >&2
    exit 1
fi

HEADER="$(readelf -h "$LIB" 2>/dev/null || true)"
if [ -z "$HEADER" ]; then
    echo "error: '$LIB' no es un ELF válido" >&2
    exit 3
fi

MACHINE="$(printf '%s\n' "$HEADER" | awk -F: '/Machine:/ {gsub(/^[ \t]+/, "", $2); print $2}')"
TYPE="$(printf '%s\n' "$HEADER" | awk -F: '/Type:/ {gsub(/^[ \t]+/, "", $2); split($2, a, " "); print a[1]}')"
CLASS="$(printf '%s\n' "$HEADER" | awk -F: '/Class:/ {gsub(/^[ \t]+/, "", $2); print $2}')"

if [ "$CLASS" != "ELF64" ] || [ "$MACHINE" != "AArch64" ] || [ "$TYPE" != "DYN" ]; then
    echo "error: '$LIB' no es un shared object ELF64 AArch64 (Class=$CLASS Machine=$MACHINE Type=$TYPE)" >&2
    exit 3
fi

DYNAMIC="$(readelf -d "$LIB" 2>/dev/null || true)"
if ! printf '%s\n' "$DYNAMIC" | grep -q 'NEEDED.*libc\.so'; then
    echo "error: '$LIB' no declara NEEDED libc.so; dlopen() de Android no la cargaría" >&2
    exit 4
fi

if [ ! -f "$REQUIRED" ]; then
    echo "error: falta la lista de símbolos requeridos '$REQUIRED'" >&2
    exit 1
fi

EXPORTED="$(readelf --dyn-syms -W "$LIB" 2>/dev/null \
    | awk '$4 ~ /^(FUNC|OBJECT)$/ && $7 != "UND" { n = $8; sub(/@.*/, "", n); print n }' \
    | sort -u || true)"

MISSING="$(comm -23 <(grep -v '^#' "$REQUIRED" | grep -v '^[[:space:]]*$' | sort -u) <(printf '%s\n' "$EXPORTED") || true)"
MISSING_COUNT="$(printf '%s\n' "$MISSING" | grep -c . || true)"

if [ "$MISSING_COUNT" != "0" ]; then
    echo "error: a '$LIB' le faltan $MISSING_COUNT símbolos FFI que exige @opentui/core 0.5.9:" >&2
    printf '%s\n' "$MISSING" | sed 's/^/  - /' >&2
    exit 5
fi

REQUIRED_COUNT="$(grep -v '^#' "$REQUIRED" | grep -cv '^[[:space:]]*$' || true)"
echo "OK: $LIB es ELF64 AArch64 DYN, declara NEEDED libc.so y exporta los $REQUIRED_COUNT símbolos FFI requeridos"
readelf -d "$LIB" 2>/dev/null | grep NEEDED | sed 's/^/  /' || true
exit 0
