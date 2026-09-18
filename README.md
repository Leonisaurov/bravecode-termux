# BraveCode en Termux (Android aarch64)

Port de `bravecode-cli` (BraveCode AI: "Agentic AI Vibe Coding CLI with free
model support") para Termux. El paquete oficial es un bundle Node/Bun que
externaliza React, Ink y el núcleo **OpenTUI** (Zig). OpenTUI no publica
binarios Android — y los de Linux son glibc, que Bionic no puede cargar — así
que este repo **compila esa librería para aarch64-linux-android en CI** y la
inyecta donde el CLI la busca.

    ./install.sh --all       # paquete npm + deps + lib nativa del CI + parche
    ./bin/bravecode          # TUI
    ./bin/bravecode --help   # comandos no interactivos

## Estado (verificado en este device)

| Ítem | Estado |
|------|--------|
| Arranque del CLI | ✅ `bravecode --version` → `0.1.57` (bun 1.3.14 bionic) |
| Comandos no interactivos | ✅ `models`, `providers`, `tools`, `agents`, `plugins`, `config` |
| Prompt real (headless) | ✅ `bravecode run "Responde únicamente con la palabra: ok"` → `ok` |
| TUI (OpenTUI 0.5.9) | ✅ renderiza y responde en tmux (prompt → "port ok", sidebar con tokens/MCP) |
| Tests | ✅ `python3 tests/run-tests.py` (38 tests, stdlib) |

## Qué hace el port

Tres problemas, tres arreglos mínimos y reversibles; no se edita ningún archivo
del paquete `bravecode-cli`.

**1. `process.platform === "android"`.** El bundle decide qué librería nativa
cargar con `getCurrentTarget()` (`dist/cli-main.mjs`): sólo acepta
`darwin|linux|win32`, así que en Termux devuelve `null`, nunca llama a
`setRenderLibPath()` y la TUI muere con *"OpenTUI is not supported on the
current platform: android-arm64"*. `runtime/platform-shim.cjs` declara
`process.platform = "linux"` (Bun lo permite; `process.arch` queda `arm64`) y
cede el arranque al bootstrap del propio paquete, que aplica su polyfill e
importa el bundle.

**2. No existe `libopentui.so` para Android.** Con el shim, el CLI busca
`@opentui/core-linux-arm64/libopentui.so`. `.github/workflows/build-opentui-android.yml`
compila la fuente de OpenTUI (`v0.5.9`) con Zig 0.16.0 y el NDK r28b
(`aarch64-linux-android.24`, `--libc android-libc.txt`) siguiendo la receta ya
validada en `../opencode-termux`, y publica el artefacto
`libopentui-android-arm64`. `install.sh --patch` copia ese `.so` sobre el
paquete de plataforma — es el único fichero que se toca, y se puede volver
atrás reinstalando deps.

Quien comprueba que la `.so` sirve es `ci/verify-libopentui.sh`: ELF AArch64 DYN,
`NEEDED libc.so` (Bionic, no glibc), los **397 símbolos FFI** que
`@opentui/core` 0.5.9 pide en `dlopen` (`ci/required-symbols.txt`, extraído del
paquete) y — con `--ndk-lib` — que todos sus símbolos indefinidos existan en las
librerías de Bionic. Una lib de otra versión (p. ej. la 0.3.4 que ya existía en
el device) falla con 44 símbolos ausentes.

**3. Bug de la TUI con OpenTUI 0.5.9: `onChange` no se dispara al escribir.**
`@opentui/core` 0.5.9 emite `INPUT` en cada tecla y `CHANGE` sólo al confirmar
(`blur`/`submit`); la TUI sincroniza su estado React con `onChange`, así que
mientras escribes su `value` sigue vacío: la paleta de `/` no aparece y
`doSubmit()` corta con `if (!value.trim()) return` (el ENTER llega al
renderable, pero el closure lee `''`). Medido en el device: teclear `abc` emite
`INPUT`×3 y un único `CHANGE`; al pulsar Enter no pasa nada.
`runtime/opentui-input-compat.cjs` envuelve `emit` del prototipo de
`InputRenderable` para que `INPUT` emita también `CHANGE` con el mismo valor,
con lo que el estado se sincroniza por tecla y el prompt se envía.

## Requisitos

- Termux aarch64 con `bun` (bionic; probado con 1.3.14), `git`, `curl`, `gh`
  (para bajar el artefacto), `readelf` (binutils) y `python3` para los tests.

## Tests

```sh
python3 tests/run-tests.py     # verificador de lib, parches, shims, launcher, install.sh, TUI
./install.sh --check           # estado del port
```

Los tests con hardware/CI se saltan solos cuando falta la pieza (NDK local, lib
nativa, tmux). La TUI se prueba en tmux (`tests/test_tui.py`).

## Limitaciones conocidas

- **Paquete cerrado y sin repo público**: el `homepage` (`bravecode.dev`) no
  resuelve DNS y `github.com/brave-code-tech/brave-ai` no existe. Los fuentes TS
  se recuperaron del sourcemap del bundle; este repo no redistribuye el paquete.
- **Provider "free" de terceros**: el modelo por defecto (`codestral-latest`) se
  sirve desde `https://codero.sohailsyed.com/api/chat`, un endpoint ajeno a
  Brave/Nous: los prompts viajan ahí salvo que configures un provider propio
  (`bravecode config`). Trátalo como servicio no confiable.
- La lib se compila contra API 24 (`minSdk`); no se han probado APIs menores.
- `embeddedTerminal*` y `clipboardService*` se exportan pero devuelven
  "unsupported" en Android (OpenTUI deja fuera ghostty-vt y los backends de
  portapapeles en este ABI): esas features no funcionan, el resto sí.
- El arreglo del punto 3 vive en `runtime/`, no en el paquete: si algún día
  bravecode-cli cambia a `onInput` (o OpenTUI corrige la semántica de `CHANGE`),
  el shim se vuelve innecesario y hay que quitarlo (los tests lo detectan).
