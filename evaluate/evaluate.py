import os
import jpype
import numpy as np
import logging
import matplotlib.pyplot as plt
from scipy.misc import imsave,imread

evaluate_root = '/mnt/A/meteorological/2500_ref_seq/'
test_root = '/mnt/A/CIKM2017/CIKM_datasets/test/'

def dBZ_to_pixel(dBZ_img):
    return (dBZ_img.astype(np.float) + 10.0) * 255.0/ 95.0

def pixel_to_dBZ(data):
    dBZ = data.astype(np.float) * 95.0 / 255.0 - 10
    return dBZ

def get_hit_miss_counts_numba(prediction, truth, thresholds=None):
    """This function calculates the overall hits and misses for the prediction, which could be used
    to get the skill scores and threat scores:
    This function assumes the input, i.e, prediction and truth are 3-dim tensors, (timestep, row, col)
    and all inputs should be between 0~1
    Parameters
    ----------
    prediction : np.ndarray
        Shape: (seq_len, height, width)
    truth : np.ndarray
        Shape: (seq_len, height, width)
    mask : np.ndarray or None
        Shape: (seq_len, height, width)
        0 --> not use
        1 --> use
    thresholds : list or tuple
    Returns
    -------
    hits : np.ndarray
        (seq_len, len(thresholds))
        TP
    misses : np.ndarray
        (seq_len, len(thresholds))
        FN
    false_alarms : np.ndarray
        (seq_len, len(thresholds))
        FP
    correct_negatives : np.ndarray
        (seq_len, len(thresholds))
        TN
    """

    assert 3 == prediction.ndim
    assert 3 == truth.ndim
    assert prediction.shape == truth.shape


    ret = _get_hit_miss_counts_numba(prediction=prediction,
                                     truth=truth,
                                     thresholds=thresholds)
    return ret[:, :, 0], ret[:, :, 1], ret[:, :, 2], ret[:, :, 3]


def _get_hit_miss_counts_numba(prediction, truth, thresholds):
    seqlen, height, width = prediction.shape
    threshold_num = len(thresholds)
    ret = np.zeros(shape=(seqlen, threshold_num, 4), dtype=np.int32)

    for i in range(seqlen):
        for m in range(height):
            for n in range(width):
                for k in range(threshold_num):
                    bpred = prediction[i][m][n] >= thresholds[k]
                    btruth = truth[i][m][n] >= thresholds[k]
                    ind = (1 - btruth) * 2 + (1 - bpred)
                    ret[i][k][ind] += 1
                    # The above code is the same as:
                    # ret[i][j][k][0] += bpred * btruth
                    # ret[i][j][k][1] += (1 - bpred) * btruth
                    # ret[i][j][k][2] += bpred * (1 - btruth)
                    # ret[i][j][k][3] += (1 - bpred) * (1- btruth)
    return ret



