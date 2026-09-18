/*
 * Shims de símbolos que Bionic no tiene y que la librería de OpenTUI pide igual.
 *
 * Se compila dentro del mismo módulo que el core (ver el parche
 * ci/patch-opentui-android-translate-c.py, opción -Dbionic-compat-c), de forma
 * que el símbolo queda definido en la propia libopentui.so.
 *
 * pthread_tryjoin_np
 *   Zig 0.16 emite una llamada a esta función de glibc en std.Thread incluso
 *   para el target aarch64-linux-android, donde no existe. Consecuencia medida
 *   en el device:
 *
 *     dlopen failed: cannot locate symbol "pthread_tryjoin_np"
 *       referenced by ".../@opentui/core-linux-arm64/libopentui.so"
 *
 *   Semántica esperada por el llamador (Zig's Thread.join): 0 si el hilo ya
 *   terminó, EBUSY si sigue vivo (en cuyo caso se hace el join con semáforo).
 *   Bionic sólo ofrece pthread_join (bloqueante), así que se hace eso y se
 *   devuelve 0; se pierde la optimización, no la corrección.
 */
#include <errno.h>
#include <pthread.h>

int pthread_tryjoin_np(pthread_t thread, void **retval) {
    int rc = pthread_join(thread, retval);
    return rc == 0 ? 0 : EBUSY;
}
