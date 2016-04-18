__author__ = 'starsdeep'
import os, sys
import json
import operator
import pandas as pd
import copy
train_pred_filename_tpl = 'train_pred_trial_%d.csv'
trails_filename = 'hyperopt_trials.json'


def load_trials(dir_path):
    trial_result_list = []
    with open(os.path.join(dir_path, trails_filename)) as infile:
        trial_result_list = json.load(infile)
    files = [os.path.join(dir_path, train_pred_filename_tpl % i) for i in range(len(trial_result_list))]
    train_pred_list = [pd.read_csv(file, encoding="ISO-8859-1", index_col=0)['train_pred'].values for file in files]
    return trial_result_list, train_pred_list

class TrialsList():

    def __init__(self):
        self.trial_result_list = []
        self.train_pred_list = []

    def append(self, trial_result_list, train_pred_list):
        if len(trial_result_list)!=len(train_pred_list):
            print("size must equal")
            sys.exit()
        self.trial_result_list += trial_result_list
        self.train_pred_list += train_pred_list

    def del_n_trial_(self, n):
        if n<0 or n>=len(self.trial_result_list):
            print("%d is invalid, current size is %d" % (n, ))
            sys.exit()
        del self.trial_result_list[n]
        del self.train_pred_list[n]

    def best_trial(self, verbose=False):
        index, trial_result = min(enumerate(self.trial_result_list), key=lambda k: k[1]['loss']) # shallow copy
        ori = self.train_pred_list[index]
        # test = ori * 0.5
        # print(ori)
        # print(test)
        if verbose:
            print("\nbest trials index is: %d" % index)
            print(trial_result)
        return index, trial_result  # deep copy

    def get_best_trial(self, verbose=False):
        index, trial_result = self.best_trial(verbose)
        train_pred = copy.deepcopy(self.train_pred_list[index])
        self.del_n_trial_(index)
        return index, trial_result, train_pred


if __name__ == '__main__':

    dir_path_list = ["./output/rfr_liaoyikang/", "./output/ridge/"]
    Trials = TrialsList()
    for dir_path in dir_path_list:
        print("loading dir " + dir_path)
        trial_result_list, train_pred_list = load_trials(dir_path)
        Trials.append(trial_result_list, train_pred_list)

    print("number of trials %d" % len(Trials.trial_result_list))
    print("best trials index %d \n %s " % (Trials.get_best_trial()))


