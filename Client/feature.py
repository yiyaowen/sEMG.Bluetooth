import math
import numpy as np
import pywt
from scipy.fft import fft


def get_zc(data):
    thresh = 0.0
    zc=0
    for i in range(len(data)):  
        if (data[i]*data[i-1]<0)and(np.fabs(data[i]-data[i-1])>thresh):
            zc+=1
    return zc/len(data)


def get_wamp(data):
    thresh = 0.02*np.max(data)
    wamp = 0
    for i in range(len(data)):
        if np.fabs(data[i]-data[i-1])>thresh:
            wamp+=1
    return wamp/len(data)


def sampEn(L:np.array,std:float,m,r):
    N = len(L)
    B = 0.0
    A = 0.0

    xmi = np.array([L[i:i+m] for i in range(N-m)])
    xmj = np.array([L[i:i+m] for i in range(N-m+1)])
     
    B = np.sum([np.sum(np.abs(xmii-xmj).max(axis=1) <= r*std)-1 for xmii in xmi])
    m += 1
    xm = np.array([L[i:i+m] for i in range(N-m+1)])
    
    A = np.sum([np.sum(np.abs(xmi-xm).max(axis=1) <= r*std)-1 for xmi in xm])
    return -np.log(A/B)


def ARC4ord(orinArray):
		tValue = len(orinArray)
		AR_coeffs = np.polyfit(range(tValue),orinArray,4)
		return AR_coeffs
		 
def get_ARC4(data):
    return np.apply_along_axis(ARC4ord, 0, data)


def sgn(num):
    if(num > 0.0):
        return 1.0
    elif(num == 0.0):
        return 0.0
    else:
        return -1.0


def denoise(new_df):
    data = new_df
    #data = data.T.tolist()  
    w = pywt.Wavelet('db2')#选择db2小波基
    [ca4,cd4, cd3, cd2, cd1] = pywt.wavedec(data, w,level=4)  # 4层小波分解

    length1 = len(cd1)
    length0 = len(data)

    Cd1 = np.array(cd1)
    abs_cd1 = np.abs(Cd1)
    median_cd1 = np.median(abs_cd1)

    sigma = (1.0 / 0.6745) * median_cd1
    lamda = sigma * math.sqrt(2.0 * math.log(float(length0 ), math.e))#固定阈值计算
    usecoeffs = []
    usecoeffs.append(ca4) 

    #软阈值去噪
    for k in range(length1):
        if (abs(cd1[k]) >= lamda):
            cd1[k] = sgn(cd1[k]) * (abs(cd1[k])-lamda)
        else:
            cd1[k] = 0.0

    length2 = len(cd2)
    for k in range(length2):
        if (abs(cd2[k]) >= lamda):
            cd2[k] = sgn(cd2[k]) * (abs(cd2[k]) - lamda)
        else:
            cd2[k] = 0.0

    length3 = len(cd3)
    for k in range(length3):
        if (abs(cd3[k]) >= lamda):
            cd3[k] = sgn(cd3[k]) * (abs(cd3[k]) - lamda)
        else:
            cd3[k] = 0.0

    length4 = len(cd4)
    for k in range(length4):
        if (abs(cd4[k]) >= lamda):
            cd4[k] = sgn(cd4[k]) * (abs(cd4[k]) - lamda)
        else:
            cd4[k] = 0.0

    usecoeffs.append(cd4)
    usecoeffs.append(cd3)
    usecoeffs.append(cd2)
    usecoeffs.append(cd1)
    recoeffs = pywt.waverec(usecoeffs, w)#信号重构
    return recoeffs


def get_fft_power_spectrum(y_values, N, f_s, f):
    f_values = np.linspace(0, f_s//f, N//f)
    fft_values_ = np.abs(fft(y_values))
    fft_values = 2/N * (fft_values_[0:int(N/2)])    
    ps_values = fft_values**2 / N
    cor_x = np.correlate(y_values, y_values, 'same')    
    cor_X = fft(cor_x, N)                 
    ps_cor = np.abs(cor_X)
    ps_cor_values = 10*np.log10(ps_cor[0:int(N/2)] / np.max(ps_cor))
    
    return f_values, fft_values, ps_values, ps_cor_values


def get_MDF(x):
    N = len(x)
    f_s = 1000
    f_values, fft_values, ps_values, ps_cor_values = get_fft_power_spectrum(x, N, f_s, 2)

    P = ps_values
    f = fft_values
 
    S = []
    for i in range(N//2):
        P1 = P[i]
        f1 = fft_values[i]
        s1 = P1*f1
        S.append(s1)
    S1 = np.sum(S)/np.sum(P)

    return S1


def get_MNF(x):
    N = len(x)
    f_s = 1000
    f_values, fft_values, ps_values, ps_cor_values = get_fft_power_spectrum(x, N, f_s, 2)
    P = ps_values
    S2 = np.sum(P)/N 
    return S2


def get_FD(x):
    N = len(x)
    f_s = 1000
    f_values, fft_values, ps_values, ps_cor_values = get_fft_power_spectrum(x, N, f_s, 2)
    P = ps_values
    f = fft_values
    S = []
    for i in range(N//2):
        P1 = P[i]
        f1 = fft_values[i]
        s1 = P1*f1
        S.append(s1)
    S1 = np.sum(S)/np.sum(P)
    S = []
    for i in range(N//2):
        P1 = P[i]
        f1 = fft_values[i]
        s2 = P1*((f1-S1)**2)
        S.append(s2)
    S3 = np.sqrt(np.sum(S) / np.sum(P))
    return S3


#获取特征数组
def get_feature(data):

    mav = np.sqrt(sum(np.fabs(data))/len(data))       

    rms = np.sqrt(sum([x ** 2 for x in data])/ len(data))

    var = np.var(data)

    wl = sum(np.fabs(np.diff(data)))/len(data)

    sampen = sampEn(data,np.std(data),2,0.15)
    
    zc = get_zc(data)

    wamp = get_wamp(data)

    ARC = get_ARC4(data).tolist()

    MNF = get_MNF(data)

    MDF = get_MDF(data)

    FD = get_FD(data)
    feature = np.array([mav,rms,var,wl,sampen,zc,wamp,ARC[1],ARC[2],ARC[3],ARC[4],MNF,MDF,FD])

    return feature
