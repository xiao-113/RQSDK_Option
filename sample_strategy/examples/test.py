import rqalpha_plus
import rqalpha_mod_option
from datetime import date, time, timedelta
from dateutil.relativedelta import relativedelta
import rqdatac
from rqdatac import options

__config__ = {
    "base": {
        "start_date": "20220101",
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
    if_price = rqdatac.get_price(['000300.XSHG'], 
                         start_date=latest_trading_date, 
                         end_date=latest_trading_date, 
                         fields='close',
                         frequency='1d',
                         expect_df=False)[0]
    #if_price = current_minute('000300.XSHG', fields = 'close').iloc[-1, -1]
    print(f"价格{if_price}")
    strike = get_nearest_strike(if_price)
    #获取当月目标行权价的合约list
    option_list = options.get_contracts(underlying='000300.XSHG', maturity=context.current_month, strike=strike)
    
    #获取目标行权价的看涨和看跌期权合约
    context.s1 = option_list[0]
    context.s2 = option_list[1]
    
    # # 验证合约有效性
    # if not all(rqdatac.instruments(c) for c in [context.s1, context.s2]):
    #     raise ValueError(f"合约{context.s1}/{context.s2}不存在")
    # # 验证合约是否到期
    # if not all(rqdatac.instruments(c).days_to_expire() >= 0 for c in [context.s1, context.s2]):
    
    #     logger.info(f"合约{context.s1}/{context.s2}到期")
    
    #     # # 获取次月合约
    #     next_month = (context.now + relativedelta(months=1)).strftime("%y%m")
    #     # # if_next = f"IF{next_month}"
    #     # if_price = get_price('000300.XSHG', start_date = context.now.date() , end_date = context.now.date() ,fields='close')['close']
    #     # new_strike = get_nearest_strike(if_price)

    #     new_option_list = options.get_contracts(underlying='000300.XSHG', maturity=next_month, strike=strike)
    #     # 开新仓
    #     context.s1 = new_option_list[0]
    #     context.s2 = new_option_list[0]
    #     update_universe([context.s1, context.s2]) #更新合约池
   
    #     context.rolled = True #标记合约更新

    #     logger.info(f"移仓完成 {context.s1}/{context.s2} @行权价{strike}")

    subscribe([context.s1, context.s2])

    print('******* INIT *******')


def get_nearest_strike(price):
    """计算最接近的平值行权价（50点间距）"""
    return round(price / 50) * 50

def before_trading(context):
    pass

def handle_bar(context, bar_dict):
    context.counter += 1
    current_time = context.now.time()
    #logger.info(f'当前时间 {current_time}')
    # 标准化时间（去除微秒）
    normalized_time = current_time.replace(microsecond=0)

   
    if not context.initialized:
        # # # 获取IF当月合约价格作为基准
        # # if_contract = f"IF{context.current_month}"
        # if_price = history_bars('000300.XSHG', 1, '1d', 'close')[0]
        # strike = get_nearest_strike(if_price)
        
        # # 生成规范合约代码
        # context.s1 = f"IO{context.current_month}C{int(strike)}"
        # context.s2 = f"IO{context.current_month}P{int(strike)}"
        # subscribe(context.s1)
        # subscribe(context.s2)

        # 验证合约有效性
        # if not all(instruments(c) for c in [context.s1, context.s2]):
        #     #raise ValueError(f"合约{context.s1}/{context.s2}不存在")
        #     # # 获取次月IF合约价格
        #     next_month = (context.now + relativedelta(months=1)).strftime("%y%m")
        #     # if_next = f"IF{next_month}"
        #     if_price = history_bars('000300.XSHG', 1, '1d', 'close')[0]
        #     new_strike = get_nearest_strike(if_price)

        #     # 开新仓
        #     context.s1 = f"IO{next_month}C{int(new_strike)}"
        #     context.s2 = f"IO{next_month}P{int(new_strike)}"
        #     update_universe([context.s1, context.s2]) #更新合约池
        #     # sell_open(context.s1, 1)
        #     # sell_open(context.s2, 1)
        #     context.rolled = True

        #     logger.info(f"移仓完成 {context.s1}/{context.s2} @行权价{new_strike}")
            
        #subscribe([context.s1, context.s2])

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
                new_strike = get_nearest_strike(if_price)

                new_option_list = options.get_contracts(underlying='000300.XSHG', maturity=next_month, strike=new_strike)
                # 开新仓
                context.s1 = new_option_list[0]
                context.s2 = new_option_list[0]
                update_universe([context.s1, context.s2]) #更新合约池
        
                context.rolled = True #标记合约更新

                logger.info(f"移仓完成 {context.s1}/{context.s2} @行权价{new_strike}")

            sell_open(context.s1, 3)
            sell_open(context.s2, 3)
            #buy_open(context.s3, 1)

        elif normalized_time == time(14, 25):
            buy_close(context.s1, 3, close_today=True)
            buy_close(context.s2, 3, close_today=True)

def after_trading(context):
    pass