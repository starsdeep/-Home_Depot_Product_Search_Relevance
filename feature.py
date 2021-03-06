#encoding=utf8
import re
import os
import pandas as pd
import time
from load_data import load_data
import hashlib
from utility import *
from SpellCorrect import *
from collections import OrderedDict
from nltk import pos_tag
from gensim.models import Word2Vec
import config.project

total_train = 74067
total_test = 166693

feature_path = './output/features/'

def load_feature(features, config):
    """
    read features from existing files, and then concat those features into a big frame using pd.concat,
    concat a list of frames can improve efficiency see http://pandas.pydata.org/pandas-docs/stable/merging.html
    for more info.
    :param features: features to load
    :return: df contains the features
    """
    if not features:
        return pd.DataFrame()
    frames = []
    data_dir = feature_path
    if "data_dir" in config:
        data_dir = config['data_dir']
    files = [os.path.join(data_dir, feature + '.csv') for feature in features]
    frames = [pd.read_csv(file, encoding="ISO-8859-1", index_col=0) for file in files]
    df = pd.concat(frames, axis=1)

    # read_csv() fills empty string with nan, which will cause a problem in build_feature, so we need to replace nan to '', see https://github.com/pydata/pandas/issues/10205 for detail
    df.fillna('', inplace=True)
    return df

def write_feature(df, features, config):
    not_save = set(config['not_save']) if 'not_save' in config else set()
    data_dir = feature_path
    if "data_dir" in config:
        data_dir = config['data_dir']
    for feature in features:
        if feature in not_save:
            continue
        print("[step]: saving feature %s ..." % feature)
        tmp_df = df[[feature]]
        tmp_df.to_csv(os.path.join(data_dir, feature + '.csv'), encoding="utf8")
    return

def load_group_feature(df, features, feat_dict, data_dir):
    if set(features) & set(feat_dict.keys()):
        for feature in list(feat_dict.keys()):
            if feature in features:
                print('[step]: trying to load feature: '+feature+' ... ',end='')
                filename = os.path.join(data_dir, feature + '.csv')
                if os.path.isfile(filename):
                    tmpdf = pd.read_csv(filename, encoding="utf-8")
                    df = df.merge(tmpdf, left_index=True, right_index=True)
                    features.remove(feature)        
                    print('feature loaded.')
                else:
                    print('feature not found.')
    return df

def load_npmat_feature(df, features, feat_dict, data_dir, weight_dict=False):
    if set(features) & set(feat_dict.keys()):
        for feature in list(feat_dict.keys()):
            if feature in features:
                print('[step]: trying to load feature: '+feature+' ... ',end='')
                if weight_dict:
                    tmpdf = load_npmat(feature, data_dir, feat_dict[feature])
                else:
                    tmpdf = load_npmat(feature, data_dir)
                if tmpdf is not None:
                    df = df.merge(tmpdf, left_index=True, right_index=True)
                    features.remove(feature)        
                    print('feature loaded.')
                else:
                    print('feature not found.')
    return df

def get_feature(config):
    data_dir = feature_path
    if "data_dir" in config:
        data_dir = config['data_dir']
    all_exist_features = set([os.path.splitext(f)[0] for f in os.listdir(data_dir) if os.path.isfile(os.path.join(data_dir,f)) and f.endswith('.csv')])
    total_features = set(config['features'])
    exist_features = total_features & all_exist_features
    recompute_features = set(config['recompute_features']) if 'recompute_features' in config else set()
    new_features = total_features - exist_features

    to_load_features = exist_features - recompute_features
    to_compute_features = recompute_features | new_features

    df_basic, num_train, num_test = load_data(config['num_train'])
    print("[step]: feature already exists, loading: \n" + ' '.join(to_load_features))
    if to_load_features:
        df_all = load_feature(to_load_features, config)
        print("[info]: length of loaded datafame %d" % df_all.shape[0])
        df_train = df_all[:num_train]
        df_test = df_all[-num_test:]
        df = pd.concat((df_train, df_test), axis=0, ignore_index=True)
        print("[info]: length of datafame after trimed with num_train %d" % df.shape[0])
        for column in df_basic.columns.values:
            if column not in df:
                df[column] = df_basic[column].copy()
    else:
        df = df_basic

    df = load_npmat_feature(df, to_compute_features, RawSvdFeatureWeightDict, data_dir, weight_dict=True)
    df = load_npmat_feature(df, to_compute_features, tSNEFeatureSourceDict, data_dir)
    df = load_group_feature(df, to_compute_features, GroupStatFeatureDict, data_dir)
    df = load_group_feature(df, to_compute_features, CooccurFeatureFuncDict, data_dir)
    print("[step]: loading done")
    print("[step]: start computing feature: " + ' '.join(to_compute_features))
    df = build_feature(df, to_compute_features, config)
    write_feature(df, to_compute_features, config)
    return df, num_train, num_test 

