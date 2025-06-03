"""
update:2025/3/24
author:Nick_Ni
"""

import pandas as pd 
import numpy as np
from scipy import stats
import statsmodels.api as sm
from tqdm import *
import os
from joblib import Parallel, delayed
import pickle

from rqdatac import *

init()
import rqdatac
# rqfactor 其他算子
from rqfactor import *
from rqfactor.extension import *
from rqfactor import Factor, REF, MA, SUM, CS_ZSCORE,STD,PCT_CHANGE,CORR,DELTA,MAX,MIN
from rqfactor.extension import UserDefinedLeafFactor

# 文件输出
import pickle


import seaborn as sns
import matplotlib.pyplot as plt

# 关闭通知
import warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger().setLevel(logging.ERROR)




# plt.style.use('default')
# plt.rcParams['figure.facecolor'] = 'white'
# plt.rcParams['font.sans-serif']=['SimHei']
# plt.rcParams['axes.unicode_minus']=False


def create_dir_not_exist(path):
    # 若不存在该路径则自动生成
    if not os.path.exists(path):
        os.makedirs(path)
    else:
        pass


# 动态券池
def INDEX_FIX(start_date,end_date,index_item):
    """
    :param start_date: 开始日 -> str
    :param end_date: 结束日 -> str 
    :param index_item: 指数代码 -> str 
    :return index_fix: 动态因子值 -> df_unstack
    """
    
    index = pd.DataFrame(dict([(k, pd.Series(v)) for k, v in index_components(index_item,start_date=start_date,end_date=end_date).items()])).T

    # 构建动态股票池 
    index_fix = index.unstack().reset_index().iloc[:,-2:]
    index_fix.columns = ['date','stock']
    index_fix.date = pd.to_datetime(index_fix.date)
    index_fix['level'] = True
    index_fix.dropna(inplace = True)
    index_fix = index_fix.set_index(['date','stock']).level.unstack()
    index_fix.fillna(False,inplace = True)

    # stock_list = index_fix.columns.tolist()
    # datetime_period = index_fix.index.tolist()

    return index_fix

# 1 券池过滤函数 ------------------------------------------------------------------------

# 1.1 新股过滤（新股财报完整性确实，没有完整的4个财报季）
def get_new_stock_filter(stock_list,datetime_period, newly_listed_threshold = 252):
    
    # 多添加一天
    datetime_period_tmp = datetime_period.copy()
    datetime_period_tmp += [pd.to_datetime(get_next_trading_date(datetime_period[-1],1))]
    # 获取上市日期
    listed_datetime_period = [rqdatac.instruments(stock).listed_date for stock in stock_list] 
    # 获取上市后的第252个交易日（新股和老股的分界点）
    newly_listed_window = pd.Series(index=stock_list, 
                                    data=[pd.to_datetime(rqdatac.get_next_trading_date(listed_date, n=newly_listed_threshold)) for listed_date in listed_datetime_period]) 
    # 防止分割日在研究日之后，后续填充不存在
    for k,v in enumerate(newly_listed_window):
        if v > datetime_period_tmp[-1]:
            newly_listed_window.iloc[k] = datetime_period_tmp[-1]

    # 标签新股，构建过滤表格
    newly_listed_window.index.names = ['order_book_id']
    newly_listed_window = newly_listed_window.to_frame('date')
    newly_listed_window['signal'] = True
    newly_listed_window = newly_listed_window.reset_index().set_index(['date','order_book_id']).signal.unstack('order_book_id').reindex(index=datetime_period_tmp)
    newly_listed_window = newly_listed_window.shift(-1).bfill().fillna(False).iloc[:-1]

    return newly_listed_window

# 1.2 st过滤（风险警示标的默认不进行研究）
def get_st_filter(stock_list,datetime_period):
    # 当st时返回1，非st时返回0
    st_filter = rqdatac.is_st_stock(stock_list,datetime_period[0],datetime_period[-1]).reindex(columns=stock_list,index = datetime_period)
    st_filter = st_filter.shift(-1).ffill()

    return st_filter

# 1.3 停牌过滤 （无法交易）
def get_suspended_filter(stock_list,datetime_period):
    # 当停牌时返回1，非停牌时返回0
    suspended_filter = rqdatac.is_suspended(stock_list,datetime_period[0],datetime_period[-1]).reindex(columns=stock_list,index=datetime_period)
    suspended_filter = suspended_filter.shift(-1).ffill()

    return suspended_filter

# 1.4 涨停过滤 （开盘无法买入）
def get_limit_up_filter(stock_list,datetime_period):
    # 涨停时返回为1,非涨停返回为0    
    price = rqdatac.get_price(stock_list,datetime_period[0],datetime_period[-1],adjust_type='none',fields = ['open','limit_up'])
    df = (price['open'] == price['limit_up']).unstack('order_book_id').shift(-1).fillna(False)

    return df

