#encoding=utf8
import numpy as np
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

total_train = 74067
total_test = 166693

feature_path = './output/features/'

def load_feature(features):
    """
    read features from existing files, and then concat those features into a big frame using pd.concat,
    concat a list of frames can improve efficiency see http://pandas.pydata.org/pandas-docs/stable/merging.html
    for more info.
    :param features: features to load
    :return: df contains the features
    """
    frames = []
    files = [os.path.join(feature_path, feature + '.csv') for feature in features]
    frames = [pd.read_csv(file, encoding="ISO-8859-1", index_col=0) for file in files]
    df = pd.concat(frames, axis=1)

    # read_csv() fills empty string with nan, which will cause a problem in build_feature, so we need to replace nan to '', see https://github.com/pydata/pandas/issues/10205 for detail
    df.fillna('', inplace=True)
    return df

def write_feature(df, features):
    for feature in features:
        tmp_df = df[[feature]]
        tmp_df.to_csv(os.path.join(feature_path, feature + '.csv'), encoding="utf8")
    return

def get_feature(config):
    all_exist_features = set([os.path.splitext(f)[0] for f in os.listdir(feature_path) if os.path.isfile(os.path.join(feature_path,f)) and f.endswith('.csv')])
    total_features = set(config['features'])
    exist_features = total_features & all_exist_features
    recompute_features = set(config['recompute_features']) if 'recompute_features' in config else set()
    new_features = total_features - exist_features

    to_load_features = exist_features - recompute_features
    to_compute_features = recompute_features | new_features

    df_basic, num_train, num_test = load_data(config['num_train'])
    print("feature already exists, loading: \n" + ' '.join(to_load_features))
    if to_load_features:
        df_all = load_feature(to_load_features)
        print("length of loaded datafame %d" % df_all.shape[0])
        df_train = df_all[:num_train]
        df_test = df_all[-num_test:]
        df = pd.concat((df_train, df_test), axis=0, ignore_index=True)
        print("length of datafame after trimed with num_train %d" % df.shape[0])
        for column in df_basic.columns.values:
            if column not in df:
                df[column] = df_basic[column].copy()
    else:
        df = df_basic
    print("loading done")
    print("start computing feature: " + ' '.join(to_compute_features))
    df = build_feature(df, to_compute_features)
    write_feature(df, to_compute_features)
    return df[:num_train], df[num_train:]

def build_feature(df, features):
    # iterate features in order, use apply() to update in time
    if not features:
        return df

    for feature in list(TextFeatureFuncDict.keys()):
        if feature in features:
            print('calculating feature: '+feature+' ...')
            feature_func = TextFeatureFuncDict[feature]
            df[feature] = df.apply(feature_func, axis=1)

    for feature in list(MatchFeatureFuncDict.keys()):
        if feature in features:
            print('calculating feature: '+feature+' ...')
            feature_func = MatchFeatureFuncDict[feature]
            df[feature] = df.apply(feature_func, axis=1)

    # compute idf features
    idf_dicts = dict()
    if set(features) & set(IdfFeatureFuncDict.keys()):
        # prepare idf_dicts, idf_dicts contains idf value for a given word
        search_terms = df['search_term'].unique()
        unique_prd = df.drop_duplicates(subset='product_uid')
        idf_dicts['search_term'] = compute_idf_dict(search_terms) # idf value from search_terms
        idf_dicts['title'] = compute_idf_dict(unique_prd['title']) # idf value from title
        idf_dicts['description'] = compute_idf_dict(unique_prd['description']) # idf value from description
        idf_dicts['brand'] = compute_idf_dict(unique_prd['brand']) # idf value from brand
        idf_dicts['composite'] = compute_idf_dict(unique_prd['description'] + ' ' + unique_prd['title'] + ' ' + unique_prd['brand']) # idf value from the those 4 fields

        for feature in list(IdfFeatureFuncDict.keys()):
            if feature in features:
                print('calculating feature: '+feature+' ...')
                feature_func = IdfFeatureFuncDict[feature]
                df[feature] = df.apply(feature_func, axis=1, idf_dicts=idf_dicts)

    # iterate features in order (iterrows cannot update in time)
    if set(features) & set(PostagFeatureFuncDict.keys()):
        print('calculating pos_tag features...')
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
                print(str(index)+' rows calculated...')

    # iterate features in order (iterrows cannot update in time)
    if set(features) & set(StatFeatureFuncDict.keys()):
        print('calculating stat features...')
        lists = {
            'list_title': df.apply(lambda row: list_common_word(row['search_term'], row['title']), axis=1),
            'list_description': df.apply(lambda row: list_common_word(row['search_term'], row['description']), axis=1),
            'len_of_title': df['len_of_title'],
            'len_of_description': df['len_of_description']
        }
        tmpdf = pd.DataFrame(lists)
        for feature in list(StatFeatureFuncDict.keys()):
            if feature in features:
                print('calculating feature: '+feature+' ...')
                feature_func = StatFeatureFuncDict[feature]
                df[feature] = tmpdf.apply(feature_func, axis=1)

    # compute CategoricalNumsizeFuncDict
    for feature in list(NumsizeFuncDict.keys()):
        if feature in features:
            print('calculating feature: '+feature+' ...')
            feature_func = NumsizeFuncDict[feature]
            df[feature] = df.apply(feature_func, axis=1)

    # iterate features in order, use apply() to update in time
    for feature in list(LastFeatureFuncDict.keys()):
        if feature in features:
            print('calculating feature: '+feature+' ...')
            feature_func = LastFeatureFuncDict[feature]
            df[feature] = df.apply(feature_func, axis=1)
    return df

