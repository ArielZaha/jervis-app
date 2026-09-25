// The executable of "Jervis Wake.app" (built by install.sh).
//
// macOS decides microphone access per app. A Python script started by a LaunchAgent isn't an app: macOS can't ask
// you about it, and the recording comes back silent or crashes inside PortAudio. So the listener (jervis_wake.py)
// runs as a child of this small program: macOS credits the child's microphone use to "Jervis Wake", whose Info.plist
// says why it needs the microphone, asks you once, and remembers. Jervis, started by the listener, inherits it too.
#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>

extern char **environ;
static pid_t child = 0;

static void forward(int signal_number) {
    if (child > 0) kill(child, signal_number);   // launchd stopping us: stop the listener with us
}

int main(void) {
    const char *home = getenv("HOME");
    if (home == NULL) return 1;
    char python[PATH_MAX], script[PATH_MAX];
    snprintf(python, sizeof python, "%s/Library/Application Support/JervisWake/venv/bin/python3", home);
    snprintf(script, sizeof script, "%s/Library/Application Support/JervisWake/jervis_wake.py", home);
    char *arguments[] = {python, script, NULL};

    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    int error = posix_spawn(&child, python, NULL, NULL, arguments, environ);
    if (error != 0) {
        fprintf(stderr, "Jervis Wake: couldn't start %s (%d)\n", python, error);
        return 1;
    }
    int status = 0;
    while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
