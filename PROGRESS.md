# Progreso del port de BraveCode a Termux

## Qué es esto

Port de `bravecode-cli` (paquete npm, "BraveCode AI") a Termux/Android aarch64.
Repo del port: `github.com/Leonisaurov/bravecode-termux` (ahí vive el CI que
compila la librería nativa de OpenTUI para Android).

## Estado actual — port completo y verificado

| Pieza | Estado | Evidencia |
|-------|--------|-----------|
| CLI arranca en Termux | ✅ | `./bin/bravecode --version` → `0.1.57` (bun 1.3.14 bionic) |
| Comandos no interactivos | ✅ | `models`, `providers`, `tools`, `agents`, `plugins`, `config` |
| Prompt real (headless) | ✅ | `bravecode run "Responde únicamente con la palabra: ok"` → `ok` |
| Lib nativa Android 0.5.9 | ✅ | artefacto del CI (21.9 MB, sha256 `c7073882…`), verificado en el device |
| TUI en tmux | ✅ | renderiza (banner, input, sidebar) y responde: prompt → `port ok` |
| Shim de plataforma | ✅ | `runtime/platform-shim.cjs` (platform=linux, arch=arm64) |
| Compat de eventos del Input | ✅ | `runtime/opentui-input-compat.cjs` (INPUT→CHANGE) |
| Compat de flechas | ✅ | mismo shim: `up/down` → `arrowUp/arrowDown`; `↓`+Enter→`plan`, `↓↓↓`+Enter→`testing` |
| Tests | ✅ | `python3 tests/run-tests.py` (40 tests, stdlib) |

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
5. **Decisiones de port**: shims mínimos (no se parchea el bundle ni el paquete
   npm) + inyección de la lib Android en
   `@opentui/core-linux-arm64/libopentui.so` (lo que el preflight del CLI busca
   cuando la plataforma es `linux`).
6. **Bug de la TUI encontrado midiendo**: `@opentui/core` 0.5.9 emite `INPUT`
   por tecla y `CHANGE` sólo al confirmar; la TUI sincroniza su estado con
   `onChange`, así que no se podía enviar nada (la paleta de `/` no abría y el
   ENTER llegaba al renderable pero `doSubmit()` leía `value` vacío). Se aisló
   con TestRenderer de OpenTUI (CHANGE×1 al teclear `abc`) y se arregló con un
   shim que emite `CHANGE` en cada `INPUT`.
7. **Segundo bug de la TUI, reportado por el usuario**: "las flechas no me
   dejan navegar entre modelos". Medido con un probe sobre el `KeyHandler` real
   del renderer: `↓` produce **un** `keypress` con `name: "down"` — el parser de
   OpenTUI 0.5.9 sólo usa `up/down/left/right` — pero `ModelAgentDialog` compara
   `arrowUp`/`arrowDown`, así que `selectedIdx` nunca se movía. El primer intento
   de shim (envolver `KeyHandler.prototype.emit`) no interceptaba nada: el
   emisor es **`InternalKeyHandler`** y `renderer.keyInput` *es*
   `renderer._internalKeyInput` (medido: `sameObject: true`,
   `keyHandlerEmitSeen: 0` vs `internalEmitSeen: 1`). Con el `emit` correcto
   envuelto, la navegación se verificó en la TUI real: 1 `↓`+Enter → `plan`,
   2 → `debug`, 3 → `testing`. Sigue pendiente (bug del CLI, no del port) que el
   resaltado no se repinta: el índice vive en un `useRef` y el componente no
   re-renderiza; `tab` lo resetea a 0. Vía visible: `bravecode config
   agent.default <id>` / `model.default <id>`.

## Iteraciones del CI (todas verificadas en el runner)

| # | Fallo | Arreglo |
|---|-------|---------|
| 1 | `mv` a `/opt` → "Device or resource busy" | NDK y zig dentro de `build/`, sin `sudo` |
| 2 | `ci/build-opentui-android.sh: Permission denied` | bit +x en git + invocación con `bash` |
| 3 | `miniaudio.h: 'pthread.h' not found` (translate-c sin headers) | parche `ci/patch-opentui-android-translate-c.py` (includes del NDK) |
| 4 | `build.zig: root source file struct 'process' has no member named 'getEnvVarOwned'` | opciones del build (`-Dndk-include`, `-Dndk-arch-include`) |
| 5 | `panic: Option 'ndk-include' declared twice` | el helper cachea las rutas (se llama una vez por translate-c) |
| 6 | `unable to find dynamic system library 'dl'/'pthread'/'m' ... searched paths: none` | en Android el módulo recibe el library path del NDK (`-Dndk-lib`) y se linkea sólo `m` |
| 7 | build verde, pero la TUI moría en `dlopen: cannot locate symbol "pthread_tryjoin_np"` | `ci/bionic-compat.c` define el símbolo dentro de la .so (`-Dbionic-compat-c`) |

Diagnósticos hechos en el device (zig 0.16.0 + NDK r29 local) antes de cada
arreglo: el translate-c de OpenTUI no hereda el `--libc`; al apuntarlo al NDK
aparece el error de nullability de `sys/time.h`; el link de Bionic no tiene
`dl`/`pthread`; y de los 171 símbolos indefinidos de la .so **sólo**
`pthread_tryjoin_np` faltaba en Bionic (medido contra las libs del NDK). Todo
eso quedó fijado en tests.

## Pendiente / siguientes pasos

- Uso real en el terminal del usuario (TUI interactiva con prompts del día a
  día); el servicio free (`codero.sohailsyed.com`) es de terceros: para trabajo
  serio, configurar un provider propio con `bravecode config`.
- Opcional: `./install.sh --bin` para exponer `bravecode` en `$PREFIX/bin`.
- ~~Revisar si el checksum del artefacto (`SHA256SUMS`) usa rutas relativas~~:
  corregido en el workflow (se genera dentro de `native/`).
