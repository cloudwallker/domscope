# Method / 方法说明

[English README](../README.md) · [中文说明](../README_ZH.md) · [Synthetic example / 合成演示](EXAMPLE.md)

DOMScope audits equality under three explicit representations. It produces descriptive statistics for an offline HTML collection; it does not infer whether a page is malicious. The representation rule is `domscope-v1`, and the report schema is `domscope-report-v1`.

DOMScope 比较三种明确定义的表示，输出离线数据集的描述性统计；它不判断页面是否恶意。规则版本为 `domscope-v1`，报告格式版本为 `domscope-report-v1`。

## 1. Input contract / 输入约定

The manifest is a UTF-8 JSON Lines file: one JSON object per sample. The directory containing the manifest is the dataset root.

| Field | Contract |
|---|---|
| `sample_id` | Required, unique string, 1–128 characters. ASCII letters, digits, `.`, `_` and `-` only; the first character must be a letter or digit. |
| `html_path` | Required relative path inside the dataset root. Absolute paths, traversal outside the root and escaping symlinks are rejected. |
| `split` | Required string: `train`, `val` or `test`. |
| `source` | Required nonempty dataset/source name without control characters. The included demonstration uses `synthetic`. |
| `label` | Integer `0` (benign), integer `1` (phishing), or `null`. Omission means `null`. Boolean and floating-point values are not labels. |
| `hostname` | Complete DNS hostname or `null`; omission means `null`. A URL, IP address or invalid hostname does not receive a joint fingerprint. A non-string, non-null value is a manifest error. |
| `encoding` | Optional supported text encoding name, default `utf-8`. Invalid names stop manifest validation. Decoding is strict; there is no automatic encoding guess. |

清单目录就是数据根目录。路径解析后不能逃出该目录；标签只能用整数 `0`、整数 `1` 或 `null`，不能用布尔值和浮点数。`hostname` 是完整主机名，不是 URL；缺失或格式非法不会使原始字节／DOM 指纹失效。

Default limits are **2 MiB per file, 5,000 manifest samples and 50,000 element nodes per page**. These are configurable workload limits, not measured performance guarantees. Oversized pages are excluded as whole samples. No shortened page or tree is used to compute a fingerprint.

## 2. Parsing and recovery / 解析与恢复

HTML is decoded using the declared encoding, then parsed by html5lib with its ElementTree builder, HTML namespaces enabled and `scripting=False`. The input must contain at least one explicit start-tag or empty-tag token. Blank input, plain text, comments alone and declarations alone are excluded, even if the parser could insert `html`, `head` and `body` nodes.

Recoverable HTML, such as an unclosed or mismatched tag, is accepted if a tree can be constructed. Parser warning codes and counts are retained. A warning does not assert that the page is useful, trustworthy or correctly labeled. Element counts and maximum depth describe the parsed element tree, including inserted elements; attributes are not element nodes.

纯空白、纯正文、仅注释或声明的文件被排除。可恢复的未闭合／错配 HTML 会接受并标记解析警告；解析器补出的元素参与结构统计。此处的“有效”只表示适合这次结构审计。

## 3. Three representations / 三类表示

| Representation | Exact meaning |
|---|---|
| `raw_hash` | SHA-256 of the original file bytes. Differences in encoding, line endings or whitespace can change it. |
| `dom_hash` | SHA-256 of the rule/configuration context and canonical ordered DOM representation. |
| `dom_host_hash` | SHA-256 of a bounded structured combination of the DOM representation and normalized complete hostname; `null` if the hostname is unavailable. |

The normalized DOM retains:

1. Element names and namespaces.
2. Parent/child boundaries and the order of element children.
3. Sorted attribute names and their namespaces, with attribute values removed.
4. Elements inserted by the parser and the parsed names of unknown elements.

Text, comments and the document type are removed. `script` and `style` elements remain as element nodes, with their text removed. The canonical JSON preserves structure and boundaries; it is not a bag of tags or a simple concatenation of names. DOM grouping checks the canonical representation rather than relying solely on a hash match.

Normalization happens **after tree construction**. Text or attribute values can affect that construction, so changing them is not guaranteed to preserve the DOM hash. Attribute order is discarded, but sibling order is retained. This is the tool's own definition, not a verified reproduction of a paper's input tensor.

