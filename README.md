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

![image-20250603094551336](C:\Users\15158\AppData\Roaming\Typora\typora-user-images\image-20250603094551336.png)

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

   

