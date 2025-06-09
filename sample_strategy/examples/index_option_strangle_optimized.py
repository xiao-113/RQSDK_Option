import rqalpha_plus
import rqalpha_mod_option
import datetime
from datetime import date, time, timedelta
from dateutil.relativedelta import relativedelta
import rqdatac
from rqdatac import options
import pandas as pd
import numpy as np

__config__ = {
    "base": {
        "start_date": "20200601",
        "end_date": "20250603",
        'frequency': '1m',
        "accounts": {
        	# 股指期权使用 future 账户
            "future": 10000000
        }
    },
    "mod": {
        "option": {
            "enabled": True,
            "exercise_slippage": 0
        },
        'sys_simulation': {
            'enabled': True,
            'matching_type': 'current_bar',
            'volume_limit': False,  #关闭成交量限制
            #'volume_percent': 0,
        },
        'sys_analyser': {
            'plot': True,
        },
    }
}

def init(context):
    # 初始化动态参数
    context.current_month = context.now.strftime("%y%m")
    print(f'当前时间 {context.now}')
    #print(f'最近交易日{date(2019, 11, 22)}')
    # context.s1 = None  # 延迟初始化看涨合约
    # context.s2 = None  # 延迟初始化看跌合约
    context.counter = 0  #计数器
    context.rolled = False #是否切换合约
    context.initialized = False  # 标记是否完成首次建仓

    #--------------信号计算初始化
    #隐历差
    context.hist_iv = []
    context.hist_iv_hv = []

    #比值PCR
    context.hist_PCR = []
    
    #期限结构
    context.hist_IVTS = []

    #偏度指数
    context.hist_skew = []

    #持仓PCR
    context.hist_hold_PCR = []

    #卖方识别
    context.hist_volume = []
    context.hist_hold = []
    context.hist_weighted_iv = []
    #----------------

    latest_trading_date = rqdatac.get_previous_trading_date(context.now.date(),n=1,market='cn')
    if_price = rqdatac.get_price(['000300.XSHG'], 
                         start_date=latest_trading_date, 
                         end_date=latest_trading_date, 
                         fields='close',
                         frequency='1d',
                         expect_df=False)[0]
    #if_price = current_minute('000300.XSHG', fields = 'close').iloc[-1, -1]
    print(f"价格{if_price}")
    call_strike = get_OTM_strike('C', if_price, 1)
    put_strike = get_OTM_strike('P', if_price, 1)
    print(f"认购/沽虚值1档行权价 {call_strike}/{put_strike}")
    
    #获取目标行权价的看涨和看跌期权合约
    context.s1 =  options.get_contracts(underlying='000300.XSHG', maturity=context.current_month, strike=call_strike)[0]
    context.s2 = options.get_contracts(underlying='000300.XSHG', maturity=context.current_month, strike=put_strike)[1]

    subscribe([context.s1, context.s2])

    print('******* INIT *******')


def get_nearest_strike(price):
    """计算最接近的平值行权价（50点间距）"""
    return round(price / 50) * 50

def get_OTM_strike(direction, price, n): 
    '''
    计算n挡 call/put虚值期权行权价
    '''

    if direction == 'C':
        return get_nearest_strike(price) + n * 50  # 看涨：行权价=ATM+n档
    else:
        return get_nearest_strike(price) - n * 50  # 看跌：行权价=ATM-n档