class SeqHKOEvaluation(object):
    def __init__(self, seq_len, threholds=None):
        if threholds==None:
            self._thresholds = dBZ_to_pixel(np.array([5.0, 20.0, 40.0]))
        else:
            self._thresholds = threholds
        self._seq_len = seq_len
        self.begin()

    def begin(self):
        self._total_hits = np.zeros((self._seq_len, len(self._thresholds)), dtype=np.int)
        self._total_misses = np.zeros((self._seq_len, len(self._thresholds)), dtype=np.int)
        self._total_false_alarms = np.zeros((self._seq_len, len(self._thresholds)), dtype=np.int)
        self._total_correct_negatives = np.zeros((self._seq_len, len(self._thresholds)),
                                                 dtype=np.int)
        self._datetime_dict = {}


    def clear_all(self):
        self._total_hits[:] = 0
        self._total_misses[:] = 0
        self._total_false_alarms[:] = 0
        self._total_correct_negatives[:] = 0


    def update(self, gt, pred):
        """

        Parameters
        ----------
        gt : np.ndarray
        pred : np.ndarray

        Returns
        -------

        """

        assert gt.shape[0] == self._seq_len
        assert gt.shape == pred.shape


        # TODO Save all the mse, mae, gdl, hits, misses, false_alarms and correct_negatives
        hits, misses, false_alarms, correct_negatives = \
            get_hit_miss_counts_numba(prediction=pred, truth=gt,thresholds=self._thresholds)

        self._total_hits += hits
        self._total_misses += misses
        self._total_false_alarms += false_alarms
        self._total_correct_negatives += correct_negatives

    def calculate_stat(self):
        """The following measurements will be used to measure the score of the forecaster

        See Also
        [Weather and Forecasting 2010] Equitability Revisited: Why the "Equitable Threat Score" Is Not Equitable
        http://www.wxonline.info/topics/verif2.html

        We will denote
        (a b    (hits       false alarms
         c d) =  misses   correct negatives)

        We will report the
        POD = a / (a + c)
        FAR = b / (a + b)
        CSI = a / (a + b + c)
        Heidke Skill Score (HSS) = 2(ad - bc) / ((a+c) (c+d) + (a+b)(b+d))
        Gilbert Skill Score (GSS) = HSS / (2 - HSS), also known as the Equitable Threat Score
            HSS = 2 * GSS / (GSS + 1)

        Returns
        -------

        """

        a = self._total_hits.astype(np.float64)
        b = self._total_false_alarms.astype(np.float64)
        c = self._total_misses.astype(np.float64)
        d = self._total_correct_negatives.astype(np.float64)

        pod = a / (a + c)
        far = b / (a + b)
        csi = a / (a + b + c)
        n = a + b + c + d
        aref = (a + b) / n * (a + c)
        gss = (a - aref) / (a + b + c - aref)
        hss = 2 * gss / (gss + 1)

        # return pod, far, csi, hss, gss,
        return pod, far, csi, hss, gss



class HKOEvaluation(object):
    def __init__(self, threholds=None):
        if threholds==None:
            self._thresholds = dBZ_to_pixel(np.array([5.0, 20.0, 40.0]))
        else:
            self._thresholds = threholds

        self.begin()

    def begin(self):

        self._total_hits = np.zeros((len(self._thresholds)), dtype=np.int)
        self._total_misses = np.zeros((len(self._thresholds)), dtype=np.int)
        self._total_false_alarms = np.zeros((len(self._thresholds)), dtype=np.int)
        self._total_correct_negatives = np.zeros((len(self._thresholds)),dtype=np.int)
        self._datetime_dict = {}


    def clear_all(self):
        self._total_hits[:] = 0
        self._total_misses[:] = 0
        self._total_false_alarms[:] = 0
        self._total_correct_negatives[:] = 0


    def update(self, gt, pred):
        """

        Parameters
        ----------
        gt : np.ndarray
        pred : np.ndarray

        Returns
        -------

        """


        hits, misses, false_alarms, correct_negatives = \
            self.get_hit_miss_counts_numba(prediction=pred, truth=gt,thresholds=self._thresholds)

        self._total_hits += hits
        self._total_misses += misses
        self._total_false_alarms += false_alarms
        self._total_correct_negatives += correct_negatives

    def _get_hit_miss_counts_numba(self,prediction, truth, thresholds):
        height, width = prediction.shape
        threshold_num = len(thresholds)
        ret = np.zeros(shape=(threshold_num, 4), dtype=np.int32)
        for m in range(height):
            for n in range(width):
                for k in range(threshold_num):
                    bpred = prediction[m][n] >= thresholds[k]
                    btruth = truth[m][n] >= thresholds[k]
                    ind = (1 - btruth) * 2 + (1 - bpred)
                    ret[k][ind] += 1
                    # The above code is the same as:
                    # ret[k][0] += bpred * btruth
                    # ret[k][1] += (1 - bpred) * btruth
                    # ret[k][2] += bpred * (1 - btruth)
                    # ret[k][3] += (1 - bpred) * (1- btruth)
        return ret

    def get_hit_miss_counts_numba(self,prediction, truth, thresholds=None):
        """This function calculates the overall hits and misses for the prediction, which could be used
        to get the skill scores and threat scores:
        This function assumes the input, i.e, prediction and truth are 3-dim tensors, (timestep, row, col)
        and all inputs should be between 0~1
        Parameters
        ----------
        prediction : np.ndarray
            Shape: (height, width)
        truth : np.ndarray
            Shape: (height, width)
        mask : np.ndarray or None
            Shape: (seq_len, height, width)
            0 --> not use
            1 --> use
        thresholds : list or tuple
        Returns
        -------
        hits : np.ndarray
            (seq_len, len(thresholds))
            TP
        misses : np.ndarray
            (seq_len, len(thresholds))
            FN
        false_alarms : np.ndarray
            (seq_len, len(thresholds))
            FP
        correct_negatives : np.ndarray
            (seq_len, len(thresholds))
            TN
        """

        assert 2 == prediction.ndim
        assert 2 == truth.ndim
        assert prediction.shape == truth.shape

        ret = self._get_hit_miss_counts_numba(prediction=prediction,
                                         truth=truth,
                                         thresholds=thresholds)
        return ret[:, 0], ret[:, 1], ret[:, 2], ret[:, 3]

    def calculate_stat(self):
        """The following measurements will be used to measure the score of the forecaster

        See Also
        [Weather and Forecasting 2010] Equitability Revisited: Why the "Equitable Threat Score" Is Not Equitable
        http://www.wxonline.info/topics/verif2.html

        We will denote
        (a b    (hits       false alarms
         c d) =  misses   correct negatives)

        We will report the
        POD = a / (a + c)
        FAR = b / (a + b)
        CSI = a / (a + b + c)
        Heidke Skill Score (HSS) = 2(ad - bc) / ((a+c) (c+d) + (a+b)(b+d))
        Gilbert Skill Score (GSS) = HSS / (2 - HSS), also known as the Equitable Threat Score
            HSS = 2 * GSS / (GSS + 1)

        Returns
        -------

        """

        a = self._total_hits.astype(np.float64)
        b = self._total_false_alarms.astype(np.float64)
        c = self._total_misses.astype(np.float64)
        d = self._total_correct_negatives.astype(np.float64)

        pod = a / (a + c)
        far = b / (a + b)
        csi = a / (a + b + c)
        n = a + b + c + d
        aref = (a + b) / n * (a + c)
        gss = (a - aref) / (a + b + c - aref)
        hss = 2 * gss / (gss + 1)

        # return pod, far, csi, hss, gss,
        return pod, far, csi, hss, gss