def build_feature(df, features, config):
    # iterate features in order, use apply() to update in time
    if not features:
        return df

    data_dir = feature_path
    if 'data_dir' in config:
        data_dir = config['data_dir']

    for feature in list(TextFeatureFuncDict.keys()):
        if feature in features:
            print('[step]: calculating feature: '+feature+' ...')
            feature_func = TextFeatureFuncDict[feature]
            df[feature] = df.apply(feature_func, axis=1)

    for feature in list(MatchFeatureFuncDict.keys()):
        if feature in features:
            print('[step]: calculating feature: '+feature+' ...')
            feature_func = MatchFeatureFuncDict[feature]
            df[feature] = df.apply(feature_func, axis=1)

    for feature in list(WorldFeatureFuncDict.keys()):
        if feature in features:
            print('[step]: calculating feature: '+feature+' ...')
            feature_func = WorldFeatureFuncDict[feature]
            df[feature] = feature_func(df)

    # compute idf features
    if (set(features) & set(IdfFeatureFuncDict.keys())) or (set(features) & set(IdfSimFeatureFuncDict.keys())) or (set(features) & set(SvdSimFeatureFuncDict.keys())) or (set(features) & set(tSNEFeatureSourceDict.keys())) or (set(features) & set(RawSvdFeatureWeightDict.keys())) or (set(features) & set(GroupStatFeatureDict)):
        # prepare idf_dicts, idf_dicts contains idf value for a given word
        search_terms = df['search_term'].unique()
        unique_prd = df.drop_duplicates(subset='product_uid')
        # fit idf vectorizer
        print('[step]: fitting tfidf_vectorizer ...')
        tfidf_vectorizer = {
            'search_term': fit_tfidf(search_terms),
            'title': fit_tfidf(unique_prd['title']),
            'description': fit_tfidf(unique_prd['description']),
            'brand': fit_tfidf(unique_prd['brand']),
            'composite': fit_tfidf(unique_prd['description'] + ' ' + unique_prd['title'] + ' ' + unique_prd['brand']), # idf value from the those 4 fields
            'origin': fit_tfidf(df['product_description'] + ' ' + df['product_title'] + ' ' + df['origin_search_term']) # idf value from the those 4 fields
        }
        # get idf value dictionary
        idf_dicts = {
            'search_term': compute_idf_dict(tfidf_vectorizer['search_term']),
            'title': compute_idf_dict(tfidf_vectorizer['title']),
            'description': compute_idf_dict(tfidf_vectorizer['description']),
            'brand': compute_idf_dict(tfidf_vectorizer['brand']),
            'composite': compute_idf_dict(tfidf_vectorizer['composite'])
        }
        # get transformed tfidf values
        print('[step]: transforming tfidf vectors ...')
        idf_func = lambda mat_name, col: tfidf_vectorizer[mat_name].transform(df[col])
        tfidf_mats = {
            'indv_Q': idf_func('search_term', 'search_term'),
            'indv_T': idf_func('title', 'title'),
            'indv_D': idf_func('description', 'description'),
            'compo_Q': idf_func('composite', 'search_term'),
            'compo_T': idf_func('composite', 'title'),
            'compo_D': idf_func('composite', 'description'),
            'compo_B': idf_func('composite', 'brand'),
            'origin_Q': idf_func('origin', 'origin_search_term'),
            'origin_T': idf_func('origin', 'product_title')
        }

        for feature in list(IdfFeatureFuncDict.keys()):
            if feature in features:
                print('[step]: calculating feature: '+feature+' ...')
                feature_func = IdfFeatureFuncDict[feature]
                df[feature] = df.apply(feature_func, axis=1, idf_dicts=idf_dicts)

        mat_to_ser = lambda x: pd.Series([row for row in x])
        tmpdf = pd.DataFrame({k: mat_to_ser(v) for k, v in tfidf_mats.items()})
        for feature in list(IdfSimFeatureFuncDict.keys()):
            if feature in features:
                print('[step]: calculating feature: '+feature+' ...')
                feature_func = IdfSimFeatureFuncDict[feature]
                df[feature] = tmpdf.apply(feature_func, axis=1)

        # group statistical features
        idx_dict = group_idx_by_relevance(df)
        for feature in list(GroupStatFeatureDict.keys()):
            if feature in features:
                print('[step]: calculating feature: '+feature+' ...')
                feature_func = GroupStatFeatureDict[feature]
                tmpdf = df.apply(feature_func, axis=1, idx_dict=idx_dict, tfidf_mats=tfidf_mats, prefix=feature)
                df.merge(tmpdf, left_index=True, right_index=True)
                tmpdf.to_csv(os.path.join(data_dir, feature + '.csv'), encoding="utf8")
                features.remove(feature)

        if (set(features) & set(tSNEFeatureSourceDict.keys())) or (set(features) & set(SvdSimFeatureFuncDict.keys())):
            # get fitted & transformed svd values
            print('[step]: transforming svd vectors ...')
            svd_func = lambda name: compute_svd(tfidf_mats[name])
            svd_mats = {
                'indv_Q': svd_func('indv_Q'),
                'indv_T': svd_func('indv_T'),
                'indv_D': svd_func('indv_D'),
                'compo_Q': svd_func('compo_Q'),
                'compo_T': svd_func('compo_T'),
                'compo_D': svd_func('compo_D'),
                'origin_Q': svd_func('origin_Q'),
                'origin_T': svd_func('origin_T')
            }
            tmpdf = pd.DataFrame({k: mat_to_ser(v) for k, v in svd_mats.items()})
            for feature in list(SvdSimFeatureFuncDict.keys()):
                if feature in features:
                    print('[step]: calculating feature: '+feature+' ...')
                    feature_func = SvdSimFeatureFuncDict[feature]
                    df[feature] = tmpdf.apply(feature_func, axis=1)
            for feature in list(tSNEFeatureSourceDict.keys()):
                if feature in features:
                    print('[step]: calculating feature: '+feature+' ...')
                    source = tSNEFeatureSourceDict[feature]
                    tmpdf = compute_tsne(feature, source, svd_mats[source], data_dir)
                    df.merge(tmpdf, left_index=True, right_index=True)
                    features.remove(feature)

        # get fitted & transformed raw svd values
        if set(features) & set(RawSvdFeatureWeightDict.keys()):
            print('[step]: transforming raw svd vectors ...')
            svd_func = lambda name: compute_svd(tfidf_mats[name], n_components=10)
            raw_svd_mats = {
                'raw_svd_Q': svd_func('compo_Q'),
                'raw_svd_T': svd_func('compo_T'),
                'raw_svd_D': svd_func('compo_D'),
                'raw_svd_B': svd_func('compo_B'),
            }
            for feature in list(RawSvdFeatureWeightDict.keys()):
                if feature in features:
                    print('[step]: calculating feature: '+feature+' ...')
                    weight = RawSvdFeatureWeightDict[feature]
                    tmpdf = patch_raw_svd(feature, raw_svd_mats[feature], weight, data_dir)
                    df.merge(tmpdf, left_index=True, right_index=True)
                    features.remove(feature)

    # co-occur
    for feature in list(CooccurFeatureFuncDict.keys()):
        if feature in features:
            print('[step]: calculating cooccur feature: '+feature+' ...')
            feature_func = CooccurFeatureFuncDict[feature]
            tmp = pd.DataFrame( feature_func(df) )
            tmp.columns = ['cooccur_tfidf_svd_'+feature+str(i) for i in tmp.columns]
            tmp.to_csv(os.path.join(data_dir, feature + '.csv'), encoding="utf8")
            df = df.merge(tmp, left_index=True, right_index=True)
            features.remove(feature)

    # iterate features in order (iterrows cannot update in time)
    if set(features) & set(PostagFeatureFuncDict.keys()):
        print('[step]: calculating pos_tag features...')
        for index, row in df.iterrows():
            tags = {'search_term': pos_tag(row['search_term'].split()),
                    'main_title': pos_tag(row['main_title'].split()),
                    'title': pos_tag(row['title'].split())}
            # caution: takes a long time
            if ('noun_of_description' in features) or ('noun_match_description' in features):
                tags['description'] = pos_tag(row['description'].split())
            for feature in list(PostagFeatureFuncDict.keys()):
                if feature in features:
                    feature_func = PostagFeatureFuncDict[feature]
                    df.loc[index, feature] = feature_func(row, tags)
            row_new = df.ix[index]
            for feature in list(IdfPostagFeatureFuncDict.keys()):
                if feature in features:
                    feature_func = IdfPostagFeatureFuncDict[feature]
                    df.loc[index, feature] = feature_func(row_new, tags, idf_dicts)
            if index%300==0:
                print("[step]: " + str(index)+' rows calculated...')

    # compute W2v features
    if set(features) & set(W2vFeatureFuncDict.keys()):
        path_w2v_pretrained_model = './input/GoogleNews-vectors-negative300.bin'
        embedder = Word2Vec.load_word2vec_format(path_w2v_pretrained_model, binary=True)
        for feature in list(W2vFeatureFuncDict.keys()):
            if feature in features:
                print('calculating feature: '+feature+' ...')
                feature_func = W2vFeatureFuncDict[feature]
                df[feature] = df.apply(feature_func, axis=1, embedder=embedder)

    # iterate features in order (iterrows cannot update in time)
    if set(features) & set(StatFeatureFuncDict.keys()):
        print('[step]: calculating stat features...')
        tmpdf = pd.DataFrame({
            'list_query': df.apply(lambda row: list_common_word(row['title'], row['search_term']), axis=1),
            'list_title': df.apply(lambda row: list_common_word(row['search_term'], row['title']), axis=1),
            'list_description': df.apply(lambda row: list_common_word(row['search_term'], row['description']), axis=1),
            'len_of_query': df['len_of_query'],
            'len_of_title': df['len_of_title'],
            'len_of_description': df['len_of_description']
        })
        for feature in list(StatFeatureFuncDict.keys()):
            if feature in features:
                print('[step]: calculating feature: '+feature+' ...')
                feature_func = StatFeatureFuncDict[feature]
                df[feature] = tmpdf.apply(feature_func, axis=1)

    # compute CategoricalNumsizeFuncDict
    for feature in list(NumsizeFuncDict.keys()):
        if feature in features:
            print('[step]: calculating feature: '+feature+' ...')
            feature_func = NumsizeFuncDict[feature]
            df[feature] = df.apply(feature_func, axis=1)

    # iterate features in order, use apply() to update in time
    for feature in list(LastFeatureFuncDict.keys()):
        if feature in features:
            print('[step]: calculating feature: '+feature+' ...')
            feature_func = LastFeatureFuncDict[feature]
            df[feature] = df.apply(feature_func, axis=1)
    print("[step]: build feature done.")
    return df