#信号计算函数---------------------------------------
#隐历差信号
def iv_hv_signal(context):
    # --- 1. 计算标的30日历史波动率（HV）---
    end_date = (context.now - timedelta(days=1)).strftime('%Y-%m-%d') #滞后一天用于生成信号
    start_date = (context.now - timedelta(days=61)).strftime('%Y-%m-%d')  # 多取数据防止缺失
    logger.info(f"计算截至日 {end_date}")
    # 获取标的收盘价（确保30日数据完整）
    close_df = rqdatac.get_price('000300.XSHG', start_date, end_date, fields='close')
    # print(f'收盘价序列{close_df}')
    if len(close_df) < 30:
        raise ValueError("标的收盘价数据不足30日")
    
    # 计算年化历史波动率（对数收益率标准差）
    close_prices = close_df['close'].values[-30:]  # 取最近30日
    log_returns = np.log(close_prices[1:] / close_prices[:-1])
    hv = log_returns.std() * np.sqrt(252)
    print(f"截至日历史波动率 {hv}")
    # --- 2. 获取期权IV并计算隐历差（滚动30日历史序列）---
    print(f"当前期权 { [context.s1, context.s2]}")
    # 获取当前日期期权IV(所有当月合约的均值代表期权市场IV)（假设context.s1/s2为认购/认沽期权代码）
    option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', maturity = context.current_month )
    
    #检查当月合约是否到期
    if not all(rqdatac.instruments(c).days_to_expire() >= 0 for c in option_list):
        # # 获取次月合约
        next_month = (context.now + relativedelta(months=1)).strftime("%y%m")
        option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', maturity = next_month)

    iv_list_df = rqdatac.options.get_greeks(option_list, start_date, end_date, fields='iv', model='implied_forward')#['iv'][-1]
    
    # 修复：先检查是否为None或空DataFrame
    if iv_list_df is None:
        raise ValueError("未获取到期权隐含波动率数据（接口返回None或空DataFrame）")
    
    iv_df = iv_list_df.groupby(['trading_date'])['iv'].mean().reset_index()
    
    # 修复：先检查是否为None或空DataFrame
    if iv_df is None:
        raise ValueError("未获取到期权隐含波动率数据（接口返回None或空DataFrame）")
    current_iv = iv_df['iv'].iloc[-1]
    print(f'截至日期权隐含波动率 {current_iv}')
    
    # 更新IV历史序列（最多保留30日）
    context.hist_iv.append(current_iv)
    if len(context.hist_iv) > 30:
        context.hist_iv.pop(0)
    
    # 计算当前隐历差并更新历史序列
    current_iv_minus_hv = current_iv - hv
    context.hist_iv_hv.append(current_iv_minus_hv)
    if len(context.hist_iv_hv) > 30:
        context.hist_iv_hv.pop(0)

    # --- 3. 信号触发（需至少30日历史数据）---
    if len(context.hist_iv_hv) >= 30:
        rolling_mean = np.mean(context.hist_iv_hv)
        rolling_std = np.std(context.hist_iv_hv)
        upper_bound = rolling_mean + rolling_std
        
        # 信号逻辑：隐历差 <= 上界时开仓(感觉应该是>=上边界时开仓，期权溢价过高更容易均值回归，双卖做空波动率)
        # 两个方向均测试
        iv_hv_signal = (current_iv_minus_hv >= upper_bound)
    else:
        iv_hv_signal = False  # 数据不足不触发
    
    return iv_hv_signal

#比值PCR信号
def PCR_signal(context):
    end_date = (context.now - timedelta(days=1)).strftime('%Y-%m-%d') #滞后一天用于生成信号
    start_date = (context.now - timedelta(days=61)).strftime('%Y-%m-%d')  # 多取数据防止缺失
    #获取所有的认购 认沽成交量

    C_option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', option_type='C',trading_date = end_date) #获取该日所有认购合约
    P_option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', option_type='P',trading_date = end_date) #获取该日所有认沽合约
    C_volume_list_df = rqdatac.get_price(C_option_list, start_date, end_date, fields='volume')
    P_volume_list_df = rqdatac.get_price(P_option_list, start_date, end_date, fields='volume')


    C_volume_df = C_volume_list_df.groupby(['date'])['volume'].sum().reset_index()
    current_C_volume = C_volume_df['volume'].iloc[-1]
    P_volume_df = P_volume_list_df.groupby(['date'])['volume'].sum().reset_index()
    current_P_volume = P_volume_df['volume'].iloc[-1]
    current_PCR = current_P_volume / current_C_volume
    
    context.hist_PCR.append(current_PCR)
    #保持只存储历史30日的数据
    if len(context.hist_PCR) > 30:
        context.hist_PCR.pop(0)

    # --- 信号触发（需至少30日历史数据）---
    if len(context.hist_PCR) >= 30:
        rolling_mean = np.mean(context.hist_PCR)
        rolling_std = np.std(context.hist_PCR)
        upper_bound = rolling_mean + rolling_std
        lower_bound = rolling_mean - rolling_std

        # 信号逻辑：下界<= 比值PCR <= 上界时开仓
        PCR_signal = (lower_bound <= current_PCR <= upper_bound)
    else:
        PCR_signal = False #数据不足无法触发

    return PCR_signal

