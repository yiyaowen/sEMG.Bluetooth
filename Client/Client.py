from multiprocessing import Process, Queue
import sys
import struct
from threading import Thread, RLock
import time

from PySide6.QtCore import QByteArray, QFile, QIODevice, QPointF, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QApplication, QWidget

from PySide6.QtCharts import \
    QChart, \
    QChartView, \
    QLineSeries, \
    QValueAxis

from PySide6.QtBluetooth import \
    QBluetoothAddress, \
    QBluetoothDeviceDiscoveryAgent, \
    QBluetoothDeviceInfo, \
    QBluetoothLocalDevice, \
    QBluetoothSocket, \
    QBluetoothServiceDiscoveryAgent, \
    QBluetoothServiceInfo


from PySide6.QtCore import QTimer
from random import random

def loadUI(ui_file_name):
    ui_file = QFile(ui_file_name)
    if not ui_file.open(QIODevice.ReadOnly):
        print(f'Failed to open {ui_file_name}: {ui_file.errorString()}')
        sys.exit(-1)
    loader = QUiLoader()
    ui_obj = loader.load(ui_file)
    ui_file.close()
    if not ui_obj:
        print(loader.errorString())
        sys.exit(-1)
    return ui_obj 


class BluetoothClient(QWidget):

    def __init__(self, comm_qs):
        super().__init__()
        self.comm_qs = comm_qs
        self.ui = loadUI('BluetoothClient.ui')
        self.setLayout(self.ui.mainPanel)
        self.resize(600, 200)
        self.setWindowTitle('表面肌电手势识别 - 蓝牙客户端')

        # Initialize basic bluetooth components.
        self.local_device = QBluetoothLocalDevice()
        self.device_agent = QBluetoothDeviceDiscoveryAgent()
        self.service_agent = QBluetoothServiceDiscoveryAgent()

        # Connect signals & slots.
        # UI
        self.ui.startButton.clicked.connect(self.startConnection)
        self.ui.stopButton.clicked.connect(self.stopConnection)
        self.ui.deviceList.currentTextChanged.connect(self.startConnection)
        self.ui.serviceList.currentIndexChanged.connect(self.requestService)
        # Bluetooth
        self.device_agent.deviceDiscovered.connect(self.addDevice)
        self.local_device.pairingFinished.connect(self.pairingDone)
        self.service_agent.serviceDiscovered.connect(self.addService)

        # Maintain a temporary service list for the socke to connect.
        self.service_list = list()

        # Stop the connection manually can cause the service callback fails,
        # but this user operation should not be displayed in the hint label.
        # The connection error should be shown only if this field is False.
        self.is_connection_stopped_by_user = False

        # Store the single byte data temporarily to make a 16-bit uint later.
        self.half_data_array = QByteArray()
        # Maintain a backend list to store all received signal sampling data.
        self.sampling_value_list = list()

        self.device_agent.start()

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

    def broadcastReceive(self, data):
        for q in self.comm_qs.values():
            q.put(data)

    @Slot()
    def readDeviceData(self):
        try:
            data_array = self.socket.read(1024)
            # Check whether there're single byte remained in previous read;
            # complete current received byte array with the sigle byte (if has).
            if len(self.half_data_array) > 0:
                data_array.push_front(self.half_data_array.data())
                self.half_data_array.clear()
            # Store the trailing single byte temporarily to handle in next read.
            if len(data_array) % 2 == 1:
                # Use operator[] instead of at() here since the latter decodes utf-8.
                self.half_data_array.append(data_array[len(data_array) - 1])
                data_array.remove(len(data_array) - 1, 1)
            # Convert byte array to 16-bit unsigned integer array (sampling values).
            if len(data_array) > 0:
                value_array = list(struct.unpack('H' * int(len(data_array) // 2), data_array.data()))
                self.sampling_value_list = self.sampling_value_list + value_array
                self.broadcastReceive(value_array) # Notify all registered processes.
        except Exception as e:
            print(f'Exception in readDeviceData, {e}')


class VisualClient(QWidget):

    def __init__(self, comm_queue):
        super().__init__()
        self.comm_queue = comm_queue
        self.ui = loadUI('VisualClient.ui')
        self.setLayout(self.ui.signalGallery)
        self.resize(800, 400)
        self.setWindowTitle('表面肌电手势识别 - 可视化客户端')

        self.initChart()

        self.signal_amplitude_list = list()

        self.lk = RLock()
        # Start an extral thread to peek communication queue.
        self.td = Thread(target=VisualClient.peekCommQueue, args=(self,))
        self.td.daemon = True
        self.td.start()

    def initChart(self):
        self.ui.series = QLineSeries()
        self.ui.series.setName('肌电信号')
        self.ui.series.setUseOpenGL(True)
        self.ui.series.setPen(QPen(QColor(65, 105, 225), 1))
        self.ui.series.replace([QPointF(x, 0) for x in range(0, 1001)])

        self.ui.axisX = QValueAxis()
        self.ui.axisX.setRange(0, 1000)
        self.ui.axisX.setTickCount(6)
        self.ui.axisX.setTitleText('时间轴')
        self.ui.axisX.setTitleFont(QFont('黑体', 16))

        self.ui.axisY = QValueAxis()
        self.ui.axisY.setRange(-10, 10)
        self.ui.axisY.setTickCount(3)
        self.ui.axisY.setMinorTickCount(1)
        self.ui.axisY.setTitleText('幅度 / 伏特')
        self.ui.axisY.setTitleFont(QFont('黑体', 16))

        self.ui.chart = QChart()
        self.ui.chart.setTitle("通道 1")
        self.ui.chart.setTitleFont(QFont('黑体', 16, QFont.Bold))
        self.ui.chart.addSeries(self.ui.series)
        self.ui.chart.setAxisX(self.ui.axisX)
        self.ui.chart.setAxisY(self.ui.axisY)
        self.ui.series.attachAxis(self.ui.axisX)
        self.ui.series.attachAxis(self.ui.axisY)

        self.ui.chartView = QChartView()
        self.ui.chartView.setChart(self.ui.chart)
        self.ui.chartView.setRenderHint(QPainter.Antialiasing)

        # Setup single channel for the time being.
        self.ui.signalGallery.addWidget(self.ui.chartView, 0, 0)

    data_received = Signal()

    def peekCommQueue(self):
        try:
            self.data_received.connect(self.updateChart)
            while True:
                self.lk.acquire()
                while not self.comm_queue.empty():
                    # Throw if the queue blocks more than 1s.
                    data_array = self.comm_queue.get(True, 1)
                    # Convert 16-bit sampling values to referenced voltage values.
                    for i in range(0, len(data_array)):
                        data_array[i] = (data_array[i] / 65536) * 5
                    self.signal_amplitude_list = self.signal_amplitude_list + data_array
                    # Notify to update the chart with new data.
                    self.data_received.emit()
                self.lk.release()
                time.sleep(0.01)
        except Exception as e:
            print(f'Exception in peekCommQueue, {e}')

    def updateChart(self):
        try:
            self.lk.acquire()
            point_vec = self.ui.series.pointsVector()
            pvec_len = len(point_vec)
            svec_len = len(self.signal_amplitude_list)
            mvec_len = min(pvec_len, svec_len)
            for i in range(0, mvec_len):
                data = self.signal_amplitude_list[svec_len - i - 1]
                point_vec[pvec_len - i - 1].setY(data)
            # Use replace instead of clear & append to improve performance.
            self.ui.series.replace(point_vec)
            self.lk.release()
        except Exception as e:
            print(f'Exception in updateChart, {e}')


def visualProcess(comm_queue):
    app = QApplication(sys.argv)
    vs_clnt = VisualClient(comm_queue)
    vs_clnt.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    app = QApplication(sys.argv)
    comm_qs = dict()
    comm_qs['visual'] = Queue()
    # Initialize bluetooth window.
    bt_clnt = BluetoothClient(comm_qs)
    bt_clnt.show()
    # Create visual window process.
    vs_proc = Process(target=visualProcess, args=(comm_qs['visual'],))
    vs_proc.start()
    sys.exit(app.exec())
