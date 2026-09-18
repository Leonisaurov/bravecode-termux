# BraveCode Termux — Agent Instructions

Port de `bravecode-cli` (CLI cerrado, bundle Node/Bun) a Termux/Android aarch64.
El bundle externaliza React/Ink y el núcleo nativo **OpenTUI**; el port **no**
parchea el paquete: compila OpenTUI para Android en CI, inyecta la .so donde el
CLI la busca y corrige tres suposiciones de entorno (plataforma, eventos del
input y nombres de flecha).

## Estructura

```
BraveCode/
├── install.sh                  # --fetch npm, --deps bun, --native (artifact CI), --patch, --all, --check, --bin
├── bin/bravecode               # launcher (bun + shims); BRAVECODE_ROOT para la copia en $PREFIX/bin
├── runtime/platform-shim.cjs   # process.platform -> 'linux' (sólo eso)
├── runtime/opentui-input-compat.cjs  # INPUT->CHANGE + alias up/down -> arrowUp/arrowDown
├── runtime/launch.cjs          # aplica shims y delega en dist/cli.cjs del paquete
├── app/                        # node_modules (bun install) + bravecode-cli extraído (no se edita)
├── native/                     # libopentui.android-arm64.so + SHA256SUMS (artefacto del CI)
├── ci/build-opentui-android.sh # clona OpenTUI, libc.txt, deps zig, parchea build.zig, compila, verifica
├── ci/verify-libopentui.sh     # contrato de la .so (ELF AArch64 + libc.so + 397 símbolos + UND resolubles)
├── ci/required-symbols.txt     # los 397 símbolos FFI de @opentui/core 0.5.9
├── ci/patch-opentui-android-translate-c.py  # parches del build.zig (translate-c, link, shim de Bionic)
├── ci/bionic-compat.c          # define pthread_tryjoin_np (glibc-only) dentro de la .so
├── .github/workflows/build-opentui-android.yml  # workflow que produce la .so
└── tests/                      # 40 tests stdlib (verificador, parches, shims, launcher, install, TUI)
```

## Causas raíz del port (cuatro)

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
3. **`onChange` no llega al escribir**. En `@opentui/core` 0.5.9 el
   `InputRenderable` emite `INPUT` por tecla y `CHANGE` sólo en
   `blur()`/`submit()`; la TUI sincroniza su estado React con `onChange`, así
   que su `value` está vacío mientras escribes: la paleta de `/` no abre y
   `doSubmit()` sale por `if (!value.trim()) return`. Fix:
   `runtime/opentui-input-compat.cjs` hace que `INPUT` emita también `CHANGE`.
4. **Las flechas no navegan el diálogo de agentes/modelos**. El parser de
   OpenTUI 0.5.9 nombra las flechas `up`/`down` (raw y kitty), pero el
   `ModelAgentDialog` compara `arrowUp`/`arrowDown` → `selectedIdx` no se mueve.
   Fix: el mismo shim re-emite `up/down/left/right` como
   `arrow*` envolviendo `emit` de **`InternalKeyHandler`** (ojo: `renderer.keyInput`
   *es* `renderer._internalKeyInput` y su `emit` no delega en `KeyHandler`; envolver
   la clase base no intercepta nada — medido). Queda un bug del CLI sin arreglar
   (no del port): el resaltado no se repinta porque el índice vive en un `useRef`;
   ver "Limitaciones" en `README.md`.

## Reglas para agentes

- **No editar `app/node_modules/bravecode-cli/`** (paquete original). Lo único
  que se sobreescribe es `@opentui/core-linux-arm64/libopentui.so`, y es
  reversible con `./install.sh --deps`.
- **Los shims son mínimos y con causa documentada**: si algo falla con el
  `'linux'` falso o con el `CHANGE` extra, se documenta en `README.md`, no se
  amplía un shim sin evidencia medida.
- **La .so la produce el CI**, no builds locales: `./install.sh --native` baja
  el artefacto. Para cambios en la receta, se edita `ci/` y se empuja (el
  workflow corre solo por `paths: ci/**`).
- **`install.sh --patch` siempre hace `rm -f` antes del `cp`**: bun enlaza los
  archivos de `node_modules` al cache con **symlinks** (en Android/SELinux no se
  pueden crear hardlinks: `ln` falla con Permission denied) y un `cp -f` directo
  escribiría a través del enlace y dejaría el cache con la lib Android dentro.
