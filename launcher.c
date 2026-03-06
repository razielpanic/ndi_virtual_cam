/*
 * NDI Virtual Cam — native app bundle launcher stub
 *
 * This tiny binary exists so that macOS Launch Services sees a real
 * Mach-O executable (arm64) instead of a shell script.  Without it,
 * Launch Services cannot determine the architecture and prompts the
 * user to install Rosetta.
 *
 * All it does is exec run.sh three directories up from its own path.
 *
 * Build (universal):
 *   clang -arch arm64 -arch x86_64 -O2 \
 *       -o "NDI Virtual Cam.app/Contents/MacOS/launcher" launcher.c
 */

#include <errno.h>
#include <libgen.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    /* Resolve absolute path of this executable */
    uint32_t bufsz = 0;
    _NSGetExecutablePath(NULL, &bufsz);
    char *exe = malloc(bufsz);
    if (!exe || _NSGetExecutablePath(exe, &bufsz) != 0) {
        fprintf(stderr, "launcher: cannot resolve executable path\n");
        return 1;
    }

    char *real = realpath(exe, NULL);
    free(exe);
    if (!real) {
        fprintf(stderr, "launcher: realpath failed: %s\n", strerror(errno));
        return 1;
    }

    /* Walk up four levels: launcher -> MacOS/ -> Contents/ -> App.app/ -> project root */
    char *dir = real;
    for (int i = 0; i < 4; i++) {
        dir = dirname(dir);
    }

    /* Build path to run.sh */
    char script[4096];
    snprintf(script, sizeof(script), "%s/run.sh", dir);

    /*
     * Augment PATH for Finder-launched environment.
     * Finder provides only /usr/bin:/bin:/usr/sbin:/sbin.  Homebrew Python
     * lives in /opt/homebrew/bin (Apple Silicon) or /usr/local/bin (Intel).
     */
    const char *path = getenv("PATH");
    char newpath[8192];
    snprintf(newpath, sizeof(newpath),
             "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin%s%s",
             path ? ":" : "", path ? path : "");
    setenv("PATH", newpath, 1);

    /* exec run.sh, passing through any arguments */
    execv(script, argv);

    /* If exec returns, it failed */
    fprintf(stderr, "launcher: exec %s failed: %s\n", script, strerror(errno));
    free(real);
    return 1;
}
