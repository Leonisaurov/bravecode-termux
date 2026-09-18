'use strict';
/**
 * Shim de plataforma para Termux/Android.
 *
 * Por qué existe: `@opentui/core` sólo publica binarios nativos para
 * darwin/linux/win32 y `bravecode-cli` decide qué librería cargar con
 * `process.platform`. En Termux `process.platform === 'android'`, así que su
 * preflight (`getCurrentTarget()` en dist/cli-main.mjs) devuelve null, nunca
 * llama a `setRenderLibPath()` y `createCliRenderer()` termina en
 * "OpenTUI is not supported on the current platform: android-arm64".
 *
 * Declarar `'linux'` hace que el preflight busque el paquete de plataforma
 * `@opentui/core-linux-arm64`; el port instala ahí la lib compilada para
 * Android (`install.sh --native` + `--patch`), que es la única que el linker
 * de Bionic puede cargar. `process.arch` se deja intacto ('arm64').
 *
 * Bun permite redefinir `process.platform`; este shim lo verifica y falla
 * ruidosamente en vez de dejar el CLI en un estado incoherente.
 *
 * @returns {'linux'} el valor efectivo de process.platform
 */
function applyPlatformShim() {
  const target = 'linux';
  if (process.platform === target) return target;

  try {
    Object.defineProperty(process, 'platform', {
      value: target,
      writable: true,
      configurable: true,
      enumerable: true,
    });
  } catch (defineErr) {
    try {
      process.platform = target;
    } catch (assignErr) {
      throw new Error(
        `no se pudo aplicar el shim de plataforma (process.platform=${process.platform}): ${assignErr.message}`,
      );
    }
  }

  if (process.platform !== target) {
    throw new Error(`el shim de plataforma no tomó efecto (process.platform=${process.platform})`);
  }
  return target;
}

module.exports = { applyPlatformShim };
