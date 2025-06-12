import datetime
import operator

import chardet
import dateutil.parser
import numpy as np
import pandas as pd
import rqdatac
from rqalpha.apis import *

__config__ = {
    "base": {
        'frequency': '1d',
      	"accounts": {
                "stock": 1000000
            }
    },
    "mod": {
        "sys_analyser": {
            "plot": True,
            "benchmark": "000300.XSHG"
        },
    }
}

'''
以下内容为用户可编辑内容
_FILE_PATH --》 权重文件路径
DATE_HEADER, ORDER_BOOK_ID_HEADER, 
SYMBOL_HEADER, WEIGHT_HEADER --》 权重文件的日期列，资产代码列，资产名称列，权重列的表头名称
'''
_FILE_PATH = "rqalpha_plus/examples/调仓权重样例.xlsx"
DATE_HEADER = 'TRADE_DT'
ORDER_BOOK_ID_HEADER = 'TICKER'
SYMBOL_HEADER = 'NAME'
WEIGHT_HEADER = 'TARGET_WEIGHT'
'''
以上内容为用户可编辑内容
'''

HEADERS = {
    DATE_HEADER, ORDER_BOOK_ID_HEADER, 
    SYMBOL_HEADER, WEIGHT_HEADER
}

def p2f(x):
    return float(str(x))
class HoldingWeightCSV:

    started_ons = property(operator.attrgetter('_started_ons'))
    order_book_ids = property(operator.attrgetter('_order_book_ids'))
    symbols = property(operator.attrgetter('_symbols'))
    ratios = property(operator.attrgetter('_ratios'))

    def __init__(self, from_file, encoding):
        try:
            self.df = pd.read_csv(
                from_file, 
                encoding=encoding, 
                parse_dates=[DATE_HEADER],
                converters={WEIGHT_HEADER:p2f}
            )
        except:
            try:
                self.df = pd.read_excel(
                    from_file, 
                    parse_dates=[DATE_HEADER],
                    converters={WEIGHT_HEADER:p2f}
                )
            except Exception as e:
                raise Exception(f"上传的文件不合法或者未知的编码, {e}")
        
        for arg in HEADERS:
            if arg not in self.df.columns:
                raise Exception(f"上传的文件不合法, 表格需要需要{HEADERS}作为表头")
        
        self.df = self.df[HEADERS]
        self._length = len(self.df[DATE_HEADER])
        self.started_ons = self.df[DATE_HEADER].tolist()
        
        for i, old_obid in zip(self.df.index, self.df[ORDER_BOOK_ID_HEADER]):
            if old_obid.endswith('.OF'):
                self.df.loc[i, ORDER_BOOK_ID_HEADER] = old_obid[:-3]
            elif not old_obid.endswith(('.XSHE', '.XSHG')):
                self.df.loc[i, ORDER_BOOK_ID_HEADER] = rqdatac.id_convert(old_obid)

        self.order_book_ids = self.df[ORDER_BOOK_ID_HEADER].tolist()
        self.symbols = self.df[SYMBOL_HEADER].tolist()
        self.ratios = self.df[WEIGHT_HEADER].tolist()

        t = self.df.groupby(DATE_HEADER).sum()
        cond = np.isclose(t[WEIGHT_HEADER], np.float(1))
        if len(t[cond]) != len(t):
            raise Exception(f"{','.join(t[[not c for c in cond]].index.format())}的权重和不为1")
    
    def __len__(self):
        return self._length

    def __str__(self):
        return f"started_ons: {self.started_ons}\n order_book_ids:{self.order_book_ids}"

    def get_weights_on(self, date):
        df:pd.DataFrame = self.df[self.df[DATE_HEADER] == pd.to_datetime(date).floor('D')]
        return df.round(6).to_dict(orient="records")

    @started_ons.setter
    def started_ons(self, values):
        if len(self) != len(values):
            raise Exception("参数长度不一致")
        for date in set(values):
            if get_next_trading_date(date + datetime.timedelta(days=-1), 1) != date:
                raise Exception(f"{date} 不是交易日")
        self._started_ons = values
        
    @order_book_ids.setter
    def order_book_ids(self, values):
        if len(self) != len(values):
            raise Exception("参数长度不一致")
        anachronistic = []
        
        fund_info = instruments(values)
        fund_info = {ins.order_book_id:ins for ins in fund_info}
        if len(fund_info) != len(set(values)):
            logger.warning(f"{','.join([v for v in values if v not in fund_info])}是无效资产代码")
        for i, obid in enumerate(values):
            info = fund_info[obid]
            date = self.started_ons[i]
            if (info.de_listed_date != '0000-00-00' and info.de_listed_date <= date):
                anachronistic.append(obid)
        if anachronistic:
            msg = f"{','.join(anachronistic)}的上市或者退市日期与所选调仓日期有逻辑错误（早于或者晚于）"
            raise Exception(msg)

    @symbols.setter
    def symbols(self, values):
        if len(self) != len(values):
            raise Exception("参数长度不一致")
        
    @ratios.setter
    def ratios(self, values):
        if len(self) != len(values):
            raise Exception("参数长度不一致")

# 在这个方法中编写任何的初始化逻辑。context对象将会在你的算法策略的任何方法之间做传递。
def init(context):
    possible_encoding = 'utf_8'
    test_str = []
    count = 0
    with open(_FILE_PATH, 'rb') as f:
        line = f.readline()
        while line and count < 50:  #Set based on lines you'd want to check
            test_str.append(line)
            count = count + 1
            line = f.readline()
        detect_result = chardet.detect(b''.join(test_str))
        possible_encoding = detect_result.get('encoding') or possible_encoding
    context.holding_weight_csv = HoldingWeightCSV(from_file=_FILE_PATH, encoding=possible_encoding)
    context.pending_actions = {}
    all_obids = list(context.holding_weight_csv.df[ORDER_BOOK_ID_HEADER].unique())    
    subscribe(all_obids)
    subscribe_event(EVENT.ORDER_UNSOLICITED_UPDATE, reorder)
    subscribe_event(EVENT.ORDER_CREATION_REJECT, reorder)

def before_trading(context):
    pass

def reorder(context, event):
    logger.warning(f"有订单创建/成交失败, 资产代码{event.order.order_book_id}，将在下一个交易日重新尝试")

def handle_bar(context, bar_dict):
    total_value = context.portfolio.total_value
    todays_records = context.holding_weight_csv.get_weights_on(context.now.date())
    if todays_records:
        context.pending_actions.clear()
        current_holding = set([pos.order_book_id for pos in get_positions()])
    
    for rec in todays_records:
        obid, weight = rec[ORDER_BOOK_ID_HEADER], rec[WEIGHT_HEADER]
        if obid in current_holding:
            current_holding.remove(obid)
        context.pending_actions[obid] = weight

    if todays_records and current_holding:
        for obid in current_holding:
            context.pending_actions[obid] = 0

    order_target_portfolio(pd.Series(context.pending_actions))

def after_trading(context):
    pass