# 2 数据清洗函数 -----------------------------------------------------------

# 2.1 MAD:中位数去极值
def mad(df,n=3 * 1.4826):
    # MAD:中位数去极值
    def filter_extreme_MAD(series,n): 
        median = series.median()
        new_median = ((series - median).abs()).median()
        return series.clip(median - n*new_median,median + n*new_median)
    # 离群值处理
    df = df.apply(lambda x :filter_extreme_MAD(x,n), axis=1)

    return df

# 2.2 标准化（去量纲）
def standardize(df):
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1), axis=0)

# 2.3 行业市值中性化
def neutralization(df,order_book_ids,index_item = '',industry_type = 'zx'):

    """
    :param df: 因子值 -> df_unstack
    :param order_book_ids: 股票队列 -> list
    :param index_item: 指数名称 -> str
    :return df_result: 残差因资质 -> df_unstack
    """

    datetime_period = df.index.tolist()
    start = datetime_period[0].strftime("%F")
    end = datetime_period[-1].strftime("%F")
    #获取行业/市值暴露度
    try:
        # 获取存储数据
        df_industry_market = pd.read_pickle(f'tmp/df_industry_market_{industry_type}_{index_item}_{start}_{end}.pkl')
    except:
        # 获取市值暴露度
        market_cap = execute_factor(LOG(Factor('market_cap_3')),order_book_ids,start,end).stack().to_frame('market_cap')
        # 获取行业暴露度
        industry_df = pd.get_dummies(get_industry_exposure(order_book_ids,
                                                           datetime_period,
                                                           industry_type))
        # 合并市值行业暴露度
        industry_df['market_cap'] = market_cap
        df_industry_market = industry_df
        df_industry_market.index.names = ['datetime','order_book_id']
        df_industry_market.dropna(inplace = True)
        create_dir_not_exist('tmp')
        df_industry_market.to_pickle(f'tmp/df_industry_market_{industry_type}_{index_item}_{start}_{end}.pkl')

    df_industry_market['factor'] = df.stack()
    df_industry_market.dropna(subset = 'factor',inplace = True)
    
    # OLS回归取残差 剥离行业市值风格的影响（残差 -> 新因子）

    # 方法一：普通 ==================

    # df_result = pd.DataFrame(columns = order_book_ids,index = datetime_period)
    # for i in tqdm(datetime_period):
    #     try:
    #         df_day = df_industry_market.loc[i]
    #         x = df_day.iloc[:,:-1]   # 市值/行业
    #         y = df_day.iloc[:,-1]    # 因子值
    #         df_result.loc[i] = sm.OLS(y.astype(float),x.astype(float),hasconst=False, missing='drop').fit().resid   # 回顾计算残差
    #     except:
    #         pass
    
    # 方法二: 多线程 ==================

    def get_ols_mult(df_industry_market,i):
        try:
            df_day = df_industry_market.loc[i]
            x = df_day.iloc[:,:-1]   # 市值/行业
            y = df_day.iloc[:,-1]    # 因子值
            resid = sm.OLS(y.astype(float),x.astype(float),hasconst=False, missing='drop').fit().resid
        except:
            resid = np.array([np.nan])
        return resid

    df_result = Parallel(n_jobs=2)(delayed(get_ols_mult)(df_industry_market,i) for i in datetime_period)
    df_result = pd.DataFrame(df_result,index = datetime_period).sort_index(axis = 1)

    df_result = df_result.dropna(how = 'all',axis = 1)                 # 删除整列为空
    df_result.index.names = ['datetime']

    return df_result


# 2.3.1 获取行业暴露度矩阵
def get_industry_exposure(order_book_ids,datetime_period,industry_type = 'zx'):
    
    """
    :param order_book_ids: 股票池 -> list
    :param datetime_period: 研究日 -> list
    :param industry_type: 行业分类标准 二选一 中信/申万 zx/sw -> str
    :return result: 虚拟变量 -> df_unstack
    """

    if industry_type not in ['zx','sw']:
        return print("select on from ['zx','sw']")
    
    # 获取行业特征数据
    if industry_type == 'zx':
        industry_map_dict = rqdatac.client.get_client().execute('__internal__zx2019_industry')
        # 构建个股/行业map
        df = pd.DataFrame(industry_map_dict, columns=["first_industry_name", "order_book_id", "start_date"])
        df.sort_values(["order_book_id", "start_date"], ascending=True, inplace=True)
        df = df.pivot(index="start_date", columns="order_book_id", values="first_industry_name").ffill()
    else:
        industry_map_dict = rqdatac.client.get_client().execute('__internal__shenwan_industry')
        df = pd.DataFrame(industry_map_dict, columns=["index_name", "order_book_id",'version', "start_date"])
        df = df[df.version == 2]
        df = df.drop_duplicates()
        df = df.set_index(['start_date','order_book_id']).index_name.unstack('order_book_id').ffill()

    # 匹配交易日
    datetime_period_base = pd.to_datetime(get_trading_dates(get_previous_trading_date(df.index[0],2),df.index[-1]))
    df.index = datetime_period_base.take(datetime_period_base.searchsorted(df.index, side='right') - 1)
    # 切片所需日期
    df = df.reset_index().drop_duplicates(subset = ['index']).set_index('index')
    df = df.reindex(index = datetime_period_base).ffill().reindex(index = datetime_period).ffill()
    inter_stock_list = list(set(df.columns) & set(order_book_ids))
    df = df[inter_stock_list].sort_index(axis = 1)
    
    #生成行业虚拟变量
    return df.stack()