chkr = SpellCheckGoogleOffline()
f_ed = open('%s/ed_clean_comment.txt' % project.project_path)
f_ed.readline()
line = f_ed.readline()
query_title_dic = {}
while line:
    if not line[0] == '#':
        terms = line.strip().split(',')
        key = terms[2][1:-1] + ',' +','.join(terms[3:])[1:-1]
        value = terms[0] + ',' + terms[1]
        query_title_dic[key] = value
    line = f_ed.readline()
f_ed.close() 
def search_term_clean(row):
    query = row['search_term']
    query = chkr.spell_correct(query)
    query = str_stem(query)
    query = query if str_is_meaningful(query) else ''
    query = str_remove_stopwords(query)

    ori_query = row['search_term']
    ori_title = row['product_title']
    key = ori_query + ',' + ori_title
    #print(key)
    if key in query_title_dic:
        value = query_title_dic[key]
        tmp_terms = value.split(',')
        query_item = tmp_terms[0]
        title_item = tmp_terms[1]
        query = query.replace(query_item,title_item)
        #print(query)
        #print(query_item + ' ' + title_item + ' ' + key)
    return query

def last_word_in_title(s, t):
    """
        How many times last word of s occurs in t
    """
    words = s.split()
    if len(words)==0:
        return 0
    return num_common_word(words[-1], t)

