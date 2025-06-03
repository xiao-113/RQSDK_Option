import rqalpha_plus
import rqalpha_mod_option
from datetime import date, time, timedelta
from dateutil.relativedelta import relativedelta
import rqdatac
from rqdatac import options

__config__ = {
    "base": {
        "start_date": "20200101",
        "end_date": "20250516",
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
    if_price = rqdatac.get_price(['510300.XSHG'], 
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
    else:
        step = 2.5
    
    strike = round(price / step) * step
    return round(strike, 6) #处理浮点数精度问题

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
    else:
        step = 0.5

    if direction == 'C':
        return round(get_nearest_strike(price) + n * step, 6)  # 看涨：行权价=ATM+n档
    else:
        return round(get_nearest_strike(price) - n * step, 6)  # 看跌：行权价=ATM-n档


def before_trading(context):
    pass

def handle_bar(context, bar_dict):
    context.counter += 1
    current_time = context.now.time()
    #logger.info(f'当前时间 {current_time}')
    # 标准化时间（去除微秒）
    normalized_time = current_time.replace(microsecond=0)

   
    if not context.initialized:


        if normalized_time == time(9, 45):
            # 验证合约是否到期
            if not all(rqdatac.instruments(c).days_to_expire() >= 0 for c in [context.s1, context.s2]):
            
                logger.info(f"合约{context.s1}/{context.s2}到期")
            
                # # 获取次月合约
                next_month = (context.now + relativedelta(months=1)).strftime("%y%m")
                latest_trading_date = rqdatac.get_previous_trading_date(context.now.date(),n=1,market='cn')
                if_price = rqdatac.get_price(['510300.XSHG'], 
                                    start_date=latest_trading_date, 
                                    end_date=latest_trading_date, 
                                    fields='close',
                                    frequency='1d',
                                    expect_df=False)[0]

                new_call_strike = get_OTM_strike('C', if_price, 1)
                new_put_strike = get_OTM_strike('P', if_price, 1)
                #print(f"认购/沽虚值1档行权价 {call_strike}/{put_strike}")
                
                #获取目标行权价的看涨和看跌期权合约
                context.s1 = options.get_contracts(underlying='510300.XSHG', maturity=next_month, strike=new_call_strike)[0]
                context.s2 = options.get_contracts(underlying='510300.XSHG', maturity=next_month, strike=new_put_strike)[1]
                
                update_universe([context.s1, context.s2]) #更新合约池
        
                context.rolled = True #标记合约更新

                logger.info(f"移仓完成 {context.s1} @行权价{new_call_strike}/{context.s2} @行权价{new_put_strike}")

            sell_open(context.s1, 3)
            sell_open(context.s2, 3)
            

        elif normalized_time == time(14, 30):
            buy_close(context.s1, 3, close_today=True)
            buy_close(context.s2, 3, close_today=True)

            logger.info(f"平今仓完成 {context.s1}/{context.s2}")


def after_trading(context):
    pass