# 2.4 因子清洗
def data_clean(df,index_fix,index_item = '',industry_type = 'zx'):
    """
    :param df: 因子值 -> df_unstack
    :param index_fix: 动态券池 -> df_unstack
    :param index_item: 指数代码 -> str
    :param industry_type: 行业分类标准 二选一 中信/申万 zx/sw -> str
    :return df: 清洗后因子值 -> df_unstack
    """
    stock_list = index_fix.columns.tolist()
    start_date = index_fix.index[0].strftime('%F')
    end_date = index_fix.index[-1].strftime('%F')
    datetime_period = index_fix.index.tolist()
    try:
        combo_mask = pd.read_pickle(f'tmp/combo_mask_{index_item}_{start_date}_{end_date}.pkl')
    except:
        # 新股过滤
        new_stock_filter = get_new_stock_filter(stock_list,datetime_period)
        # st过滤
        st_filter = get_st_filter(stock_list,datetime_period)
        # 停牌过滤
        suspended_filter = get_suspended_filter(stock_list,datetime_period)

        combo_mask = (new_stock_filter.astype(int) 
                    + st_filter.astype(int)
                    + suspended_filter.astype(int)
                    + (~index_fix).astype(int)) == 0

        create_dir_not_exist('tmp')
        combo_mask.to_pickle(f'tmp/combo_mask_{index_item}_{start_date}_{end_date}.pkl')
    
    df = df.mask(~combo_mask).dropna(how = 'all',axis = 1)
    # 离群值 标准化 中性化 标准化
    df = standardize(neutralization(standardize(mad(df)),stock_list,index_item,industry_type))
    df = df.apply(lambda x: x.astype(float))

    try:
        limit_up_filter = pd.read_pickle(f'tmp/limit_up_filter_{index_item}_{start_date}_{end_date}.pkl')
    except:
        # 涨停过滤
        limit_up_filter = get_limit_up_filter(stock_list,datetime_period)
        limit_up_filter.to_pickle(f'tmp/limit_up_filter_{index_item}_{start_date}_{end_date}.pkl')
    
    df = df.mask(limit_up_filter)
    
    return df

# 3 单因子检测函数 -----------------------------------------------------------

# 3.1 IC计算  
def Quick_Factor_Return_N_IC(df,n,index_item,name = '',Rank_IC = True):

    """
    :param df: 因子值 -> df_unstack
    :param n: 调仓日 -> int
    :param index_item: 券池 -> str
    :param name: 因子名称 -> str
    :param True/False: Rank_ic/Normal_ic -> bool
    :return result: ic序列 -> series
    :return report: ic报告 -> dataframe
    """
    # 基础数据获取
    order_book_ids = df.columns.tolist()
    datetime_period = df.index
    start = datetime_period.min().strftime('%F')
    end = datetime_period.max().strftime('%F')
    
    # 提取预存储数据
    try:
        # 开盘价
        open = pd.read_pickle(f'tmp/open_{index_item}_{start}_{end}.pkl')
    except:
        # 新建预存储文档
        create_dir_not_exist('tmp')
        # 拿一个完整的券池表格，防止有些股票在某些日期没有数据，导致缓存数据不全，影响其他因子计算
        index_fix = INDEX_FIX(start,end,index_item)
        order_book_ids = index_fix.columns.tolist()
        datetime_period = index_fix.index.tolist()
        # 获取开盘价
        open = get_price(order_book_ids, start_date = start, end_date = end,frequency='1d',fields='open').open.unstack('order_book_id')
        # 存储
        open.to_pickle(f'tmp/open_{index_item}_{start}_{end}.pkl')

    
    # 未来一段收益股票的累计收益率计算
    return_n = open.pct_change(n).shift(- n - 1)

    # 计算IC
    if Rank_IC == True:
        result = df.corrwith(return_n,axis = 1,method='spearman').dropna(how = 'all')
    else:
        result = df.corrwith(return_n,axis = 1,method='pearson').dropna(how = 'all')
    
    # t检验 单样本
    t_stat,_ = stats.ttest_1samp(result, 0)
    
    # 因子报告
    report = {'name': name,
    'IC mean':round(result.mean(),4),
    'IC std':round(result.std(),4),
    'IR':round(result.mean()/result.std(),4),
    'IC>0':round(len(result[result>0].dropna())/len(result),4),
    'ABS_IC>2%':round(len(result[abs(result) > 0.02].dropna())/len(result),4),
    't_stat':round(t_stat,4),
    }
    
    # 打印报告
    print(report)
    report = pd.DataFrame([report])
    
    return result,report