# Following features in dicts will be calculated from top to bottom

# Features of pure texts
TextFeatureFuncDict = OrderedDict([
    ('ori_stem_search_term', lambda row: str_stem(row['search_term'])),
    ('origin_search_term', lambda row: row['search_term']),
    ('typeid', lambda row: typeid_stem(typeid_extract(row['product_title']))),
    ('title', lambda row: str_stem(row['product_title'])),
    ('main_title', lambda row: str_stem(main_title_extract(row['product_title']))),
    ('search_term', lambda row: search_term_clean(row)),
    ('description', lambda row: str_stem(row['product_description'])),
    ('brand', lambda row: str_stem(row['brand'])),
    ('numsize_of_query', lambda row: " ".join(numsize_of_query(row['search_term'])).replace('  ',' ')),
    ('numsize_of_title', lambda row: " ".join(numsize_of_str(row['title'])).replace('  ',' ')),
    ('numsize_of_main_title', lambda row: " ".join(numsize_of_str(row['main_title'])).replace('  ',' ')),
    ('numsize_of_description', lambda row: " ".join(numsize_of_str(row['description'])).replace('  ',' ')),

    ('query_title_co_occur_11gram', lambda row: cooccur(row['ori_stem_search_term'], row['title'], 1, 1)),
    ('query_title_co_occur_22gram', lambda row: cooccur(row['ori_stem_search_term'], row['title'], 2, 2)),
    ('query_title_co_occur_12gram', lambda row: cooccur(row['ori_stem_search_term'], row['title'], 1, 2)),
    ('query_title_co_occur_21gram', lambda row: cooccur(row['ori_stem_search_term'], row['title'], 2, 1)),

    ('query_description_co_occur_11gram', lambda row: cooccur(row['ori_stem_search_term'], row['description'], 1, 1)),
    ('query_description_co_occur_22gram', lambda row: cooccur(row['ori_stem_search_term'], row['description'], 2, 2)),
    ('query_description_co_occur_12gram', lambda row: cooccur(row['ori_stem_search_term'], row['description'], 1, 2)),
    ('query_description_co_occur_21gram', lambda row: cooccur(row['ori_stem_search_term'], row['description'], 2, 1)),
])

