Importer.loadQtBinding("qt.core");

// Start AmarokPidgin.py
params = new Array();
params[0] = Amarok.Info.scriptPath() + "/MPRISPidgin.py";
params[1] = Amarok.Info.scriptPath() + "/AmarokPidgin.py";
var amarokpidgin = new QProcess(Amarok);
amarokpidgin.start("python", params);

// TODO find out how to cleanup
function Clear() {
    amarokpidgin.terminate();
}
