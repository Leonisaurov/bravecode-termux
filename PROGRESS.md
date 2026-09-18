# Progreso del port de BraveCode a Termux

## Qué es esto

Port de `bravecode-cli` (paquete npm, "BraveCode AI") a Termux/Android aarch64.
Repo del port: `github.com/Leonisaurov/bravecode-termux` (el CI que compila la
librería nativa vive ahí).

## Estado actual

| Pieza | Estado | Evidencia |
|-------|--------|-----------|
| CLI arranca en Termux | ✅ | `./bin/bravecode --version` → `0.1.57` (bun 1.3.14 bionic) |
| Comandos no interactivos | ✅ | `models`, `providers`, `tools`, `agents`, `plugins`, `config` |
| Prompt real (headless) | ✅ | `bravecode run "Responde únicamente con la palabra: ok"` → `ok` |
| Shim de plataforma | ✅ | `runtime/platform-shim.cjs` (test: platform=linux, arch=arm64) |
| Deps JS | ✅ | `bun install --ignore-scripts` en `app/` (154 paquetes) |
| Lib nativa Android (0.5.9) | ⏳ | CI `build-opentui-android.yml` (repo del port) |
| TUI en tmux | ⏳ | depende de la lib nativa |
| Tests | ✅ | `python3 tests/run-tests.py` (29 tests, stdlib) |

## Cómo llegamos aquí (decisiones con evidencia)

1. **Identificación del paquete**: `bravecode-cli@0.1.57`, mantener
   `brave-code-tech`, `homepage: https://bravecode.dev` (DNS inexistente) y
   `repository: github.com/brave-code-tech/brave-ai` (no existe). Los fuentes TS
   se recuperaron del `cli-main.mjs.map` (541 archivos con `sourcesContent`).
2. **Runtime**: el bin `dist/cli.cjs` es un wrapper CJS con shebang
   `#!/usr/bin/env bun` que exige Bun; Termux tiene bun 1.3.14 bionic
   (NDK r28b). Node también ejecutaría el bundle, pero el guard del CLI aborta
   sin bun.
3. **Bloqueadores**: (a) `process.platform === 'android'` deja sin resolver la
   librería nativa; (b) `@opentui/core` 0.5.9 no publica binarios Android y los
   de Linux son glibc. La copia que ya existía en el device (freebuf,
   OpenTUI 0.3.4) **no sirve**: le faltan 44 de los 397 símbolos FFI de 0.5.9
   (verificado con `readelf` + `ci/required-symbols.txt`).
4. **Receta de build**: portada de `../opencode-termux/opentui/scripts/build-opentui.sh`
   (zig + NDK bionic descrito por `--libc android-libc.txt`). En 0.5.9 el core
   Zig está en `packages/native/` (no en `packages/core/src/zig`) y pide
   `.zig-version 0.16.0`; los deps zig (uucode/yoga/ghostty) se vendorizan con
   `src/vendor/update-zig-deps.sh` (descarga con SHA-256 verificado).
5. **Decisiones de port**: shim mínimo de plataforma (no se parchea el bundle ni
   el paquete npm) + inyección de la lib Android en
   `@opentui/core-linux-arm64/libopentui.so` (lo que el preflight del CLI busca
   cuando la plataforma es `linux`).

## Iteraciones del CI (todas verificadas en el runner)

| # | Fallo | Arreglo |
|---|-------|---------|
| 1 | `mv` a `/opt` → "Device or resource busy" | NDK y zig dentro de `build/`, sin `sudo` |
| 2 | `ci/build-opentui-android.sh: Permission denied` | bit +x en git + invocación con `bash` |
| 3 | `miniaudio.h: 'pthread.h' not found` (translate-c sin headers) | parche `ci/patch-opentui-android-translate-c.py` (includes del NDK) |
| 4 | `build.zig: root source file struct 'process' has no member named 'getEnvVarOwned'` | opciones del build (`-Dndk-include`, `-Dndk-arch-include`) |
| 5 | `panic: Option 'ndk-include' declared twice` | el helper cachea las rutas (se llama una vez por translate-c) |

Diagnóstico previo hecho en local con el device (zig 0.16.0 + NDK r29): el
translate-c de OpenTUI no hereda el `--libc`, y al apuntarlo al NDK aparece el
error de nullability de `sys/time.h` (headers bionic con `_Nullable`), que se
resuelve anulando esas macros. Ese par de hechos está fijado en los tests.

## Pendiente

- Bajar el artefacto del CI (`./install.sh --native`), aplicarlo (`--patch`) y
  verificar la TUI en tmux (`tests/test_tui.py`).
- Probar una sesión real de la TUI con prompt (consume el servicio free de
  terceros: `codero.sohailsyed.com`).
- Opcional: `./install.sh --bin` para exponer `bravecode` en `$PREFIX/bin`.
