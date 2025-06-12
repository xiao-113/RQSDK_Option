from rqalpha_plus.apis import *

# 可以自己import我们平台支持的第三方python模块，比如pandas、numpy等。

# 在这个方法中编写任何的初始化逻辑。context对象将会在你的算法策略的任何方法之间做传递。
__config__ = {
    "base": {
        "accounts": {
            "future": 1000000,
        },
        "start_date": "20250513",
        "end_date": "20250518",
        'frequency': 'tick',
    },
    'mod': {
        # 模拟撮合模块
        'sys_simulation': {
            # 撮合方式。current_bar 当前 bar 收盘价成交，next_bar 下一 bar 开盘价成交，best_own 己方最优价格成交（tick 回测使用）
            # best_counterparty 对手方最优价格成交（tick 回测使用），last 最新价成交（tick 回测使用）
            'matching_type': 'best_own'
        }
    }
}


def init(context):
    # context内引入全局变量s1
    context.s1 = "IF2506"
    context.fired = False

    # 初始化时订阅合约行情。订阅之后的合约行情会在handle_tick中进行更新。
    subscribe(context.s1)
    # 实时打印日志
    logger.info("RunInfo: {}".format(context.run_info))


# before_trading此函数会在每天策略交易开始前被调用，当天只会被调用一次
def before_trading(context):
    pass


# 你选择的期货数据更新将会触发此段逻辑
def handle_tick(context, tick):
    # 开始编写你的主要的算法逻辑
    # tick 可以获取到当前订阅的合约的快照行情
    # context.portfolio 可以获取到当前投资组合信息
    if not context.fired:
        logger.info(tick)
        buy_open(context.s1, 1)
        context.fired = True


def after_trading(context):
    pass