- **Siempre** `python3 tests/run-tests.py` antes de dar algo por bueno. Los
  tests fijan las causas raíz: `test_glibc_lib_is_rejected` (libc.so.6 vs
  libc.so), `test_unresolved_symbols_are_reported` (pthread_tryjoin_np),
  `test_shim_makes_change_fire_per_keystroke` (eventos del Input),
  `test_arrows_get_aliases_without_duplicating_normal_keys` (flechas) y
  `test_tui_renders_in_tmux` (TUI real).
- **No instalar paquetes** (`pkg install`, `npm i -g`) sin pedirlo: `--deps`
  instala sólo dentro de `app/`.
- El workflow **no usa `sudo`/`/opt`**: NDK y zig se instalan dentro de
  `build/` (el runner rechazaba `mv` a `/opt` con "Device or resource busy").

## Entorno Termux relevante

| Variable | Valor |
|----------|-------|
| `$PREFIX` | `/data/data/com.termux/files/usr` |
| `$TMPDIR` | `/data/data/com.termux/files/usr/tmp` (el launcher lo exporta si falta) |
| Shebang | `/data/data/com.termux/files/usr/bin/sh` (`/usr/bin/env` no existe) |
| `bun` | bionic, NDK r28b, 1.3.14 (reporta `platform=android`, `arch=arm64`) |
| `BRAVECODE_ROOT` / `BRAVECODE_APP_DIR` / `BRAVECODE_BUN` | overrides del launcher |
| `BRAVECODE_VERSION` / `BRAVECODE_NATIVE_DIR` / `BRAVECODE_GH_REPO` / `BRAVECODE_NDK_LIB` | overrides de `install.sh` / verificador |
| `BRAVECODE_DEBUG=1` | el launcher imprime por qué falló un shim |

## Reconstruir la lib nativa

1. `gh workflow run build-opentui-android.yml` (o push a `ci/**`).
2. `gh run watch` hasta `success` (~1.5 min con cache, ~4 min en frío).
3. `./install.sh --native && ./install.sh --patch && ./install.sh --check`.
4. Verificación real: `python3 tests/run-tests.py` (incluye la TUI en tmux) y un
   prompt manual en la TUI.

## Pitfalls ya resueltos (no volver a tropezar)

- `translate-c` de OpenTUI **no hereda el `--libc`**: sin los include dirs del
  NDK falla con `'pthread.h' not found`; con ellos aparece
  `nullability specifier cannot be applied to non-pointer type` en
  `sys/time.h`. Se arregla en `ci/patch-opentui-android-translate-c.py`.
- En Zig 0.16 no existe `std.process.getEnvVarOwned` ni `std.posix.getenv`: los
  datos entran como opciones del build (`-Dndk-include`, `-Dndk-arch-include`,
  `-Dndk-lib`, `-Dbionic-compat-c`), leídas **una sola vez** (`b.option`
  paniquea con `Option 'ndk-include' declared twice` porque los helpers se
  llaman por cada paso translate-c).
- En Android el link no puede pedir `dl`/`pthread` (no existen en Bionic) y Zig
  no encuentra `m` sin `-L` al NDK (`searched paths: none`).
- Zig 0.16 emite `pthread_tryjoin_np` (glibc) en `std.Thread` para
  `linux-android`; `ci/bionic-compat.c` lo define dentro de la propia .so. Sin
  eso, bun:ffi falla en `dlopen` con *"cannot locate symbol"*.
- El `.so` de OpenTUI ≥0.4.5 exporta stubs `unsupported` de `embeddedTerminal*`
  y `clipboardService*` cuando el ABI no trae ghostty-vt (Android), así que los
  397 símbolos existen aunque esas features no funcionen.
- `@opentui/core-linux-arm64` declara `os: ["linux"]`: bun lo instala igual en
  Android, pero **no** hay que fiarse de que sea cargable (ver verificador).
- `ci/verify-libopentui.sh` usa `grep -vxF -f` en vez de `comm`: con `LANG`
  UTF-8 `comm` comparaba mal y daba falsos positivos; además el handler del
  `trap EXIT` debe terminar con `return 0` o machaca los códigos de salida 2-7.
- `gh run download` falla al extraer si los archivos ya existen: `--native`
  limpia antes `native/libopentui.android-arm64.so` y `native/SHA256SUMS`.
