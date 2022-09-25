from datetime import datetime
from multiprocessing import Process, Queue
import os
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

import design


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

        self.ui.startButton.clicked.connect(self.startConnection)
        self.ui.stopButton.clicked.connect(self.stopConnection)
        self.ui.deviceList.currentTextChanged.connect(self.startConnection)
        self.ui.serviceList.currentIndexChanged.connect(self.requestService)
        
        self.local_device = QBluetoothLocalDevice()
        self.device_agent = QBluetoothDeviceDiscoveryAgent()
        self.service_agent = QBluetoothServiceDiscoveryAgent()

        self.device_agent.deviceDiscovered.connect(self.addDevice)
        self.local_device.pairingFinished.connect(self.pairingDone)
        self.service_agent.serviceDiscovered.connect(self.addService)

        # Maintain a temporary service list for the socke to connect.
        self.service_list = list()

        # Stopping the connection can cause the service callback fails,
        # but this operation should not be displayed in the hint label.
        # The connection error can be shown only if this field is False.
        self.is_connection_stopped_by_user = False

        # Store the single byte data temporarily to make a 16-bit uint later.
        self.half_data_array = QByteArray()
        # Maintain a backend list to store all received signal sampling data.
        self.sampling_value_list = list()

        self.device_agent.start()

    def closeEvent(self, _):
        try:
            # Notify the server to stop sampling.
            self.socket.write(b'\x02')
            self.socket.readAll()
        except Exception as _:
            pass
        os._exit(0) # Use this to terminate all threads.

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
            # Try to pair with the target device.
            name_addr = self.ui.deviceList.currentText().split(' @ ')
            if len(name_addr) == 2:
                addr = name_addr[1]
                self.local_device.requestPairing(QBluetoothAddress(addr), QBluetoothLocalDevice.Paired)
        except Exception as e:
            print(f'Exception in startConnection, {e}')

    @Slot()
    def stopConnection(self):
        try:
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
            # Notify the server to start sampling.
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
            # Check whether there are bytes remained in the previous reading.
            # Complete current received byte array with those bytes (if have).
            if len(self.half_data_array) > 0:
                data_array.push_front(self.half_data_array.data())
                self.half_data_array.clear()
            # Store the trailing bytes temporarily to handle in the next reading.
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

    def __init__(self, comm_queue, notify_queue, callback_queue):
        super().__init__()

        self.channel_index = 0
        self.comm_queue = comm_queue
        self.notify_queue = notify_queue
        self.callback_queue = callback_queue

        self.ui = loadUI('VisualClient.ui')
        self.setLayout(self.ui.mainLayout)
        self.resize(800, 600)
        self.setWindowTitle('表面肌电手势识别 - 可视化客户端')

        self.ui.channel = types.SimpleNamespace()
        self.ui.channel.t = [self.makeTimeDomainChart('通道 ' + str(i)) for i in range(1, 3)]
        self.ui.channel.f = [self.makeFreqDomainChart('通道 ' + str(i)) for i in range(1, 3)]
        # Support visualizing 2-channel data dynamically.
        self.ui.signalGallery.addWidget(self.ui.channel.t[0].chartView, 0, 0)
        self.ui.signalGallery.addWidget(self.ui.channel.t[1].chartView, 0, 1)
        self.ui.signalGallery.addWidget(self.ui.channel.f[0].chartView, 1, 0)
        self.ui.signalGallery.addWidget(self.ui.channel.f[1].chartView, 1, 1)

        self.ui.startButton.clicked.connect(self.startCollect)
        self.ui.stopButton.clicked.connect(self.stopCollect)

        self.signal_amplitude_list = [list() for i in range(0, 2)]

        self.lk = RLock()

        self.td1 = Thread(target=VisualClient.peekCommQueue, args=(self,))
        self.td1.daemon = True
        self.td1.start()

        self.td2 = Thread(target=VisualClient.peekCallbackQueue, args=(self,))
        self.td2.daemon = True
        self.td2.start()

    def closeEvent(self, _):
        self.exportCompleteData()
        self.notify_queue.put('CLOSE')
        os._exit(0) # Use this to terminate all threads.

    def dateTimeNowStr(self):
        return datetime.now().strftime('%Y-%m-%d-%H-%M-%S')

    def makeTimeDomainChart(self, title):
        return self.makeGeneralChart(title, '时间', (0, 1000), 6, '幅度 / 伏特', (0, 3.3), 2)

    def makeFreqDomainChart(self, title):
        return self.makeGeneralChart(title, '频率', (-500, 500), 6, '幅度 / 绝对值', (0, 1000), 2)

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
        chart.axisX.setTitleFont(QFont('微软雅黑', 9))

        chart.axisY = QValueAxis()
        chart.axisY.setRange(*yrange)
        chart.axisY.setTickCount(ytick)
        chart.axisY.setTitleText(ylabel)
        chart.axisY.setTitleFont(QFont('微软雅黑', 9))

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

    @Slot()
    def startCollect(self):
        self.ui.startButton.setEnabled(False)
        self.ui.stopButton.setEnabled(True)
        self.collect_start = [len(self.signal_amplitude_list[i]) for i in range(0, 2)]
        self.ui.infoLabel.setText('正在收集......')

    @Slot()
    def stopCollect(self):
        self.collect_stop = [len(self.signal_amplitude_list[i]) for i in range(0, 2)]
        info_text = str()
        for i in range(0, 2):
            if i != 0:
                info_text = info_text + ', '
            info_text = info_text + '通道 ' + str(i + 1) + ' ( '
            info_text = info_text + str(self.collect_stop[i] - self.collect_start[i]) + ' 点 )'
        self.ui.infoLabel.setText(info_text)
        self.exportSliceData()
        self.ui.startButton.setEnabled(True)
        self.ui.stopButton.setEnabled(False)

    def exportSliceData(self):
        for i in range(0, 2):
            signal_len = len(self.signal_amplitude_list[i])
            a = min(self.collect_start[i], signal_len - 1)
            b = max(min(self.collect_stop[i], signal_len), a + 1)
            src_data = self.signal_amplitude_list[i][a:b]
            # Append 2-channel offline signal data.
            offline_dir = 'export/slices/' + self.dateTimeNowStr()
            if not os.path.exists(offline_dir):
                os.makedirs(offline_dir)
            np.save(offline_dir + '/channel' + str(i + 1) + '.npy', src_data)
            # Overwrite 2-channel runtime signal data.
            runtime_dir = 'export/runtime'
            if not os.path.exists(runtime_dir):
                os.mkdir(runtime_dir)
            np.save(runtime_dir + '/channel' + str(i + 1) + '.npy', src_data)

    data_received = Signal()

    def peekCommQueue(self):
        try:
            self.data_received.connect(self.updateChart)
            while True:
                self.lk.acquire()
                while not self.comm_queue.empty():
                    # Throw if the queue blocks more than 1 second.
                    data_array = self.comm_queue.get(True, 1)
                    # Convert 16-bit sampling values to referenced voltage values.
                    for i in range(0, len(data_array)):
                        data_array[i] = (data_array[i] / 65536) * 3.3
                        self.signal_amplitude_list[self.channel_index].append(data_array[i])
                        self.channel_index = (self.channel_index + 1) % 2
                    # Notify to update the chart with new data.
                    self.data_received.emit()
                self.lk.release()
                # Prevnet the UI thread from getting stuck.
                time.sleep(0.01)
        except Exception as e:
            print(f'Exception in peekCommQueue, {e}')

    @Slot()
    def updateChart(self):
        try:
            self.lk.acquire()
            self.updateTimeDomainChart()
            self.updateFreqDomainChart()
            self.lk.release()
        except Exception as e:
            print(f'Exception in updateChart, {e}')

    def updateTimeDomainChart(self):
        for i in range(0, 2):
            point_vec = self.ui.channel.t[i].series.pointsVector()
            pvec_len = len(point_vec)
            svec_len = len(self.signal_amplitude_list[i])
            mvec_len = min(pvec_len, svec_len)
            for j in range(0, mvec_len):
                data = self.signal_amplitude_list[i][svec_len - j - 1]
                point_vec[pvec_len - j - 1].setY(data)
            # Use replace instead of clear & append to improve performance.
            self.ui.channel.t[i].series.replace(point_vec)

    def updateFreqDomainChart(self):
        for i in range(0, 2):
            point_vec = self.ui.channel.t[i].series.pointsVector()
            t_domain = [p.y() for p in point_vec]
            if len(t_domain) > 1000:
                t_domain = t_domain[0:1000]
            elif len(t_domain) < 1000:
                t_domain = t_domain + [0] * (1000 - len(t_domain))
            f_domain = abs(np.fft.fftshift(np.fft.fft(t_domain)))
            point_vec = [QPointF(x - 500, f_domain[x]) for x in range(0, 1000)]
            # Use replace instead of clear & append to improve performance.
            self.ui.channel.f[i].series.replace(point_vec)

    result_received = Signal(str)

    def peekCallbackQueue(self):
        try:
            self.result_received.connect(self.updateResult)
            while True:
                self.lk.acquire()
                while not self.callback_queue.empty():
                    # Throw if the queue blocks more than 1 second.
                    result_text = self.callback_queue.get(True, 1)
                    # Notify to update the label with new result.
                    self.result_received.emit(result_text)
                self.lk.release()
                # Prevnet the UI thread from getting stuck.
                time.sleep(0.01)
        except Exception as e:
            print(f'Exception in peekCallbackQueue, {e}')  

    @Slot(str)
    def updateResult(self, result_text):
        self.ui.startButton.setEnabled(True)
        self.ui.resultLabel.setText(result_text)

    def exportCompleteData(self):
        complete_dir = 'export/complete/' + self.dateTimeNowStr()
        if not os.path.exists(complete_dir):
            os.makedirs(complete_dir)
        for i in range(0, 2):
            f = open(complete_dir + '/channel' + str(i + 1) + '.txt', 'w')
            for elem in self.signal_amplitude_list[i]:
                f.write(str(elem) + '\n')
            f.close()


