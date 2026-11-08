// atomic-hyprland SDDM greeter: clock, name, one password field, session and
// power controls. Colours come from theme.conf (rendered from the default
// palette at image build). No virtual keyboard: InputMethod= is empty in
// /etc/sddm.conf.d/10-atomic-hyprland.conf and nothing here imports one.
import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: root

    property string fontFamily: config.font
    property bool failed: false

    Image {
        anchors.fill: parent
        source: config.background
        fillMode: Image.PreserveAspectCrop
    }
    Rectangle {
        anchors.fill: parent
        color: config.background_color
        visible: config.background === ""
    }

    Timer {
        interval: 1000; running: true; repeat: true
        onTriggered: {
            var now = new Date()
            clock.text = Qt.formatTime(now, "HH:mm")
            date.text = Qt.formatDate(now, "dddd d MMMM")
        }
    }

    Column {
        anchors.centerIn: parent
        spacing: 8

        Text {
            id: clock
            anchors.horizontalCenter: parent.horizontalCenter
            text: Qt.formatTime(new Date(), "HH:mm")
            font.family: root.fontFamily
            font.pixelSize: 72
            font.weight: Font.Light
            color: config.foreground
        }
        Text {
            id: date
            anchors.horizontalCenter: parent.horizontalCenter
            text: Qt.formatDate(new Date(), "dddd d MMMM")
            font.family: root.fontFamily
            font.pixelSize: 16
            color: config.foreground_dim
        }
        Item { width: 1; height: 24 }

        TextInput {
            id: userName
            anchors.horizontalCenter: parent.horizontalCenter
            text: userModel.lastUser
            font.family: root.fontFamily
            font.pixelSize: 15
            color: config.foreground
            selectionColor: config.accent
            selectedTextColor: config.background_color
            horizontalAlignment: TextInput.AlignHCenter
            KeyNavigation.tab: password
            Keys.onReturnPressed: password.forceActiveFocus()
        }

        Rectangle {
            id: field
            anchors.horizontalCenter: parent.horizontalCenter
            width: 320; height: 40
            radius: 3
            color: config.background_alt
            border.width: 1
            border.color: root.failed ? config.critical : config.accent

            TextInput {
                id: password
                anchors.fill: parent
                anchors.leftMargin: 12; anchors.rightMargin: 12
                verticalAlignment: TextInput.AlignVCenter
                echoMode: TextInput.Password
                passwordCharacter: "•"
                font.family: root.fontFamily
                font.pixelSize: 15
                color: config.foreground
                selectionColor: config.accent
                selectedTextColor: config.background_color
                focus: true
                onTextChanged: root.failed = false
                Keys.onReturnPressed: sddm.login(userName.text, password.text, session.index)
                Keys.onEnterPressed: sddm.login(userName.text, password.text, session.index)
            }
            Text {
                anchors.centerIn: parent
                visible: password.text === "" && !password.activeFocus
                text: "password"
                font.family: root.fontFamily
                font.pixelSize: 13
                color: config.foreground_dim
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.failed
            text: "wrong password"
            font.family: root.fontFamily
            font.pixelSize: 12
            color: config.critical
        }
    }

    // Session: shows the current entry, click cycles through sessionModel.
    Item {
        id: session
        property int index: sessionModel.lastIndex
        anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.margins: 24
        width: sessionLabel.implicitWidth; height: sessionLabel.implicitHeight
        Text {
            id: sessionLabel
            text: (sessionModel.data(sessionModel.index(session.index, 0), Qt.UserRole + 4) || "session") + "  󰅀"
            font.family: root.fontFamily
            font.pixelSize: 12
            color: config.foreground_dim
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: session.index = (session.index + 1) % sessionModel.rowCount()
        }
    }

    // Power: suspend, reboot, shutdown.
    Row {
        anchors.left: parent.left; anchors.bottom: parent.bottom
        anchors.margins: 24
        spacing: 18
        Repeater {
            model: [
                { glyph: "󰒲", action: function() { sddm.suspend() } },
                { glyph: "󰜉", action: function() { sddm.reboot() } },
                { glyph: "󰐥", action: function() { sddm.powerOff() } }
            ]
            delegate: Text {
                text: modelData.glyph
                font.family: root.fontFamily
                font.pixelSize: 18
                color: hover.containsMouse ? config.accent : config.foreground_dim
                MouseArea {
                    id: hover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: modelData.action()
                }
            }
        }
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            root.failed = true
            password.text = ""
            password.forceActiveFocus()
        }
    }

    Component.onCompleted: {
        if (userName.text === "") userName.forceActiveFocus(); else password.forceActiveFocus()
    }
}
