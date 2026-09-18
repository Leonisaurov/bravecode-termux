#!/usr/bin/env bash
# Verifica que un libopentui.so sirva para cargarse con bun:ffi en Termux/Android
# y para responder a la tabla FFI de @opentui/core 0.5.9.
#
# Uso:
#   ci/verify-libopentui.sh <ruta.so> [lista-simbolos.txt] [--ndk-lib <dir>]
#
#   --ndk-lib <dir>  (o BRAVECODE_NDK_LIB) directorio de librerías de Bionic del
#                    NDK (…/sysroot/usr/lib/aarch64-linux-android/<api>). Con él
#                    se comprueba además que TODOS los símbolos indefinidos de la
#                    .so existan en libc/libm/libdl/… de Bionic (los que no, se
#                    ven en el device como "dlopen failed: cannot locate symbol").
#                    Sin él ese chequeo se omite.
#
# Códigos de salida:
#   0  ok
#   1  falta la lista de símbolos / NDK mal indicado
#   2  el archivo no existe
#   3  no es un shared object ELF64 AArch64
#   4  no declara NEEDED libc.so
#   5  faltan símbolos FFI requeridos por @opentui/core 0.5.9
#   6  está enlazada contra glibc (libc.so.6), no contra Bionic
#   7  símbolos indefinidos que Bionic no tiene (glibc-only)
set -euo pipefail

LIB=""
REQUIRED=""
NDK_LIB_DIR="${BRAVECODE_NDK_LIB:-}"
TMPDIR_SELF=""

cleanup() {
    # `return 0` explícito: si el handler del trap termina con estado != 0,
    # bash lo propaga como código de salida del script y se pierden los exit 2-7.
    if [ -n "${TMPDIR_SELF:-}" ]; then rm -rf "$TMPDIR_SELF"; fi
    return 0
}
trap cleanup EXIT

while [ $# -gt 0 ]; do
    case "$1" in
        --ndk-lib)
            [ $# -ge 2 ] || { echo "error: --ndk-lib necesita un directorio" >&2; exit 1; }
            NDK_LIB_DIR="$2"; shift 2 ;;
        --ndk-lib=*)
            NDK_LIB_DIR="${1#--ndk-lib=}"; shift ;;
        -h|--help)
            sed -n '2,21p' "$0"; exit 0 ;;
        *)
            if [ -z "$LIB" ]; then LIB="$1"; elif [ -z "$REQUIRED" ]; then REQUIRED="$1"; else
                echo "error: argumento de más: $1" >&2; exit 1
            fi
            shift ;;
    esac
done

[ -n "$LIB" ] || { sed -n '2,21p' "$0"; exit 1; }
[ -n "$REQUIRED" ] || REQUIRED="$(cd "$(dirname "$0")" && pwd)/required-symbols.txt"

[ -f "$LIB" ] || { echo "error: no existe la librería '$LIB'" >&2; exit 2; }

for tool in readelf awk sed grep; do
    command -v "$tool" >/dev/null 2>&1 || { echo "error: falta '$tool'" >&2; exit 1; }
done

TMPDIR_SELF="$(mktemp -d)"

HEADER="$(readelf -h "$LIB" 2>/dev/null || true)"
[ -n "$HEADER" ] || { echo "error: '$LIB' no es un ELF legible" >&2; exit 3; }

MACHINE="$(printf '%s\n' "$HEADER" | awk -F: '/Machine:/ {gsub(/^[ \t]+/, "", $2); print $2}')"
TYPE="$(printf '%s\n' "$HEADER" | awk -F: '/Type:/ {gsub(/^[ \t]+/, "", $2); split($2, a, " "); print a[1]}')"
CLASS="$(printf '%s\n' "$HEADER" | awk -F: '/Class:/ {gsub(/^[ \t]+/, "", $2); print $2}')"

if [ "$CLASS" != "ELF64" ] || [ "$MACHINE" != "AArch64" ] || [ "$TYPE" != "DYN" ]; then
    echo "error: '$LIB' no es un shared object ELF64 AArch64 (Class=$CLASS Machine=$MACHINE Type=$TYPE)" >&2
    exit 3
fi

readelf -d "$LIB" 2>/dev/null > "$TMPDIR_SELF/dynamic.txt" || true
sed -n 's/.*Shared library: \[\([^]]*\)\].*/\1/p' "$TMPDIR_SELF/dynamic.txt" | LC_ALL=C sort -u > "$TMPDIR_SELF/needed.txt"

# glibc vs Bionic primero: glibc versiona sus soname (libc.so.6, libm.so.6,
# libpthread.so.0…); Bionic no (libc.so, libm.so). Así se distingue la .so
# oficial de Linux que publica @opentui/core de la que compilamos para Android.
GLIBC_DEPS="$(grep -E '\.so\.[0-9]' "$TMPDIR_SELF/needed.txt" || true)"
if [ -n "$GLIBC_DEPS" ]; then
    echo "error: '$LIB' está enlazada contra glibc y no contra Bionic ($(printf '%s' "$GLIBC_DEPS" | tr '\n' ' ')); el linker de Android no puede cargarla" >&2
    exit 6
