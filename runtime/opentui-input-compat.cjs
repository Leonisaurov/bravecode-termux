'use strict';
/**
 * Compatibilidad de eventos del Input de OpenTUI 0.5.9 con la TUI de BraveCode.
 *
 * En @opentui/core 0.5.9 el renderable `Input` emite:
 *   - INPUT  en cada tecla (`insertText`, borrados…)
 *   - CHANGE sólo en `blur()` / `submit()`  (semántica de "valor confirmado")
 *   - ENTER  en `submit()`
 *
 * La TUI del CLI sincroniza su estado React con `onChange`, así que mientras se
 * escribe el `value` del estado sigue vacío: la paleta de `/` no aparece y
 * `doSubmit()` corta con `if (!value.trim()) return` — el ENTER llega al
 * renderable, pero el closure lee '' y nunca se envía el prompt. Comprobado en
 * el device: escribiendo "abc" sólo se emite un CHANGE (en el submit), y con el
 * shim se emite uno por tecla.
 *
 * El shim envuelve `emit` del prototipo de InputRenderable para que INPUT emita
 * también CHANGE con el mismo valor. No toca el paquete npm ni el bundle.
 */
const path = require('node:path');
const { createRequire } = require('node:module');
const { pathToFileURL } = require('node:url');

const EMPTY = Symbol.for('bravecode.opentui-input-compat');

/** Carga `@opentui/core` (o un subpath, p.ej. `@opentui/core/testing`) tal como
 *  lo hará el bundle (mismo node_modules). */
async function loadCore(subpath = '') {
  const appDir = process.env.BRAVECODE_APP_DIR || path.join(__dirname, '..', 'app');
  const require_ = createRequire(path.join(appDir, 'package.json'));
  const resolved = require_.resolve(`@opentui/core${subpath}`);
  return import(pathToFileURL(resolved).href);
}

/**
 * Hace que INPUT emita además CHANGE con el mismo valor.
 * @returns {Promise<boolean>} true si el shim quedó aplicado
 */
async function applyInputChangeShim() {
  let core;
  try {
    core = await loadCore();
  } catch (err) {
    if (process.env.BRAVECODE_DEBUG) console.error('[bravecode] input-compat: no pude cargar @opentui/core:', err.message);
    return false;
  }
  const proto = core.InputRenderable && core.InputRenderable.prototype;
  const events = core.InputRenderableEvents;
  if (!proto || !events || !events.INPUT || !events.CHANGE) return false;
  if (proto[EMPTY]) return true;

  const originalEmit = proto.emit;
  if (typeof originalEmit !== 'function') return false;

  Object.defineProperty(proto, 'emit', {
    configurable: true,
    writable: true,
    value: function emitWithChange(event, ...args) {
      const result = originalEmit.call(this, event, ...args);
      if (event === events.INPUT) {
        try {
          originalEmit.call(this, events.CHANGE, ...args);
        } catch {
          /* un listener de CHANGE no debe romper el input */
        }
      }
      return result;
    },
  });
  Object.defineProperty(proto, EMPTY, { value: true, configurable: true });
  return true;
}

module.exports = { applyInputChangeShim, loadCore };