#期限结构信号
def IVTS_signal(context):
    end_date = (context.now - timedelta(days=1)).strftime('%Y-%m-%d') #滞后一天用于生成信号
    start_date = (context.now - timedelta(days=61)).strftime('%Y-%m-%d')  # 多取数据防止缺失
    #获取当月合约和次月合约
    option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', maturity = context.current_month )
    next_month = (context.now + relativedelta(months=1)).strftime("%y%m")
    next_option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', maturity = next_month )
    #检查当月合约是否到期
    if not all(rqdatac.instruments(c).days_to_expire() >= 0 for c in option_list):
        # # 获取次月合约
        next_month = (context.now + relativedelta(months=1)).strftime("%y%m")
        next_next_month = (context.now + relativedelta(months=2)).strftime("%y%m")
        option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', maturity = next_month)
        next_option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', maturity = next_next_month)
    #获取当月合约和次月合约当日成交量
    volume_list_df = rqdatac.get_price(option_list, start_date, end_date, fields='volume')
    volume_list_df.index = volume_list_df.index.set_names(['order', 'date'], level=[0, 1])
    next_volume_list_df = rqdatac.get_price(next_option_list, start_date, end_date, fields='volume')
    next_volume_list_df.index = next_volume_list_df.index.set_names(['order', 'date'], level=[0, 1])
    #计算当月合约和次月合约对应IV
    iv_list_df = rqdatac.options.get_greeks(option_list, start_date, end_date, fields='iv', model='implied_forward')
    iv_list_df.index = iv_list_df.index.set_names(['order', 'date'], level=[0, 1])
    next_iv_list_df = rqdatac.options.get_greeks(next_option_list, start_date, end_date, fields='iv', model='implied_forward')
    next_iv_list_df.index = next_iv_list_df.index.set_names(['order', 'date'], level=[0, 1])
    #筛选当月、次月当日成交量前四合约，加权计算IV
    # 当月：筛选每日成交量前四的order
    top4_orders_volume = (
        volume_list_df
        .groupby('date', group_keys=False)  # 按日期分组
        .apply(lambda x: x.nlargest(4, 'volume'))  # 每组取volume最大的4个order
        .reset_index()  
        [['order', 'date', 'volume']]  
    )
    #merge关联IV数据（保留每日volume前四合约的IV）
    top4_iv_volume_df = pd.merge(
        top4_orders_volume,
        iv_list_df.reset_index(), 
        on=['order', 'date'],
        how='left'
    )
    top4_iv_volume_df.set_index(['order', 'date'], inplace=True)

    # 计算每日加权平均IV（按volume加权）
    daily_weighted_iv = (
        top4_iv_volume_df.groupby('date')
        .apply(lambda x: np.average(x['iv'], weights=x['volume']))
        .rename('weighted_iv')
    )
    current_weighted_iv = daily_weighted_iv.iloc[-1]
    print(f'当前当月合约加权隐含波动率 {current_weighted_iv}')

    # 次月
    # 次月：筛选每日成交量前四的order
    next_top4_orders_volume = (
        next_volume_list_df
        .groupby('date', group_keys=False)  # 按日期分组
        .apply(lambda x: x.nlargest(4, 'volume'))  # 每组取volume最大的4个order
        .reset_index()  
        [['order', 'date', 'volume']]  
    )
    #merge关联IV数据（保留每日volume前四合约的IV）
    next_top4_iv_volume_df = pd.merge(
        next_top4_orders_volume,
        next_iv_list_df.reset_index(), 
        on=['order', 'date'],
        how='left'
    )
    next_top4_iv_volume_df.set_index(['order', 'date'], inplace=True)

    # 计算每日加权平均IV（按volume加权）
    next_daily_weighted_iv = (
        next_top4_iv_volume_df.groupby('date')
        .apply(lambda x: np.average(x['iv'], weights=x['volume']))
        .rename('weighted_iv')
    )
    current_next_weighted_iv = next_daily_weighted_iv.iloc[-1]
    print(f'当前次月合约加权隐含波动率 {current_next_weighted_iv}')
    
    #当前期限结构
    current_IVTS = current_weighted_iv - current_next_weighted_iv
    context.hist_IVTS.append(current_IVTS)
    #保持只存储历史30日的数据
    if len(context.hist_IVTS) > 30:
        context.hist_IVTS.pop(0)

    # --- 信号触发（需至少30日历史数据）---
    if len(context.hist_IVTS) >= 30:
        rolling_mean = np.mean(context.hist_IVTS)
        rolling_std = np.std(context.hist_IVTS)
        upper_bound = rolling_mean + rolling_std
        lower_bound = rolling_mean - rolling_std

        # 信号逻辑1：期限因子 >= 上界时开仓
        IVTS_signal = (current_IVTS >= upper_bound)
        # 信号逻辑2：反向择时 期限因子在上下界之间开仓
        # IVTS_signal = (lower_bound <= current_IVTS <= upper_bound)
        # 信号逻辑3：期限因子 > 0 时即开仓
        # IVTS_signal = (current_IVTS > 0)
    else:
        IVTS_signal = False #数据不足无法触发

    return IVTS_signal

