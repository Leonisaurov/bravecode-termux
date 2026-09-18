#!/usr/bin/env bash
# Compila libopentui.so para Android aarch64 (Termux) desde la fuente upstream
# de OpenTUI.
#
# Receta portada del pipeline validado en ../opencode-termux
# (opentui/scripts/build-opentui.sh): Zig + NDK bionic descrito por
# --libc android-libc.txt, target aarch64-linux-android.<API>. La diferencia es
# el ref (v0.5.9 en vez de la copia vendorizada 0.4.5) y que el árbol de fuentes
# y las dependencias Zig (uucode/yoga/ghostty) se preparan aquí mismo.
#
# Uso:
#   ci/build-opentui-android.sh
#
# Variables:
#   OPENTUI_REF        ref/tag a compilar            (v0.5.9)
#   OPENTUI_TARGET     triple+API de Zig             (aarch64-linux-android.24)
#   OPENTUI_OPTIMIZE   modo de optimización de Zig   (ReleaseSafe)
#   ANDROID_API        minSdk / dir de CRT del NDK   (24)
#   ZIG_BIN            binario de Zig 0.16.x         (zig del PATH)
#   ANDROID_NDK_HOME   NDK raíz con toolchains/llvm  (autodetectado)
#   WORK_DIR           árbol de build                (<repo>/build)
#   OUT_LIB            destino de la .so             (<repo>/native/libopentui.android-arm64.so)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENTUI_REF="${OPENTUI_REF:-v0.5.9}"
OPENTUI_REPO="${OPENTUI_REPO:-https://github.com/anomalyco/opentui.git}"
OPENTUI_TARGET="${OPENTUI_TARGET:-aarch64-linux-android.24}"
OPENTUI_OPTIMIZE="${OPENTUI_OPTIMIZE:-ReleaseSafe}"
ANDROID_API="${ANDROID_API:-24}"
ANDROID_TRIPLE="${ANDROID_TRIPLE:-aarch64-linux-android}"
ZIG_BIN="${ZIG_BIN:-zig}"
WORK_DIR="${WORK_DIR:-$REPO_ROOT/build}"
OUT_LIB="${OUT_LIB:-$REPO_ROOT/native/libopentui.android-arm64.so}"
SRC_DIR="$WORK_DIR/opentui-src"
LIBC_FILE="$WORK_DIR/android-libc.txt"

