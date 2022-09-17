from multiprocessing import Process, Queue
import sys
import struct
from threading import Thread, RLock
import time
import types

import numpy as np

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

    def __del__(self):
        super().__del__()
        # TODO: fix 1st-received-error-byte bug.
        # Notify the server to stop sampling.
        self.socket.write(b'\x02')
        self.socket.readAll()

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
            # TODO: fix 1st-received-error-byte bug.
            # Notify the server to stop sampling.
            self.socket.write(b'\x02')
            self.socket.readAll()
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
        try:
            # TODO: fix 1st-received-error-byte bug.
            # Notify the server to send sampling data.
            self.socket.readAll()
            self.socket.write(b'\x01')
            self.ui.stateIndicator.setText('设备已就绪')
        except Exception as e:
            print(f'Exception in requestDone, {e}')

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
        self.resize(800, 800)
        self.setWindowTitle('表面肌电手势识别 - 可视化客户端')

        self.ui.channel = self.makeChannelChart()
        # Setup single channel for the time being.
        self.ui.signalGallery.addWidget(self.ui.channel.t.chartView, 0, 0)
        self.ui.signalGallery.addWidget(self.ui.channel.f.chartView, 1, 0)

        self.signal_amplitude_list = list()

        self.lk = RLock()
        # Start an extral thread to peek communication queue.
        self.td = Thread(target=VisualClient.peekCommQueue, args=(self,))
        self.td.daemon = True
        self.td.start()

    def makeChannelChart(self):
        channel = types.SimpleNamespace()

        channel.t = self.makeGeneralChart('时域', '时间', (0, 1000), 6, '幅度 / 伏特', (0, 3.3), 2)
        channel.f = self.makeGeneralChart('频域', '频率', (-500, 500), 6, '幅度 / 绝对值', (0, 1000), 2)

        return channel

    def makeGeneralChart(self, title, xlabel, xrange, xtick, ylabel, yrange, ytick):
        chart = types.SimpleNamespace()

        chart.series = QLineSeries()
        chart.series.setName('肌电信号')
        chart.series.setUseOpenGL(True)
        chart.series.setPen(QPen(QColor(65, 105, 225), 1))
        chart.series.replace([QPointF(x, 0) for x in range(0, 1001)])

        chart.axisX = QValueAxis()
        chart.axisX.setRange(*xrange)
        chart.axisX.setTickCount(xtick)
        chart.axisX.setTitleText(xlabel)
        chart.axisX.setTitleFont(QFont('黑体', 16))

        chart.axisY = QValueAxis()
        chart.axisY.setRange(*yrange)
        chart.axisY.setTickCount(ytick)
        chart.axisY.setTitleText(ylabel)
        chart.axisY.setTitleFont(QFont('黑体', 16))

        chart.chart = QChart()
        chart.chart.setTitle(title)
        chart.chart.setTitleFont(QFont('黑体', 16, QFont.Bold))
        chart.chart.addSeries(chart.series)
        chart.chart.setAxisX(chart.axisX)
        chart.chart.setAxisY(chart.axisY)
        chart.series.attachAxis(chart.axisX)
        chart.series.attachAxis(chart.axisY)

        chart.chartView = QChartView()
        chart.chartView.setChart(chart.chart)
        chart.chartView.setRenderHint(QPainter.Antialiasing)

        return chart

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
                        data_array[i] = (data_array[i] / 65536) * 3.3
                    self.signal_amplitude_list = self.signal_amplitude_list + data_array
                    # Notify to update the chart with new data.
                    self.data_received.emit()
                self.lk.release()
                # Prevnet UI thread from getting stuck.
                time.sleep(0.01)
        except Exception as e:
            print(f'Exception in peekCommQueue, {e}')

    def updateChart(self):
        try:
            self.lk.acquire()
            self.updateTimeDomainChart()
            self.updateFreqDomainChart()
            self.lk.release()
        except Exception as e:
            print(f'Exception in updateChart, {e}')

    def updateTimeDomainChart(self):
        point_vec = self.ui.channel.t.series.pointsVector()
        pvec_len = len(point_vec)
        svec_len = len(self.signal_amplitude_list)
        mvec_len = min(pvec_len, svec_len)
        for i in range(0, mvec_len):
            data = self.signal_amplitude_list[svec_len - i - 1]
            point_vec[pvec_len - i - 1].setY(data)
        # Use replace instead of clear & append to improve performance.
        self.ui.channel.t.series.replace(point_vec)

    def updateFreqDomainChart(self):
        point_vec = self.ui.channel.t.series.pointsVector()
        t_domain = [p.y() for p in point_vec]
        if len(t_domain) > 1000:
            t_domain = t_domain[0:1000]
        elif len(t_domain) < 1000:
            t_domain = t_domain + [0] * (1000 - len(t_domain))
        f_domain = abs(np.fft.fftshift(np.fft.fft(t_domain)))
        point_vec = [QPointF(x-500, f_domain[x]) for x in range(0, 1000)]
        # Use replace instead of clear & append to improve performance.
        self.ui.channel.f.series.replace(point_vec)

    def saveData(self):
        f = open('data.txt', 'w')
        for elem in self.signal_amplitude_list:
            f.write(str(elem) + '\n')
        f.close()


def visualProcess(comm_queue):
    app = QApplication(sys.argv)
    vs_clnt = VisualClient(comm_queue)
    vs_clnt.show()
    rcode = app.exec()
    vs_clnt.saveData()
    sys.exit(rcode)


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
