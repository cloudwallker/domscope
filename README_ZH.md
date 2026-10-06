# DOMScope

中文简介：离线 HTML 结构审计与证据查看器：比较跨划分重合和标签冲突，通过中英界面筛选样本、检查惰性源码并导出报告。

English summary: An offline HTML structure audit and evidence viewer with Chinese/English report navigation, sample filters, inert source previews and exports.

[English](README.md) | 中文

离线检查网页数据中的结构重合、跨划分重复与标签冲突。DOMScope 对保存好的 HTML 分别计算原始字节、规范 DOM、DOM＋完整 hostname 三类指纹，并将结果追溯到具体样本。

An offline audit tool for structural overlap and label conflicts in HTML datasets. DOMScope compares saved pages as raw bytes, normalized DOM trees, and DOM plus complete hostname, tracing results to individual samples.

CLI 在本机 CPU 上审计提供的 HTML 文件，只读 Streamlit 页面负责查看报告、筛选样本和对照源码片段。运行不需要 GPU、模型权重或 API Key。

![合成演示审计结果：原始字节、规范 DOM、DOM 加域名的测试集对训练集重合率依次为 25%、50%、25%](docs/images/demo-results.png)

*图片来自内置八页合成样本的真实 CLI 输出，用于展示工具行为，不代表真实网页中的频率或检测器性能。*

![domscope](docs/images/cartoon-infographic.png)

## 运行合成演示

需要 **Python 3.12 或更新版本**。在包含 `pyproject.toml` 的项目目录打开终端。

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
```

macOS / Linux：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

若 PowerShell 禁止激活脚本，可用 `.\.venv\Scripts\python.exe` 替代 `python`，用 `.\.venv\Scripts\streamlit.exe` 替代 `streamlit`；无需修改执行策略。

先生成报告，再打开查看器：

```bash
python -m domscope audit --manifest examples/manifest.jsonl --out outputs/demo
streamlit run app.py -- --report outputs/demo/summary.json
```

打开 Streamlit 输出的本地地址。界面默认中文，可切换英文；概览中比较两种样本口径，案例中筛选样本并查看片段，导出页提供报告下载。HTML 源码以文本显示。

**已有内容的输出目录会被拒绝。** 重复演示时改用新目录，例如 `outputs/demo-2`，同时把查看器路径改为 `outputs/demo-2/summary.json`。修改输入后需要重新运行 CLI；刷新查看器不会重新计算。

内置八份页面均为**合成演示数据**，`0` / `1` 标签为构造案例所设，不代表这些静态页面具有恶意行为。以下是可手算核对的预期值：

| 指标 | 预期分子 / 分母 |
|---|---:|
| 原始字节 test → train 重合率 | 1 / 4 = 25% |
| 规范 DOM test → train 重合率 | 2 / 4 = 50% |
| DOM＋hostname test → train 重合率 | 1 / 4 = 25% |
| 原始字节未重合的测试样本中，DOM 重合比例 | 1 / 3 ≈ 33.3% |
| 全部已标注样本的 DOM 经验冲突错误比例 | 1 / 8 = 12.5% |
| 冲突 DOM 组涉及的已标注样本比例 | 4 / 8 = 50% |

[演示说明](docs/EXAMPLE.md)列出了八个样本和计算过程。这些构造值展示审计方法，不代表真实数据中的出现频率或检测器性能。

## 审计自己的离线 HTML

在数据目录放置 UTF-8 编码的 JSON Lines 清单，每行一个样本：

```json
{"sample_id":"page-001","html_path":"html/001.html","split":"train","source":"my-dataset","label":0,"hostname":"login.example","encoding":"utf-8"}
```

`html_path` 相对清单目录，解析符号链接后也必须位于该目录内。`split` 取 `train`、`val` 或 `test`；`label` 取 `0`（良性）、`1`（钓鱼）或 `null`（未标注）。`hostname` 填完整 DNS 主机名，不填 URL。主机名缺失或非法时，样本仍参加原始字节和 DOM 审计，联合指纹不可用。省略 `label` 或 `hostname` 等同于 `null`；省略 `encoding` 时使用 `utf-8`。

```bash
python -m domscope audit --manifest data/manifest.jsonl --out outputs/my-audit
```

默认上限为单文件 2 MiB、单次 5,000 个样本、单页 50,000 个元素节点。可配置参数见 `python -m domscope audit --help`，完整输入约定与失败处理见[方法说明](docs/METHOD.md)。可恢复的 HTML 会被接受并记录解析警告；用于计算指纹的页面不会被静默截断。

## 如何读报告

**DOM 有效样本集**在同一批成功解析的样本上比较原始字节和 DOM。**hostname 有效样本集**取其中主机名有效的子集，在该子集重新比较三类表示。应在同一口径内比较百分比；主机名缺失不能悄悄改变主表原始字节／DOM 的分母。

重合率按目标样本计数：其指纹只要在训练集中出现过，该目标样本就计一次。分母为零时报告 `null`／不适用。未知标签仍参加重合和重复统计，但不参加标签冲突指标。规范化保留元素顺序、父子关系和属性名，在解析完成后去掉正文与属性值；修改内容仍可能影响解析器构建出的树。

每次运行写出六个文件：

| 产物 | 内容 |
|---|---|
| `summary.json` | 指标、分母、规则、版本与运行元数据 |
| `samples.csv` | 逐样本指纹、元数据与重合标记 |
| `groups.csv` | DOM 分组与成员样本 ID |
| `issues.csv` | 排除原因及其他已记录问题 |
| `cases.jsonl` | 样本 ID、源码／规范 DOM 片段与截断标记 |
| `report.md` | 便于阅读的审计摘要 |

每种片段最多 4,000 个字符，指纹仍使用完整的有效输入。报告可能包含敏感源码、主机名和样本标识，分享前应检查全部产物。CSV 导出会处理可能被表格软件执行为公式的单元格；精确的片段和样本 ID 文本可从 JSONL 读取。

## 开发与研究边界

运行本地检查：

```bash
python -m pytest
```

CI 配置在 Windows、Ubuntu 上使用 Python 3.12 执行该命令。

DOMScope 提供描述性数据审计。共享模板、标签错误或时间变化都可能产生混合标签组。经验冲突错误比例仅描述：在当前已标注样本上，只依赖这份规范 DOM、且对同组样本作相同判断的分类器，其经验最优拟合错误比例。它不是泛化误差、所有检测器的错误下界或 SpecularNet 的复现结果。

项目受 [SpecularNet](https://arxiv.org/abs/2603.01874) 的域名与 HTML 结构建模，以及 [PhreshPhish](https://arxiv.org/abs/2507.10854) 对泄漏和现实评估的讨论启发。DOMScope 自行定义规范化规则，不声称复现两篇论文的完整处理流程。具体规则与参考资料见 [METHOD.md](docs/METHOD.md)。
