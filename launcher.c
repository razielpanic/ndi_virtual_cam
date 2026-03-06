/*
 * NDI Virtual Cam — native app bundle launcher stub
 *
 * This tiny binary exists so that macOS Launch Services sees a real
 * Mach-O executable (arm64) instead of a shell script.  Without it,
 * Launch Services cannot determine the architecture and prompts the
 * user to install Rosetta.
 *
 * It forks and execs run.sh, capturing its output.  If run.sh exits
 * without exec-ing the Python app (i.e. a setup error), the captured
 * output is shown in a native macOS dialog so the operator sees why.
 *
 * Build (universal):
 *   clang -arch arm64 -arch x86_64 -O2 \
 *       -o "NDI Virtual Cam.app/Contents/MacOS/launcher" launcher.c
 */

#include <errno.h>
#include <libgen.h>
#include <mach-o/dyld.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

/* Show a native macOS error dialog via osascript */
static void show_error_dialog(const char *msg) {
    /* Truncate to first ~500 chars to keep the dialog readable */
    char buf[600];
    snprintf(buf, sizeof(buf), "%.500s", msg);
    /* Escape double quotes for AppleScript */
    for (char *p = buf; *p; p++) {
        if (*p == '"') *p = '\'';
        if (*p == '\n' && *(p+1) == '\0') *p = '\0';
    }
    char script[1024];
    snprintf(script, sizeof(script),
        "display dialog \"%s\" with title \"NDI Virtual Cam\" "
        "buttons {\"OK\"} default button \"OK\" with icon stop", buf);
    pid_t pid;
    char *osargv[] = {"osascript", "-e", script, NULL};
    if (posix_spawnp(&pid, "osascript", NULL, NULL, osargv, environ) == 0) {
        waitpid(pid, NULL, 0);
    }
}

int main(int argc, char *argv[]) {
    /* Resolve absolute path of this executable */
    uint32_t bufsz = 0;
    _NSGetExecutablePath(NULL, &bufsz);
    char *exe = malloc(bufsz);
    if (!exe || _NSGetExecutablePath(exe, &bufsz) != 0) {
        show_error_dialog("Cannot resolve application path.");
        return 1;
    }

    char *real = realpath(exe, NULL);
    free(exe);
    if (!real) {
        show_error_dialog("Cannot resolve application path.");
        return 1;
    }

    /* Build path to run.sh in Contents/Resources/ (sibling of MacOS/) */
    char *dir = dirname(real);  /* .../Contents/MacOS -> .../Contents */
    dir = dirname(dir);
    char script[4096];
    snprintf(script, sizeof(script), "%s/Resources/run.sh", dir);

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

    /*
     * Create a pipe to capture run.sh's stdout/stderr.
     * On success, run.sh ends with exec (replacing itself with Python),
     * and the pipe's write end is inherited — it stays open and we never
     * reach the read loop below.  On failure, run.sh exits, the write
     * end closes, and we read the error output to show in a dialog.
     */
    int pipefd[2];
    if (pipe(pipefd) != 0) {
        /* Pipe failed — just exec directly and hope for the best */
        execv(script, argv);
        return 1;
    }

    pid_t child = fork();
    if (child < 0) {
        show_error_dialog("Failed to launch application.");
        return 1;
    }

    if (child == 0) {
        /* Child: redirect stdout/stderr to pipe, exec run.sh */
        close(pipefd[0]);
        dup2(pipefd[1], STDOUT_FILENO);
        dup2(pipefd[1], STDERR_FILENO);
        close(pipefd[1]);
        execv(script, argv);
        /* If exec fails */
        dprintf(STDERR_FILENO, "Cannot run %s: %s\n", script, strerror(errno));
        _exit(127);
    }

    /* Parent: wait for child and capture output if it fails */
    close(pipefd[1]);

    int status = 0;
    waitpid(child, &status, 0);

    if (WIFEXITED(status) && WEXITSTATUS(status) != 0) {
        /* run.sh exited with an error — read the output and show it */
        char output[2048] = {0};
        ssize_t total = 0;
        ssize_t n;
        while ((n = read(pipefd[0], output + total,
                         sizeof(output) - 1 - total)) > 0) {
            total += n;
            if (total >= (ssize_t)sizeof(output) - 1) break;
        }
        output[total] = '\0';
        close(pipefd[0]);

        if (total > 0) {
            show_error_dialog(output);
        } else {
            show_error_dialog("Application failed to start. "
                              "Check the log at ~/Library/Logs/ndi_to_vcam.log");
        }
        return WEXITSTATUS(status);
    }

    close(pipefd[0]);
    return 0;
}
