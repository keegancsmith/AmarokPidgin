Importer.loadQtBinding("qt.core");

Amarok.Engine.trackChanged.connect(send);
Amarok.Engine.trackFinished.connect(send);
Amarok.Engine.trackPlayPause.connect(send);

// Setup communication with AmarokPidgin.py
params = new Array();
params[0] = Amarok.Info.scriptPath() + "/AmarokPidgin.py";
params[1] = "amarok2";
var amarokpidgin = new QProcess(Amarok);
amarokpidgin.start("python", params);


function send() {
    var state = Amarok.Engine.engineState();
    if (state == 0)
        amarokpidgin.write("playing\n");
    else
        amarokpidgin.write("stopped\n");
}


function cleanup() {
    Amarok.Engine.trackChanged.disconnect(changed);
    Amarok.Engine.trackFinished.disconnect(finished);
    Amarok.Engine.trackPlayPause.disconnect(playPause);
    amarokpidgin.terminate();
}


function Clear() {
    cleanup();
}