#偏度指数信号
def skew_index_signal(context):
    end_date = (context.now - timedelta(days=1)).strftime('%Y-%m-%d') #滞后一天用于生成信号
    start_date = (context.now - timedelta(days=61)).strftime('%Y-%m-%d')  # 多取数据防止缺失

    #获取所有的认购 认沽合约
    C_option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', option_type='C', maturity = context.current_month) #获取该日所有当月认购合约
    P_option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', option_type='P', maturity = context.current_month) #获取该日所有当月认沽合约
    #检查当月合约是否到期
    if not all((rqdatac.instruments(c).days_to_expire() >= 0 for c in C_option_list) 
               and (rqdatac.instruments(c).days_to_expire() >= 0 for c in P_option_list)):
        # # 获取次月合约
        next_month = (context.now + relativedelta(months=1)).strftime("%y%m")
        C_option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', option_type='C', maturity = next_month)
        P_option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', option_type='P', maturity = next_month)
    #获取认沽/认购合约成交量
    C_volume_list_df = rqdatac.get_price(C_option_list, start_date, end_date, fields='volume')
    P_volume_list_df = rqdatac.get_price(P_option_list, start_date, end_date, fields='volume')
    C_volume_list_df.index = C_volume_list_df.index.set_names(['order', 'date'], level=[0, 1])
    P_volume_list_df.index = P_volume_list_df.index.set_names(['order', 'date'], level=[0, 1])
    #计算认购/认沽合约对应IV
    C_iv_list_df = rqdatac.options.get_greeks(C_option_list, start_date, end_date, fields='iv', model='implied_forward')
    C_iv_list_df.index = C_iv_list_df.index.set_names(['order', 'date'], level=[0, 1])
    P_iv_list_df = rqdatac.options.get_greeks(P_option_list, start_date, end_date, fields='iv', model='implied_forward')
    P_iv_list_df.index = P_iv_list_df.index.set_names(['order', 'date'], level=[0, 1])
    
    #计算认购侧加权隐含波动率
    #merge关联IV数据
    C_iv_volume_df = pd.merge(
        C_volume_list_df,
        C_iv_list_df.reset_index(), 
        on=['order', 'date'],
        how='left'
    )
    C_iv_volume_df.set_index(['order', 'date'], inplace=True)

    # 计算每日加权平均IV（按volume加权）
    C_daily_weighted_iv = (
        C_iv_volume_df.groupby('date')
        .apply(lambda x: np.average(x['iv'], weights=x['volume']))
        .rename('weighted_iv')
    )
    current_C_weighted_iv = C_daily_weighted_iv.iloc[-1]
    
    #计算认沽侧加权隐含波动率
    #merge关联IV数据
    P_iv_volume_df = pd.merge(
        P_volume_list_df,
        P_iv_list_df.reset_index(), 
        on=['order', 'date'],
        how='left'
    )
    P_iv_volume_df.set_index(['order', 'date'], inplace=True)

    # 计算每日加权平均IV（按volume加权）
    P_daily_weighted_iv = (
        P_iv_volume_df.groupby('date')
        .apply(lambda x: np.average(x['iv'], weights=x['volume']))
        .rename('weighted_iv')
    )
    current_P_weighted_iv = P_daily_weighted_iv.iloc[-1]

    #当前偏度指数
    current_skew = current_P_weighted_iv - current_C_weighted_iv
    print(f'当前偏度指数 {current_skew}')

    context.hist_skew.append(current_skew)
    #保持只存储历史30日的数据
    if len(context.hist_skew) > 30:
        context.hist_skew.pop(0)

    # --- 信号触发（需至少30日历史数据）---
    if len(context.hist_skew) >= 30:
        rolling_mean = np.mean(context.hist_skew)
        rolling_std = np.std(context.hist_skew)
        upper_bound = rolling_mean + rolling_std
        lower_bound = rolling_mean - rolling_std

        # 信号逻辑：下界 <= 偏度指数 <= 上界时开仓
        skew_index_signal = (lower_bound <= current_skew <= upper_bound)
    else:
        skew_index_signal = False #数据不足无法触发

    return skew_index_signal