# Features for matching words
MatchFeatureFuncDict = OrderedDict([
    ('ori_query_in_title', lambda row: num_whole_word(row['ori_stem_search_term'], row['title'])),
    ('query_in_main_title', lambda row: num_whole_word(row['search_term'], row['main_title'])),
    ('query_in_title', lambda row: num_whole_word(row['search_term'], row['title'])),
    ('query_in_description', lambda row: num_whole_word(row['search_term'], row['description'])),   
    ('query_last_word_in_main_title', lambda row: last_word_in_title(row['search_term'], row['main_title'])),
    ('query_last_word_in_title', lambda row: last_word_in_title(row['search_term'], row['title'])),
    ('query_last_word_in_description', lambda row: last_word_in_title(row['search_term'], row['description'])),
    ('word_in_main_title', lambda row: num_common_word(row['search_term'], row['main_title'])),
    ('word_in_main_title_weighted', lambda row: num_common_word(row['search_term'], row['main_title'], weighted=True)),
    ('word_in_main_title_exact', lambda row: num_common_word(row['search_term'], row['main_title'], exact_matching=True)),
    ('word_in_main_title_ordered', lambda row: num_common_word_ordered(row['search_term'], row['main_title'])),
    ('word_in_title', lambda row: num_common_word(row['search_term'], row['title'])),
    
    ('word_in_title_weighted', lambda row: num_common_word(row['search_term'], row['title'], weighted=True)),
    
    ('word_in_title_exact', lambda row: num_common_word(row['search_term'], row['title'], exact_matching=True)),
    ('word_in_title_ordered', lambda row: num_common_word_ordered(row['search_term'], row['title'])),
    ('ori_word_in_title_ordered', lambda row: num_common_word_ordered(row['ori_stem_search_term'], row['title'])),
    ('word_in_description', lambda row: num_common_word(row['search_term'], row['description'])),
    ('word_in_description_exact', lambda row: num_common_word(row['search_term'], row['description'], exact_matching=True)),
    ('word_in_brand', lambda row: num_common_word(row['search_term'], row['brand'])),
    ('word_in_typeid', lambda row: num_common_word(row['ori_stem_search_term'], row['typeid'], exact_matching=False)),

    ('bigram_in_title', lambda row: num_common_word(row['search_term'], row['title'], ngram=2)),
    ('bigram_in_main_title', lambda row: num_common_word(row['search_term'], row['main_title'], ngram=2)),
    ('bigram_in_description', lambda row: num_common_word(row['search_term'], row['description'], ngram=2)),
    ('bigram_in_brand', lambda row: num_common_word(row['search_term'], row['brand'], ngram=2)),

    ('search_term_fuzzy_match', lambda row: seg_words(row['search_term'], row['title'])),
    ('len_of_search_term_fuzzy_match', lambda row: words_of_str(row['search_term_fuzzy_match'])),

    ('word_with_er_count_in_query', lambda row: count_er_word_in_(row['search_term'])),
    ('word_with_er_count_in_title', lambda row: count_er_word_in_(row['title'])),
    ('first_er_in_query_occur_position_in_title', lambda row: find_er_position(row['search_term'], row['title'])),

    ('len_of_query', lambda row: words_of_str(row['search_term'])),
    ('len_of_main_title', lambda row: words_of_str(row['main_title'])),
    ('len_of_title', lambda row: words_of_str(row['title'])),
    ('len_of_description', lambda row: words_of_str(row['description'])),
    ('len_of_brand', lambda row: words_of_str(row['brand'])),
    ('chars_of_typeid', lambda row: len(row['typeid'])),
    ('chars_of_query', lambda row: len(row['search_term'])),

    ('ratio_main_title', lambda row :row['word_in_main_title'] / (row['len_of_query']+1.0)),
    ('ratio_main_title_exact', lambda row :row['word_in_main_title_exact'] / (row['len_of_query']+1.0)),
    ('ratio_main_title_ordered', lambda row :row['word_in_main_title_ordered'] / (row['len_of_query']+1.0)),
    ('ratio_title', lambda row :row['word_in_title'] / (row['len_of_query']+1.0)),
    ('ratio_title_exact', lambda row :row['word_in_title_exact'] / (row['len_of_query']+1.0)),
    ('ratio_title_ordered', lambda row :row['word_in_title_ordered'] / (row['len_of_query']+1.0)),
    ('ratio_ori_title_ordered', lambda row :row['ori_word_in_title_ordered'] / (row['len_of_query']+1.0)),
    ('ratio_description', lambda row :row['word_in_description'] / (row['len_of_query']+1.0)),
    ('ratio_description_exact', lambda row :row['word_in_description_exact'] / (row['len_of_query']+1.0)),
    ('ratio_brand', lambda row :row['word_in_brand'] / (row['len_of_query']+1.0)),
    ('ratio_typeid', lambda row :row['word_in_typeid'] / (row['len_of_query']+1.0)),

    ('ratio_bigram_title', lambda row: row['bigram_in_title'] / (row['len_of_query']+1.0)),
    ('ratio_bigram_main_title', lambda row: row['bigram_in_main_title'] / (row['len_of_query']+1.0)),
    ('ratio_bigram_description', lambda row: row['bigram_in_description'] / (row['len_of_query']+1.0)),
    ('ratio_bigram_brand', lambda row: row['bigram_in_brand'] / (row['len_of_query']+1.0)),


    # generated by generate_offline_features/title_query_BM25_and_description_query_BM25.py
    ('title_query_BM25', lambda row: row['title_query_BM25']),
    ('description_query_BM25', lambda row: row['description_query_BM25']),


    ('query_is_general', lambda row: row['query_is_general']),

    # basic distance features
    ('query_title_jaccard_1', lambda row: compute_dist(row['search_term'], row['title'], 'jaccard', 1)),
    ('query_title_dicedist_1', lambda row: compute_dist(row['search_term'], row['title'], 'dicedist', 1)),
    ('query_description_jaccard_1', lambda row: compute_dist(row['search_term'], row['description'], 'jaccard', 1)),
    ('query_description_dicedist_1', lambda row: compute_dist(row['search_term'], row['description'], 'dicedist', 1)),
    ('title_description_jaccard_1', lambda row: compute_dist(row['title'], row['description'], 'jaccard', 1)),
    ('title_description_dicedist_1', lambda row: compute_dist(row['title'], row['description'], 'dicedist', 1)),

    ('query_title_jaccard_2', lambda row: compute_dist(row['search_term'], row['title'], 'jaccard', 2)),
    ('query_title_dicedist_2', lambda row: compute_dist(row['search_term'], row['title'], 'dicedist', 2)),
    ('query_description_jaccard_2', lambda row: compute_dist(row['search_term'], row['description'], 'jaccard', 2)),
    ('query_description_dicedist_2', lambda row: compute_dist(row['search_term'], row['description'], 'dicedist', 2)),
    ('title_description_jaccard_2', lambda row: compute_dist(row['title'], row['description'], 'jaccard', 2)),
    ('title_description_dicedist_2', lambda row: compute_dist(row['title'], row['description'], 'dicedist', 2)),
])

