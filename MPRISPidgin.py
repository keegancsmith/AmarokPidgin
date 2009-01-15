#!/usr/bin/env python
# Keegan Carruthers-Smith 2009 <keegan.csmith@gmail.com>
# Distributed under the GPLv2

import dbus, dbus.glib
import os, sys
from subprocess import Popen, PIPE

args = ('python', sys.argv[1], 'amarok2')
amarokpidgin = Popen(args, bufsize=1, stdin=PIPE).stdin

def statusChanged(status, *args):
    if status[0] == 0:
        msg = 'playing'
    else:
        msg = 'stopped'
    amarokpidgin.write(msg + '\n')
    amarokpidgin.flush()
    print msg


def init_dbus():
    bus = dbus.SessionBus()
    bus.add_signal_receiver(statusChanged, 'StatusChange',
                            'org.freedesktop.MediaPlayer')


if __name__ == "__main__":
    init_dbus()

    import gobject
    loop = gobject.MainLoop()
    loop.run()
