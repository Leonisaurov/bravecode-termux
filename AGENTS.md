# BraveCode Termux — Agent Instructions

Port de `bravecode-cli` (CLI cerrado, bundle Node/Bun) a Termux/Android aarch64.
El bundle externaliza React/Ink y el núcleo nativo **OpenTUI**; el port **no**
parchea el bundle: compila OpenTUI para Android en CI e inyecta la .so donde el
CLI la busca, más un shim de plataforma.

## Estructura

```
BraveCode/
├── install.sh              # --fetch npm, --deps bun, --native (artifact CI), --patch, --all, --check, --bin
├── bin/bravecode           # launcher (bun + shim); BRAVECODE_ROOT para la copia en $PREFIX/bin
├── runtime/platform-shim.cjs  # process.platform -> 'linux' (sólo eso)
├── runtime/launch.cjs      # aplica el shim y delega en dist/cli.cjs del paquete
├── app/                    # node_modules (bun install) + bravecode-cli extraído (no se edita)
├── native/                 # libopentui.android-arm64.so + SHA256SUMS (artefacto del CI)
├── ci/build-opentui-android.sh     # clona OpenTUI, libc.txt, deps zig, zig build, verifica
├── ci/verify-libopentui.sh         # contrato de la .so (ELF AArch64 + libc.so + 397 símbolos + no-glibc)
├── ci/required-symbols.txt         # los 397 símbolos FFI de @opentui/core 0.5.9
├── ci/patch-opentui-android-translate-c.py  # headers del NDK para translate-c
├── .github/workflows/build-opentui-android.yml  # workflow que produce la .so
└── tests/                  # tests stdlib (verificador, parche, shim, launcher, install, TUI)
```

## Causa raíz del port (dos)

1. **`process.platform === 'android'`**. `getCurrentTarget()` del bundle sólo
   acepta darwin/linux/win32 → en Termux devuelve null → nunca llama a
   `setRenderLibPath()` → `createCliRenderer()` falla con *"OpenTUI is not
   supported on the current platform: android-arm64"*. Fix:
   `runtime/platform-shim.cjs` declara `'linux'` (Bun lo permite;
   `process.arch` queda `arm64`).
2. **No hay `libopentui.so` para Android**. `@opentui/core` publica binarios
   para linux/darwin/win32 (glibc/musl), que Bionic no carga. Fix: el workflow
   compila OpenTUI v0.5.9 para `aarch64-linux-android.24` (zig 0.16.0 + NDK
   r28b, receta de `../opencode-termux`) y `install.sh --patch` la copia sobre
   `app/node_modules/@opentui/core-linux-arm64/libopentui.so`.

## Reglas para agentes

- **No editar `app/node_modules/bravecode-cli/`** (paquete original). Lo único
  que se sobreescribe es `@opentui/core-linux-arm64/libopentui.so`, y es
  reversible con `./install.sh --deps`.
- **No tocar `runtime/platform-shim.cjs` para "arreglar" otra cosa**: el shim
  sólo existe por el punto 1. Si algo falla con `linux` falso, se documenta en
  `README.md` (limitaciones), no se amplía el shim sin evidencia.
- **La .so la produce el CI**, no builds locales: `./install.sh --native` baja
  el artefacto. Para cambios en la receta, se edita `ci/` y se empuja (el
  workflow corre solo por `paths: ci/**`).
- **Siempre** `python3 tests/run-tests.py` antes de dar algo por bueno. El test
  `test_glibc_lib_is_rejected` documenta por qué el verificador distingue
  `libc.so.6` (glibc) de `libc.so` (Bionic): si falla, la .so volvió a ser la de
  Linux y la TUI no arrancará.
- **El workflow no usa `sudo`/`/opt`**: NDK y zig se instalan dentro de
  `build/` (el runner rechazaba `mv` a `/opt` con "Device or resource busy").
- **No instalar paquetes** (`pkg install`, `npm i -g`) sin pedirlo: `--deps`
  instala sólo dentro de `app/`.

## Entorno Termux relevante

| Variable | Valor |
|----------|-------|
| `$PREFIX` | `/data/data/com.termux/files/usr` |
| `$TMPDIR` | `/data/data/com.termux/files/usr/tmp` (el launcher lo exporta si falta) |
| Shebang | `/data/data/com.termux/files/usr/bin/sh` (`/usr/bin/env` no existe) |
| `bun` | bionic, NDK r28b, 1.3.14 (reporta `platform=android`, `arch=arm64`) |
| `BRAVECODE_ROOT` / `BRAVECODE_APP_DIR` / `BRAVECODE_BUN` | overrides del launcher |
| `BRAVECODE_VERSION` / `BRAVECODE_NATIVE_DIR` / `BRAVECODE_GH_REPO` | overrides de `install.sh` |

## Reconstruir la lib nativa

1. `gh workflow run build-opentui-android.yml` (o push a `ci/**`).
2. `gh run list --workflow=build-opentui-android.yml` y esperar `success`.
3. `./install.sh --native && ./install.sh --patch && ./install.sh --check`.
4. Verificación real: `python3 tests/run-tests.py` (incluye la TUI en tmux).

## Pitfalls ya resueltos (no volver a tropezar)

- `translate-c` de OpenTUI **no hereda el `--libc`**: sin los include dirs del
  NDK falla con `'pthread.h' not found`; con ellos aparece
  `nullability specifier cannot be applied to non-pointer type` en
  `sys/time.h`. Se arregla en `ci/patch-opentui-android-translate-c.py`.
- En Zig 0.16 no existe `std.process.getEnvVarOwned`: los include dirs entran
  como opciones del build (`-Dndk-include`, `-Dndk-arch-include`).
- El `.so` de OpenTUI ≥0.4.5 exporta stubs `unsupported` de `embeddedTerminal*`
  y `clipboardService*` cuando el ABI no trae ghostty-vt (Android), así que los
  397 símbolos existen aunque esas features no funcionen.
- `@opentui/core-linux-arm64` declara `os: ["linux"]`: bun lo instala igual en
  Android, pero **no** hay que fiarse de que sea cargable (ver verificador).
