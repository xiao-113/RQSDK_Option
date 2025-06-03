from rqalpha_plus.apis import *

__config__ = {
    "base": {
        "start_date": "20200101",
        "end_date": "20200221",
        'frequency': '1d',
        "accounts": {
            # 股指期权使用 future 账户
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
'''
策略类型：跨期组合策略（跨式套利+股指对冲）
操作标的​​：
IO2002C3900：沪深300股指看涨期权（行权价3900）
IO2002P3900：沪深300股指看跌期权（行权价3900）
IF2002：沪深300股指期货

核心动作​​（handle_bar函数）：
​​卖出开仓3手看涨期权​​（sell_open）
​​买入开仓3手看跌期权​​（buy_open）
​​买入开仓1手股指期货​​（buy_open）
'''

def init(context):
    context.s1 = 'IO2002C3900'
    context.s2 = 'IO2002P3900'
    context.s3 = 'IF2002'

    subscribe(context.s1)
    subscribe(context.s2)
    subscribe(context.s3)

    context.counter = 0
    print('******* INIT *******')


def before_trading(context):
    pass


def handle_bar(context, bar_dict):
    context.counter += 1
    if context.counter == 1:
        sell_open(context.s1, 3)
        buy_open(context.s2, 3)
        buy_open(context.s3, 1)


def after_trading(context):
    pass