def hold_PCR_signal(context):
    end_date = (context.now - timedelta(days=1)).strftime('%Y-%m-%d') #滞后一天用于生成信号
    start_date = (context.now - timedelta(days=61)).strftime('%Y-%m-%d')  # 多取数据防止缺失
    #获取所有的认购 认沽成交量

    C_option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', option_type='C',trading_date = end_date) #获取该日所有认购合约
    P_option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', option_type='P',trading_date = end_date) #获取该日所有认沽合约
    C_hold_list_df = rqdatac.get_price(C_option_list, start_date, end_date, fields='open_interest')
    P_hold_list_df = rqdatac.get_price(P_option_list, start_date, end_date, fields='open_interest')


    C_hold_df = C_hold_list_df.groupby(['date'])['open_interest'].sum().reset_index()
    current_C_hold = C_hold_df['open_interest'].iloc[-1]
    P_hold_df = P_hold_list_df.groupby(['date'])['open_interest'].sum().reset_index()
    current_P_hold = P_hold_df['open_interest'].iloc[-1]
    current_hold_PCR = current_P_hold / current_C_hold
    
    context.hist_hold_PCR.append(current_hold_PCR)
    #保持只存储历史30日的数据
    if len(context.hist_hold_PCR) > 30:
        context.hist_hold_PCR.pop(0)

    # --- 信号触发（需至少30日历史数据）---
    if len(context.hist_hold_PCR) >= 30:
        rolling_mean = np.mean(context.hist_hold_PCR)
        rolling_std = np.std(context.hist_hold_PCR)
        upper_bound = rolling_mean + rolling_std
        lower_bound = rolling_mean - rolling_std

        # 信号逻辑：下界<= 持仓PCR <= 上界时开仓
        hold_PCR_signal = (lower_bound <= current_hold_PCR <= upper_bound)
    else:
        hold_PCR_signal = False #数据不足无法触发

    return hold_PCR_signal

#卖方市场识别信号
def sell_side_signal(context):
    end_date = (context.now - timedelta(days=1)).strftime('%Y-%m-%d') #滞后一天用于生成信号
    start_date = (context.now - timedelta(days=61)).strftime('%Y-%m-%d')  # 多取数据防止缺失

    option_list = rqdatac.options.get_contracts(underlying='000300.XSHG', trading_date = end_date) #获取该日所有合约
    #获取所有合约成交量、持仓量
    volume_hold_list_df = rqdatac.get_price(option_list, start_date, end_date, fields=['volume','open_interest'])
    volume_hold_list_df.index = volume_hold_list_df.index.set_names(['order', 'date'], level=[0, 1])
    #获取所有合约隐含波动率
    iv_list_df = rqdatac.options.get_greeks(option_list, start_date, end_date, fields='iv', model='implied_forward')
    iv_list_df.index = iv_list_df.index.set_names(['order', 'date'], level=[0, 1])
    #merge关联IV数据
    iv_volume_hold_list_df = pd.merge(
        volume_hold_list_df,
        iv_list_df.reset_index(), 
        on=['order', 'date'],
        how='left'
    )
    iv_volume_hold_list_df.set_index(['order', 'date'], inplace=True)
    #当前期权市场成交量
    volume_df = iv_volume_hold_list_df.groupby(['date'])['volume'].sum().reset_index()
    current_volume = volume_df['volume'].iloc[-1]
    #当前期权市场持仓量
    hold_df = iv_volume_hold_list_df.groupby(['date'])['open_interest'].sum().reset_index()
    current_hold = hold_df['open_interest'].iloc[-1]
    #当前期权市场（成交量加权）隐含波动率
    daily_weighted_iv = (
        iv_volume_hold_list_df.groupby('date')
        .apply(lambda x: np.average(x['iv'], weights=x['volume']))
        .rename('weighted_iv')
    )
    current_weighted_iv = daily_weighted_iv.iloc[-1]

    context.hist_volume.append(current_volume)
    context.hist_hold.append(current_hold)
    context.hist_weighted_iv.append(current_weighted_iv)
    #保持只存储历史30日的数据
    if len(context.hist_volume) > 30:
        context.hist_volume.pop(0)
    if len(context.hist_hold) > 30:
        context.hist_hold.pop(0)
    if len(context.hist_weighted_iv) > 30:
        context.hist_weighted_iv.pop(0)

    # --- 信号触发（需至少30日历史数据）---
    if len(context.hist_volume) >= 30:
        rolling_mean = np.mean(context.hist_volume)
        rolling_std = np.std(context.hist_volume)
        upper_bound = rolling_mean + rolling_std
        
        # 信号逻辑：成交量 >= 上界时开仓
        volume_signal = (current_volume >= upper_bound)
    else:
        volume_signal = False #数据不足无法触发

    # --- 信号触发（需至少30日历史数据）---
    if len(context.hist_hold) >= 30:
        rolling_mean = np.mean(context.hist_hold)
        rolling_std = np.std(context.hist_hold)
        upper_bound = rolling_mean + rolling_std

        # 信号逻辑：持仓量 >= 上界时开仓
        hold_signal = (current_hold >= upper_bound)
    else:
        hold_signal = False #数据不足无法触发

    # --- 信号触发（需至少30日历史数据）---
    if len(context.hist_weighted_iv) >= 30:
        rolling_mean = np.mean(context.hist_weighted_iv)
        rolling_std = np.std(context.hist_weighted_iv)
        lower_bound = rolling_mean - rolling_std

        # 信号逻辑：波动率 <= 下界时开仓
        iv_signal = (current_weighted_iv <= lower_bound)
    else:
        iv_signal = False #数据不足无法触发

    #三个同时满足触发卖方识别
    sell_side_signal = (volume_signal and hold_signal and iv_signal)
    return sell_side_signal
    