# 3.2 因子收益率检验
# 多进程
def factor_ret_tvalue(df,n,index_item,name = '',industry_type = 'zx'):

    """
    :param df: 因子值 -> unstack
    :param n: 调仓日 -> int
    :param index_item: 券池 -> str
    :param name: 因子名称 -> str
    :return result: tvalue值 -> dataframe
    :return report: tvalue报告 -> dataframe
    """

    # 基础数据获取
    datetime_period = df.index
    start = datetime_period.min().strftime('%F')
    end = datetime_period.max().strftime('%F')

    # 提取预存储数据
    try:
        # 开盘价
        open = pd.read_pickle(f'tmp/open_{index_item}_{start}_{end}.pkl')
        # 行业市值
        df_industry_market = pd.read_pickle(f'tmp/df_industry_market_{industry_type}_{index_item}_{start}_{end}.pkl')
        # 异方差权重 流通市值根
        mc2_sqrt = pd.read_pickle(f'tmp/mc2_sqrt_{index_item}_{start}_{end}.pkl')
    except:
        # 新建预存储文档
        create_dir_not_exist('tmp')
        # 拿一个完整的券池表格，防止有些股票在某些日期没有数据，导致缓存数据不全，影响其他因子计算
        index_fix = INDEX_FIX(start,end,index_item)
        order_book_ids = index_fix.columns.tolist()
        
        # 获取开盘价
        open = get_price(order_book_ids, start_date=start, end_date=end,frequency='1d',fields='open').open.unstack('order_book_id')
        # 存储
        open.to_pickle(f'tmp/open_{index_item}_{start}_{end}.pkl')

        # 获取行业/市值暴露度
        # 获取市值暴露度
        market_cap = execute_factor(LOG(Factor('market_cap_3')),order_book_ids,start,end).stack().to_frame('market_cap')
        # 获取行业暴露度
        industry_df = pd.get_dummies(get_industry_exposure(order_book_ids,
                                                           datetime_period,
                                                           industry_type))
        # 合并市值行业暴露度
        industry_df['market_cap'] = market_cap
        df_industry_market = industry_df
        df_industry_market.index.names = ['datetime','order_book_id']
        df_industry_market.dropna(inplace = True)
        # 存储
        df_industry_market.to_pickle(f'tmp/df_industry_market_{industry_type}_{index_item}_{start}_{end}.pkl')

        # 异方差权重流通市值根
        mc2 = execute_factor((Factor('a_share_market_val_in_circulation')),order_book_ids,start,end)
        mc2_sqrt = np.sqrt(mc2)
        # 存储
        mc2_sqrt.to_pickle(f'tmp/mc2_sqrt_{index_item}_{start}_{end}.pkl')

    # 自变量 因变量 合表
    return_n = open.pct_change(n).shift(- n - 1).dropna(how = 'all')
    df_industry_market['return_n'] = return_n.stack()
    df_industry_market['factor'] = df.stack()
    # 去空
    df_industry_market.dropna(subset = ['factor','return_n'],inplace = True)

    # 加权最小二乘法
    def get_wls_mult(df_industry_market,t):
        try:
            # 截面
            df_industry_market_tmp = df_industry_market.loc[t]
            y = df_industry_market_tmp['return_n']
            x = df_industry_market_tmp.drop('return_n',axis = 1)
            # 回归
            reg = sm.WLS(y,x,weights=mc2_sqrt.loc[t,x.index],missing='drop').fit()
            result = [t,reg.tvalues.loc['factor'],reg.params.loc['factor']]
        except:
            result = [t,np.nan,np.nan]
    
        return result

    # 多进程
    tvalue = Parallel(n_jobs=2)(delayed(get_wls_mult)(df_industry_market,i) for i in datetime_period)
    # 报告存储
    tvalue = pd.DataFrame(tvalue,columns=['date','t_value','factor_ret']).set_index('date').dropna()

    # tvalue 报告
    report = {'name': name,
            # t 值序列绝对值均值——因子显著性的重要判据
            'tvalue_abs_mean':round(tvalue['t_value'].abs().mean(),4),
            # t 值序列均值——与 1)结合，能判断因子 t 值正负方向是否稳定
            'tvalue_mean':round(tvalue['t_value'].mean(),4),
            # t 值序列绝对值大于 2 的占比——判断因子的显著性是否稳定
            'tvalue_abs>2%':round(len(tvalue[tvalue['t_value'] > 2])/len(tvalue),4),
            # 因子收益率序列均值——判断因子收益率的大小
            'factor_ret_mean':round(tvalue.factor_ret.mean(),4)
            }

    # 打印报告
    print(report)
    report = pd.DataFrame([report])
    
    return tvalue,report

