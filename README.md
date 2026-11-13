# Kingdom Rush TAS Lab

Experimental frame stepping and input replay for the original **Kingdom Rush, Windows Steam edition**. Requires your own game installation; no game binaries or assets are included.

初代《王国保卫战》Windows Steam 版的实验性 TAS 工具：暂停、逐帧推进、键鼠输入录制和回放、重复回放状态对比，以及**重演式回档、书签和输入分支**。回档从全新进程重放到指定帧，不是即时内存存档。整关同步的实测范围见 [验证记录](docs/validation.md)。

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
| `movie --output lab/my.movie.json` | 导出输入时间线，回放模式下也保留未来输入；退出前保存 |
| `input --args JSON` | 给原生输入回调排队，JSON 包含 `name` 和 `args` |
| `takeover` | 在暂停处接管回放并删除未来输入；通常使用下面带自动历史备份的 `rewind --edit` |
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

早期本机录制中的物理 W 键只产生了 `textinput`，首波实际通过鼠标按钮启动。当前回档验收另行通过控制接口验证了 W 按下／保持／释放和鼠标坐标恢复；这不等于验证了所有键位或技能效果。

## 回档、书签与分支

先暂停并等待所有推进结束。尚未执行的键鼠输入需要先推进执行；工具会拒绝静默丢弃它们。

```powershell
python tools/launch.py --replay examples/southport-normal.movie.json
python tools/control.py advance --count 3741
python tools/rewind.py save battle
python tools/control.py advance --count 1000
python tools/rewind.py load battle
```

`load` 会关闭当前实验进程，使用新的隔离存档重放到书签帧，然后核对实体、战斗状态、随机数摘要和键鼠按住状态。核对失败会返回错误、保留诊断报告，并停在暂停的回放模式。原输入和状态自动备份到 `lab/kr1-test/history/`；书签位于 `lab/kr1-test/bookmarks/`，同名书签不会被覆盖。

```powershell
# 后退 120 个外层更新帧，保留原来的未来输入
python tools/rewind.py back 120

# 回到指定帧，并从这里重新录制后续输入
python tools/rewind.py seek 3741 --edit

# 或从书签接管输入
python tools/rewind.py load battle --edit
```

默认保持回放模式，可继续 `advance`。加 `--edit` 后，旧时间线先归档，再删除目标帧及其之后的输入并开始录制；之前的输入和当前按住的键鼠状态保留。第 F 帧是已经完成 F 次更新、尚未执行编号为 F 的输入的位置。

任意 `seek`/`back` 目标通常没有旧状态可对比，因此报告中 `verified` 为 `null`，表示已重放到目标帧；书签 `load` 才具有保存时的状态用于核对。回档耗时随目标帧增长，启动画面和前段输入会重新出现，不能瞬间跳转。当前仅支持从全新实验存档开始的时间线。

录像必须包含匹配的运行器哈希；旧版录像和书签不能跨运行器版本直接载入。仓库附带的样本已更新版本条件并重新验证。

程序化接口也可直接调用 `rewind.save(name)`、`rewind.load(name, edit=True)` 和 `rewind.seek(frame, edit=True)`。启动器会拒绝重复启动受管理的实验窗口，控制器使用进程锁避免并发覆盖命令文件。

需要提前停止长批次推进或回档时，先在运行命令的终端按 `Ctrl+C`，再执行 `python tools/control.py quit`。前一步停止控制器并释放锁，后一步退出实验游戏；单独结束控制器不保证游戏中的待执行步骤立即取消。

实机回档验收（会启动和关闭实验游戏，需使用完整首关样本）：

```powershell
python tools/verify_rewind.py --output lab/verification-rewind-new
```

本机验收的 14 项检查全部通过，包括载入战斗书签后再次通关、后退并修改输入、按住键恢复，以及分支录像的独立回放。[验证摘要](docs/rewind-validation.json)

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

### 完整首关样本与结算修复

`southport-normal` 是 Southport 普通难度战役的完整输入，包含教程弹窗、补塔和援军。录像长度 26141 个外层更新帧、199 条输入事件，包含一段查看教程时的长暂停，未优化通关速度。

```powershell
python tools/verify_replay.py --movie examples/southport-normal.movie.json --checkpoints examples/southport-normal.checkpoints.json --require-victory --record-reference --runs 3 --output lab/verification-southport-full
```

旧版曾在三次回放中出现一次结算边界的 1 tick 差异，严格验证判为失败。加密检查发现第 26081 帧首先出现暂停状态不同。当前修复让 HUMP 计时器按注册顺序遍历固定快照，回调中新建的计时器下一轮才更新，避免在遍历期间改变哈希表造成不稳定更新顺序。游戏原有计时算术、回调和战斗逻辑保留；这是实验运行器的显式调度规则。检查点现为 **232 个**，包含第 25900–26100 帧的逐帧检查。[机器可读摘要](docs/southport-normal-validation.json)

修复后三次独立回放均通过 **232/232** 检查点，均为原生胜利、3 星、19 点生命、终点战斗 tick 16290。该结论限于上述本机环境和首关样本，不代表全部关卡或所有隐藏状态。

`--require-victory` 会核对游戏原生 `store.game_outcome`、所有波次结束标志和剩余生命。录像自带 `expected_outcome` 时也会自动执行这些检查，避免把“录像结束”误当成“关卡胜利”。跨回放的状态比较仍然保持严格。

不启动游戏的工具测试：

```powershell
python -m unittest discover -s tests -v
```

GitHub Actions 只运行工具测试，不包含商业游戏，也不运行实际游戏回放。

## 同步方法与限制

- 替换外层循环，以 `1/60` 秒调用原始更新函数，每次更新对应一次绘制。输入通过原游戏的键鼠回调执行，不直接创建塔或修改金币、伤害和敌人血量。
- 保留原 PRNG 算法，固定虚拟时钟、Lua 和 LÖVE 的随机种子；**每次 `game.init` 前重设种子为 `246420`**。这是工具新增的实验初始条件，不是原版的默认行为。
- 仅在启动时固定种子的早期测试曾失步；进关重设种子和稳定计时器调度是当前明确的实验条件。其他关卡和机器尚未验证。
- 状态比较覆盖实体可序列化组件（深度 6）、部分 store 字段、金币、生命、波次、tick、LÖVE RNG 状态，以及 Lua RNG 调用次数和累计摘要；不包含协程栈、C 层内存和所有隐藏状态。
- 回档通过重新启动和重放重建协程与随机数状态，不序列化协程栈或 C 层内存。`snapshot` 本身仍不能恢复游戏。没有即时内存存档、跨机器确定性保证或音视频导出。
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
