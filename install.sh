#!/usr/bin/env bash
# Instalador del port de BraveCode para Termux/Android.
#
#   ./install.sh --fetch    descarga bravecode-cli desde npm a app/node_modules/
#   ./install.sh --deps     instala las dependencias JS (bun install)
#   ./install.sh --native   descarga del CI la lib libopentui.so para Android
#   ./install.sh --patch    copia esa lib sobre @opentui/core-linux-arm64
#   ./install.sh --all      fetch + deps + native + patch
#   ./install.sh --check    informa del estado (exit 1 si falta algo)
#   ./install.sh --bin      instala el launcher en $PREFIX/bin
#
# Variables: BRAVECODE_VERSION (fija la versión npm), BRAVECODE_APP_DIR,
#            BRAVECODE_NATIVE_DIR, BRAVECODE_GH_REPO, PREFIX, BRAVECODE_BUN.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${BRAVECODE_APP_DIR:-$REPO_ROOT/app}"
NATIVE_DIR="${BRAVECODE_NATIVE_DIR:-$REPO_ROOT/native}"
NATIVE_LIB="$NATIVE_DIR/libopentui.android-arm64.so"
PKG_DIR="$APP_DIR/node_modules/bravecode-cli"
PLATFORM_PKG_DIR="$APP_DIR/node_modules/@opentui/core-linux-arm64"
PLATFORM_LIB="$PLATFORM_PKG_DIR/libopentui.so"
VERIFY="$REPO_ROOT/ci/verify-libopentui.sh"
REGISTRY="${BRAVECODE_REGISTRY:-https://registry.npmjs.org}"
GH_REPO="${BRAVECODE_GH_REPO:-Leonisaurov/bravecode-termux}"
ARTIFACT_NAME="${BRAVECODE_ARTIFACT:-libopentui-android-arm64}"
WORKFLOW_FILE="build-opentui-android.yml"

