import QtQuick 2.15
import QtQuick.Layouts 1.15
import org.kde.plasma.core 2.0 as PlasmaCore
import org.kde.plasma.components 3.0 as PlasmaComponents3
import org.kde.plasma.extras 2.0 as PlasmaExtras
import "logic.js" as Logic

ColumnLayout {
    id: full

    property var backend
    readonly property var usage: backend.usage

    Layout.minimumWidth: PlasmaCore.Units.gridUnit * 18
    Layout.preferredWidth: Layout.minimumWidth
    spacing: PlasmaCore.Units.smallSpacing

    PlasmaExtras.Heading {
        level: 4
        text: "Claude limits"
        Layout.fillWidth: true
    }

    Repeater {
        model: full.usage ? full.usage.limits : []

        delegate: ColumnLayout {
            Layout.fillWidth: true
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                PlasmaComponents3.Label {
                    text: modelData.label
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                PlasmaComponents3.Label {
                    text: modelData.percent + "%"
                    font.bold: true
                    color: full.backend.colorFor(modelData.percent)
                }
            }
            PlasmaComponents3.ProgressBar {
                Layout.fillWidth: true
                from: 0
                to: 100
                value: Math.min(100, Math.max(0, modelData.percent))
            }
            PlasmaComponents3.Label {
                text: Logic.formatReset(modelData.resets_at, full.backend.nowMs)
                visible: text !== ""
                opacity: 0.7
                font: PlasmaCore.Theme.smallestFont
            }
        }
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        visible: text !== ""
        color: PlasmaCore.Theme.negativeTextColor
        text: full.usage === null ? "Loading…"
            : full.usage.status !== "ok" ? Logic.errorText(full.usage.reason) : ""
    }

    RowLayout {
        Layout.fillWidth: true
        PlasmaComponents3.Label {
            text: "Updated: " + Logic.formatTime(full.usage ? full.usage.fetched_at : null)
            opacity: 0.7
            Layout.fillWidth: true
        }
        PlasmaComponents3.ToolButton {
            icon.name: "view-refresh"
            text: "Refresh"
            onClicked: full.backend.refresh()
        }
    }
}