def before_trading(context):
    context.initialized = False #每日盘前记号初始化
    # context.signal_1 = iv_hv_signal(context)
    # print(f'今日隐历差信号 {context.signal_1}')
    # context.signal_2 = PCR_signal(context)
    # print(f'今日比值PCR信号 {context.signal_2}')
    # context.signal_3 = IVTS_signal(context)
    # print(f'今日期限结构信号 {context.signal_3}')
    # context.signal_4 = skew_index_signal(context)
    # print(f'今日偏度指数信号 {context.signal_4}')
    # context.signal_5 = hold_PCR_signal(context)
    # print(f'今日持仓PCR信号 {context.signal_5}')
    # context.signal_6 = sell_side_signal(context)
    # print(f'今日卖方市场识别信号 {context.signal_6}')

    # #信号合成
    # context.combined_signal = all([
    #                                 context.signal_1, 
    #                                 context.signal_2, 
    #                                 context.signal_3,
    #                                 context.signal_4, 
    #                                 context.signal_5 
                                    #context.signal_6
                                # ])
    # print(f'今日合成信号 {context.combined_signal}')
    pass

def handle_bar(context, bar_dict):
    context.counter += 1
    current_time = context.now.time()
    normalized_time = current_time.replace(microsecond=0)
    
    # 初始化逻辑（保持不变）
    if normalized_time == time(9, 31) and not context.initialized: 
        C_days_to_expire = rqdatac.instruments(context.s1).days_to_expire(context.now.date())
        P_days_to_expire = rqdatac.instruments(context.s2).days_to_expire(context.now.date())
        print(f'{context.s1}距离到期天数{C_days_to_expire}')
        print(f'{context.s2}距离到期天数{P_days_to_expire}')
        
        if C_days_to_expire==0 or P_days_to_expire==0:
            logger.info(f"合约{context.s1}/{context.s2}到期:")
            next_month = (context.now + relativedelta(months=1)).strftime("%y%m")
            latest_trading_date = rqdatac.get_previous_trading_date(context.now.date(),n=1,market='cn')
            if_price = rqdatac.get_price(['000300.XSHG'], 
                                start_date=latest_trading_date, 
                                end_date=latest_trading_date, 
                                fields='close',
                                frequency='1d',
                                expect_df=False)[0]

            new_call_strike = get_OTM_strike('C', if_price, 1)
            new_put_strike = get_OTM_strike('P', if_price, 1)
            
            context.s1 = options.get_contracts(underlying='000300.XSHG', maturity=next_month, strike=new_call_strike)[0]
            context.s2 = options.get_contracts(underlying='000300.XSHG', maturity=next_month, strike=new_put_strike)[1]
            update_universe([context.s1, context.s2])
            context.rolled = True
            logger.info(f"移仓完成 {context.s1} @行权价{new_call_strike}/{context.s2} @行权价{new_put_strike}")

        # 初始化数据
        context.price_df_1 = rqdatac.get_price(context.s1, context.now.date(), context.now.date(), '1m').reset_index()
        context.price_df_2 = rqdatac.get_price(context.s2, context.now.date(), context.now.date(), '1m').reset_index()
        context.price_df_1['datetime'] = context.price_df_1['datetime'].dt.strftime('%H:%M:%S')
        context.price_df_2['datetime'] = context.price_df_2['datetime'].dt.strftime('%H:%M:%S')
        context.price_df_1 = context.price_df_1.set_index('datetime')
        context.price_df_2 = context.price_df_2.set_index('datetime')
        context.initialized = True
        context.has_opened = False  # 新增：开仓状态标记
        context.open_attempt_time = time(9, 35)  # 初始开仓尝试时间
        context.open_attempt_count = 0  # 开仓尝试次数计数器
        context.close_attempt_time = time(14, 25)  # 初始平仓尝试时间
        context.close_attempt_count = 0  # 平仓尝试次数计数器

    # 开仓逻辑（仅在未开仓时尝试）
    if not context.has_opened and normalized_time == context.open_attempt_time:
        success = try_trade(
            context,
            action="开仓",
            target_time=context.open_attempt_time,
            trade_func=lambda: [sell_open(context.s1, 3), sell_open(context.s2, 3)],
            trade_args=[]
        )
        
        if success:
            context.has_opened = True
            context.open_time = context.now
            logger.info("成功开仓，记录开仓状态")
        else:
            # 开仓失败，准备下一次尝试
            context.open_attempt_count += 1
            if context.open_attempt_count < 30:  # 最多尝试30分钟
                # 计算下一个尝试时间
                next_attempt_time = (datetime.datetime.combine(datetime.date.today(), context.open_attempt_time) + 
                                   datetime.timedelta(minutes=1)).time()
                context.open_attempt_time = next_attempt_time
                logger.info(f"开仓失败，将在{next_attempt_time}再次尝试")
            else:
                logger.warning("开仓尝试次数已达上限，放弃开仓")

    # 平仓逻辑（仅在已开仓时尝试）
    elif context.has_opened and normalized_time == context.close_attempt_time:
        success = try_trade(
            context,
            action="平仓",
            target_time=context.close_attempt_time,
            trade_func=lambda: [
                buy_close(context.s1, 3, close_today=True),
                buy_close(context.s2, 3, close_today=True)
            ],
            trade_args=[]
        )
        
        if success:
            context.has_opened = False
            logger.info("成功平仓，重置开仓状态")
        else:
            # 平仓失败，准备下一次尝试
            context.close_attempt_count += 1
            if context.close_attempt_count < 30:  # 最多尝试30分钟
                # 计算下一个尝试时间
                next_attempt_time = (datetime.datetime.combine(datetime.date.today(), context.close_attempt_time) + 
                                   datetime.timedelta(minutes=1)).time()
                context.close_attempt_time = next_attempt_time
                logger.info(f"平仓失败，将在{next_attempt_time}再次尝试")
            else:
                logger.warning("平仓尝试次数已达上限，放弃平仓")

def try_trade(context, action, target_time, trade_func, trade_args):
    """改进后的交易尝试函数（结合normalized_time判断）"""
    time_str = target_time.strftime("%H:%M:%S")
    
    try:
        # 获取成交量数据
        volume_1 = context.price_df_1.loc[time_str, 'volume']
        volume_2 = context.price_df_2.loc[time_str, 'volume']
        
        # 检查成交量是否满足条件
        if volume_1 > 0 and volume_2 > 0:
            trade_func(*trade_args)
            logger.info(f"{action}成功，时间: {time_str}")
            return True
            
        logger.info(f"{time_str} 成交量不足（{volume_1}/{volume_2}），继续尝试")
        return False
        
    except KeyError:
        logger.info(f"{time_str} 数据不存在，跳过")
        return False    

def after_trading(context):
    pass