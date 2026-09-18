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

## Estado

| Ítem | Estado |
|------|--------|
| Arranque del CLI | ✅ `bravecode --version` / `--help` (bun 1.3.14 bionic) |
| Comandos no interactivos | ✅ `models`, `providers`, `tools`, `agents`, `plugins`, `config` |
| Prompt real (headless) | ✅ `bravecode run "..."` contra el endpoint free del paquete |
| TUI (OpenTUI 0.5.9) | ✅ con `native/libopentui.android-arm64.so` (CI) + `install.sh --patch` |
| Tests | ✅ `python3 tests/run-tests.py` (stdlib) |

## Qué hace el port

Dos problemas, dos arreglos mínimos y reversibles:

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

`ci/verify-libopentui.sh` es la puerta: exige ELF AArch64 DYN, `NEEDED libc.so`
y los **397 símbolos FFI** que `@opentui/core` 0.5.9 pide en `dlopen`
(`ci/required-symbols.txt`, extraído del paquete). Una lib de otra versión
(p. ej. la 0.3.4 que ya existía en el device) falla con 44 símbolos ausentes.

## Requisitos

- Termux aarch64 con `bun` (bionic; probado con 1.3.14), `git`, `curl`, `gh`
  (para bajar el artefacto), `readelf` (binutils) y `python3` para los tests.

## Tests

```sh
python3 tests/run-tests.py     # verificador de lib, shim, launcher, install.sh, TUI
./install.sh --check           # estado del port
```

## Limitaciones conocidas

- **Paquete cerrado y sin repo público**: el `homepage` (`bravecode.dev`) no
  resuelve DNS y `github.com/brave-code-tech/brave-ai` no existe. Los fuentes TS
  se recuperan del sourcemap del bundle; este repo no redistribuye el paquete.
- **Provider "free" de terceros**: el modelo por defecto
  (`codestral-latest`) se sirve desde `https://codero.sohailsyed.com/api/chat`,
  un endpoint ajeno a Brave/Nous: los prompts viajan ahí salvo que configures
  un provider propio (`bravecode config`). Trátalo como servicio no confiable.
- La lib se compila contra API 24 (`minSdk`); no se han probado APIs menores.
- `embeddedTerminal*` y `clipboardService*` se exportan pero devuelven
  "unsupported" en Android (OpenTUI deja fuera ghostty-vt y los backends de
  portapapeles en este ABI): sus features no funcionan, el resto sí.