# Features dependending on pos_tag dict
StatFeatureFuncDict = OrderedDict([
    ('min_of_QinT', lambda row: stat_list(row['list_title'], 'max') / (row['len_of_title']+1.0)),
    ('max_of_QinT', lambda row: stat_list(row['list_title'], 'min') / (row['len_of_title']+1.0)),
    ('median_of_QinT', lambda row: stat_list(row['list_title'], 'median') / (row['len_of_title']+1.0)),
    ('mean_of_QinT', lambda row: stat_list(row['list_title'], 'mean') / (row['len_of_title']+1.0)),
    ('std_of_QinT', lambda row: stat_list(row['list_title'], 'std') / (row['len_of_title']+1.0)),
    ('min_of_QinD', lambda row: stat_list(row['list_description'], 'max') / (row['len_of_description']+1.0)),
    ('max_of_QinD', lambda row: stat_list(row['list_description'], 'min') / (row['len_of_description']+1.0)),
    ('median_of_QinD', lambda row: stat_list(row['list_description'], 'median') / (row['len_of_description']+1.0)),
    ('mean_of_QinD', lambda row: stat_list(row['list_description'], 'mean') / (row['len_of_description']+1.0)),
    ('std_of_QinD', lambda row: stat_list(row['list_description'], 'std') / (row['len_of_description']+1.0)),
    ('min_of_QfromT', lambda row: stat_list(row['list_query'], 'min') / (row['len_of_query']+1.0)),
    ('max_of_QfromT', lambda row: stat_list(row['list_query'], 'max') / (row['len_of_query']+1.0)),
    ('median_of_QfromT', lambda row: stat_list(row['list_query'], 'median') / (row['len_of_query']+1.0)),
    ('mean_of_QfromT', lambda row: stat_list(row['list_query'], 'mean') / (row['len_of_query']+1.0)),
    ('std_of_QfromT', lambda row: stat_list(row['list_query'], 'std') / (row['len_of_query']+1.0)),
])

# Features dependending on pos_tag dict
PostagFeatureFuncDict = OrderedDict([
    ('noun_of_query', lambda row, tags: noun_of_str(tags['search_term'])),
    ('noun_of_title', lambda row, tags: noun_of_str(tags['title'])),
    ('noun_of_main_title', lambda row, tags: noun_of_str(tags['main_title'])),
    ('noun_of_description', lambda row, tags: noun_of_str(tags['description'])),
    ('noun_match_main_title', lambda row, tags: num_common_noun(row['search_term'], tags['main_title'])),
    ('noun_match_title', lambda row, tags: num_common_noun(row['search_term'], tags['title'])),
    ('noun_match_main_title_ordered', lambda row, tags: num_common_noun_ordered(row['search_term'], tags['main_title'])),
    ('noun_match_title_ordered', lambda row, tags: num_common_noun_ordered(row['search_term'], tags['title'])),
    ('noun_match_description', lambda row, tags: num_common_noun(row['search_term'], tags['description'])),
    ('match_last_noun_main', lambda row, tags: match_last_k_noun(row['search_term'], tags['main_title'], 1)),
    ('match_last_2_noun_main', lambda row, tags: match_last_k_noun(row['search_term'], tags['main_title'], 2)),
    ('match_last_3_noun_main', lambda row, tags: match_last_k_noun(row['search_term'], tags['main_title'], 3)),
    ('match_last_5_noun_main', lambda row, tags: match_last_k_noun(row['search_term'], tags['main_title'], 5)) # average nouns in main of all data: 5.3338
])

# categorical feature for numsize, 用来表征query和title,description的匹配情况的feature,是binary feature
NumsizeFuncDict = OrderedDict([
    ('numsize_count_in_main_title', lambda row: num_numsize_word(row['numsize_of_query'], row['main_title'])), #deprecated
    ('numsize_count_in_title', lambda row: num_numsize_word(row['numsize_of_query'], row['title'])), #deprecated
    ('numsize_count_in_description', lambda row: num_numsize_word(row['numsize_of_query'], row['description'])), #deprecated
    ('numsize_match_title', lambda row: num_common_word(row['search_term'], row['numsize_of_title'], exact_matching=False)),
    ('numsize_match_description', lambda row: num_common_word(row['search_term'], row['numsize_of_description'], exact_matching=False)),
    ('numsize_match_title_exact', lambda row: num_common_word(row['search_term'], row['numsize_of_title'], exact_matching=True)),
    ('numsize_match_description_exact', lambda row: num_common_word(row['search_term'], row['numsize_of_description'], exact_matching=True)),
    ('chars_of_numsize_query', lambda row: len(row['numsize_of_query'])),
    ('len_of_numsize_query', lambda row: words_of_str(row['numsize_of_query'])),
    ('len_of_numsize_main_title', lambda row: words_of_str(row['numsize_of_main_title'])),
    ('len_of_numsize_title', lambda row: words_of_str(row['numsize_of_title'])),
    ('len_of_numsize_description', lambda row: words_of_str(row['numsize_of_description'])),

    ('numsize_title_case1', lambda row: len(row['numsize_of_query'])==0 and len(row['numsize_of_title'])==0),
    ('numsize_title_case2', lambda row: len(row['numsize_of_query'])==0 and len(row['numsize_of_title'])>0),
    ('numsize_title_case3', lambda row: len(row['numsize_of_query'])>0 and len(row['numsize_of_title'])==0),
    ('numsize_title_case4', lambda row: len(row['numsize_of_query'])>0 and len(row['numsize_of_title'])>0 and len(set(row['numsize_of_query']) & set(row['numsize_of_title']))==0),
    ('numsize_title_case5', lambda row: len(row['numsize_of_query'])>0 and len(row['numsize_of_title'])>0 and len(set(row['numsize_of_query']) & set(row['numsize_of_title']))>0),
    ('numsize_description_case1', lambda row: len(row['numsize_of_query'])==0 and len(row['numsize_of_description'])==0),
    ('numsize_description_case2', lambda row: len(row['numsize_of_query'])==0 and len(row['numsize_of_description'])>0),
    ('numsize_description_case3', lambda row: len(row['numsize_of_query'])>0 and len(row['numsize_of_description'])==0),
    ('numsize_description_case4', lambda row: len(row['numsize_of_query'])>0 and len(row['numsize_of_description'])>0 and len(set(row['numsize_of_query']) & set(row['numsize_of_description']))==0),
    ('numsize_description_case5', lambda row: len(row['numsize_of_query'])>0 and len(row['numsize_of_description'])>0 and len(set(row['numsize_of_query']) & set(row['numsize_of_description']))>0),
])

