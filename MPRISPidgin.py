#!/usr/bin/env python
# Keegan Carruthers-Smith 2009 <keegan.csmith@gmail.com>
# Distributed under the GPLv2

import dbus, dbus.glib
import os, os.path, sys, signal
from subprocess import Popen, PIPE, STDOUT

os.chdir(os.path.dirname(sys.argv[1]))
args = ('python', sys.argv[1], 'amarok2')
amarokpidgin = Popen(args, bufsize=1, stdin=PIPE)


def statusChanged(status, *args):
    if status[0] == 0:
        msg = 'playing'
    else:
        msg = 'stopped'
    amarokpidgin.stdin.write(msg + '\n')
    amarokpidgin.stdin.flush()


def init_dbus():
    bus = dbus.SessionBus()
    bus.add_signal_receiver(statusChanged, 'StatusChange',
                            'org.freedesktop.MediaPlayer')


def cleanup(signum, frame):
    if signum in (signal.SIGTERM, signal.SIGKILL):
        amarokpidgin.stdin.write('quit\n')
        sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, cleanup)

    init_dbus()

    import gobject
    loop = gobject.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        cleanup(signal.SIGKILL, 0)
