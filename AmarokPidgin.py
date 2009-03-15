#!/usr/bin/env python
# Keegan Carruthers-Smith 2006-2009 <keegan.csmith@gmail.com>
# Distributed under the GPLv2

import dbus
import re
import signal
import xml.parsers.expat
from commands import getoutput, getstatusoutput
from sys import stdin, exit, argv
from time import sleep
from ConfigParser import ConfigParser
from StringIO import StringIO
from Queue import Queue
from random import choice

DEBUG = False

DEFAULT_CONFIG = """
[AmarokPidgin]
status_name = Media
status_message = Listening to $title by $artist on $album [Amarok]
cover_icon = false
censor = false
censor_words = # Put words here separated by a | eg: word1|word2|word3
display = status # Where to display song playing. either status or nick
variable_map = # Put a lambda statement here that will be passed every (variable,value).
variable_imports = # Put import statements here for any modules that may be needed to run variable_map
"""

class ParseLyrics(object):
    def __init__(self, lyric_xml):
        p = xml.parsers.expat.ParserCreate()

        p.StartElementHandler = self.start_element
        p.EndElementHandler = self.end_element
        p.CharacterDataHandler = self.char_data

        self.page_url = ''
        self.lyrics = []

        p.Parse(lyric_xml)

    def start_element(self, name, attrs):
        if 'page_url' in attrs:
            self.page_url = attrs['page_url']

    def end_element(self, name):
        # Normalize data
        self.lyrics = ''.join(self.lyrics).split('\n')
        # Remove uneeded whitespace
        self.lyrics = [s.strip() for s in self.lyrics]
        # Remove empty lines
        self.lyrics = filter(bool, self.lyrics)

    def char_data(self, data):
        self.lyrics.append(data)


class Amarok2(object):
    """
    Dictionary like interface to Amarok2's metadata. Uses Amaroks MPRIS DBUS
    interface.
    """
    def __init__(self):
        bus = dbus.SessionBus()
        obj = bus.get_object('org.mpris.amarok', '/Player')
        interface = 'org.freedesktop.MediaPlayer'
        self.player = dbus.Interface(obj, dbus_interface=interface)

    def __getitem__(self, key):
        return self.player.GetMetadata().get(key, '')

    def is_playing(self):
        return self.player.GetStatus()[0] == 0

    def listen(self):
        while True:
            message = stdin.readline().strip()
            assert message in ('playing', 'stopped', 'quit')
            if message == 'quit':
                exit(0)
            yield message

    def passive_popup(self, msg):
        # TODO send passive msg to Amarok 2
        pass


class Amarok1(object):
    """
    Dictionary like interface to Amarok1's metadata. Uses Amaroks DCOP
    interface.
    """
    def __getitem__(self, key):
        if key == "lyricsURL": #URL is extracted from lyrics
            value = getoutput("dcop amarok player lyrics 2> /dev/null")
        else:
            value = getoutput("dcop amarok player %s 2> /dev/null" % key)

        if key == 'coverImage' and 'nocover' in value:
            value = ''

        return value.strip()

    def is_playing(self):
        return getoutput('dcop amarok player isPlaying 2> /dev/null').lower() == "true"

    def listen(self):
        """
        Generator that listens for messages from stdin.
        """
        while True:
            message = stdin.readline()

            if len(message) == 0:
                break

            #self.log("Got message: %s" % message)

            # Function that given a list, will tell you if any of the
            # strings are in message
            is_in = lambda li: len([x for x in li if x in message]) > 0

            if is_in( ("trackChange", "playing") ):
                yield 'playing'
            elif is_in( ("empty", "idle", "paused") ):
                yield 'stopped'
            elif "configure" in message:
                yield 'configure'

    def passive_popup(self, msg):
        getoutput("dcop amarok playlist popupMessage '%s' 2> /dev/null" % msg)


