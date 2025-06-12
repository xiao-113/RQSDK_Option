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
        "start_date": "20250501",
        "end_date": "20250603",
        'frequency': '1m',
        "accounts": {
        	# ETF期权使用 stock 账户
            "stock": 1000000
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
    if_price = rqdatac.get_price(['510300.XSHG'], #华泰柏瑞300ETF
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
    context.s1 =  options.get_contracts(underlying='510300.XSHG', maturity=context.current_month, strike=call_strike)[0]
    context.s2 = options.get_contracts(underlying='510300.XSHG', maturity=context.current_month, strike=put_strike)[1]

    subscribe([context.s1, context.s2])

    print('******* INIT *******')

def get_nearest_strike(price):
    """计算ETF期权最接近的平值行权价（需根据具体ETF调整间距）
    
    参数：
        price: ETF当前价格（如510300.SH的实时价格）
    返回：
        最接近交易所规则的行权价
    
    沪深300ETF期权（510300）行权价间距规则：
    | 价格区间      | 间距 |
    |--------------|------|
    | 3元以下      | 0.05 |
    | 3元至5元     | 0.1  |
    | 5元至10元    | 0.25 |
    | 10元至20元   | 0.5  |
    | 20元至50元   | 1.0  |
    | 50元以上     | 2.5  |
    """
    if price < 3:
        step = 0.05
    elif 3 <= price < 5:
        step = 0.1
    elif 5 <= price < 10:
        step = 0.25
    elif 10 <= price < 20:
        step = 0.5
    elif 20 <= price < 50:
        step = 1.0
    elif 50 <= price <100:
        step = 2.5
    else:
        step = 5
    
    strike = round(price / step) * step
    return round(strike, 2) #处理浮点数精度问题

def get_OTM_strike(direction, price, n): 
    '''
    计算n挡 call/put虚值期权行权价
    '''
    if price < 3:
        step = 0.05
    elif 3 <= price < 5:
        step = 0.1
    elif 5 <= price < 10:
        step = 0.25
    elif 10 <= price < 20:
        step = 0.5
    elif 20 <= price < 50:
        step = 1.0
    elif 50 <= price <100:
        step = 2.5
    else:
        step = 5

    if direction == 'C':
        return round(get_nearest_strike(price) + n * step, 2)  # 看涨：行权价=ATM+n档
    else:
        return round(get_nearest_strike(price) - n * step, 2)  # 看跌：行权价=ATM-n档


def before_trading(context):
    context.initialized = False #每日盘前记号初始化
    context.order_current_month = context.now.strftime("%y%m")
    print(f'当前月份{context.order_current_month}')
    
    # 检查合约状态
    C_days_to_expire = rqdatac.instruments(context.s1).days_to_expire(context.now.date())
    P_days_to_expire = rqdatac.instruments(context.s2).days_to_expire(context.now.date())
    print(f'{context.s1}距离到期天数{C_days_to_expire}')
    print(f'{context.s2}距离到期天数{P_days_to_expire}')
    # 如果到期，到期月份切换到下月
    if C_days_to_expire <= 0 or P_days_to_expire <= 0:
        logger.info(f"合约{context.s1}/{context.s2}到期:")
        next_month = (context.now + relativedelta(months=1)).strftime("%y%m")
        context.order_current_month = next_month #标记当前合约到期月份
    else:
        context.order_current_month = (rqdatac.instruments(context.s1, market='cn').maturity_date).replace("-", "")[2:6]
    print(f'当前合约到期月份 {context.order_current_month}')

    #切换合约：虚值一档
    latest_trading_date = rqdatac.get_previous_trading_date(context.now.date(),n=1,market='cn')
    if_price = rqdatac.get_price(['510300.XSHG'], 
                        start_date=latest_trading_date, 
                        end_date=latest_trading_date, 
                        fields='close',
                        frequency='1d',
                        expect_df=False)[0]
    #if_price = current_minute('000300.XSHG', fields = 'close').iloc[-1, -1]
    print(f"最近一个交易日标的价格{if_price}")
    call_strike = get_OTM_strike('C', if_price, 1)
    put_strike = get_OTM_strike('P', if_price, 1)
    # print(f"认购/沽虚值1档行权价 {call_strike}/{put_strike}")
    #获取目标行权价的看涨和看跌期权合约
    context.s1 =  options.get_contracts(underlying='510300.XSHG', maturity=context.order_current_month, strike=call_strike)[0]
    context.s2 = options.get_contracts(underlying='510300.XSHG', maturity=context.order_current_month, strike=put_strike)[1]
    print(f'今日目标认购/沽虚值1档合约 {context.s1} @行权价{call_strike}/{context.s2} @行权价{put_strike}')
    update_universe([context.s1, context.s2])
    context.rolled = True
    logger.info(f"移仓完成 {context.s1} /{context.s2}")
    

    #信号计算
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
    
    # 初始化逻辑
    if normalized_time == time(9, 31) and not context.initialized: 
        # #切换合约
        # latest_trading_date = rqdatac.get_previous_trading_date(context.now.date(),n=1,market='cn')
        # if_price = rqdatac.get_price(['000300.XSHG'], 
        #                     start_date=latest_trading_date, 
        #                     end_date=latest_trading_date, 
        #                     fields='close',
        #                     frequency='1d',
        #                     expect_df=False)[0]
        # #if_price = current_minute('000300.XSHG', fields = 'close').iloc[-1, -1]
        # print(f"最近一个交易日标的价格{if_price}")
        # call_strike = get_OTM_strike('C', if_price, 1)
        # put_strike = get_OTM_strike('P', if_price, 1)
        # # print(f"认购/沽虚值1档行权价 {call_strike}/{put_strike}")
        # #获取目标行权价的看涨和看跌期权合约
        # context.s1 =  options.get_contracts(underlying='000300.XSHG', maturity=context.current_month, strike=call_strike)[0]
        # context.s2 = options.get_contracts(underlying='000300.XSHG', maturity=context.current_month, strike=put_strike)[1]
        # print(f'今日目标认购/沽虚值1档合约 {context.s1} @行权价{call_strike}/{context.s2} @行权价{put_strike}')
        # # update_universe([context.s1, context.s2])

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
    # if context.signal_4 and not context.has_opened and normalized_time == context.open_attempt_time:
        success = try_trade(
            context,
            action="开仓",
            target_time=context.open_attempt_time,
            trade_func=lambda: [sell_open(context.s1, 100), sell_open(context.s2, 100)],
            trade_args=[]
        )
        
        if success:
            context.has_opened = True
            context.open_time = context.now
            logger.info(f"成功开仓{context.s1} / {context.s2}，记录开仓状态")
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
                buy_close(context.s1, 100, close_today=True),
                buy_close(context.s2, 100, close_today=True)
            ],
            trade_args=[]
        )
        
        if success:
            context.has_opened = False
            logger.info(f"成功平仓{context.s1} / {context.s2}，重置开仓状态")
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