log() { printf '>>> %s\n' "$*"; }
warn() { printf 'aviso: %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

usage() {
    cat <<'EOF'
Instalador del port de BraveCode (Termux/Android)

  ./install.sh --fetch    descarga el paquete bravecode-cli desde npm
  ./install.sh --deps     instala las dependencias JS (bun install --ignore-scripts)
  ./install.sh --native   baja del CI la lib nativa libopentui.so (Android arm64)
  ./install.sh --patch    aplica la lib nativa a @opentui/core-linux-arm64
  ./install.sh --all      fetch + deps + native + patch
  ./install.sh --check    estado del port (exit != 0 si falta algo)
  ./install.sh --bin      instala el launcher en $PREFIX/bin/bravecode

Después:  ./bin/bravecode --help   (comandos no interactivos)
          ./bin/bravecode          (TUI; requiere --native + --patch)
EOF
}

need_bun() {
    if [ -n "${BRAVECODE_BUN:-}" ]; then
        command -v "$BRAVECODE_BUN" >/dev/null 2>&1 || die "BRAVECODE_BUN='$BRAVECODE_BUN' no es ejecutable"
    else
        have bun || die "no encuentro 'bun' en PATH (pkg install bun)"
    fi
}

# ---------------------------------------------------------------- --fetch
cmd_fetch() {
    have curl || die "falta curl"
    local version="${BRAVECODE_VERSION:-}"
    if [ -z "$version" ]; then
        log "consultando la última versión de bravecode-cli en el registry"
        version="$(curl -fsSL "$REGISTRY/bravecode-cli/latest" \
            | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')" \
            || die "no pude resolver la versión de bravecode-cli"
    fi
    local tarball="$APP_DIR/bravecode-cli-$version.tgz"
    mkdir -p "$APP_DIR"
    log "descargando bravecode-cli@$version"
    curl -fsSL --retry 3 -o "$tarball" "$REGISTRY/bravecode-cli/-/bravecode-cli-$version.tgz" \
        || die "falló la descarga del paquete"
    rm -rf "$PKG_DIR"
    mkdir -p "$PKG_DIR"
    tar xzf "$tarball" -C "$PKG_DIR" --strip-components=1
    [ -f "$PKG_DIR/dist/cli-main.mjs" ] || die "el paquete no trae dist/cli-main.mjs"
    log "bravecode-cli@$version en $PKG_DIR"
}

# ---------------------------------------------------------------- --deps
cmd_deps() {
    need_bun
    [ -f "$PKG_DIR/package.json" ] || die "falta el paquete; ejecuta antes ./install.sh --fetch"
    if [ ! -f "$APP_DIR/package.json" ]; then
        log "generando app/package.json (deps del paquete + binario de plataforma)"
        python3 - "$PKG_DIR/package.json" "$APP_DIR/package.json" <<'PY'
import json, sys
src = json.load(open(sys.argv[1]))
deps = dict(src["dependencies"])
# El CLI resuelve la lib nativa vía este paquete de plataforma; el port mete
# aquí la lib compilada para Android (install.sh --patch).
deps.setdefault("@opentui/core-linux-arm64", src["dependencies"]["@opentui/core"])
out = {
    "name": "bravecode-termux-app",
    "private": True,
    "description": "node_modules de bravecode-cli para el port de Termux/Android",
    "dependencies": deps,
}
json.dump(out, open(sys.argv[2], "w"), indent=2, sort_keys=True)
PY
    fi
    log "bun install --ignore-scripts"
    ( cd "$APP_DIR" && bun install --ignore-scripts )
    log "dependencias listas en $APP_DIR/node_modules"
}

# ---------------------------------------------------------------- --native
cmd_native() {
    mkdir -p "$NATIVE_DIR"
    have gh || die "falta gh (CLI de GitHub) para bajar el artefacto del CI"
    log "buscando el último build correcto en $GH_REPO"
    local run_id
    run_id="$(gh run list --repo "$GH_REPO" --workflow "$WORKFLOW_FILE" --status success \
        --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)"
    [ -n "$run_id" ] || die "no hay runs correctos de $WORKFLOW_FILE en $GH_REPO"
    log "descargando artefacto '$ARTIFACT_NAME' del run $run_id"
    rm -f "$NATIVE_LIB"
    gh run download "$run_id" --repo "$GH_REPO" -n "$ARTIFACT_NAME" -D "$NATIVE_DIR"
    [ -f "$NATIVE_LIB" ] || die "el artefacto no traía $(basename "$NATIVE_LIB")"
    if [ -f "$NATIVE_DIR/SHA256SUMS" ]; then
        ( cd "$NATIVE_DIR" && sha256sum -c SHA256SUMS ) || die "el checksum del artefacto no cuadra"
    fi
    log "lib nativa: $NATIVE_LIB ($(du -h "$NATIVE_LIB" | cut -f1))"
}

# ---------------------------------------------------------------- --patch
cmd_patch() {
    [ -f "$NATIVE_LIB" ] || die "no hay lib nativa; ejecuta antes ./install.sh --native"
    log "verificando contrato de la lib (ELF AArch64 + NEEDED libc.so + símbolos FFI)"
    bash "$VERIFY" "$NATIVE_LIB"
    [ -d "$PLATFORM_PKG_DIR" ] || die "falta $PLATFORM_PKG_DIR; ejecuta antes ./install.sh --deps"
    cp -f "$NATIVE_LIB" "$PLATFORM_LIB"
    cmp -s "$NATIVE_LIB" "$PLATFORM_LIB" || die "la copia a node_modules no quedó idéntica"
    log "TUI habilitada: $PLATFORM_LIB usa la lib Android"
}

# ---------------------------------------------------------------- --check
cmd_check() {
    local failures=0
    note() { printf '  %-22s %s\n' "$1" "$2"; }

    if [ -n "${BRAVECODE_BUN:-}" ]; then
        if command -v "$BRAVECODE_BUN" >/dev/null 2>&1; then note "bun" "ok ($(bun --version 2>/dev/null))"; else note "bun" "FALTA"; failures=$((failures+1)); fi
    elif have bun; then note "bun" "ok ($(bun --version))"
    else note "bun" "FALTA (pkg install bun)"; failures=$((failures+1)); fi

    if [ -f "$PKG_DIR/dist/cli-main.mjs" ]; then note "paquete" "ok ($(python3 -c 'import json;print(json.load(open("'"$PKG_DIR"'/package.json"))["version"])' 2>/dev/null))"
    else note "paquete" "FALTA (./install.sh --fetch)"; failures=$((failures+1)); fi

    local missing=""
    for dep in react @opentui/core @opentui/react; do
        [ -d "$APP_DIR/node_modules/$dep" ] || missing="$missing $dep"
    done
    if [ -z "$missing" ]; then note "deps JS" "ok"; else note "deps JS" "FALTAN:$missing (./install.sh --deps)"; failures=$((failures+1)); fi

    lib_rel="${NATIVE_LIB#"$REPO_ROOT"/}"
    if [ -f "$NATIVE_LIB" ]; then
        note "lib nativa" "$lib_rel ok ($(du -h "$NATIVE_LIB" | cut -f1), sha256 $(sha256sum "$NATIVE_LIB" | cut -c1-12))"
    else
        note "lib nativa" "$lib_rel FALTA (./install.sh --native)"; failures=$((failures+1))
    fi

    plat_rel="${PLATFORM_LIB#"$REPO_ROOT"/}"
    if [ -f "$PLATFORM_LIB" ]; then
        if cmp -s "$NATIVE_LIB" "$PLATFORM_LIB" 2>/dev/null; then
            note "lib aplicada" "$plat_rel ok"
        else
            note "lib aplicada" "$plat_rel DESACTUALIZADA (./install.sh --patch)"; failures=$((failures+1))
        fi
    else
        note "lib aplicada" "$plat_rel FALTA (./install.sh --patch)"; failures=$((failures+1))
    fi

    if [ -f "$NATIVE_LIB" ]; then
        if bash "$VERIFY" "$NATIVE_LIB" >/dev/null 2>&1; then note "contrato FFI" "ok"; else note "contrato FFI" "NO CUMPLE"; failures=$((failures+1)); fi
    fi

    if [ "$failures" -eq 0 ]; then
        echo "estado: listo (./bin/bravecode)"
        return 0
    fi
    echo "estado: faltan $failures comprobaciones"
    return 1
}

# ---------------------------------------------------------------- --bin
cmd_bin() {
    local prefix="${PREFIX:-}"
    [ -n "$prefix" ] || die "PREFIX no está definido (¿Termux?)"
    mkdir -p "$prefix/bin"
    local dest="$prefix/bin/bravecode"
    {
        printf '#!%s/bin/sh\n' "$prefix"
        printf '# Launcher instalado por install.sh --bin; BRAVECODE_ROOT fija el port.\n'
        printf 'BRAVECODE_ROOT=%s; export BRAVECODE_ROOT\n' "$REPO_ROOT"
        printf 'exec "%s/bin/bravecode" "$@"\n' "$REPO_ROOT"
    } > "$dest" 2>/dev/null || die "no pude escribir $dest"
    chmod +x "$dest"
    log "launcher instalado: $dest"
    log "prueba: bravecode --help"
}

main() {
    [ $# -gt 0 ] || { usage; exit 1; }
    local did=0
    for arg in "$@"; do
        case "$arg" in
            --fetch) cmd_fetch; did=1 ;;
            --deps) cmd_deps; did=1 ;;
            --native) cmd_native; did=1 ;;
            --patch) cmd_patch; did=1 ;;
            --all) cmd_fetch; cmd_deps; cmd_native; cmd_patch; did=1 ;;
            --check) cmd_check; did=1 ;;
            --bin) cmd_bin; did=1 ;;
            -h|--help) usage; exit 0 ;;
            *) usage; die "opción desconocida: $arg" ;;
        esac
    done
    [ "$did" -eq 1 ] || { usage; exit 1; }
}

main "$@"