规范 DOM 保留元素与属性名的命名空间、父子边界和元素顺序；属性名排序后保留，正文与属性值在建树之后去掉。某些值会影响建树，因此不能把“去掉属性值”理解成“任意改值都不会影响指纹”。

Hostnames are lowercased, have one trailing root dot removed, and are encoded to ASCII using Python's IDNA codec. All subdomains are preserved: `a.example` and `b.example` differ. The report records the Python version and normalization/parser configuration. Missing and invalid hostname states are explicit and are never collapsed into a shared empty-string joint fingerprint.

## 4. Cohorts and denominators / 有效集合与分母

Let `E_dom` be the successfully read and parsed samples, and `E_host` the subset of `E_dom` with a valid hostname.

| Report cohort | Comparisons |
|---|---|
| `cohorts.dom` / DOM-valid | Raw bytes and normalized DOM, both over `E_dom`. |
| `cohorts.host` / Hostname-valid | Raw bytes, normalized DOM and DOM + hostname, all recomputed over `E_host`. |

Each cohort includes its size and split counts. Training and target splits are restricted to that same cohort before overlap is computed. Hostname absence does not alter the main raw/DOM cohort. Do not rank percentages taken from different cohorts as though they shared a denominator.

Every ratio is stored as `{numerator, denominator, value}`. When the denominator is zero, `value` is `null`; the viewer shows not applicable instead of `0%`. Overlap is also not applicable when no eligible training samples exist. Unknown labels still participate in representation groups and overlap counts.

所有比例均带分子、分母和值。分母为零时值为 `null`，界面显示不适用；没有有效训练样本时，重合指标也不适用。主表在 `E_dom` 比较原始字节与 DOM；联合表示在 `E_host` 中与另外两类重新比较，不能混用两张表的分母。

## 5. Duplication and overlap / 重复与重合

For a selected cohort containing `N` samples and a representation with `U` unique groups:

| Metric | Numerator | Denominator |
|---|---|---|
| Redundant sample proportion | `N − U` | `N` |
| Duplicate-group sample proportion | Number of samples in groups of size at least 2 | `N` |
| Target → train overlap | Number of target samples whose fingerprint appears in training | Number of target samples |
| Extra DOM overlap | Number of target samples unseen as raw bytes in training but seen as DOM | Number of target samples unseen as raw bytes in training |

Both `val → train` and `test → train` are reported. Each target sample is counted once, regardless of how many copies occur in training. If there is no eligible training sample, overlap is not applicable, with `value: null` and `reason: no_training_samples`; the target denominator is still retained. If no target sample exists, overlap is also not applicable.

For example, a four-sample group contributes three redundant samples but four samples to duplicate-group coverage. These metrics answer different questions and are not interchangeable.

重合按目标样本计数，训练中有多份副本也只把该目标样本计一次。“原始不重合时的结构重合率”的分母仅包含原始字节没在训练中出现过的目标样本，不能用全部目标样本代替。

## 6. Label conflict / 标签冲突

Conflict metrics use **normalized DOM groups**. They are computed for all valid samples, for each split, and for each source. In each scope, remove unlabeled samples from the label counts and rebuild the within-scope counts. A group is mixed only if that scope contains both labels `0` and `1`.

Let `n(g, 0)` and `n(g, 1)` be the numbers of labeled samples in DOM group `g`, and `L` the number of labeled samples in the selected scope.

| Metric | Definition |
|---|---|
| Mixed DOM groups | Number of groups with `n(g, 0) > 0` and `n(g, 1) > 0`. |
| Conflict sample proportion | Labeled samples in mixed groups, divided by `L`. |
| Empirical conflict error | `sum_g min(n(g, 0), n(g, 1)) / L`. |

An unlabeled member of a mixed group does not enter either conflict numerator or denominator. If no labeled samples exist, both proportions are not applicable. A group may be mixed across the whole dataset but not within one split or source.

For label-count groups `(3, 1)`, `(1, 2)` and `(2, 0)`, empirical conflict error is `(1 + 1 + 0) / 9 = 2/9`; conflict sample proportion is `(4 + 3) / 9 = 7/9`. Adding unlabeled members changes neither ratio.