# tfidf features
IdfFeatureFuncDict = OrderedDict([
    ('local_idf_of_title', lambda row, idf_dicts: idf_common_word(row['ori_stem_search_term'], row['title'], idf_dicts['search_term'])),
    ('local_idf_of_title_exact', lambda row, idf_dicts: idf_common_word(row['ori_stem_search_term'], row['title'], idf_dicts['search_term'], exact_matching=True)),
    ('local_idf_of_description', lambda row, idf_dicts: idf_common_word(row['ori_stem_search_term'], row['description'], idf_dicts['search_term'])),
    ('local_idf_of_brand', lambda row, idf_dicts: idf_common_word(row['ori_stem_search_term'], row['brand'], idf_dicts['search_term'])),
    ('idf_of_title', lambda row, idf_dicts: idf_common_word(row['search_term'], row['title'], idf_dicts['title'])),
    ('ori_idf_of_title', lambda row, idf_dicts: idf_common_word(row['ori_stem_search_term'], row['title'], idf_dicts['title'])),
    ('idf_of_title_exact', lambda row, idf_dicts: idf_common_word(row['ori_stem_search_term'], row['title'], idf_dicts['title'], exact_matching=True)),
    ('idf_of_description', lambda row, idf_dicts: idf_common_word(row['search_term'], row['description'], idf_dicts['description'])),
    ('idf_of_brand', lambda row, idf_dicts: idf_common_word(row['search_term'], row['brand'], idf_dicts['brand'])),
    ('composite_idf_of_title', lambda row, idf_dicts: idf_common_word(row['search_term'], row['title'], idf_dicts['composite'])),
    ('ori_composite_idf_of_title', lambda row, idf_dicts: idf_common_word(row['ori_stem_search_term'], row['title'], idf_dicts['composite'])),
    ('composite_idf_of_title_exact', lambda row, idf_dicts: idf_common_word(row['ori_stem_search_term'], row['title'], idf_dicts['composite'], exact_matching=True)),
    ('composite_idf_of_description', lambda row, idf_dicts: idf_common_word(row['search_term'], row['description'], idf_dicts['composite'])),
    ('composite_idf_of_brand', lambda row, idf_dicts: idf_common_word(row['search_term'], row['brand'], idf_dicts['composite'])),
])

# tfidf similarity features
IdfSimFeatureFuncDict = OrderedDict([
    ('idf_cos_sim_QT_origin', lambda row: compute_distance(row['origin_Q'], row['origin_T'])),
    ('idf_cos_sim_QT', lambda row: compute_distance(row['compo_Q'], row['compo_T'])),
    ('idf_cos_sim_QD', lambda row: compute_distance(row['compo_Q'], row['compo_D'])),
    ('idf_cos_sim_TD', lambda row: compute_distance(row['compo_T'], row['compo_D'])),
])

# tfidf-svd similarity & sne features
SvdSimFeatureFuncDict = OrderedDict([
    ('svd_cos_sim_QT_origin', lambda row: compute_distance([row['origin_Q']], [row['origin_T']])),
    ('svd_cos_sim_QT', lambda row: compute_distance([row['compo_Q']], [row['compo_T']])),
    ('svd_cos_sim_QD', lambda row: compute_distance([row['compo_Q']], [row['compo_D']])),
    ('svd_cos_sim_TD', lambda row: compute_distance([row['compo_T']], [row['compo_D']])),
])

RawSvdFeatureWeightDict = OrderedDict([
    ('raw_svd_Q', 1.0),
    ('raw_svd_T', 1.0),
    ('raw_svd_D', 1.0),
    ('raw_svd_B', 1.0),
])

tSNEFeatureSourceDict = OrderedDict([
    ('tSNE_indv_Q', 'indv_Q'),
    ('tSNE_indv_T', 'indv_T'),
    ('tSNE_indv_D', 'indv_D'),
    ('tSNE_compo_Q', 'compo_Q'),
    ('tSNE_compo_T', 'compo_T'),
    ('tSNE_compo_D', 'compo_D'),
])