def seq_eva_hss_csi(true_fold,pred_fold):
    hko_eva = SeqHKOEvaluation(10)
    valid_root_path = 'valid_test.txt'
    sample_indexes = np.loadtxt(valid_root_path)
    for index in sample_indexes:
        true_current_fold = os.path.join(true_fold,'sample_'+str(int(index)))
        pre_current_fold = os.path.join(pred_fold,'sample_'+str(int(index)))
        pred_imgs = []
        true_imgs = []
        for t in range(6, 16, 1):
            pred_path = os.path.join(pre_current_fold,'img_'+str(t)+'.png')
            true_path = os.path.join(true_current_fold,'img_'+str(t)+'.png')
            pred_img = imread(pred_path)
            true_img = imread(true_path)
            pred_imgs.append(pred_img)
            true_imgs.append(true_img)
        pred_imgs = np.array(pred_imgs).astype(np.float)
        true_imgs = np.array(true_imgs).astype(np.float)

        hko_eva.update(true_imgs,pred_imgs)

    pod, far, csi, hss, gss = hko_eva.calculate_stat()
    return hss,csi

def eva_hss_csi(true_fold,pred_fold):
    hko_eva = HKOEvaluation()
    valid_root_path = 'valid_test.txt'
    sample_indexes = np.loadtxt(valid_root_path)
    for index in sample_indexes:
        true_current_fold = os.path.join(true_fold,'sample_'+str(int(index)))
        pre_current_fold = os.path.join(pred_fold,'sample_'+str(int(index)))
        for t in range(6, 16, 1):
            pred_path = os.path.join(pre_current_fold,'img_'+str(t)+'.png')
            true_path = os.path.join(true_current_fold,'img_'+str(t)+'.png')
            pred_img = imread(pred_path)
            true_img = imread(true_path)
            hko_eva.update(true_img, pred_img)
    pod, far, csi, hss, gss = hko_eva.calculate_stat()
    return hss,csi