fi

if ! grep -qx 'libc\.so' "$TMPDIR_SELF/needed.txt"; then
    echo "error: '$LIB' no declara NEEDED libc.so; dlopen() de Android no la cargaría" >&2
    exit 4
fi

if [ ! -f "$REQUIRED" ]; then
    echo "error: falta la lista de símbolos requeridos '$REQUIRED'" >&2
    exit 1
fi

# Símbolos exportados (definidos) de la librería, sin versión.
readelf --dyn-syms -W "$LIB" 2>/dev/null \
    | awk '$4 ~ /^(FUNC|OBJECT|NOTYPE|IFUNC|TLS)$/ && $7 != "UND" { n = $8; sub(/@.*/, "", n); if (n != "") print n }' \
    | LC_ALL=C sort -u > "$TMPDIR_SELF/exported.txt" || true

# Requeridos que no están: grep -vxF -f (comm depende del orden/collation y con
# locale UTF-8 daba falsos positivos).
grep -v '^#' "$REQUIRED" | grep -v '^[[:space:]]*$' | LC_ALL=C sort -u > "$TMPDIR_SELF/required.txt"
grep -vxF -f "$TMPDIR_SELF/exported.txt" "$TMPDIR_SELF/required.txt" > "$TMPDIR_SELF/missing.txt" || true
MISSING_COUNT="$(grep -c . "$TMPDIR_SELF/missing.txt" || true)"

if [ "$MISSING_COUNT" != "0" ]; then
    echo "error: a '$LIB' le faltan $MISSING_COUNT símbolos FFI que exige @opentui/core 0.5.9:" >&2
    sed 's/^/  - /' "$TMPDIR_SELF/missing.txt" >&2
    exit 5
fi

# Símbolos indefinidos contra las librerías de Bionic del NDK. Un símbolo que
# Bionic no exporta (p. ej. pthread_tryjoin_np, que Zig 0.16 emite para
# linux-android) hace fallar dlopen en el device: mejor detectarlo aquí.
if [ -n "$NDK_LIB_DIR" ]; then
    [ -d "$NDK_LIB_DIR" ] || { echo "error: --ndk-lib '$NDK_LIB_DIR' no es un directorio" >&2; exit 1; }
    : > "$TMPDIR_SELF/bionic.txt"
    for soname in libc.so libm.so libdl.so liblog.so libandroid.so libz.so; do
        [ -f "$NDK_LIB_DIR/$soname" ] || continue
        readelf --dyn-syms -W "$NDK_LIB_DIR/$soname" 2>/dev/null \
            | awk '$4 ~ /^(FUNC|OBJECT|NOTYPE|IFUNC|TLS)$/ && $7 != "UND" { n = $8; sub(/@.*/, "", n); if (n != "") print n }' \
            >> "$TMPDIR_SELF/bionic.txt" || true
    done
    if [ ! -s "$TMPDIR_SELF/bionic.txt" ]; then
        echo "error: en '$NDK_LIB_DIR' no encontré librerías de Bionic (libc.so…)" >&2
        exit 1
    fi
    readelf --dyn-syms -W "$LIB" 2>/dev/null \
        | awk '$7 == "UND" { n = $8; sub(/@.*/, "", n); if (n != "") print n }' \
        | LC_ALL=C sort -u > "$TMPDIR_SELF/undefined.txt" || true
    LC_ALL=C sort -u "$TMPDIR_SELF/bionic.txt" > "$TMPDIR_SELF/bionic-sorted.txt"
    grep -vxF -f "$TMPDIR_SELF/bionic-sorted.txt" "$TMPDIR_SELF/undefined.txt" > "$TMPDIR_SELF/unresolved.txt" || true
    UNRESOLVED_COUNT="$(grep -c . "$TMPDIR_SELF/unresolved.txt" || true)"
    if [ "$UNRESOLVED_COUNT" != "0" ]; then
        echo "error: '$LIB' pide $UNRESOLVED_COUNT símbolos que Bionic no tiene (dlopen fallaría en el device):" >&2
        sed 's/^/  - /' "$TMPDIR_SELF/unresolved.txt" >&2
        exit 7
    fi
fi

REQUIRED_COUNT="$(grep -c . "$TMPDIR_SELF/required.txt" || true)"
echo "OK: $LIB es ELF64 AArch64 DYN, declara NEEDED libc.so, exporta los $REQUIRED_COUNT símbolos FFI requeridos"
if [ -n "$NDK_LIB_DIR" ]; then
    echo "    y todos sus símbolos indefinidos existen en las librerías de Bionic de $NDK_LIB_DIR"
fi
sed 's/^/  /' "$TMPDIR_SELF/needed.txt"
exit 0
