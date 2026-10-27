import QtQuick
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as P5Support
import "logic.js" as Logic

PlasmoidItem {
    id: root

    property var usage: null
    property double nowMs: Date.now()
    readonly property string helperCommand: "\"$HOME/.local/bin/claude-usage\""
        + " --warn " + Plasmoid.configuration.warnThreshold
        + " --crit " + Plasmoid.configuration.critThreshold

    function colorFor(percent) {
        switch (Logic.level(percent)) {
        case "crit":
            return Kirigami.Theme.negativeTextColor;
        case "warn":
            return Kirigami.Theme.neutralTextColor;
        default:
            return Kirigami.Theme.positiveTextColor;
        }
    }

    function refresh() {
        if (executable.connectedSources.indexOf(helperCommand) === -1)
            executable.connectSource(helperCommand);
    }

    Plasmoid.icon: "utilities-system-monitor"
    toolTipMainText: "Claude Usage"
    toolTipSubText: Logic.tooltipText(usage, nowMs)
    compactRepresentation: CompactRepresentation { backend: root }
    fullRepresentation: FullRepresentation { backend: root }

    P5Support.DataSource {
        id: executable
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => {
            disconnectSource(sourceName);
            root.usage = Logic.merge(root.usage,
                                     Logic.parseOutput(data["exit code"], data["stdout"]));
            root.nowMs = Date.now();
        }
    }

    Timer {
        interval: Math.max(2, Plasmoid.configuration.refreshMinutes) * 60 * 1000
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