def start_jd():
    jarpath = "CIKM_Eva.jar"
    jvmPath = jpype.getDefaultJVMPath()
    jpype.startJVM(jvmPath, "-ea", "-Djava.class.path=%s" % (jarpath))
    javaClass = jpype.JClass("Main")
    jd = javaClass()
    return jd

def eva_hss_csi_java(model_name,jd):

    result = jd.evaluate(model_name,test_root,evaluate_root)
    hss = []
    csi = []

    for i in range(3):
        hss.append(result[0][i])
        csi.append(result[1][i])

    return hss,csi

def seq_eva_hss_csi_java(model_name,jd):

    result = jd.evaluate_seq(model_name,test_root,evaluate_root)
    hss = []
    csi = []

    for t in range(10):
        cur_hss = []
        cur_csi = []
        for i in range(3):
            cur_hss.append(result[0][t][i])
            cur_csi.append(result[1][t][i])

        hss.append(cur_hss)
        csi.append(cur_csi)
    hss = np.array(hss)
    csi = np.array(csi)

    return hss,csi



def eval_test(true_fold,pred_fold):
    res = 0
    valid_root_path = 'valid_test.txt'
    sample_indexes = np.loadtxt(valid_root_path)
    for index in sample_indexes:
        true_current_fold = os.path.join(true_fold,'sample_'+str(int(index)))
        pre_current_fold = os.path.join(pred_fold,'sample_'+str(int(index)))
        pred_imgs = []
        true_imgs = []
        for t in range(6, 16, 1):
            pred_path = os.path.join(pre_current_fold,'img_'+str(t)+'.png')
            true_path = os.path.join(true_current_fold,'img_'+str(t)+'.png')
            pred_img = imread(pred_path)
            true_img = imread(true_path)
            pred_imgs.append(pred_img)
            true_imgs.append(true_img)
        pred_imgs = np.array(pred_imgs).astype(np.float)
        true_imgs = np.array(true_imgs).astype(np.float)
        pred_imgs = pixel_to_dBZ(pred_imgs)
        true_imgs = pixel_to_dBZ(true_imgs)

        sample_mse = np.square(pred_imgs - true_imgs).mean()
        res = res+sample_mse
    res = res/len(sample_indexes)
    return res

def sequence_mse(true_fold,pred_fold):
    res = [0 for _ in range(10)]
    valid_root_path = 'valid_test.txt'
    sample_indexes = np.loadtxt(valid_root_path)

    for i in sample_indexes:
        true_current_fold = os.path.join(true_fold, 'sample_' + str(int(i)))
        pre_current_fold = os.path.join(pred_fold, 'sample_' + str(int(i)))
        sample_res = []
        for t in range(6, 16, 1):
            pred_path = os.path.join(pre_current_fold, 'img_' + str(t) + '.png')
            true_path = os.path.join(true_current_fold,  'img_' + str(t) + '.png')
            pre_img = imread(pred_path)
            true_img = imread(true_path)
            pre_img = pixel_to_dBZ(pre_img)
            true_img = pixel_to_dBZ(true_img)
            current_res = np.square(pre_img - true_img).mean()
            sample_res.append(current_res)
        for i in range(len(res)):
            res[i] = res[i]+sample_res[i]

    for i in range(len(res)):
        res[i] = res[i] / len(sample_indexes)
    return res


def plot_seq_mse(datas,names,model_names):

    x = []
    for i in range(1, 11, 1):
        x.append(i*6)
    plt.figure(figsize=(7.5,5))

    for idx,name in enumerate(names):
        plt.plot(x,datas[name])
        names[idx] = model_names[idx]+':'+str(np.mean(np.array(datas[name])))[:5]

    plt.grid()
    plt.legend(names)
    plt.xticks(x)
    plt.xlabel('Leadtime (Minutes)')
    plt.ylabel('Mean Square Error (MSE)')
    plt.savefig('ablation_mse_seq.png')
    plt.show()


