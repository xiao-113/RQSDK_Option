### 环境、组件配置

1. 装Ricequant SDK配件包

   ```bash
   pip install -i https://pypi.tuna.tsinghua.edu.cn/simple rqsdk
   ```

2. 切换到已经装好 Ricequant SDK 的虚拟环境

3. 在配置好Ricequant SDK的环境中通过下列命令来更新到最新的许可证

   ```bash
   rqsdk license
   ```

   该命令是交互式的，您只需要根据命令提示填入所需信息即可。配置完毕后可以调用`rqsdk license info`来查看刚配置的许可证信息。

4. 安装回测引擎

   ```
   rqsdk install <安装代码>
   
   ```

   ![image-20250603093943921](C:\Users\15158\AppData\Roaming\Typora\typora-user-images\image-20250603093943921.png)

*注意：在安装某个产品时，如果上表中已说明组件依赖关系，则其所依赖的组建都会被同时安装上。例如运行了上述的命令安装了 RQAlpha Plus，那么 RQFactor 和 RQOptimizer 也会同时被装上。*



### 回测简易流程

1. 更新基础数据（所有回测均需要用到，所以需要每次更新）和目标数据

```bash
rqsdk update-data
```

可通过rqsdk update-data --help 查看更新选项

```bash
Usage: rqsdk update-data [OPTIONS]

更新运行回测所需的历史数据

例如:

* 更新日线数据:  rqsdk update-data --base --enable-bjse

* 更新股票、期权分钟数据:  rqsdk update-data --minbar stock --minbar option

* 更新鸡蛋期货合约tick数据:  rqsdk update-data --tick JD

* 更新豆粕1985及其合约的衍生品tick数据:  rqsdk update-data --tick M1905 --with-derivatives

* 更新已下载的分钟线和tick数据:  rqsdk update-data --smart

Options:

  -d, --data-bundle-path DIRECTORY
                                  bundle 目录，默认为 <用户目录>\.rqalpha-plus
  --base                          更新基础数据及日线，注意: 任何回测都需要依赖基础数据
  --minbar TEXT                   更新分钟线数据，可选的参数值有 [stock, futures, fund, index, option, convertible] 或
                                  underlying_symbol 或 order_book_id
  --tick TEXT                     更新tick数据，可选的参数值有 [stock, futures, fund, index, option, convertible] 或
                                  underlying_symbol 或 order_book_id
  --with-derivatives              更新分钟线和 tick 时同时更新选择的合约的衍生品数据
  -c, --concurrency INTEGER       并行的线程数量，需要低于 rqdatac 的最大可用连接数
  --smart                         检索本地已经存在的分钟线和 tick 数据，增量更新对应品种的数据和日线数据
  --rebuild                       将指定的合约 h5 文件从头进行更新，仅对 --minbar、--tick生效
  --help                          Show this message and exit.
```



例如：更新回测基础数据及000001.XSHE的分钟线数据

```bash
rqsdk update-data --base --minbar 000001.XSHE
```

在上述命令执行完毕后，将会在`<用户目录>\.rqalpha-plus\bundle`目录下创建历史行情数据的缓存文件。

*这是 Ricequant SDK 管理缓存文件的默认目录，您可以通过参数`-d <完整路径>`进行定制化。在回测时同样可以指定`-d`参数来更改 RQAlpha Plus 读取回测历史文件的位置。*

2. 准备进行一次回测

```bash
rqalpha-plus run -f 环境中策略文件所在文件夹/<策略文件名称>.py <-s 2018-01-01 -e 2018-12-31 -fq 1m --plot --account stock 100000>
```

<...>中为参数配置 具体可用`rqalpha-plus run --help`命令查看，参数也可以直接在策略文件中`__config__`模块配置。

可以用官方提供的样例策略尝试，策略编写、数据调取方法具体参照https://www.ricequant.com/doc/rqalpha-plus/tutorial.html RQAlpha Plus - 回测框架使用教程及https://www.ricequant.com/doc/rqalpha-plus/api/RQAlphaPlus API 手册





### 期权策略回测流程

1. 环境、许可证配置

2. 更新基础回测数据，标的数据和要用到的标的衍生品数据

   ```bash
   rqsdk update-data --base --minbar 000300.XSHG --with-derivatives
   ```

3. 运行策略回测并可视化

   ```bash
   rqalpha-plus run -f examples/index_option_straddle.py -p
   ```

   

**期权发单接口**

- buy_open：多头开仓，接受合约代码、交易数量、限价单价格（可选）为参数
- sell_close：多头平仓，接受合约代码、交易数量、限价单价格（可选）、是否平今（可选）为参数

```python
buy_open("RB2010", 2)

sell_close("RB2010", 1, price=3100, close_today=True)
```

- sell_open：空头开仓，参数与 `buy_open` 相同
- buy_close：空头平仓，参数与 `sell_close` 相同

具体参数设置可参照API文档

https://www.ricequant.com/doc/rqalpha-plus/api/api/order_api.html

**回测时账户设置**：期权持仓分属股票（STOCK）和期货（FUTURE）账户，其中 ETF 期权属于股票账户，商品期权和股指期权属于期货账户。



**行权方式**

- 行权采用现金交割，即将行权产生的盈利或亏损直接计入现金中。
- 主动行权：期权可通过 [`exercise` 接口 (opens new window)](https://www.ricequant.com/doc/rqalpha-plus/api/api/order_api.html#exercise)主动行权，该函数接收合约代码和行权数量两个参数

```python
exercise("M1905C2350", 2)
```

- 被动行权：期权持有至到期日将会触发自动行权。对于权利方（多头）持仓，若 RQAlphaPlus 判定行权可以盈利，则触发自动行权，否则仓位作废；而义务方（空头）持仓会在 RQAlphaPlus 判定对手方可以盈利时触发行权。

- 行权滑点：为了模拟真实市场中行权委托与到账间这段时间段内底层标的价格发生波动带来的风险，RQAlphaPlus 提供了行权滑点功能，通过配置行权滑点，可以使得行权盈利的判定更为严苛。对于认购期权，0.1 的滑点代表即使在交割日标的价格降低 10%，本次行权仍然能盈利；而对于认沽期权，代表在交割日即使标的价格上涨 10%，仍然能盈利。默认行权滑点为 0 。行权滑点只会影响自动行权的判定，而不影响行权交割的金额。通过策略文件

  xxx.py种__config__模块设置

  ```python
  {"mod": {"option": {"exercise_slippage": 0.1}}}
  ```

  

  **权利金和保证金**

  - 权利方（多头）：开仓需要缴纳权利金，该过程与股票的开仓类似
  - 义务方（空头）：开仓会收取权利金并付出保证金，保证金会被冻结（类似期货开仓）；同时义务方也采取逐日盯市制度，每日盘后结算，浮盈浮亏将被计入现金。