# 3.3 分层效应
def group_g(df,n,g,index_item,name = '',rebalance = False):

    """
    :param df: 因子值 -> unstack
    :param n: 调仓日 -> int
    :param g: 分组数量 -> int 
    :param index_item: 券池名 -> str 
    :param name: 因子名 -> str 
    :return group_return: 各分组日收益率 -> dataframe
    :return turnover_ratio: 各分组日调仓日换手率 -> dataframe
    """
    
    # 信号向后移动一天
    df = df.shift(1).iloc[1:]

    # 基础数据获取
    order_book_ids = df.columns.tolist()
    datetime_period = df.index
    start = datetime_period.min().strftime('%F')
    end = datetime_period.max().strftime('%F')

    # 提取预存储数据
    try:
        # 未来一天收益率
        return_1d = pd.read_pickle(f'tmp/return_1d_{index_item}_{start}_{end}.pkl')
    except:
        # 新建预存储文档
        create_dir_not_exist('tmp')
        # 拿一个完整的券池表格，防止有些股票在某些日期没有数据，导致缓存数据不全，影响其他因子计算
        index_fix = INDEX_FIX(start,end,index_item)
        order_book_ids = index_fix.columns.tolist()
        # 未来一天收益率
        return_1d = get_price(order_book_ids,start,get_next_trading_date(end,1),'1d','open','pre',False,True).open.unstack('order_book_id').pct_change().shift(-1).dropna(axis = 0,how = 'all').stack()
        # 存储
        return_1d.to_pickle(f'tmp/return_1d_{index_item}_{start}_{end}.pkl')

    # 数据喝收益合并
    group = df.stack().to_frame('factor')
    group['current_renturn'] = return_1d
    group = group.dropna()
    group.reset_index(inplace = True)
    group.columns = ['date','stock','factor','current_renturn']

    # 空换手率 和 空分组收益率表格
    turnover_ratio = pd.DataFrame()
    group_return = pd.DataFrame()

    datetime_period = pd.to_datetime(group.date.unique())

    # 按步长周期调仓
    for i in range(0,len(datetime_period)-1,n):  # -1 防止刚好切到最后一天没法计算
        # 截面分组
        single = group[group.date == datetime_period[i]].sort_values(by = 'factor')
        # 根据值的大小进行切分
        single.loc[:,'group'] = pd.qcut(single.factor,g, list(range(1,g+1))).to_list()
        group_dict = {}
        # 分组内的股票
        for j in range(1,g+1):
            group_dict[j] = single[single.group == j].stock.tolist()
        
        # 计算换手率
        turnover_ratio_temp = []
        if i == 0:
            # 首期分组成分股 存入历史
            temp_group_dict = group_dict
        else:
            # 分组计算换手率
            for j in range(1,g+1):
                turnover_ratio_temp.append(len(list(set(temp_group_dict[j]).difference(set(group_dict[j]))))/len(set(temp_group_dict[j])))
            # 存储分组换手率
            turnover_ratio = pd.concat([turnover_ratio,
                                        pd.DataFrame(turnover_ratio_temp,
                                                    index = ['G{}'.format(j) for j in list(range(1,g+1))],
                                                    columns = [datetime_period[i]]).T],
                                                    axis = 0)
            # 存入历史
            temp_group_dict = group_dict
        
        # 获取周期
        # 不够一个调仓周期，剩下的都是最后一个周期
        if i < len(datetime_period)-n:
            period = group[group.date.isin(datetime_period[i:i+n])]
        else:
            # 完整周期
            period = group[group.date.isin(datetime_period[i:])]

        # 计算各分组收益率（期间不rebalance权重）
        group_return_temp = []
        for j in range(1,g+1):
            if rebalance:
                # 横截面汇总
                group_ret_combine_ret = period[period.stock.isin(group_dict[j])].set_index(['date','stock']).current_renturn.unstack('stock').mean(axis = 1)

            else:
                # 组内各标的数据
                group_ret = period[period.stock.isin(group_dict[j])].set_index(['date','stock']).current_renturn.unstack('stock')
                # 标的累计收益
                group_ret_combine_cumnet = (1 + group_ret).cumprod().sum(axis = 1)
                # 组合的逐期收益
                group_ret_combine_ret = group_ret_combine_cumnet.pct_change()
                # 第一期填补
                group_ret_combine_ret.iloc[0] = group_ret.iloc[0].mean()
                
            # 合并各分组
            group_return_temp.append(group_ret_combine_ret)
        
        # 每个步长期间的收益合并
        group_return = pd.concat([group_return,pd.DataFrame(group_return_temp,index = ['G{}'.format(j) for j in list(range(1,g+1))]).T],axis = 0)
        # 进度
        print('\r 当前：{} / 总量：{}'.format(i,len(datetime_period)),end='')
    
    # 基准，各组的平均收益
    group_return['Benchmark'] = group_return.mean(axis = 1)
    group_return = (group_return+1).cumprod()
    # 年化华收益计算
    group_annual_ret = (group_return.iloc[-1] ** (252/len(group_return)) - 1)
    group_annual_ret -= group_annual_ret.Benchmark
    group_annual_ret = group_annual_ret.drop('Benchmark').to_frame('annual_ret')
    group_annual_ret['group'] = list(range(1,g+1))
    corr_value = round(group_annual_ret.corr(method = 'spearman').iloc[0,1],4)
    group_annual_ret.annual_ret.plot(kind = 'bar',figsize = (10,5),title = f'{name}_分层超额年化收益_单调性{corr_value}')

    group_return.plot(figsize = (10,5),title =  f'{name}_分层净值表现')

    yby_performance = group_return.pct_change().resample('Y').apply(lambda x : (1+x).cumprod().iloc[-1]).T
    yby_performance -= yby_performance.loc['Benchmark']
    yby_performance = yby_performance.replace(0,np.nan).dropna(how = 'all')
    yby_performance.plot(kind = 'bar',
                         figsize = (10,5),
                         title =  f'{name}_逐年分层年化收益',
                         color = ['powderblue','lightskyblue','cornflowerblue','steelblue','royalblue'])

    return group_return,turnover_ratio