def plot_seq_hss_or_csi(datas,names,model_names,type):

    x = []
    for i in range(1, 11, 1):
        x.append(i * 6)

    for threashold_i in range(3):

        plt.figure(figsize=(7.5,5))


        for idx,name in enumerate(names):

            plt.plot(x,datas[name][:,threashold_i])


        plt.grid()
        plt.legend(model_names)
        plt.xticks(x)
        plt.xlabel('Leadtime (Minutes)')
        if type == 'HSS':
            plt.ylabel('Heidk Skill Score (HSS)')
        if type == 'CSI':
            plt.ylabel('Critical Success Index (CSI)')

        plt.savefig(type+'_'+str(threashold_i)+'.png')
        plt.show()


def mse_test(test_model_list,model_names):
    test_model_mse = {}
    for i,model in enumerate(test_model_list):
        mse = eval_test(test_root, os.path.join(evaluate_root, model))
        test_model_mse[model] = mse
        print('The mse of "', model_names[i] ,'" is: ',str(test_model_mse[model]))
    return test_model_mse

def seq_hss_csi_test(test_model_list,model_names,is_java=True,is_plot=True):
    if is_java:
        jd = start_jd()
    test_model_hss = {}
    test_model_csi = {}
    for i,model in enumerate(test_model_list):
        if is_java:
            hss, csi = seq_eva_hss_csi_java(model, jd)
        else:
            hss,csi = seq_eva_hss_csi(test_root, os.path.join(evaluate_root, model))
        test_model_hss[model] = hss
        test_model_csi[model] = csi
        mean_hss = np.mean(hss, 0)
        mean_csi = np.mean(csi, 0)
        print('The hss and csi of "', model_names[i] ,'" is: ')
        print(hss.shape, mean_hss)
        print(csi.shape, mean_csi)
        print()

    if is_plot:
        plot_seq_hss_or_csi(test_model_hss,test_model_list,model_names,'HSS')
        plot_seq_hss_or_csi(test_model_csi,test_model_list,model_names,'CSI')

    if is_java:
        jpype.shutdownJVM()

    return test_model_hss,test_model_csi

def hss_csi_test(test_model_list,model_names,is_java=True):
    if is_java:
        jd = start_jd()
    test_model_hss = {}
    test_model_csi = {}
    for i,model in enumerate(test_model_list):
        if is_java:
            hss,csi = eva_hss_csi_java(model,jd)
        else:
            hss,csi = eva_hss_csi(test_root, os.path.join(evaluate_root, model))
        test_model_hss[model] = hss
        test_model_csi[model] = csi
        mean_hss = np.mean(hss)
        mean_csi = np.mean(csi)
        print('The hss and csi of "', model_names[i] ,'" is: ')
        print(hss, mean_hss)
        print(csi, mean_csi)
    if is_java:
        jpype.shutdownJVM()
    return test_model_hss,test_model_csi


def mse_sequence_test(test_model_list,model_names,is_plot=True):
    seq_mse_res = {}
    for model in test_model_list:
        seq_mse = sequence_mse(test_root, os.path.join(evaluate_root, model))
        seq_mse_res[model] = seq_mse

    if is_plot:
        plot_seq_mse(seq_mse_res,test_model_list,model_names)
    return seq_mse_res

if __name__ == '__main__':
    test_model_list = [
        "CIKM_dec_ConvLSTM_test",
        "CIKM_dec_ST_ConvLSTM_test",
        "CIKM_dec_TrajLSTM_test",
        "CIKM_dec_ST_TrajLSTM_test",
        "CIKM_dec_PFST_ConvLSTM_test",
    ]
    model_names = [
        "ConvLSTM",
        "ST-LSTM",
        "TrajLSTM",
        "ST-TrajLSTM",
        "PFST-LSTM"
    ]


    # mse_test(test_model_list,model_names)
    # mse_sequence_test(test_model_list,model_names)

    # the speed of calculating the HSS and CIS by python is too slow. So, we utilize java to computer it

    # seq_hss_csi_test(test_model_list,model_names)
    # hss_csi_test(test_model_list, model_names)

