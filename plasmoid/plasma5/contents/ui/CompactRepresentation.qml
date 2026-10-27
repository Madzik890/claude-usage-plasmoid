import QtQuick 2.15
import QtQuick.Layouts 1.15
import org.kde.plasma.core 2.0 as PlasmaCore
import org.kde.plasma.components 3.0 as PlasmaComponents3
import org.kde.plasma.plasmoid 2.0
import "logic.js" as Logic

MouseArea {
    id: compact

    property var backend
    readonly property var usage: backend.usage
    readonly property bool hasLimits: usage !== null && usage.limits.length > 0

    Layout.minimumWidth: label.implicitWidth + PlasmaCore.Units.smallSpacing * 2
    Layout.preferredWidth: Layout.minimumWidth
    hoverEnabled: true
    onClicked: plasmoid.expanded = !plasmoid.expanded

    PlasmaComponents3.Label {
        id: label
        anchors.centerIn: parent
        text: Logic.compactText(compact.usage)
        font.bold: true
        color: compact.hasLimits ? compact.backend.colorFor(Logic.maxPercent(compact.usage.limits))
                                 : PlasmaCore.Theme.textColor
        opacity: compact.usage !== null && compact.usage.status === "ok" ? 1.0 : 0.5
    }
}
