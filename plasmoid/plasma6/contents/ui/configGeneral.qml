import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.SimpleKCM {
    property alias cfg_refreshMinutes: refreshSpin.value
    property alias cfg_warnThreshold: warnSpin.value
    property alias cfg_critThreshold: critSpin.value

    Kirigami.FormLayout {
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
}
