import feature
import joblib
import numpy as np


class design:
    def __init__(self, model_path):
        self.model = joblib.load(model_path)

    def func(self, data_array):
        data_array[0] = feature.denoise(data_array[0])
        data_array[1] = feature.denoise(data_array[1])
        now_feature = np.array([np.hstack((feature.get_feature(data_array[0]), feature.get_feature(data_array[1])))])
        now_gesture = int(self.model.predict(now_feature)[0])
        gesture_name = ['握拳', 'OK', '内翻', '外翻', '点赞', '静息']
        return gesture_name[now_gesture]