class AmarokPidgin(object):
    variables = ("album", "artist", "genre", "title", "track", "year",
                 "nowPlaying", "lyricsURL", "lyrics", "score", "rating")

    def __init__(self, amarok):
        """
        Connects too Pidgin's dbus interface.
        Stores the following variables:
            default - The default status
            purple - Pidgin dbus interface
            status - The status id for AmarokPidgin
            song - The songs string for the status. If not set, it is null
        """

        if DEBUG:
            self.logf = file("/tmp/AmarokPidgin.log", "a")
            print >>self.logf, "-"*60
            print >>self.logf, "Using engine " + type(amarok).__name__

        self.config = None
        self.parse_config()
        self.amarok = amarok

        # Get the purple object
        bus = dbus.SessionBus()
        obj = bus.get_object("im.pidgin.purple.PurpleService",
                             "/im/pidgin/purple/PurpleObject")
        purple = dbus.Interface(obj, "im.pidgin.purple.PurpleInterface")

        # Get the status object
        status_name = self.config.get("AmarokPidgin", "status_name")
        status = purple.PurpleSavedstatusFind(status_name)

        if status == 0: # Doesn't exist, create
            #current = purple.PurpleSavedstatusGetCurrent()
            #status_type = purple.PurpleSavedstatusGetType(current)
            # Make status type available instead
            status_type = purple.PurplePrimitiveGetTypeFromId("tune")
            if status_type == 0: # Doesnt have tune status
                status_type = purple.PurplePrimitiveGetTypeFromId("available")
            status = purple.PurpleSavedstatusNew(status_name, status_type)

        self.default        = purple.PurpleSavedstatusGetCurrent()
        self.purple         = purple
        self.status         = status
        self.nicks          = {}
        self.nicks_in_use   = set()
        self.song           = None
        self.revert_status  = False
        self.buddyicon      = purple.PurplePrefsGetPath("/pidgin/accounts/buddyicon")

        # Load variable map
        try:
            self.variable_map = eval(self.config.get("AmarokPidgin", "variable_map"))
            self.log("Loaded variable_map")

            # Quick sanity check on function
            assert isinstance(self.variable_map("album",  "a test"), basestring)
            assert isinstance(self.variable_map("artist", ""), basestring)
        except:
            self.log("Using identity variable_map")
            self.variable_map = lambda x,y: y
        else:
            self.log("variable_map passed sanity check")

        # If currently playing, change status
        if amarok.is_playing():
            self.song = self.get_currently_playing()
            self.update_display(self.song)
            self.update_buddyicon(self.amarok['coverImage'])


    def log(self,message):
        if DEBUG:
            try:
                print >>self.logf, message
                self.logf.flush()
            except UnicodeEncodeError:
                print >>self.logf, "Couldn't log. UnicodeEncodeError"


    def parse_config(self):
        "Reads in the configuration file."
        config = ConfigParser()

        # Set Defaults
        defaults = StringIO(DEFAULT_CONFIG)
        config.readfp(defaults)
        defaults.close()

        # Read in config
        try:
            config_fp = file("AmarokPidgin.ini", "r")
            config.readfp(config_fp)
            config_fp.close()
        except:
            self.log("Could not read in AmarokPidgin.ini")

        self.config = config


    def configure(self):
        "Shows a kdialog to change status message"
        try:
            def kdialog(dialog_type, text):
                cmd = ('kdialog --title "AmarokPidgin Configuration" '
                       '--%s %s 2> /dev/null') % (dialog_type, text)
                return getstatusoutput(cmd)

            if getstatusoutput('kdialog -v &> /dev/null')[0] != 0:
                msg = ('You do not have kdialog installed, so you cannot '
                       'configure AmarokPidgin')
                self.amarok.passive_popup(msg)
                raise Exception

            # Configure display to use
            current_display = self.config.get("AmarokPidgin", "display")
            if current_display == "status":
                selected = ("on","off")
            else:
                selected = ("off","on")

            msg = "Please pick where to display the Now Playing message."
            text = '"%s" status status %s nick nick %s' % ((msg,) + selected)
            new_display = kdialog('radiolist', text)[1]

            if new_display in ('nick','status'):
                self.config.set("AmarokPidgin", "display", new_display)


            # Configure status message
            current_status = self.config.get("AmarokPidgin", "status_message")
            current_status = current_status.replace("$","\\$")
            variables = ', \\$'.join(AmarokPidgin.variables)
            msg = ("This will change the format of your Now Playing message.\n"
                   "Valid variables are: \\$%s.") % variables
            text = '"%s" "%s"' % (msg, current_status)
            new_status = kdialog('textinputbox', text)[1]
            self.config.set("AmarokPidgin", "status_message", new_status)


            # Configure whether to update the Buddy Icon
            msg = ("Would you like AmarokPidgin to update your Buddy Icon "
                   "with the currently playing track's album cover?")
            status = kdialog('yesno', '"%s"' % msg)[0] and 'false' or 'true'
            if status == 'false':
                self.restore_buddyicon()
            self.config.set('AmarokPidgin', 'cover_icon', status)


            # Write updated config file
            config_fp = file("AmarokPidgin.ini", "w")
            self.config.write(config_fp)
            config_fp.close()
        except:
            self.log("Error occurred during config")


    def _update_status(self, message):
        "Changes the displayed status"

        # Update the status object if necessary
        current = self.purple.PurpleSavedstatusGetCurrent()
        if current != self.status:
            # Removing code adds functionality! :D
            #status_name = self.purple.PurpleSavedstatusGetTitle(self.status)
            #status_type = self.purple.PurpleSavedstatusGetType(current);
            #self.purple.PurpleSavedstatusDelete(status_name)
            #self.status = self.purple.PurpleSavedstatusNew(status_name, status_type)
            self.default = current
            if self.revert_status: # Switch back to Media Status
                current = self.status


        # Update Purple's status
        self.purple.PurpleSavedstatusSetMessage(self.status, message)
        if current == self.status:
            self.purple.PurpleSavedstatusActivate(self.status)


    def _update_nick(self, message):
        "Changes the displayed nickname"

        nick_ids = self.purple.PurpleAccountsGetAllActive()

        for nick_id in nick_ids:
            # Store default nick
            if nick_id not in self.nicks:
                nick = self.purple.PurpleAccountGetAlias(nick_id)
                self.nicks[nick_id] = nick

            # Update nick
            self.purple.PurpleAccountSetAlias(nick_id, message)

            # Add to nicks in use, for checking when not in use
            self.nicks_in_use.add(nick_id)

        # Restore nicks
        for nick_id in self.nicks_in_use.difference(nick_ids):
            self.purple.PurpleAccountSetAlias(nick_id, nick[nick_id])


    def decode(self, message):
        "Tries to decode the message"
        encodings = ['utf8', 'iso-8859-1']

        try:
            import chardet
            encodings.append(chardet.detect(message)['encoding'])
        except ImportError:
            pass

        # Try and decode message
        for encoding in encodings:
            try:
                message = message.decode(encoding)
            except:
                self.log("DecodeError: Could not decode '%s' as %s" % \
                         (message, encoding))
            else:
                return message


        self.log("DecodeError: No decodings worked. Using replace")
        try:
            return message.decode('utf8', 'replace')
        except:
            self.log("DecodeError: Replace decoding did not work. Returning raw message.")
            return message


    def update_display(self, message):
        "Changes the displayed message."

        message = self.decode(message)
        if not message:
            return

        # Censors message if necessary
        if self.config.getboolean("AmarokPidgin", "censor"):
            # Builds a regular expression for matching expletives
            expletives = self.config.get("AmarokPidgin", "censor_words")
            censor_re  = re.compile('(%s)' % expletives, re.IGNORECASE)

            # Returns the a censored version of the match's string
            censor = lambda match: '*' * len(match.group(0))

            # Censor the message
            message = censor_re.sub(censor, message)

        # Update the necessary display
        display = self.config.get("AmarokPidgin", "display")

        # Either nick or status. Defaults to status
        if display != 'nick':
            display = 'status'
            self._update_status(message)
        else:
            self._update_nick(message)

        self.log("Updating %s: %d %s" % (display, self.status, message))


    def restore_nicks(self):
        "Restores the nicks to there defaults"

        for nick_id in self.nicks:
            self.purple.PurpleAccountSetAlias(nick_id, self.nicks[nick_id])


    def get_currently_playing(self):
        "Gets the currently playing song from amarok."
        new_status = self.config.get("AmarokPidgin", "status_message")

        for var in AmarokPidgin.variables:
            if not ("$" + var) in new_status:
                continue

            value = self.amarok[var]

            if var == "year" and value == "0":
                value = ''
            if var == "title" and len(value) == 0:
                # if title is empty, nowPlaying returns something reasonable
                new_status = new_status.replace("$title", "$nowPlaying")
                continue
            if var.startswith("lyrics"):
                try:
                    l = ParseLyrics(value)
                except xml.parsers.expat.ExpatError:
                    pass
                value = ''
                if var == "lyrics" and l.lyrics:
                    value = choice(l.lyrics).encode("utf8")
                elif var == "lyricsURL" and l.page_url:
                    value = l.page_url.encode("utf8")


            value = self.variable_map(var, value)
            new_status = new_status.replace("$" + var, value)

        return new_status


    def update_buddyicon(self, cover):
        """
        Updates Pidgin's default Buddy Icon if the cover_icon setting is true
        """
        if not self.config.getboolean("AmarokPidgin", "cover_icon"):
            return

        current = self.purple.PurplePrefsGetPath("/pidgin/accounts/buddyicon")

        # The current cover isn't an album cover, so update the fallback buddy
        # icon. This is just a heuristic, it won't always work.
        if not 'albumcovers' in current:
            self.buddyicon = current

        # Buddy Icon should be default if display is 'status' and the media
        # status is not selected.
        display = self.config.get("AmarokPidgin", "display")
        cur_status = self.purple.PurpleSavedstatusGetCurrent()
        if cover != '' and display == 'status' and cur_status != self.status:
            cover = ''
            if current != self.buddyicon:
                self.log("Changing Buddy Icon to default because the media "
                         "status is not selected")

        # Switch back the original Buddy Icon
        if cover == '':
            cover = self.buddyicon

        # Cover is the same, do not update
        if cover == current:
            self.log("Buddy Icon is already " + repr(cover))
            return

        # Update the cover
        self.log("Changing Buddy Icon to " + repr(cover))
        self.purple.PurplePrefsSetPath("/pidgin/accounts/buddyicon", cover)


    def restore_buddyicon(self):
        self.update_buddyicon('')


    def listen(self):
        """
        Listens for events from Amarok.
        """
        for action in self.amarok.listen():
            if action == 'playing':
                message = self.get_currently_playing()
                self.log("Previously Playing: %s" % self.song)
                self.log("Currently Playing: %s" % message)

                # The song has changed, update status
                if message != self.song:
                    self.song = message
                    self.update_display(message)

                self.update_buddyicon(self.amarok['coverImage'])

                self.revert_status = False

            elif action == 'stopped':
                if self.purple.PurpleSavedstatusGetCurrent() == self.status:
                    self.revert_status = True
                    self.purple.PurpleSavedstatusActivate(self.default)
                self.song = None
                self.restore_buddyicon()

                self.log("Default: %d" % self.default)

            elif action == 'configure':
                self.configure()


