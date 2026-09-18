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
 *
 * El mismo archivo trae `applyKeyAliasShim()`: en 0.5.9 el parser de teclas
 * nombra las flechas `up`/`down` (raw y kitty), pero la TUI de BraveCode compara
 * con `arrowUp`/`arrowDown`, así que su diálogo de agentes/modelos nunca movía
 * `selectedIdx`. El shim re-emite el `keypress` con el nombre `arrow*` además
 * del original (el core sigue recibiendo el suyo: cursor, edición…).
 */
const path = require('node:path');
const { createRequire } = require('node:module');
const { pathToFileURL } = require('node:url');

const EMPTY = Symbol.for('bravecode.opentui-input-compat');
const KEYS_EMPTY = Symbol.for('bravecode.opentui-key-alias');

/** Nombres que la TUI espera para las flechas frente a los del parser. */
const ARROW_ALIASES = {
  up: 'arrowUp',
  down: 'arrowDown',
  left: 'arrowLeft',
  right: 'arrowRight',
};

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

/**
 * Las flechas llegan como `up`/`down` (el parser de OpenTUI 0.5.9 no usa
 * `arrowUp`/`arrowDown` ni en raw ni en kitty), pero la TUI del CLI compara con
 * `arrowUp`/`arrowDown`: su diálogo de modelos/agentes no navega con las
 * flechas. Este shim re-emite el `keypress` con el nombre alternativo, de modo
 * que la app lo entienda; quien usa los nombres nativos (el propio core:
 * edición, movimiento de cursor) sigue recibiendo el evento original.
 *
 * @returns {Promise<boolean>} true si el shim quedó aplicado
 */
async function applyKeyAliasShim() {
  let core;
  try {
    core = await loadCore();
  } catch (err) {
    if (process.env.BRAVECODE_DEBUG) console.error('[bravecode] key-alias: no pude cargar @opentui/core:', err.message);
    return false;
  }
  // El renderer expone `keyInput === _internalKeyInput` y esa instancia es un
  // InternalKeyHandler, cuya implementación de `emit` NO delega en la clase base
  // (medido: envolver KeyHandler.prototype.emit no intercepta nada). Hay que
  // envolver la clase que realmente emite.
  const cls = core.InternalKeyHandler || core.KeyHandler;
  const proto = cls && cls.prototype;
  if (!proto) return false;
  if (proto[KEYS_EMPTY]) return true;

  const originalEmit = proto.emit;
  if (typeof originalEmit !== 'function') return false;

  Object.defineProperty(proto, 'emit', {
    configurable: true,
    writable: true,
    value: function emitWithArrowAliases(event, payload, ...rest) {
      const result = originalEmit.call(this, event, payload, ...rest);
      if (event === 'keypress' && payload && ARROW_ALIASES[payload.name] && payload.eventType !== 'release') {
        try {
          const clone = Object.create(Object.getPrototypeOf(payload));
          Object.assign(clone, payload);
          clone.name = ARROW_ALIASES[payload.name];
          originalEmit.call(this, 'keypress', clone);
          if (process.env.BRAVECODE_KEYS_DEBUG) {
            const listeners =
              typeof this.listenerCount === 'function' ? this.listenerCount('keypress') : '?';
            require('node:fs').appendFileSync(
              process.env.BRAVECODE_KEYS_DEBUG,
              `alias ${payload.name}->${clone.name} listeners=${listeners}\n`,
            );
          }
        } catch {
          /* un alias no debe romper el input */
        }
      }
      return result;
    },
  });
  Object.defineProperty(proto, KEYS_EMPTY, { value: true, configurable: true });
  return true;
}

module.exports = { applyInputChangeShim, applyKeyAliasShim, loadCore };