def visualProcess(comm_queue, notify_queue, callback_queue):
    app = QApplication(sys.argv)
    vs_clnt = VisualClient(comm_queue, notify_queue, callback_queue)
    vs_clnt.show()
    sys.exit(app.exec())


class RecognitionClient(QWidget):

    def __init__(self, comm_queue, notify_queue, callback_queue):
        super().__init__()

        self.channel_index = 0
        self.comm_queue = comm_queue
        self.notify_queue = notify_queue
        self.callback_queue = callback_queue
        self.design = design.design('model/1s_model.pkl')

        self.signal_amplitude_list = [list() for i in range(0, 2)]

        self.lk = RLock()

        self.td1 = Thread(target=RecognitionClient.peekCommQueue, args=(self,))
        self.td1.daemon = True
        self.td1.start()

        self.td2 = Thread(target=RecognitionClient.peekNotifyQueue, args=(self,))
        self.td2.daemon = True
        self.td2.start()

    data_received = Signal()

    def peekCommQueue(self):
        try:
            self.data_received.connect(self.analyzeSignalData)
            while True:
                self.lk.acquire()
                while not self.comm_queue.empty():
                    # Throw if the queue blocks more than 1 second.
                    data_array = self.comm_queue.get(True, 1)
                    # Convert 16-bit sampling values to referenced voltage values.
                    for i in range(0, len(data_array)):
                        data_array[i] = (data_array[i] / 65536) * 3.3
                        self.signal_amplitude_list[self.channel_index].append(data_array[i])
                        self.channel_index = (self.channel_index + 1) % 2
                    # Notify to update the chart with new data.
                    self.data_received.emit()
                self.lk.release()
                # Prevnet the UI thread from getting stuck.
                time.sleep(0.01)
        except Exception as e:
            print(f'Exception in peekCommQueue, {e}')

    def peekNotifyQueue(self):
        try:
            while True:
                self.lk.acquire()
                while not self.notify_queue.empty():
                    msg_text = self.notify_queue.get(True, 1)
                    if msg_text == 'CLOSE':
                        os._exit(0) # Use this to terminate all threads.
                self.lk.release()
                # Prevent the main thread from getting stuck.
                time.sleep(0.01)
        except Exception as e:
            print(f'Exception in peekNotifyQueue, {e}')

    # last_signal_index = 1000
    # last_signal_name = '静息'

    # prev_signal_names = ['静息' for i in range(0,4)]

    def analyzeSignalData(self):
        datasize = min(len(self.signal_amplitude_list[0]), len(self.signal_amplitude_list[1]))

        # Continuous Check
        if datasize > 1000:
            data1 = self.signal_amplitude_list[0][-1000:]
            data2 = self.signal_amplitude_list[1][-1000:]
            data_array = np.vstack((data1, data2))
            self.callback_queue.put(self.design.func(data_array))

        # Double Check
        # if datasize - self.last_signal_index > 200:
        #     self.last_signal_index = datasize
        #     data1 = self.signal_amplitude_list[0][-1000:]
        #     data2 = self.signal_amplitude_list[1][-1000:]
        #     data_array = np.vstack((data1, data2))
        #     curr_signal_name = self.design.func(data_array)
        #     if curr_signal_name == self.last_signal_name:
        #         self.callback_queue.put(curr_signal_name)
        #     self.last_signal_name = curr_signal_name

        # Multi Check
        # if datasize > 1000:
        #     data1 = self.signal_amplitude_list[0][-1000:]
        #     data2 = self.signal_amplitude_list[1][-1000:]
        #     data_array = np.vstack((data1, data2))
        #     self.prev_signal_names.append(self.design.func(data_array))
        #     self.prev_signal_names.pop(0)
        #     # Find max count name.
        #     name_count_dict = dict()
        #     for name in self.prev_signal_names:
        #         if name in name_count_dict:
        #             name_count_dict[name] = name_count_dict[name] + 1
        #         else:
        #             name_count_dict[name] = 1
        #     max_count = 0
        #     max_count_name = str()
        #     for name, count in name_count_dict.items():
        #         if count > max_count:
        #             max_count = count
        #             max_count_name = name
        #     self.callback_queue.put(max_count_name)

def recognitionProcess(comm_queue, notify_queue, callback_queue):
    app = QApplication(sys.argv)
    rg_clnt = RecognitionClient(comm_queue, notify_queue, callback_queue)
    rg_clnt.hide()
    sys.exit(app.exec())


if __name__ == '__main__':
    app = QApplication(sys.argv)

    comm_qs = dict()
    comm_qs['visual'] = Queue()
    comm_qs['recognition'] = Queue()

    # Bluetooth Client
    bt_clnt = BluetoothClient(comm_qs)
    bt_clnt.show()

    ntfy_q = Queue()
    clbk_q = Queue()

    # Visual Client
    vs_proc = Process(target=visualProcess, args=(comm_qs['visual'],ntfy_q,clbk_q,))
    vs_proc.start()

    # Recognition Client
    rg_proc = Process(target=recognitionProcess, args=(comm_qs['recognition'],ntfy_q,clbk_q,))
    rg_proc.start()

    sys.exit(app.exec())