log() { printf '>>> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "falta el comando '$1'"; }
for c in git curl tar gzip readelf "$ZIG_BIN"; do need "$c"; done

resolve_ndk() {
    if [ -n "${ANDROID_NDK_HOME:-}" ] && [ -d "$ANDROID_NDK_HOME/toolchains/llvm/prebuilt" ]; then
        printf '%s\n' "$ANDROID_NDK_HOME"; return 0
    fi
    local candidate
    for candidate in \
        /opt/android-ndk \
        "${ANDROID_NDK_ROOT:-}" \
        "$HOME/Android/ndk/29.0.14033849" \
        "$HOME/Android/ndk/29.0.14206865" \
        "$HOME/Android/ndk/r29-termux"; do
        if [ -n "$candidate" ] && [ -d "$candidate/toolchains/llvm/prebuilt" ]; then
            printf '%s\n' "$candidate"; return 0
        fi
    done
    die "no encontré un NDK; exporta ANDROID_NDK_HOME"
}

NDK="$(resolve_ndk)"
# El host prebuilt del NDK puede ser linux-x86_64 (CI) o linux-aarch64 (Termux).
HOST_TAG=""
for tag in linux-x86_64 linux-aarch64 darwin-x86_64 darwin-arm64; do
    if [ -d "$NDK/toolchains/llvm/prebuilt/$tag/sysroot" ]; then HOST_TAG="$tag"; break; fi
done
[ -n "$HOST_TAG" ] || die "el NDK '$NDK' no tiene un prebuilt de host conocido"
SYSROOT="$NDK/toolchains/llvm/prebuilt/$HOST_TAG/sysroot"
CRT_DIR="$SYSROOT/usr/lib/$ANDROID_TRIPLE/$ANDROID_API"

log "zig: $("$ZIG_BIN" version)"
log "ndk: $NDK (host $HOST_TAG, API $ANDROID_API)"
log "target: $OPENTUI_TARGET ($OPENTUI_OPTIMIZE)"

# --- 1. libc.txt generado para este NDK/API (nunca versionado, ver skill zig-libc-android)
for f in \
    "$SYSROOT/usr/include/stdlib.h" \
    "$SYSROOT/usr/include/sys/errno.h" \
    "$CRT_DIR/crtbegin_dynamic.o" \
    "$CRT_DIR/crtend_android.o" \
    "$CRT_DIR/libc.so"; do
    [ -r "$f" ] || die "el NDK no aporta '$f' (¿API/arquitectura equivocadas?)"
done
mkdir -p "$(dirname "$LIBC_FILE")"
{
    printf 'include_dir=%s/usr/include\n' "$SYSROOT"
    printf 'sys_include_dir=%s/usr/include/%s\n' "$SYSROOT" "$ANDROID_TRIPLE"
    printf 'crt_dir=%s\n' "$CRT_DIR"
    printf 'msvc_lib_dir=\n'
    printf 'kernel32_lib_dir=\n'
    printf 'gcc_dir=\n'
} > "$LIBC_FILE"
log "libc.txt: $LIBC_FILE"

# --- 2. fuente de OpenTUI en el ref pedido
mkdir -p "$WORK_DIR"
if [ -d "$SRC_DIR/.git" ]; then
    have="$(git -C "$SRC_DIR" rev-parse HEAD 2>/dev/null || true)"
    want="$(git -C "$SRC_DIR" rev-parse --verify --quiet "$OPENTUI_REF^{commit}" 2>/dev/null || true)"
    if [ -n "$want" ] && [ "$want" = "$have" ]; then
        log "fuente ya en $OPENTUI_REF ($have)"
    else
        log "fuente presente en $have; checkout $OPENTUI_REF"
        if ! git -C "$SRC_DIR" fetch --depth 1 --force origin "$OPENTUI_REF" >/dev/null 2>&1 \
           || ! git -C "$SRC_DIR" checkout --detach FETCH_HEAD >/dev/null 2>&1; then
            log "no pude mover el árbol al ref pedido; re-clonando"
            rm -rf "$SRC_DIR"
        fi
    fi
fi
if [ ! -d "$SRC_DIR/.git" ]; then
    log "clonando $OPENTUI_REPO ($OPENTUI_REF)"
    git clone --depth 1 --branch "$OPENTUI_REF" "$OPENTUI_REPO" "$SRC_DIR"
fi
NATIVE_DIR="$SRC_DIR/packages/native"
[ -f "$NATIVE_DIR/build.zig" ] || die "no existe $NATIVE_DIR/build.zig (¿cambió el layout del repo?)"
log "commit: $(git -C "$SRC_DIR" rev-parse HEAD)"

# --- 3. dependencias Zig (uucode/yoga/ghostty) desde el vendor del repo
if [ ! -f "$NATIVE_DIR/zig-deps/.ready" ]; then
    log "preparando dependencias Zig (descarga de uucode/yoga/ghostty)"
    ( cd "$NATIVE_DIR" && sh src/vendor/update-zig-deps.sh && sh scripts/prepare-zig-deps.sh )
fi

# --- 3.5 parche del build.zig: los translate-c necesitan los headers del NDK
# (si no, 'pthread.h'/'math.h' not found; ver ci/patch-opentui-android-translate-c.py)
python3 "$REPO_ROOT/ci/patch-opentui-android-translate-c.py" "$NATIVE_DIR/build.zig"
export BRAVECODE_NDK_INCLUDE="$SYSROOT/usr/include"
export BRAVECODE_NDK_ARCH_INCLUDE="$SYSROOT/usr/include/$ANDROID_TRIPLE"
for d in "$BRAVECODE_NDK_INCLUDE" "$BRAVECODE_NDK_ARCH_INCLUDE"; do
    [ -d "$d" ] || die "el NDK no aporta el include '$d'"
done
log "translate-c incluirá: $BRAVECODE_NDK_INCLUDE $BRAVECODE_NDK_ARCH_INCLUDE"

# --- 4. build
export ZIG_LOCAL_CACHE_DIR="${ZIG_LOCAL_CACHE_DIR:-$WORK_DIR/cache/zig}"
export ZIG_GLOBAL_CACHE_DIR="${ZIG_GLOBAL_CACHE_DIR:-$WORK_DIR/cache/zig-global}"
mkdir -p "$ZIG_LOCAL_CACHE_DIR" "$ZIG_GLOBAL_CACHE_DIR"
PREFIX="$WORK_DIR/zig-out"
rm -rf "$PREFIX"
log "zig build (release, target $OPENTUI_TARGET)"
( cd "$NATIVE_DIR" && "$ZIG_BIN" build \
    -Dlibrary-target="$OPENTUI_TARGET" \
    -Doptimize="$OPENTUI_OPTIMIZE" \
    --libc "$LIBC_FILE" \
    --prefix "$PREFIX" \
    --cache-dir "$ZIG_LOCAL_CACHE_DIR" \
    --global-cache-dir "$ZIG_GLOBAL_CACHE_DIR" )

BUILT="$(find "$WORK_DIR/lib" "$PREFIX" -name libopentui.so -type f 2>/dev/null | head -n1 || true)"
if [ -z "$BUILT" ]; then
    log "no hay libopentui.so en $WORK_DIR/lib; candidatos encontrados:"
    find "$WORK_DIR" -name 'libopentui.so' -type f 2>/dev/null | head -n 5 >&2 || true
    die "no se generó libopentui.so bajo $WORK_DIR/lib"
fi
mkdir -p "$(dirname "$OUT_LIB")"
cp -f "$BUILT" "$OUT_LIB"
log "artefacto: $OUT_LIB ($(du -h "$OUT_LIB" | cut -f1))"

# --- 5. verificación de contrato (AArch64 DYN + NEEDED libc.so + 397 símbolos FFI)
bash "$REPO_ROOT/ci/verify-libopentui.sh" "$OUT_LIB"
readelf -h "$OUT_LIB" | grep -E 'Class|Machine|Type' | sed 's/^/  /'
