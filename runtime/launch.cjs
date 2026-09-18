'use strict';
/**
 * Arranque del CLI de BraveCode en Termux/Android.
 *
 * Orden deliberado (no cambiar):
 *   1. aplicar el shim de plataforma, para que el preflight de la TUI del
 *      bundle vea 'linux-arm64' y apunte a la lib Android;
 *   2. aplicar el shim de eventos del Input (OpenTUI 0.5.9 emite CHANGE sólo en
 *      el submit, y con él la TUI no puede enviar nada desde su onChange);
 *   3. ceder el control al bootstrap del propio paquete (`dist/cli.cjs`), que
 *      instala el polyfill de self/window/document que necesitan
 *      react-devtools-core e ink y sólo después importa `dist/cli-main.mjs`.
 *
 * El bundle se carga desde `bravecode-cli` en el node_modules de la app; no se
 * copia ni se parchea ningún archivo del paquete original.
 */
const path = require('node:path');
const { applyPlatformShim } = require('./platform-shim.cjs');
const { applyInputChangeShim } = require('./opentui-input-compat.cjs');

const appDir = process.env.BRAVECODE_APP_DIR || path.join(__dirname, '..', 'app');
const bootstrap = path.join(appDir, 'node_modules', 'bravecode-cli', 'dist', 'cli.cjs');

applyPlatformShim();

applyInputChangeShim()
  .catch((err) => {
    if (process.env.BRAVECODE_DEBUG) console.error('[bravecode] input-compat falló:', err && err.message);
    return false;
  })
  .then(() => {
    try {
      require(bootstrap);
    } catch (err) {
      console.error(
        `[bravecode] no se pudo cargar el CLI desde ${bootstrap}:`,
        err && err.message ? err.message : err,
      );
      process.exit(1);
    }
  });