The empirical error describes the lowest fitting error **on these labeled samples** for a classifier restricted to this exact DOM representation and required to give identical decisions to identical representations. It is not a generalization error, population bound, trained test result, or error bound for a model that also uses hostnames or other inputs.

冲突比例只使用相应范围内的已标注样本。经验错误是对当前样本按组取多数类得到的描述性最优拟合误差，不是训练后测试成绩，更不是 SpecularNet 的错误下界。共享模板、错标和时间变化也可能形成混合标签组。

## 7. Failure policy / 失败处理

| Condition | Outcome |
|---|---|
| Invalid JSON, duplicate IDs, invalid field types, split/label errors, unsupported encoding names, unsafe paths or too many manifest samples | Stop the audit with an input error. |
| Missing/unreadable HTML, decoding failure, oversized file, excessive element count, no explicit element token or unrecoverable parse failure | Record the sample issue, exclude that sample, continue with other samples. |
| Recoverable HTML parse warning | Keep the sample and record warning codes/counts. |
| Missing or invalid hostname string | Keep the raw/DOM sample; no joint fingerprint. |
| All samples excluded | Fail rather than emit a misleading successful all-zero report. |
| Nonempty output directory | Refuse replacement; choose a new output directory. |
| Missing, incompatible or out-of-directory viewer artifact | Reject the report and ask for a newly generated valid report. |

The report writer stages the artifacts before publishing the output directory. The viewer reads those artifacts and does not reread or execute input HTML. The CLI uses a nonzero exit status for failure.

## 8. Outputs, reproducibility and sharing / 产物与复核

The output directory contains `summary.json`, `samples.csv`, `groups.csv`, `issues.csv`, `cases.jsonl` and `report.md`. `summary.json` records the rule/schema versions, parser/Python configuration, limits, counts, input digests, timing and relative artifact names. Reports identify input samples by ID and relative path, without embedding resolved local absolute paths.

`cases.jsonl` contains one record per accepted sample with `sample_id`, `raw_preview`, `dom_preview`, `raw_preview_truncated` and `dom_preview_truncated`. Each preview is at most 4,000 characters. These are display snippets; all hashes and groups use the full accepted content. CSV uses UTF-8 with a BOM and neutralizes formula-like spreadsheet cells. JSONL retains exact sample IDs and preview strings.

For identical input bytes, metadata, versions and configuration, fingerprints and descriptive statistics are reproducible. Run timestamps and durations can differ. A change in parser or rule context can change a DOM fingerprint; compare metadata before comparing reports across environments.

Reports are **not anonymized**. Previews, hostnames, source names and sample IDs may disclose private information even though local absolute paths are omitted. Inspect all six files before sharing real-data reports. The included static HTML is synthetic; it contains no JavaScript, external resources or forms.

展示片段的截断不会改变指纹和统计。报告不等于匿名数据：源码、主机名、来源和 ID 仍可能敏感，分享前应逐项检查。相同输入、版本及配置下应得到相同指纹和统计，时间戳与耗时可不同。

## 9. Scope and references / 范围与参考资料

DOMScope performs exact equality checks for its own representations. It does not train a model, fetch live websites, match approximately similar trees, evaluate detection accuracy, or establish the prevalence of overlap in real datasets. The synthetic example is a reproducible explanation of the calculations.

The research motivation comes from [Phishing the Phishers with SpecularNet: Hierarchical Graph Autoencoding for Reference-Free Web Phishing Detection](https://arxiv.org/abs/2603.01874), whose abstract describes domain-name and HTML-structure inputs, and [PhreshPhish: A Real-World, High-Quality, Large-Scale Phishing Website Dataset and Benchmark](https://arxiv.org/abs/2507.10854), which discusses leakage and realistic evaluation. These references motivate audit questions; they do not validate DOMScope's normalization as a reproduction of either system.

Implementation references: [html5lib documentation](https://html5lib.readthedocs.io/en/latest/) for HTML parsing and tree builders; [Streamlit dataframe documentation](https://docs.streamlit.io/develop/api-reference/data/st.dataframe) for interactive table display. Actual runtime versions belong to each generated report.

本项目是独立的表示审计实现，不声称首次发现泄漏、复现论文全部输入流程或提高了检测性能。真实数据中可能没有明显结构冲突，这仍是有效的审计结果。