chkr = SpellCheckGoogleOffline()
def search_term_clean(query):
    query = chkr.spell_correct(query)
    query = str_stem(query)
    query = query if str_is_meaningful(query) else ''
    query = str_remove_stopwords(query)
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
    ('search_term', lambda row: search_term_clean(row['search_term'])),
    ('description', lambda row: str_stem(row['product_description'])),
    ('brand', lambda row: str_stem(row['brand'])),
    ('numsize_of_query', lambda row: " ".join(numsize_of_query(row['search_term'])).replace('  ',' ')),
    ('numsize_of_title', lambda row: " ".join(numsize_of_str(row['title'])).replace('  ',' ')),
    ('numsize_of_main_title', lambda row: " ".join(numsize_of_str(row['main_title'])).replace('  ',' ')),
    ('numsize_of_description', lambda row: " ".join(numsize_of_str(row['description'])).replace('  ',' ')),
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
    ('ori_word_in_title_ordered', lambda row: num_common_word_ordered(row['ori_stem_search_term'], row['title'])),
    ('word_in_title_ordered', lambda row: num_common_word_ordered(row['search_term'], row['title'])),
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
    ('ratio_title', lambda row :row['word_in_title'] / (row['len_of_query']+1.0)),
    ('ratio_main_title_exact', lambda row :row['word_in_main_title_exact'] / (row['len_of_query']+1.0)),
    ('ratio_title_exact', lambda row :row['word_in_title_exact'] / (row['len_of_query']+1.0)),
    ('ratio_main_title_ordered', lambda row :row['word_in_main_title_ordered'] / (row['len_of_query']+1.0)),
    ('ratio_title_ordered', lambda row :row['word_in_title_ordered'] / (row['len_of_query']+1.0)),
    ('ratio_description', lambda row :row['word_in_description'] / (row['len_of_query']+1.0)),
    ('ratio_description_exact', lambda row :row['word_in_description_exact'] / (row['len_of_query']+1.0)),
    ('ratio_brand', lambda row :row['word_in_brand'] / (row['len_of_query']+1.0)),

    ('ratio_bigram_title', lambda row: row['bigram_in_title'] / (row['len_of_query']+1.0)),
    ('ratio_bigram_main_title', lambda row: row['bigram_in_main_title'] / (row['len_of_query']+1.0)),
    ('ratio_bigram_description', lambda row: row['bigram_in_description'] / (row['len_of_query']+1.0)),
    ('ratio_bigram_brand', lambda row: row['bigram_in_brand'] / (row['len_of_query']+1.0)),


    # generated by generate_offline_features/title_query_BM25_and_description_query_BM25.py
    ('title_query_BM25', lambda row: row['title_query_BM25']),
    ('description_query_BM25', lambda row: row['description_query_BM25']),


    ('query_is_general', lambda row: row['query_is_general']),
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

# idf feature
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

if __name__=='__main__':
    import doctest
    doctest.testmod()