GroupStatFeatureDict = OrderedDict([
    ('group_idf_cos_sim_T', lambda row, idx_dict, tfidf_mats, prefix: group_sim_list(row, idx_dict, tfidf_mats['compo_T'], prefix)),
    ('group_idf_cos_sim_D', lambda row, idx_dict, tfidf_mats, prefix: group_sim_list(row, idx_dict, tfidf_mats['compo_D'], prefix)),
])

WorldFeatureFuncDict = OrderedDict([
    ('query_id', lambda df: generate_qid(df['search_term'], total_train)),
])

# Idf - Pos_tag features, calculate after postag features!
IdfPostagFeatureFuncDict = OrderedDict([
    ('idf_of_title_noun', lambda row, tags, idf_dicts: idf_common_noun(row['search_term'], tags['title'], idf_dicts['composite'], row['noun_of_query'] + 1.0)),
    ('idf_of_main_title_noun', lambda row, tags, idf_dicts: idf_common_noun(row['search_term'], tags['main_title'], idf_dicts['composite'], row['noun_of_query'] + 1.0)),
    ('idf_of_description_noun', lambda row, tags, idf_dicts: idf_common_noun(row['search_term'], tags['description'], idf_dicts['composite'], row['noun_of_query'] + 1.0)),
    ('idf_max_noun_match_title', lambda row, tags, idf_dicts: idf_max_noun_match(row['search_term'], tags['title'], idf_dicts['composite'], 1)),
    ('idf_max_2_noun_match_title', lambda row, tags, idf_dicts: idf_max_noun_match(row['search_term'], tags['title'], idf_dicts['composite'], 2)),
    ('idf_max_3_noun_match_title', lambda row, tags, idf_dicts: idf_max_noun_match(row['search_term'], tags['title'], idf_dicts['composite'], 3)),
    ('idf_max_5_noun_match_title', lambda row, tags, idf_dicts: idf_max_noun_match(row['search_term'], tags['title'], idf_dicts['composite'], 5)),
])

W2vFeatureFuncDict = OrderedDict([
    ('w2v_query_title_avgmax_sim', lambda row, embedder: w2v_avgmax_similarity(row['search_term'], row['title'], embedder)),
    ('w2v_query_title_avgmin_dist', lambda row, embedder: w2v_avgmin_dist(row['search_term'], row['title'], embedder)),
])

# Statistical Features
LastFeatureFuncDict = OrderedDict([
    ('ratio_noun_match_title', lambda row: row['noun_match_title'] / (row['noun_of_query']+1)),
    ('ratio_noun_match_main_title', lambda row: row['noun_match_main_title'] / (row['noun_of_query']+1)),

    ('ratio_noun_match_title_ordered', lambda row: row['noun_match_title_ordered'] / (row['noun_of_query']+1)),
    ('ratio_noun_match_main_title_ordered', lambda row: row['noun_match_main_title_ordered'] / (row['noun_of_query']+1)),
    ('ratio_noun_match_description', lambda row: row['noun_match_description'] / (row['noun_of_query']+1)),

    ('ratio_numsize_main_title', lambda row :row['numsize_word_in_main_title'] / (row['len_of_numsize_query']+1)),
    ('ratio_numsize_title', lambda row :row['numsize_word_in_title'] / (row['len_of_numsize_query']+1)),
    ('ratio_numsize_description', lambda row :row['numsize_word_in_description'] / (row['len_of_numsize_query']+1)),
    ('ratio_numsize_match_title', lambda row :row['numsize_match_title'] / (row['len_of_numsize_query']+1)),
    ('ratio_numsize_match_description', lambda row :row['numsize_match_description'] / (row['len_of_numsize_query']+1)),
    ('ratio_numsize_match_title_exact', lambda row :row['numsize_match_title_exact'] / (row['len_of_numsize_query']+1)),
    ('ratio_numsize_match_description_exact', lambda row :row['numsize_match_description_exact'] / (row['len_of_numsize_query']+1)),
])


CooccurFeatureFuncDict = OrderedDict([
    ('q_t_11gram', lambda df: tfidf_tsvd_cooccur(df['query_title_co_occur_11gram'])),
    ('q_t_22gram', lambda df: tfidf_tsvd_cooccur(df['query_title_co_occur_22gram'])),
    ('q_t_12gram', lambda df: tfidf_tsvd_cooccur(df['query_title_co_occur_12gram'])),
    ('q_t_21gram', lambda df: tfidf_tsvd_cooccur(df['query_title_co_occur_21gram'])),

    ('q_d_11gram', lambda df: tfidf_tsvd_cooccur(df['query_description_co_occur_11gram'])),
    ('q_d_22gram', lambda df: tfidf_tsvd_cooccur(df['query_description_co_occur_22gram'])),
    ('q_d_12gram', lambda df: tfidf_tsvd_cooccur(df['query_description_co_occur_12gram'])),
    ('q_d_21gram', lambda df: tfidf_tsvd_cooccur(df['query_description_co_occur_21gram'])),
    
])


if __name__=='__main__':
    import doctest
    doctest.testmod()