# Made a global for cleanup script
amarokPidgin = None

def cleanup(signum, frame):
    "Tries to change the status back to the default"
    global amarokPidgin
    try:
        if amarokPidgin:
            amarokPidgin.purple.PurpleSavedstatusActivate(amarokPidgin.default)
            amarokPidgin.restore_nicks()
            amarokPidgin.restore_buddyicon()
            amarokPidgin = None
    except:
        pass

    if signum in (signal.SIGTERM, signal.SIGKILL):
        exit(0)

def log_exception():
    if DEBUG:
        logf = file("/tmp/AmarokPidgin.log", "a")
        print >>logf, "*"*60
        import traceback
        traceback.print_exc(file=logf)
        logf.close()

if __name__ == "__main__":
    interfacecls = Amarok1
    if len(argv) > 1 and argv[1] == 'amarok2':
        interfacecls = Amarok2

    signal.signal(signal.SIGTERM, cleanup)
    while True:
        try:
            interface = interfacecls()
            amarokPidgin = AmarokPidgin(interface)
            amarokPidgin.listen()
        except dbus.DBusException:
            # This usually means Pidgin has closed.  Change the status
            # as well as sleep for 20 seconds, hoping Pidgin would have
            # started up.
            cleanup(0,0)
            log_exception()
            sleep(20)
        except: # Unexpected error, don't carry on looping
            cleanup(0,0)
            log_exception()
            raise
