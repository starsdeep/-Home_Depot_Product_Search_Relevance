#[Home Depot Product Search Relevance](https://www.kaggle.com/c/home-depot-product-search-relevance) on Kaggle


## 组织形式与目标

### 目标

参加比赛获得好名次是我们共同的目标，但是我更希望的是能在比赛的过程中，真正学到有用的知识。参加这个比赛的现在已经有6个人了，每个人都有自己的分工，或者是收集资料，查看bad case，编写代码，如果每个人能把自己在完成工作的时候遇到的好的资料或者任何有收获的点分享出来，每一个人就相当于做了6份工作，对大家都是一个很好的事情。


### 文档管理
* 关于sklearn pipeline的使用， [这里有一篇很好的文章](http://zacstewart.com/2014/08/05/pipelines-of-featureunions-of-pipelines.html)

#### Idea

我们在完成自己任务的过程中，可能突然会冒出很多想法，这些都值得记录下来。每个人看到一个idea觉得make sense, 值得一试，就可以主动的去把这个idea实现,准备实现的时候，在idea那栏里，做个简单的说明，比如“正在实现--廖翊康”，这样大家就不会做到重复的工作。

#### 实验结果
每当测试完一组算法或者feature,希望大家把结果都记录到**实验结果**


#### bad case
在跑实验的时候，查看bad case 是一个很重要的过程，关于bad case的分析，就记录到 **bad case**一栏。

#### 知识分享

祝博，王博可能会看一下这方面的论文，论文的总结可以放到doc文件夹下。其他人比赛的过程中的遇到的任何值得分享的收获也可以放上来。


## 环境配置


 
### program environment

* python 3.5
* python library:

    in the requirements.txt
    to install it using : `pip3.5 install -r requirements.txt`
    
* nltk: you need download nltk models **punkt**,

    
### how to run
1. put files into input folder including:attributes.csv,product_descriptions.csv 
2. run `python3.5 framework.py 1000 ./output/rfr_all`, 1000 means take 1000 instances as train data, you can change it to another number, and -1 means take all instances (may take 20 minutes)



## Idea

chenqiang


* stem with pos tag using nltk.stem.wordnet.WordNetLemmatizer. [done, chenqinag]
* train three classification model to predict 1,2 and 3, output average score of these three as result. [done chenqiang, not recommended, liaoyikang]
* 加特征, title中时否有几个er结尾的单词，query是否有er结尾的单词，query中第一个er结尾的单词出现在title中那些er结尾单词列表的第几个，如果没有出现则为-1 [done, chenqiang]
* 加特征, 加query和title,description,BM25相似度 [chen qiang done]

fenixlin

* train 13 xgboost classifier to classify 'y>12? y>11? ...' 13 times, predict with probablity sum [not planned yet]
* introduce stop words and some rules to cut search query. [done, fenixlin]
* use stanford parser to do semantic analysis and build more features [doing, fenixlin]
* use google service to check and fix spelling of search query, see scripts in forum [ not planned yet]


liaoyikang

* 改进feature 计算过程 缩短每次流程运行的时间[doing, liaoyikang]
* 使用"桶"，将连续值离散化，测试效果[doing, liaoyikang]
* 增加2-gram的feature，见bad case 4
* 增加feature，是否是连续匹配。比如hot dog，虽然是匹配但不是连续匹配. 见bad case 4
* 增加feature, 统计词性匹配，有一些形容词匹配，但主题匹配的并没有用，比如query 是 doubl side stapl， title是Double-Sided Organizer，或者见bad case 3.






## Bad case 分析

* query是树，product是修理树的工具, query是mower，product是mower的布
* query是电池，product是一个工具，同时title中有说不含电池


###典型bad case

|编号| query | title |原因|改进方法
|---|---|---|---|---|
| 1 |Ryobi ONE+ 18 in. 18-Volt Lithium-Ion Cordless Hedge Trimmer - Battery and Charger Not Included|18volt. batteri charger|主语不一样，反义处理 not included 处理|反义词处理|
|2|topiari tree|Romano 4 ft. Boxwood Spiral Topiary Tree|query是简单的词，title确是一个很详细的东西，所以应该是一般性匹配|增加query len / title/len|
|3|bronz green|Green Matters 3-Light Mahogany Bronze Vanity Fixture|主题词不匹配，green 形容词匹配，没啥用||
|4|hot dog|HealthSmart Digger Dog Reusable Hot and Cold Pack||







## 实验结果记录

| submit date | name | offline |          | online  |   compare  |feature                  | model                   | other trick                                   | comments |
| ---------- |-------- | --------|---------|---------|------------|-------------------------|-------------------------|-----------------------------------------------|----------|
| 2016-03-03  | chenqiang | 0.47447 |  0       | 0.47571 |    0       |  query_in_title etc     | RandomForestRegressor   | remove stop words                             | base line|
| 2016-03-11  | chenqiang | 0.47477 |  +0.0003 | 0.47587 |   +.00016  |  query_in_title etc     | RandomForestRegressor   | add binary to True in TfidfVectorizer         |          |
| 2016-03-12  | chenqiang | 0.47335 |  -.00112 | 0.47566 |   -.00005  |                         |                         | {'rfr__max_features': 5, 'rfr__max_depth': 30}|          |
| unsubmitted | fenixlin  | 0.49002 |          |          |            |                         | XGBoost Regressor      |                                               |          |
| unsubmitted | fenixlin  | 4.83365 |          |          |            |                         | RandomForestClassifier | classify once with independent labels(1~13)   |          |
| 2016-03-16  | chenqiang | 0.47284 |  -.00163 |  0.47566 |   -.00005  |  fixed bug replacing query_in_description with query_in_title | RandomForestRegressor | stem with pos tag using nltk.stem.wordnet.WordNetLemmatizer|
| 2016-03-17  | chenqiang | 0.47083 |  -.00364 |  0.47824 |   +.00253  |  {'rfr__max_features': 7, 'rfr__max_depth': 50}  加入特征，, "title_query_BM25", "description_query_BM25"|  RandomForestRegressor|                |          |
| 2016-03-17  | chenqiang | 0.47046 |  -.00401 |  0.47677 |   +.00106  |  {'rfr__max_features': 5, 'rfr__max_depth': 50}  加入特征，, er        |  RandomForestRegressor|                |          |
| 2016-03-18  | fenixlin  | 0.47249 |  -.00198 |  0.47484 |   -.00087  |  rfr_all{5,30}+删除无主体的搜索词  　  |  RandomForestRegressor|                |          |
| 2016-03-19  | chenqiang | 0.6, 0.6, 0.6|     |  0.50780 |   +.3209   | BM25, no er, get optimised depth and features|  train three classification model |   |                 |
| 2016-03-19  | liaoyikang |0.47265|     |   |      | add search_term_clean 做了拼写纠错好去除stopwords| rfr |   |                 |

