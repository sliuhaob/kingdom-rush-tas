# Kingdom Rush TAS Lab

Experimental frame stepping and input replay for the original **Kingdom Rush, Windows Steam edition**. Requires your own game installation; no game binaries or assets are included.

初代《王国保卫战》Windows Steam 版的实验性 TAS 工具：暂停、逐帧推进、键鼠输入录制和回放，以及重复回放状态对比。当前是首关首波的同步原型，尚未验证完整关卡，也没有真正的存档／回档。

## 已验证的环境

| 项目 | 值 |
| --- | --- |
| 游戏 | 初代 Kingdom Rush，Steam App ID `246420` |
| 构建 | 游戏 `6.4.46`，Steam build `24662480` |
| 游戏引擎 | 游戏自带 LÖVE `0.10.2` / LuaJIT |
| 原版 EXE SHA-256 | `ebb4a3a9fd4fa6a30fb98e2b39fb32f0eff8630d47a3951b658339c26ce91e7b` |
| 工具环境 | Windows、Python 3.11+，仅使用 Python 标准库 |
| 实验条件 | 1024×768 窗口、每步 `1/60` 秒、种子 `246420`、全新实验存档 |

补丁脚本会拒绝不匹配的 EXE。更新后的游戏构建需要重新适配和验证，不能直接沿用本样本的兼容性结论。

## 开始使用

下载或克隆仓库，在仓库根目录打开 PowerShell。先找到原版目录：

```powershell
python tools/kr_lab.py discover
```

把下面的示例目录替换为 `discover` 输出的游戏目录。工具使用固定实验目录名 `kr1-test`，请保留 `--name` 的值：

```powershell
python tools/kr_lab.py inspect "C:/Program Files (x86)/Steam/steamapps/common/Kingdom Rush" --output lab/inventory.json
python tools/kr_lab.py prepare "C:/Program Files (x86)/Steam/steamapps/common/Kingdom Rush" --name kr1-test
python tools/instrument.py
python tools/audit.py
```

`prepare` 复制游戏并备份现有原版存档，检查复制文件的哈希，拒绝覆盖已有实验目录。`instrument.py` 只修改 `lab/kr1-test/game/Kingdom Rush.exe`；原版安装保持不变。制作补丁时请关闭实验游戏。

运行附带的首波输入样本：

```powershell
python tools/launch.py --replay examples/southport-probe.movie.json
python tools/control.py advance --count 3741 --output lab/replayed-state.json
python tools/control.py quit
```

每次启动使用新的 `kingdom_rush_tas_<随机标识>` 存档目录，通常位于 `%APPDATA%`。这个随机标识只用于隔离文件，与游戏种子无关。实验副本关闭 Steam 成就、新闻和 HTTP 服务。仓库不需要额外安装 LÖVE。

## 制作输入录像

```powershell
python tools/launch.py
python tools/control.py advance --count 300
python tools/control.py advance --count 1
python tools/control.py movie --output lab/my.movie.json
python tools/control.py quit
```

游戏从第 0 个更新帧暂停。在窗口内点击后，事件会排队，下一次推进才执行。`advance` 等待指定帧数全部完成；`step` 只提交推进请求。单次最多推进 36000 帧，只运行一个实验窗口和一个控制器。

常用命令：

| 命令 | 用途 |
| --- | --- |
| `pause` / `resume` | 暂停 / 连续运行；连续运行不保证墙钟实时速度 |
| `advance --count N` | 等待精确推进 N 帧，需要先暂停且无待执行步骤 |
| `snapshot --output lab/state.json` | 导出当前可观测状态 |
| `movie --output lab/my.movie.json` | 导出本次录制的输入；应在退出前保存 |
| `input --args JSON` | 给原生输入回调排队，JSON 包含 `name` 和 `args` |
| `quit` | 退出实验游戏 |

需要精确按键时，可以使用 Python 控制接口，避免不同 PowerShell 版本对 JSON 引号的处理差异：

```python
import sys
sys.path.insert(0, "tools")
from control import request, advance

request("input", name="keypressed", args=["w", "w", False])
advance(1)
request("input", name="keyreleased", args=["w", "w"])
advance(1)
```

本机录制样本中的物理 W 键只产生了 `textinput`，不能据此认定游戏收到了 `keypressed`；首波实际通过鼠标按钮启动。持续按键、鼠标轮询和其他技能输入仍需继续验证。