# 4 回测检验框架 ----------------------------------------------------------- 

# 4.1 买入队列构建
def get_buy_list(df,top_tpye = 'rank',rank_n = 100,quantile_q = 0.8):
    """
    :param df: 因子值 -> dataframe/unstack
    :param top_tpye: 选择买入队列方式，从['rank','quantile']选择一种方式 -> str
    :param rank_n: 值最大的前n只的股票 -> int
    :param quantile_q: 值最大的前n分位数的股票 -> float
    :return df: 买入队列 -> dataframe/unstack
    """

    if top_tpye == 'rank':
        df = df.rank(axis  = 1,ascending=False) <= rank_n
    elif top_tpye == 'quantile':
        df = df.sub(df.quantile(quantile_q,axis = 1),axis = 0) > 0
    else:
        print("select one from ['rank','quantile']")

    df = df.astype(int)
    df = df.replace(0,np.nan).dropna(how = 'all',axis = 1)
    
    return df

# 4.2 获取标的收益
def get_bar(df,adjust):
    """
    :param df: 买入队列 -> dataframe/unstack
    :return ret: 基准的逐日收益 -> dataframe
    """
    start_date = get_previous_trading_date(df.index.min(),1).strftime('%F')
    end_date = df.index.max().strftime('%F')
    stock_list = df.columns.tolist()
    price_open = get_price(stock_list,start_date,end_date,fields=['open'],adjust_type=adjust).open.unstack('order_book_id')
    
    return price_open

# 4.3 获取基准收益
def get_benchmark(df,benchmark,benchmark_type = 'mcw'):
    """
    :param df: 买入队列 -> dataframe/unstack
    :param benchmark: 基准指数 -> str
    :return ret: 基准的逐日收益 -> dataframe
    """
    start_date = get_previous_trading_date(df.index.min(),1).strftime('%F')
    end_date = df.index.max().strftime('%F')
    if benchmark_type == 'mcw':
        price_open = get_price([benchmark],start_date,end_date,fields=['open']).open.unstack('order_book_id')
    else:
        index_fix = INDEX_FIX(start_date,end_date,benchmark)
        stock_list = index_fix.columns.tolist()
        price_open = get_price(stock_list,start_date,end_date,fields=['open']).open.unstack('order_book_id')
        price_open = price_open.pct_change().mask(~index_fix).mean(axis = 1)
        price_open = (1 + price_open).cumprod().to_frame(benchmark)
    
    return price_open


