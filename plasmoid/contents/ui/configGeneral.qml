import QtQuick 2.15
import QtQuick.Controls 2.15 as QQC2
import org.kde.kirigami 2.5 as Kirigami

Kirigami.FormLayout {
    property alias cfg_refreshMinutes: refreshSpin.value
    property alias cfg_warnThreshold: warnSpin.value
    property alias cfg_critThreshold: critSpin.value

    QQC2.SpinBox {
        id: refreshSpin
        Kirigami.FormData.label: "Refresh interval (min):"
        from: 2
        to: 60
    }
    QQC2.SpinBox {
        id: warnSpin
        Kirigami.FormData.label: "Warning notification (%):"
        from: 1
        to: 100
    }
    QQC2.SpinBox {
        id: critSpin
        Kirigami.FormData.label: "Critical notification (%):"
        from: 1
        to: 100
    }
}