## 重复回放验证

公开样本和检查点均在 `examples/`，不依赖开发者的私有 `lab/` 记录。先准备好实验副本，再生成一次参考运行，随后独立启动三次进行比较：

```powershell
python tools/verify_replay.py --record-reference --runs 3 --output lab/verification-new
```

复用该参考记录继续检查时，输出到另一个新目录：

```powershell
python tools/verify_replay.py --reference lab/verification-new/reference.jsonl --runs 3 --output lab/verification-recheck
```

输出目录必须不存在，避免覆盖旧证据。第三次回放会改变推进分批并插入真实停顿。脚本比较六个检查点、完整记录和录像结束标志，并在每次完成后退出实验游戏。自定义样本可通过 `--movie` 和 `--checkpoints` 指定；检查点文件是严格递增的帧号数组，最后一项必须等于录像的 `end_frame`。

初始实测：3741 个外层更新帧、29 条输入事件；三次独立启动在六个检查点一致。该结论只覆盖启动到首波战斗，不代表通关。详见 [验证范围和结果](docs/validation.md)。

不启动游戏的工具测试：

```powershell
python -m unittest discover -s tests -v
```

GitHub Actions 只运行工具测试，不包含商业游戏，也不运行实际游戏回放。

## 同步方法与限制

- 替换外层循环，以 `1/60` 秒调用原始更新函数，每次更新对应一次绘制。输入通过原游戏的键鼠回调执行，不直接创建塔或修改金币、伤害和敌人血量。
- 保留原 PRNG 算法，固定虚拟时钟、Lua 和 LÖVE 的随机种子；**每次 `game.init` 前重设种子为 `246420`**。这是工具新增的实验初始条件，不是原版的默认行为。
- 仅在启动时固定种子的早期测试曾失步；采用进关重设种子的方式后，首波样本通过重复验证。这不保证其他关卡或其他机器不会失步。
- 状态比较覆盖实体可序列化组件（深度 6）、部分 store 字段、金币、生命、波次、tick、LÖVE RNG 状态，以及 Lua RNG 调用次数和累计摘要；不包含协程栈、C 层内存和所有隐藏状态。
- 当前没有真正的即时存档、回档、完整关卡验证、跨机器确定性保证或音视频导出。`snapshot` 是检查数据，不能恢复游戏。修改早先的输入后需要重新启动回放。
- 异步加载可能影响进关帧；样本固定坐标依赖指定的窗口与界面条件。
- 本项目是自定义运行器的实验原型，未获得 TAS 社区认证。展示作品时应注明构建、工具版本和固定种子规则。

## 仓库内容与致谢

`tools/` 是 Python 命令行工具，`runtime/` 是自行编写的 Lua 控制脚本，`examples/` 是输入样本与检查点，`tests/` 是不依赖游戏的测试。

`lab/`、游戏 EXE/DLL、游戏资源、原版脚本、存档、备份、日志和本机检测报告均不发布。安装后生成的实验游戏副本也不应作为本仓库的附件上传。

- [Lumi_Nox 的 Kingdom Rush 注入工具](https://github.com/MIO-456/Lumi_Nox/blob/main/games/kingdom_rush/patch.py)：可执行文件内 LÖVE 归档与更新循环接入的技术先例。
- [Lumi_Nox 游戏结构研究](https://github.com/MIO-456/Lumi_Nox/blob/main/docs/games/kingdom-rush-reverse-engineering.md)：实体、游戏 store 和内部接口的参考资料。其直接实体操作不作为本工具的输入实现。
- [Classic2TAS](https://github.com/CelesteClassic/Classic2TAS)：其他 LÖVE 游戏的 TAS 交互与输入时间线设计参考，不是本游戏的现成适配器。
- [TASVideos 工具要求](https://tasvideos.org/EmulatorResources/Requirements)与[玩家速通经验](https://www.speedrun.com/kr/forums/v637z)。

本仓库自行编写的工具、文档与输入样本采用 [MIT License](LICENSE)。该许可不覆盖 Kingdom Rush、LÖVE 或其他第三方软件。Kingdom Rush 属于 Ironhide Game Studio；本项目是非官方工具，需要用户自行安装游戏。