# 4.4 回测框架
def backtest(df_weight, change_n = 20, cash = 10000 * 10000, tax = 0.0005, other_tax = 0.0001, commission = 0.0002, min_fee = 5, cash_interest_yield = 0.02):

    # 基础参数
    inital_cash = cash                                                                                                            # 起始资金
    stock_holding_num_hist = 0                                                                                                    # 初始化持仓       
    buy_cost = other_tax + commission                                                                                             # 买入交易成本
    sell_cost = tax + other_tax + commission                                                                                      # 卖出交易成本
    cash_interest_daily = (1 + cash_interest_yield) ** (1/252) - 1                                                                # 现金账户利息(日)
    account = pd.DataFrame(index = df_weight.index,columns=['total_account_asset','holding_market_cap','cash_account'])           # 账户信息存储
    price_open = get_bar(df_weight,'none')                                                                                        # 获取开盘价格数据
    price_open_pre = get_bar(df_weight,'post')                                                                                    # 获取后复权价格数据
    stock_round_lot = pd.Series(dict([(i,instruments(i).round_lot) for i in df_weight.columns.tolist()]))                         # 标的最小买入数量
    change_day = sorted(set(df_weight.index.tolist()[::change_n] + [df_weight.index[-1]]))                                        # 调仓日期

    # 滚动计算
    for i in tqdm(range(0,len(change_day)-1)):
        start_date = change_day[i]
        end_date = change_day[i+1]

        # 获取给定权重
        df_weight_temp = df_weight.loc[start_date].dropna()
        stock_list_temp = df_weight_temp.index.tolist()
        # 计算个股持股数量 = 向下取整(给定权重 * 可用资金 // 最小买入股数) * 最小买入股数
        stock_holding_num = ((df_weight_temp 
                            * cash 
                            / (price_open.loc[start_date,stock_list_temp] * (1 + sell_cost))        # 预留交易费用
                            // stock_round_lot.loc[stock_list_temp]) 
                            * stock_round_lot.loc[stock_list_temp])

        # 仓位变动      
        ## 防止相减为空 & 剔除无变动
        stock_holding_num_change = stock_holding_num.sub(stock_holding_num_hist,fill_value = 0).replace(0,np.nan).dropna()
        # 获取期间价格
        price_open_temp = price_open.loc[start_date]           # 引入完整券池
        
        # 计算交易成本 (可设置万一免五)
        def calc_fee(x,min_fee):
            if x < 0:
                fee_temp = -1 * x * sell_cost                                                                                       # 印花税 + 过户费等 + 佣金
            else:
                fee_temp = x * buy_cost                                                                                             # 过户费等 + 佣金
            # 最低交易成本限制
            if fee_temp > min_fee:
                return fee_temp
            else:
                return min_fee

        transaction_costs = ((price_open_temp
                            * stock_holding_num_change)).apply(lambda x: calc_fee(x,min_fee)).sum()
        
        adjust_ratio = price_open_pre.loc[start_date:end_date]/price_open_pre.loc[start_date]                                        # 复权比率
        adjust_ratio_price = adjust_ratio.T.mul(price_open_temp,axis = 0).dropna(how = 'all').T                                      # 除权价格复权
        
        # 计算期间市值 （交易手续费在现金账户计提）
        holding_market_cap = (adjust_ratio_price * stock_holding_num).sum(axis =1)
        cash_account = cash - transaction_costs - holding_market_cap.loc[start_date]
        cash_account = pd.Series([cash_account * ((1 + cash_interest_daily)**(i+1)) for i in range(0,len(holding_market_cap))],
                                index = holding_market_cap.index)
        total_account_asset = holding_market_cap + cash_account
        
        # 将当前持仓存入 
        stock_holding_num_hist = stock_holding_num
        # 下一期期初可用资金
        cash = total_account_asset.loc[end_date]

        account.loc[start_date:end_date,'total_account_asset'] = round(total_account_asset,2)
        account.loc[start_date:end_date,'holding_market_cap'] = round(holding_market_cap,2)
        account.loc[start_date:end_date,'cash_account'] = round(cash_account,2)

    account.loc[pd.to_datetime(get_previous_trading_date(account.index.min(),1))] = [inital_cash,0,inital_cash]
    account = account.sort_index()
    
    return account

# 4.5 回测绩效指标绘制
def get_performance_analysis(account_result,rf = 0.03,benchmark_index = '000985.XSHG'):

    # 加入基准    
    performance = pd.concat([account_result['total_account_asset'].to_frame('strategy'),
                             get_benchmark(account_result,benchmark_index)],axis = 1)
    performance_net = performance.pct_change().dropna(how = 'all')                                # 清算至当日开盘
    performance_cumnet = (1 + performance_net).cumprod()
    performance_cumnet['alpha'] = performance_cumnet['strategy']/performance_cumnet[benchmark_index]
    performance_cumnet = performance_cumnet.fillna(1)

    # 指标计算
    performance_pct = performance_cumnet.pct_change().dropna()

    # 策略收益
    strategy_name,benchmark_name,alpha_name = performance_cumnet.columns.tolist() 
    Strategy_Final_Return = performance_cumnet[strategy_name].iloc[-1] - 1

    # 策略年化收益
    Strategy_Annualized_Return_EAR = (1 + Strategy_Final_Return) ** (252/len(performance_cumnet)) - 1

    # 基准收益
    Benchmark_Final_Return = performance_cumnet[benchmark_name].iloc[-1] - 1

    # 基准年化收益
    Benchmark_Annualized_Return_EAR = (1 + Benchmark_Final_Return) ** (252/len(performance_cumnet)) - 1

    # alpha 
    ols_result = sm.OLS(performance_pct[strategy_name] * 252 - rf, sm.add_constant(performance_pct[benchmark_name] * 252 - rf)).fit()
    Alpha = ols_result.params[0]

    # beta
    Beta = ols_result.params[1]

    # beta_2 = np.cov(performance_pct[strategy_name],performance_pct[benchmark_name])[0,1]/performance_pct[benchmark_name].var()
    # 波动率
    Strategy_Volatility = performance_pct[strategy_name].std() * np.sqrt(252)

    # 夏普
    Strategy_Sharpe = (Strategy_Annualized_Return_EAR - rf)/Strategy_Volatility

    # 下行波动率
    strategy_ret = performance_pct[strategy_name]
    Strategy_Down_Volatility = strategy_ret[strategy_ret < 0].std() * np.sqrt(252)

    # sortino
    Sortino = (Strategy_Annualized_Return_EAR - rf)/Strategy_Down_Volatility
    
    # 跟踪误差
    Tracking_Error = (performance_pct[strategy_name] - performance_pct[benchmark_name]).std() * np.sqrt(252)

    # 信息比率
    Information_Ratio = (Strategy_Annualized_Return_EAR - Benchmark_Annualized_Return_EAR)/Tracking_Error

    # 最大回测
    i = np.argmax((np.maximum.accumulate(performance_cumnet[strategy_name]) 
                    - performance_cumnet[strategy_name])
                    /np.maximum.accumulate(performance_cumnet[strategy_name]))
    j = np.argmax(performance_cumnet[strategy_name][:i])
    Max_Drawdown = (1-performance_cumnet[strategy_name][i]/performance_cumnet[strategy_name][j])

    # 卡玛比率
    Calmar = (Strategy_Annualized_Return_EAR)/Max_Drawdown

    # 超额收益
    Alpha_Final_Return = performance_cumnet[alpha_name].iloc[-1] - 1

    # 超额年化收益
    Alpha_Annualized_Return_EAR = (1 + Alpha_Final_Return) ** (252/len(performance_cumnet)) - 1

    # 超额波动率
    Alpha_Volatility = performance_pct[alpha_name].std() * np.sqrt(252)

    # 超额夏普
    Alpha_Sharpe = (Alpha_Annualized_Return_EAR - rf)/Alpha_Volatility

    # 超额最大回测
    i = np.argmax((np.maximum.accumulate(performance_cumnet[alpha_name]) 
                    - performance_cumnet[alpha_name])
                    /np.maximum.accumulate(performance_cumnet[alpha_name]))
    j = np.argmax(performance_cumnet[alpha_name][:i])
    Alpha_Max_Drawdown = (1-performance_cumnet[alpha_name][i]/performance_cumnet[alpha_name][j])

    # 胜率
    performance_pct['win'] = performance_pct[alpha_name] > 0
    Win_Ratio = performance_pct['win'].value_counts().loc[True] / len(performance_pct)

    # 盈亏比
    profit_lose = performance_pct.groupby('win')[alpha_name].mean()
    Profit_Lose_Ratio = abs(profit_lose[True]/profit_lose[False])
    

    result = {
        '策略累计收益':round(Strategy_Final_Return,4),
        '策略年化收益': round(Strategy_Annualized_Return_EAR,4),
        '基准累计收益':round(Benchmark_Final_Return,4),
        '基准年化收益': round(Benchmark_Annualized_Return_EAR,4),
        '阿尔法':round(Alpha,4),
        '贝塔':round(Beta,4),
        '波动率':round(Strategy_Volatility,4),
        '夏普比率':round(Strategy_Sharpe,4),
        '下行波动率':round(Strategy_Down_Volatility,4),
        '索提诺比率':round(Sortino,4),
        '跟踪误差':round(Tracking_Error,4),
        '信息比率':round(Information_Ratio,4),
        '最大回撤':round(Max_Drawdown,4),
        '卡玛比率': round(Calmar,4),
        '超额累计收益':round(Alpha_Final_Return,4),
        '超额年化收益': round(Alpha_Annualized_Return_EAR,4),
        '超额波动率':round(Alpha_Volatility,4),
        '超额夏普':round(Alpha_Sharpe,4),
        '超额最大回测':round(Alpha_Max_Drawdown,4),
        '胜率':round(Win_Ratio,4),
        '盈亏比':round(Profit_Lose_Ratio,4)

    }
    

    return performance_cumnet,result