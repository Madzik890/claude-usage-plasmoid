import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import "logic.js" as Logic

MouseArea {
    id: compact

    property var backend
    readonly property var usage: backend.usage
    readonly property bool hasLimits: usage !== null && usage.limits.length > 0

    Layout.minimumWidth: label.implicitWidth + Kirigami.Units.smallSpacing * 2
    Layout.preferredWidth: Layout.minimumWidth
    hoverEnabled: true
    onClicked: backend.expanded = !backend.expanded

    PlasmaComponents3.Label {
        id: label
        anchors.centerIn: parent
        text: Logic.compactText(compact.usage)
        font.bold: true
        color: compact.hasLimits ? compact.backend.colorFor(Logic.maxPercent(compact.usage.limits))
                                 : Kirigami.Theme.textColor
        opacity: compact.usage !== null && compact.usage.status === "ok" ? 1.0 : 0.5
    }
}
