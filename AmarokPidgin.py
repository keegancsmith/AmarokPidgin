#!/usr/bin/env python
# Keegan Carruthers-Smith 2008 <keegan.csmith@gmail.com>
# Distributed under the GPLv2

import dbus
import re
import signal
import xml.parsers.expat
from commands import getoutput
from sys import stdin, exit
from time import sleep
from ConfigParser import ConfigParser
from StringIO import StringIO
from random import choice

DEBUG = False

DEFAULT_CONFIG = """
[AmarokPidgin]
status_name = Media
status_message = Listening to $title by $artist on $album [Amarok]
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


class AmarokPidgin(object):
    variables = ("album", "artist", "genre", "title", "track", "year",
                 "nowPlaying", "lyricsURL", "lyrics", "score", "rating")

    def __init__(self):
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

        self.config = None
        self.parse_config()

        # Get the purple object
        bus = dbus.SessionBus()
        obj = bus.get_object("im.pidgin.purple.PurpleService", "/im/pidgin/purple/PurpleObject")
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

        # Load variable map
        try:
            exec(self.config.get("AmarokPidgin", "variable_imports"))
        except:
            pass
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
        if getoutput('dcop amarok player isPlaying 2> /dev/null').lower() == "true":
            self.song = self.get_currently_playing()
            self.update_display(self.song)


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
            title = "AmarokPidgin Configuration"

            # Configure display to use
            text = "Please pick where to display the Now Playing message."
            current_display = self.config.get("AmarokPidgin", "display")
            if current_display == "status":
                selected = ("on","off")
            else:
                selected = ("off","on")

            new_display = getoutput(('kdialog --title "%s" --radiolist "%s" ' + 
                                     'status status %s ' + 
                                     'nick nick %s 2> /dev/null') %
                                    (title, text, selected[0], selected[1]))

            if new_display in ('nick','status'):
                self.config.set("AmarokPidgin", "display", new_display)


            # Configure status message
            current_status = self.config.get("AmarokPidgin", "status_message").replace("$","\\$")
            text = "This will change the format of your Now Playing message.\n" + \
                   "Valid variables are: \\$%s." % ', \\$'.join(AmarokPidgin.variables)

            new_status = getoutput('kdialog --title "%s" --textinputbox "%s" "%s" 2> /dev/null' %
                                    (title, text, current_status))

            self.config.set("AmarokPidgin", "status_message", new_status)


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
        return message.decode('utf8', 'replace')


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

            if var == "lyricsURL": #URL is extracted from lyrics
                value = getoutput("dcop amarok player lyrics 2> /dev/null")
            else:
                value = getoutput("dcop amarok player %s 2> /dev/null" % var)
            value = value.strip()

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


    def listenForSongChanges(self):
        "Listens for song changes from stdin. This method is blocking."
        while True:
            message = stdin.readline()

            if len(message) == 0:
                break

            self.log("Got message: %s" % message)

            # Function that given a list, will tell you if any of the
            # strings are in message
            is_in = lambda li: len([x for x in li if x in message]) > 0

            if is_in( ("trackChange", "playing") ):
                message = self.get_currently_playing()
                self.log("Previously Playing: %s" % message)
                self.log("Currently Playing: %s" % message)
                if message != self.song: # The song has changed, update status
                    self.song = message
                    self.update_display(message)
                self.revert_status = False

            elif is_in( ("empty", "idle", "paused") ):
                if self.purple.PurpleSavedstatusGetCurrent() == self.status:
                    self.revert_status = True
                    self.purple.PurpleSavedstatusActivate(self.default)
                self.song = None

                self.log("Default: %d" % self.default)

            elif "configure" in message:
                self.configure()


# Made a global for cleanup script
amarokPidgin = None

def cleanup(signum, frame):
    "Tries too change the status back too the default"
    global amarokPidgin
    try:
        if amarokPidgin:
            amarokPidgin.purple.PurpleSavedstatusActivate(amarokPidgin.default)
            amarokPidgin.restore_nicks()
            amarokPidgin = None
    except:
        pass

    if signum == signal.SIGTERM:
        exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, cleanup)
    while True:
        try:
            amarokPidgin = AmarokPidgin()
            amarokPidgin.listenForSongChanges()
        except dbus.DBusException:
            # This usually means Pidgin has closed.  Change the status
            # aswell as sleep for 20 seconds, hoping Pidgin would have
            # started up.
            cleanup(0,0)
            if DEBUG:
                logf = file("/tmp/AmarokPidgin.log", "a")
                print >>logf, "*"*60
                import traceback
                traceback.print_exc(file=logf)
                logf.close()
            sleep(20)
        else: # Unexpected error, dont carry on looping
            cleanup(0,0)
            break
