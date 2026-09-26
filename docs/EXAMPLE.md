# Eight-sample synthetic example / 八样本合成演示

[English README](../README.md) · [中文说明](../README_ZH.md) · [Method / 方法](METHOD.md)

All eight HTML pages are self-contained synthetic examples. The labels are assigned to demonstrate grouping and are not judgments about malicious behavior. There are no scripts, forms or external resources.

八个页面均为自制静态合成样本。标签仅用于构造审计案例，不表示页面具有恶意行为；页面不含脚本、表单或外部资源。

## Samples / 样本

`R1`–`R7` and `D1`–`D5` below are explanatory group names, **not actual fingerprint values**. The sample named `D1` belongs to the illustrative DOM group `D4`.

下表的 R、D 编号是说明用等价组，不是实际哈希值。注意样本 ID `D1` 与说明中的 DOM 组 `D1` 含义不同。

| ID | Split / 划分 | Label / 标签 | Raw group / 字节组 | DOM group / 结构组 | Hostname |
|---|---|---:|---|---|---|
| [A1](../examples/html/A1.html) | train | 0 | R1 | D1 | a.example |
| [A2](../examples/html/A2.html) | train | 0 | R2 | D1 | b.example |
| [B1](../examples/html/B1.html) | train | 0 | R3 | D2 | docs.example |
| [C1](../examples/html/C1.html) | train | 1 | R4 | D3 | c.example |
| [A3](../examples/html/A3.html) | test | 1 | R5 | D1 | other.example |
| [A4](../examples/html/A4.html) | test | 0 | R1 | D1 | a.example |
| [D1](../examples/html/D1.html) | test | 1 | R6 | D4 | new.example |
| [E1](../examples/html/E1.html) | test | 0 | R7 | D5 | help.example |

A1 and A4 have identical file bytes and hostname. A2 and A3 change text and attribute values while retaining the same parsed element/attribute-name structure as A1. A2 also reorders two attributes. B1, C1, D1 and E1 each have a different DOM from every other group.

A1 与 A4 的文件字节、hostname 均相同。A2、A3 修改了正文和属性值，但保留相同的解析后元素／属性名结构；A2 还重排了两个属性。其余四个样本的 DOM 各不相同，也不与 A 组相同。

## Hand calculations / 手算预期

There are eight DOM-valid and hostname-valid samples, with four in training and four in test. Thus both cohorts contain exactly the same samples in this example. There is no validation split, so `val → train` ratios are not applicable.

八个样本在两种口径内均有效；训练、测试各四个，无验证集。因此本例两种口径的分母相同，`val → train` 为不适用。

| Test sample / 测试样本 | Raw seen in train / 字节已见 | DOM seen in train / DOM 已见 | Joint seen in train / 联合已见 |
|---|---|---|---|
| A3 | No / 否 | Yes / 是 | No / 否 |
| A4 | Yes / 是 | Yes / 是 | Yes / 是 |
| D1 | No / 否 | No / 否 | No / 否 |
| E1 | No / 否 | No / 否 | No / 否 |

Expected overlap follows directly from those four rows:

| Metric / 指标 | Calculation / 计算 |
|---|---|
| Raw test → train / 字节重合 | A4 only: `1/4 = 25%` |
| DOM test → train / 结构重合 | A3 and A4: `2/4 = 50%` |
| DOM + hostname test → train / 联合重合 | A4 only: `1/4 = 25%` |
| Extra DOM overlap / 原始不重合时的结构重合 | A3 among A3, D1, E1: `1/3 ≈ 33.3%` |

The last denominator is **three raw-unseen test samples**, not all four test samples. A3 matches two training members by DOM, but is counted only once.

最后一项的分母是原始字节未见的三个测试样本，不能写成四个。A3 虽与两个训练样本共享 DOM，也只计一次。

Across all eight samples:

| Representation / 表示 | Unique groups / 唯一组数 | Redundant / 冗余比例 | In duplicate groups / 重复组覆盖比例 |
|---|---:|---:|---:|
| Raw bytes / 原始字节 | 7 | `1/8` | `2/8` |
| Normalized DOM / 规范 DOM | 5 | `3/8` | `4/8` |
| DOM + hostname | 7 | `1/8` | `2/8` |

Only the DOM group containing A1, A2, A3 and A4 is mixed: it has three label-0 members and one label-1 member. Consequently, the number of mixed groups is `1`, the conflict sample proportion is `4/8 = 50%`, and the empirical conflict error is `min(3, 1)/8 = 1/8 = 12.5%`.

只有 A1、A2、A3、A4 所在组混合了两种标签：三个 `0`、一个 `1`。混合组数为 `1`，冲突涉及比例为 `4/8 = 50%`，经验冲突错误比例为 `min(3, 1)/8 = 1/8 = 12.5%`。

Scope matters: within training the A group has only label `0`, so train conflict metrics are `0/4`. Within test, A3 and A4 form a mixed group, giving conflict coverage `2/4` and empirical error `1/4`. The sole source is `synthetic`, so that source's metrics equal the all-sample metrics.

范围会改变结果：训练范围内 A 组只有标签 `0`，两个冲突比例均为 `0/4`；测试范围内 A3、A4 构成混合组，冲突涉及比例为 `2/4`，经验错误为 `1/4`。唯一来源是 `synthetic`，该来源的结果与全部样本结果相同。

## A short walkthrough / 简短演示流程

After following the installation commands in the README, run:

```bash
python -m domscope audit --manifest examples/manifest.jsonl --out outputs/demo
streamlit run app.py -- --report outputs/demo/summary.json
```

Use a new output directory for each rerun; a nonempty directory is refused. 按 README 安装后执行上述命令；每次重复运行应换用新的输出目录。

1. In the overview, compare `1/4`, `2/4`, `1/4` and note the cohort sizes. 在概览核对三类重合率与各自口径。
2. Inspect A3: its bytes and hostname are unseen in training, but its DOM is shared with A1 and A2. 查看 A3：字节和主机名未见，DOM 与训练中的 A1、A2 相同。
3. Inspect A4: it is an exact byte copy of A1 with the same hostname. 查看 A4：它与 A1 的字节及主机名均相同。
4. Compare the A-group source snippets and normalized DOM, then inspect its mixed labels. 对照 A 组源码片段、规范 DOM 与标签。
5. Inspect the exported sample/group rows and recompute the counts above. 从导出的逐样本与组明细重新核对计数。

The example illustrates exact duplication, benign template sharing and mixed labels within one representation. It does not establish how often these occur in real data, and its empirical conflict calculation is not a trained detector's evaluation.

本例展示字节重复、良性页面共享结构以及同表示不同标签三种情形；不证明它们在真实数据中出现的频率，也不产生训练后检测性能结论。
