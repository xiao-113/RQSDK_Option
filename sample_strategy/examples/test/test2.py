from rqalpha_plus.apis import *
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

__config__ = {
    "base": {
        "start_date": "20220101",
        "end_date": "20250518",
        'frequency': '1d',
        "accounts": {
            "future": 1000000
        }
    },
    "mod": {
        "option": {
            "enabled": True,
            "exercise_slippage": 0.11
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
    context.s1 = None  # 延迟初始化看涨合约
    context.s2 = None  # 延迟初始化看跌合约
    context.counter = 0
    context.rolled = False
    context.initialized = False  # 标记是否完成首次建仓

def get_nearest_strike(price):
    """计算最接近的平值行权价（50点间距）"""
    return round(price / 50) * 50

# def get_expiry_date(contract):
#     """计算合约到期日（每月第三个周五）"""
#     year = 2000 + int(contract[2:4])
#     month = int(contract[4:6])
#     first_day = datetime(year, month, 1)
#     first_friday = first_day + timedelta(days=(4 - first_day.weekday()) % 7)
#     return first_friday + timedelta(days=14)

# def need_rollover(context):
#     """判断是否需要移仓"""
#     if context.rolled or not context.initialized:
#         return False
#     expiry_date = get_expiry_date(context.s1)
#     return (expiry_date - context.now).days <= 5

def handle_bar(context, bar_dict):
    
    context.counter += 1
    
    # 首次执行时初始化合约
    if not context.initialized:
        # # 获取IF当月合约价格作为基准
        # if_contract = f"IF{context.current_month}"
        if_price = history_bars('000300.XSHG', 1, '1d', 'close')[0]
        strike = get_nearest_strike(if_price)
        
        # 生成规范合约代码
        context.s1 = f"IO{context.current_month}C{int(strike)}"
        context.s2 = f"IO{context.current_month}P{int(strike)}"
        
        # 验证合约有效性
        if not all(instruments(c) for c in [context.s1, context.s2]):
            raise ValueError(f"合约{context.s1}/{context.s2}不存在")
            
        subscribe([context.s1, context.s2])
        sell_open(context.s1, 3)
        sell_open(context.s2, 3)
        context.initialized = True
        logger.info(f"初始建仓 {context.s1}/{context.s2} @行权价{strike}")
        return
    
    # # 移仓逻辑
    # if need_rollover(context):
    # # 获取次月IF合约价格
    next_month = (context.now + relativedelta(months=1)).strftime("%y%m")
    # if_next = f"IF{next_month}"
    if_price = history_bars('000300.XSHG', 1, '1d', 'close')[0]
    new_strike = get_nearest_strike(if_price)
    
    # # 平旧仓
    # buy_close(context.s1, 3)
    # buy_close(context.s2, 3)
    
    # 开新仓
    context.s1 = f"IO{next_month}C{int(new_strike)}"
    context.s2 = f"IO{next_month}P{int(new_strike)}"
    update_universe([context.s1, context.s2]) #更新合约池
    sell_open(context.s1, 3)
    sell_open(context.s2, 3)
    context.rolled = True
    
    logger.info(f"移仓完成 {context.s1}/{context.s2} @行权价{new_strike}")
    #plot("rollover", context.now)

def after_trading(context):
    pass