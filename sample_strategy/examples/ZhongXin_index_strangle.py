import rqalpha_plus
import rqalpha_mod_option
from datetime import date, time, timedelta
from dateutil.relativedelta import relativedelta
import rqdatac
# rqdatac.init()
import numpy as np
import pandas as pd

__config__ = {
    "base": {
        "start_date": "20210101",
        "end_date": "20250522",
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
            'volume_limit': False,
            'volume_percent': 0,
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
    context.s1 =  rqdatac.options.get_contracts(underlying='000300.XSHG', maturity=context.current_month, strike=call_strike)[0]
    context.s2 = rqdatac.options.get_contracts(underlying='000300.XSHG', maturity=context.current_month, strike=put_strike)[1]

    subscribe([context.s1, context.s2])

    context.hist_iv = []      # 存储每日IV
    context.hist_iv_hv = []   # 存储每日隐历差
    context.signal_1 = False

    context.hist_PCR = []     #存储历史PCR
    context.signal_2 = False
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
    # # 初始化历史数据存储（在initialize中定义）
    # if not hasattr(context, 'hist_iv'):
    #     context.hist_iv = []  # 存储每日IV
    # if not hasattr(context, 'hist_iv_hv'):
    #     context.hist_iv_hv = []  # 存储每日隐历差
    print(f"当前期权 { [context.s1, context.s2]}")
    # 获取当前日期期权IV（假设context.s1/s2为认购/认沽期权代码）
    iv_df_s1 = rqdatac.options.get_greeks(context.s1, start_date, end_date, fields='iv', model='implied_forward')['iv'][-1]
    iv_df_s2 = rqdatac.options.get_greeks(context.s2, start_date, end_date, fields='iv', model='implied_forward')['iv'][-1]
    print(f'当前期权隐含波动率 {iv_df_s1} {iv_df_s2}')
    # 修复：先检查是否为None或空DataFrame
    if iv_df_s1 is None or iv_df_s2 is None:
        raise ValueError("未获取到期权隐含波动率数据（接口返回None或空DataFrame）")
    current_iv = (iv_df_s1 + iv_df_s2) / 2
    
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
        
        # 信号逻辑：隐历差 <= 上界时开仓
        iv_hv_signal = (current_iv_minus_hv <= upper_bound)
    else:
        iv_hv_signal = False  # 数据不足不触发
    
    return iv_hv_signal

def sell_side_signal(context):
    pass

def PCR_signal(context):
    end_date = (context.now - timedelta(days=1)).strftime('%Y-%m-%d') #滞后一天用于生成信号
    start_date = (context.now - timedelta(days=61)).strftime('%Y-%m-%d')  # 多取数据防止缺失
    #获取认购 认沽成交量序列
    C_volume = rqdatac.get_price(context.s1, start_date, end_date, fields='volume')
    P_volume = rqdatac.get_price(context.s2, start_date, end_date, fields='volume')
    if len(P_volume) < 30 or len(C_volume) < 30:
        raise ValueError("合约成交量数据不足30日")
    
    current_P_volume = P_volume['volume'].values[-1]
    current_C_volume = C_volume['volume'].values[-1]
    current_PCR = current_P_volume / current_C_volume
    
    context.hist_PCR.append(current_PCR)
    if len(context.histPCR) > 30:
        context.hist_PCR.pop(0)

    # --- 3. 信号触发（需至少30日历史数据）---
    if len(context.hist_PCR) >= 30:
        rolling_mean = np.mean(context.hist_PCR)
        rolling_std = np.std(context.hist_PCR)
        upper_bound = rolling_mean + rolling_std
        lower_bound = rolling_mean - rolling_std

        # 信号逻辑：隐历差 <= 上界时开仓
        PCR_signal = (lower_bound <= current_PCR <= upper_bound)
    else:
        PCR_signal = False #数据不足无法触发

    return PCR_signal



def before_trading(context):
    context.signal_1 = iv_hv_signal(context)
    # logger.info(f'当前时间（盘前信号处理）{context.now}')
    print(f'今日信号：{context.signal_1}')
    # pass

def handle_bar(context, bar_dict):
    context.counter += 1
    current_time = context.now.time()
    #logger.info(f'当前时间 {current_time}')
    # 标准化时间（去除微秒）
    normalized_time = current_time.replace(microsecond=0)

    # def iv_hv_signal(context):
    #     # --- 1. 计算标的30日历史波动率（HV）---
    #     end_date = (context.now - timedelta(days=1)).strftime('%Y-%m-%d') #滞后一天用于生成信号
    #     start_date = (context.now - timedelta(days=61)).strftime('%Y-%m-%d')  # 多取数据防止缺失
        
    #     # 获取标的收盘价（确保30日数据完整）
    #     close_df = rqdatac.get_price('000300.XSHG', start_date, end_date, fields='close')
    #     if len(close_df) < 30:
    #         raise ValueError("标的收盘价数据不足30日")
        
    #     # 计算年化历史波动率（对数收益率标准差）
    #     close_prices = close_df['close'].values[-30:]  # 取最近30日
    #     log_returns = np.log(close_prices[1:] / close_prices[:-1])
    #     hv = log_returns.std() * np.sqrt(252)

    #     # --- 2. 获取期权IV并计算隐历差（滚动30日历史序列）---
    #     # 初始化历史数据存储（在initialize中定义）
    #     if not hasattr(context, 'hist_iv'):
    #         context.hist_iv = []  # 存储每日IV
    #     if not hasattr(context, 'hist_iv_hv'):
    #         context.hist_iv_hv = []  # 存储每日隐历差
        
    #     # 获取当前日期期权IV（假设context.s1/s2为认购/认沽期权代码）
    #     iv_df = rqdatac.options.get_greeks(
    #         [context.s1, context.s2],
    #         end_date,
    #         end_date,
    #         fields='iv',
    #         model='implied_forward'
    #     )
    #     # 修复：先检查是否为None或空DataFrame
    #     if iv_df is None or (hasattr(iv_df, 'empty') and iv_df.empty):
    #         raise ValueError("未获取到期权隐含波动率数据（接口返回None或空DataFrame）")
    #     current_iv = iv_df['iv'].mean()
        
    #     # 更新IV历史序列（最多保留30日）
    #     context.hist_iv.append(current_iv)
    #     if len(context.hist_iv) > 30:
    #         context.hist_iv.pop(0)
        
    #     # 计算当前隐历差并更新历史序列
    #     current_iv_minus_hv = current_iv - hv
    #     context.hist_iv_hv.append(current_iv_minus_hv)
    #     if len(context.hist_iv_hv) > 30:
    #         context.hist_iv_hv.pop(0)

    #     # --- 3. 信号触发（需至少30日历史数据）---
    #     if len(context.hist_iv_hv) >= 30:
    #         rolling_mean = np.mean(context.hist_iv_hv)
    #         rolling_std = np.std(context.hist_iv_hv)
    #         upper_bound = rolling_mean + rolling_std
            
    #         # 图片中的信号逻辑：隐历差 <= 上界时开仓
    #         context.iv_hv_signal = (current_iv_minus_hv <= upper_bound)
    #     else:
    #         context.iv_hv_signal = False  # 数据不足不触发
        
    #     return context.iv_hv_signal
    
   
    if not context.initialized:


        if normalized_time == time(9, 45):
            # 验证合约是否到期
            if not all(rqdatac.instruments(c).days_to_expire() >= 0 for c in [context.s1, context.s2]):
            
                logger.info(f"合约{context.s1}/{context.s2}到期")
            
                # # 获取次月合约
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
                #print(f"认购/沽虚值1档行权价 {call_strike}/{put_strike}")
                
                #获取目标行权价的看涨和看跌期权合约
                context.s1 = rqdatac.options.get_contracts(underlying='000300.XSHG', maturity=next_month, strike=new_call_strike)[0]
                context.s2 = rqdatac.options.get_contracts(underlying='000300.XSHG', maturity=next_month, strike=new_put_strike)[1]
                
                update_universe([context.s1, context.s2]) #更新合约池
        
                context.rolled = True #标记合约更新

                logger.info(f"切换到合约 {context.s1} @行权价{new_call_strike}/{context.s2} @行权价{new_put_strike}")


            # 只有离到期日大于等于5天开仓，规避临近到期日的升波风险
            if all(rqdatac.instruments(c).days_to_expire() >= 3 for c in [context.s1, context.s2]):
                #if context.signal_1: #如果发出隐历差开仓信号
                logger.info("发出隐利差开仓信号")
                sell_open(context.s1, 3)
                sell_open(context.s2, 3)
        

        elif normalized_time == time(14, 30):
            buy_close(context.s1, 3, close_today=True)
            buy_close(context.s2, 3, close_today=True)

            logger.info(f"平今仓完成 {context.s1}/{context.s2}")

def after_trading(context):
    pass