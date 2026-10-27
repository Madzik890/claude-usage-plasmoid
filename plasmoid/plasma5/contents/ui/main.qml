import QtQuick 2.15
import org.kde.plasma.core 2.0 as PlasmaCore
import org.kde.plasma.plasmoid 2.0
import "logic.js" as Logic

Item {
    id: root

    property var usage: null
    property double nowMs: Date.now()
    readonly property string helperCommand: "\"$HOME/.local/bin/claude-usage\""
        + " --warn " + plasmoid.configuration.warnThreshold
        + " --crit " + plasmoid.configuration.critThreshold

    function colorFor(percent) {
        switch (Logic.level(percent)) {
        case "crit":
            return PlasmaCore.Theme.negativeTextColor;
        case "warn":
            return PlasmaCore.Theme.neutralTextColor;
        default:
            return PlasmaCore.Theme.positiveTextColor;
        }
    }

    function refresh() {
        if (executable.connectedSources.indexOf(helperCommand) === -1)
            executable.connectSource(helperCommand);
    }

    Plasmoid.icon: "utilities-system-monitor"
    Plasmoid.toolTipMainText: "Claude Usage"
    Plasmoid.toolTipSubText: Logic.tooltipText(usage, nowMs)
    Plasmoid.compactRepresentation: CompactRepresentation { backend: root }
    Plasmoid.fullRepresentation: FullRepresentation { backend: root }

    PlasmaCore.DataSource {
        id: executable
        engine: "executable"
        connectedSources: []
        onNewData: {
            disconnectSource(sourceName);
            root.usage = Logic.merge(root.usage,
                                     Logic.parseOutput(data["exit code"], data["stdout"]));
            root.nowMs = Date.now();
        }
    }

    Timer {
        interval: Math.max(2, plasmoid.configuration.refreshMinutes) * 60 * 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }

    Timer {
        interval: 30 * 1000
        running: true
        repeat: true
        onTriggered: root.nowMs = Date.now()
    }
}
