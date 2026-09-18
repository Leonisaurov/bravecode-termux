'use strict';
/**
 * Arranque del CLI de BraveCode en Termux/Android.
 *
 * Orden deliberado (no cambiar):
 *   1. aplicar el shim de plataforma, para que el preflight de la TUI del
 *      bundle vea 'linux-arm64' y apunte a la lib Android;
 *   2. ceder el control al bootstrap del propio paquete (`dist/cli.cjs`), que
 *      instala el polyfill de self/window/document que necesitan
 *      react-devtools-core e ink y sólo después importa `dist/cli-main.mjs`.
 *
 * El bundle se carga desde `bravecode-cli` en el node_modules de la app; no se
 * copia ni se parchea ningún archivo del paquete original.
 */
const path = require('node:path');
const { applyPlatformShim } = require('./platform-shim.cjs');

const appDir = process.env.BRAVECODE_APP_DIR || path.join(__dirname, '..', 'app');
const bootstrap = path.join(appDir, 'node_modules', 'bravecode-cli', 'dist', 'cli.cjs');

applyPlatformShim();

try {
  require(bootstrap);
} catch (err) {
  console.error(`[bravecode] no se pudo cargar el CLI desde ${bootstrap}:`, err && err.message ? err.message : err);
  process.exit(1);
}
