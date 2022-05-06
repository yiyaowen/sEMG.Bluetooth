import sys

from PySide6.QtCore import QFile, QIODevice, Slot
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCharts import QChart, QChartView

from PySide6.QtBluetooth import \
    QBluetoothAddress, \
    QBluetoothDeviceDiscoveryAgent, \
    QBluetoothDeviceInfo, \
    QBluetoothLocalDevice, \
    QBluetoothSocket, \
    QBluetoothServiceDiscoveryAgent, \
    QBluetoothServiceInfo


class SemgClient(QWidget):
    def __init__(self):
        super().__init__()

        # Initialize UI layout.
        self.loadUI()
        self.resize(800, 600)
        self.setWindowTitle('表面肌电手势识别 - 客户端')

        # Initialize bluetooth utils.
        self.local_device = QBluetoothLocalDevice()
        self.device_agent = QBluetoothDeviceDiscoveryAgent()
        self.service_agent = QBluetoothServiceDiscoveryAgent()

        # Connect signals & slots
        self.ui.startButton.clicked.connect(self.startConnection)
        self.ui.stopButton.clicked.connect(self.stopConnection)
        self.ui.deviceList.currentTextChanged.connect(self.startConnection)
        self.ui.serviceList.currentIndexChanged.connect(self.requestService)
        
        self.device_agent.deviceDiscovered.connect(self.addDevice)
        self.local_device.pairingFinished.connect(self.pairingDone)
        self.service_agent.serviceDiscovered.connect(self.addService)

        # Maintain a temporary service list for the socke to connect.
        self.service_list = list()

        # Stop the connection manually can cause the service callback fails,
        # but this user operation should not be displayed in the hint label.
        # The connection error should be shown only if this field is False.
        self.is_connection_stopped_by_user = False

        self.device_agent.start()

        self.chart_view = QChartView()
        self.chart = QChart()
        self.chart.setTitle("数据曲线")
        self.chart_view.setChart(self.chart)
        self.ui.signalGallery.addWidget(self.chart_view, 0, 0)

    def loadUI(self):
        # Search UI form definition file.
        ui_file_name = 'form.ui'
        ui_file = QFile(ui_file_name)
        if not ui_file.open(QIODevice.ReadOnly):
            print(f'Failed to open {ui_file_name}: {ui_file.errorString()}')
            sys.exit(-1)

        # Load UI widget from definition file.
        loader = QUiLoader()
        self.ui = loader.load(ui_file)
        ui_file.close()
        if not self.ui:
            print(loader.errorString())
            sys.exit(-1)

        self.setLayout(self.ui.mainPanel)

    @Slot(QBluetoothDeviceInfo)
    def addDevice(self, info):
        addr = info.address().toString()
        text = f'{info.name()} @ {addr}'
        max_count = self.ui.deviceList.maxCount()
        self.ui.deviceList.insertItem(max_count, text)

    @Slot()
    def startConnection(self):
        try:
            self.ui.startButton.setEnabled(False)
            self.ui.stateIndicator.setText('正在连接')
            # Try pair with target device.
            name_addr = self.ui.deviceList.currentText().split(' @ ')
            if len(name_addr) == 2:
                addr = name_addr[1]
                self.local_device.requestPairing(QBluetoothAddress(addr), QBluetoothLocalDevice.Paired)
        except Exception as e:
            print(f'Exception in startConnection, {e}')

    @Slot()
    def stopConnection(self):
        try:
            self.is_connection_stopped_by_user = True
            name_addr = self.ui.deviceList.currentText().split(' @ ')
            if len(name_addr) == 2:
                addr = name_addr[1]
                self.local_device.requestPairing(QBluetoothAddress(addr), QBluetoothLocalDevice.Unpaired)
        except Exception as e:
            print(f'Exception in stopConnection, {e}')

    @Slot(QBluetoothAddress, QBluetoothLocalDevice.Pairing)
    def pairingDone(self, address, pairing):
        try:
            if pairing == QBluetoothLocalDevice.Paired or pairing == QBluetoothLocalDevice.AuthorizedPaired:
                self.ui.stateIndicator.setText('已连接, 正在请求服务')
                # Search all available services.
                self.service_list.clear()
                self.ui.serviceList.clear()
                self.service_agent.stop()
                self.service_agent.clear()
                self.service_agent.setRemoteAddress(address)
                self.service_agent.start()
            else:
                self.ui.startButton.setEnabled(True)
                self.ui.stateIndicator.setText('无连接')
        except Exception as e:
            print(f'Exception in pairingDone, {e}')

    @Slot(QBluetoothServiceInfo)
    def addService(self, info):
        self.service_list.append(info)
        text = f'{info.serviceName()} @ {info.serviceDescription()}'
        max_count = self.ui.serviceList.maxCount()
        self.ui.serviceList.insertItem(max_count, text)

    @Slot(str)
    def requestService(self, index):
        try:
            if index >= 0 and index < len(self.service_list):
                self.socket = QBluetoothSocket(QBluetoothServiceInfo.RfcommProtocol)
                self.socket.connected.connect(self.requestDone)
                self.socket.errorOccurred.connect(self.requestFailed)
                self.socket.readyRead.connect(self.readDeviceData)
                self.socket.connectToService(self.service_list[index])
        except Exception as e:
            print(f'Exception in requestService, {e}')

    @Slot()
    def requestDone(self):
        self.ui.stateIndicator.setText('设备已就绪')

    @Slot()
    def requestFailed(self):
        if not self.is_connection_stopped_by_user:
            self.ui.stateIndicator.setText('连接请求服务失败')

    @Slot()
    def readDeviceData(self):
        if (self.socket.isReadable()):
            data = self.socket.read(1024)
            self.ui.recogResultLabel.setText(data.toStdString())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    client = SemgClient()
    client.show()
    sys.exit(app.exec())
