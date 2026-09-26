"""A read-only, local report viewer. Run the audit CLI before opening this app."""
import argparse
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

from domscope.report import ReportError
from domscope.viewer import load_bundle


st.set_page_config(page_title="DOMScope · Structure Audit", page_icon="🔎", layout="wide")
st.markdown("""<style>
.block-container {max-width:1240px;padding-top:2.5rem;padding-bottom:3rem;}
[data-testid="stMetric"] {background:white;border:1px solid #e0e7eb;border-radius:12px;padding:16px 20px;}
[data-testid="stMetricValue"] {font-variant-numeric:tabular-nums;}
h1 {letter-spacing:-.035em;font-weight:750!important;}
.eyebrow {color:#11786a;font-size:12px;font-weight:700;letter-spacing:.15em;margin-bottom:12px;}
.subhead {color:#617482;font-size:17px;line-height:1.65;max-width:760px;margin-bottom:22px;}
.local-badge {display:inline-block;color:#11786a;background:#e5f3ed;border:1px solid #c7e4d9;padding:7px 12px;border-radius:30px;font-size:12px;letter-spacing:.07em;}
[data-testid="stTabs"] {margin-top:20px;}
@media(max-width:600px){.block-container{padding:1.2rem 1rem;}h1{font-size:2rem!important;}.subhead{font-size:15px;}}
</style>""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## DOMScope")
    st.caption("OFFLINE STRUCTURE AUDITING")
    language = st.selectbox("语言 / Language", ["中文", "English"], key="language")


def t(zh, en):
    return zh if language == "中文" else en


def fmt(metric):
    if metric["value"] is None:
        return t("不适用", "N/A")
    return f"{metric['value']:.1%} · {metric['numerator']}/{metric['denominator']}"


parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--report", default=str(Path(__file__).parent / "outputs/demo/summary.json"))
args, _ = parser.parse_known_args()
with st.sidebar:
    st.divider()
    report_path = st.text_input(t("报告文件", "Report file"), args.report, key="report_path")
    st.caption(t("读取本地 summary.json 和同目录明细。", "Reads summary.json and evidence in the same folder."))
    st.markdown(t("**只读查看器**\n\n离线运行 · 不训练模型 · 不访问网页", "**Read-only viewer**\n\nOffline · No model training · No page fetching"))

st.markdown('<div class="eyebrow">DOMSCOPE / RESEARCH UTILITIES</div>', unsafe_allow_html=True)
st.title(t("看见网页背后的相同结构", "Different pages. Shared structure."))
st.markdown('<div class="subhead">' + t("对比原始 HTML、DOM 与域名联合表示，追溯跨划分重合和标签冲突。",
                 "Compare raw HTML, DOM and hostname representations. Trace split overlap and label conflicts to their evidence.") + '</div>', unsafe_allow_html=True)

if not Path(report_path).is_file():
    st.info(t("先运行一次审计，再在左侧选择生成的 summary.json。", "Run an audit first, then select its summary.json in the sidebar."))
    st.code("python -m domscope audit --manifest examples/manifest.jsonl --out outputs/demo", language="bash")
    st.stop()
try:
    bundle = load_bundle(Path(report_path))
except ReportError as exc:
    st.error(t("无法读取报告：", "Unable to read report: ") + str(exc))
    st.stop()

summary, samples, groups = bundle["summary"], bundle["samples"], bundle["groups"]
if summary["data_kind"] == "synthetic":
    st.markdown('<span class="local-badge">' + t("合成演示数据 · 用于核对工具行为", "SYNTHETIC DEMO · FOR TOOL VERIFICATION") + '</span>', unsafe_allow_html=True)
else:
    st.info(t("用户提供的数据：标签和来源未经本工具核验。", "User-supplied data: labels and provenance are not verified by this tool."))
st.write("")
cards = st.columns(4)
for column, label, value in zip(cards,
                               [t("有效网页", "Valid pages"), t("排除样本", "Excluded pages"), t("DOM 结构组", "DOM groups"), t("混合标签组", "Mixed-label groups")],
                               [summary["counts"]["valid"], summary["counts"]["excluded"], len(groups), summary["dom_conflicts"]["all"]["mixed_groups"]]):
    column.metric(label, str(value))

overview, cases_tab, exports = st.tabs([t("概览", "Overview"), t("案例", "Cases"), t("导出", "Export")])
with overview:
    st.subheader(t("同一批样本，三种观察方式", "One cohort. Three representations."))
    cohort_name = st.radio(t("比较范围", "Comparison cohort"), ["dom", "host"], horizontal=True,
                           format_func=lambda x: t("全部有效 DOM", "All valid DOM") if x == "dom" else t("仅有效 DOM＋域名", "Valid DOM + hostname"), key="cohort")
    cohort = summary["cohorts"][cohort_name]
    st.caption(t("各行使用相同样本集合；缺失域名仅影响联合比较。", "Every row uses the same eligible samples; missing hostnames affect only the hostname cohort.")
               + f" N = {cohort['size']} · train {cohort['split_counts']['train']} / val {cohort['split_counts']['val']} / test {cohort['split_counts']['test']}")
    records = []
    for field, rep in cohort["representations"].items():
        name = {"raw_hash": t("原始 HTML 字节", "Raw HTML bytes"), "dom_hash": "DOM", "dom_host_hash": "DOM + hostname"}[field]
        records.append({t("表示", "Representation"): name,
                        t("独立组数", "Unique groups"): rep["unique_groups"],
                        "test → train": fmt(rep["overlap"]["test_to_train"]),
                        "val → train": fmt(rep["overlap"]["val_to_train"]),
                        t("冗余样本", "Redundancy"): fmt(rep["redundant_samples"]),
                        t("重复组覆盖", "In duplicate groups"): fmt(rep["duplicate_group_samples"])})
    st.dataframe(pd.DataFrame(records), hide_index=True, width="stretch")
    extra = cohort["extra_dom_overlap"]["test_to_train"]
    st.info(t("原始字节未在训练集中出现的测试样本中，DOM 仍然重合：", "Among raw-unseen test samples, DOM still overlaps with training: ") + fmt(extra))
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.subheader(t("结构组有多大", "How large are the groups?"))
        sizes = Counter(g["size"] for g in groups)
        chart = pd.DataFrame({t("组内样本数", "Samples per group"): [str(k) for k in sorted(sizes)],
                              t("结构组数", "Number of groups"): [sizes[k] for k in sorted(sizes)]})
        st.bar_chart(chart, x=chart.columns[0], y=chart.columns[1], color="#11786A", height=240)
    with right:
        st.subheader(t("相同结构，标签可能不同", "Shared structure, different labels"))
        c = summary["dom_conflicts"]["all"]
        st.write(t("冲突涉及的已标注样本", "Labeled samples in conflicting groups") + ": **" + fmt(c["conflict_samples"]) + "**")
        st.write(t("DOM 经验冲突错误比例", "Empirical DOM conflict error") + ": **" + fmt(c["empirical_error"]) + "**")
        st.caption(t("此处范围为全部有效 DOM，含纯标签组；它描述当前样本，不能视为模型错误率或泛化下界。",
                     "Scope: all valid DOM samples, including pure-label groups. This describes this sample, not model error or a generalization bound."))
        st.caption(t("结构重合不等于恶意、同一钓鱼套件或已证实的数据泄漏。", "Structural overlap does not establish maliciousness, common kit origin or data leakage."))
    with st.expander(t("按划分／来源检查标签冲突", "Label conflicts by split / source")):
        rows = []
        for axis in ("by_split", "by_source"):
            for name, c in summary["dom_conflicts"][axis].items():
                rows.append({t("范围", "Scope"): f"{axis}: {name}", t("已标注", "Labeled"): c["labeled_samples"],
                             t("混合组", "Mixed groups"): c["mixed_groups"], t("冲突样本", "Conflict samples"): fmt(c["conflict_samples"]),
                             t("经验错误", "Empirical error"): fmt(c["empirical_error"])})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

with cases_tab:
    st.subheader(t("从统计回到证据", "Follow the numbers to the evidence"))
    dom_only = st.checkbox(t("只看原始不重合、DOM 重合的留出样本", "Only held-out samples with raw-unseen, DOM-seen structure"),
                           value=any(s["dom_only_seen_in_train"] for s in samples), key="dom_only")
    filters = st.columns(4)
    all_label = t("全部", "All")
    source = filters[0].selectbox(t("来源", "Source"), [all_label] + sorted({s["source"] for s in samples}), key="source")
    split = filters[1].selectbox(t("划分", "Split"), [all_label, "train", "val", "test"], key="split")
    label = filters[2].selectbox(t("标签", "Label"), [all_label, "0 · benign", "1 · phishing", t("未标注", "Unlabeled")], key="label")
    group_id = filters[3].selectbox(t("结构组", "DOM group"), [all_label] + [g["group_id"] for g in groups],
                                  format_func=lambda value: value[:12] if value != all_label else value, key="group")
    filtered = [s for s in samples if (not dom_only or s["dom_only_seen_in_train"])
                and (source == all_label or s["source"] == source)
                and (split == all_label or s["split"] == split)
                and (group_id == all_label or s["dom_hash"] == group_id)
                and (label == all_label or (s["label"] == 0 and label.startswith("0"))
                     or (s["label"] == 1 and label.startswith("1")) or (s["label"] is None and label in ("未标注", "Unlabeled")))]
    if not filtered:
        st.info(t("此筛选下没有样本。", "No samples match these filters."))
    else:
        sid = st.selectbox(t("查看样本", "Inspect a sample"), [s["sample_id"] for s in filtered], key="sample")
        selected = next(s for s in filtered if s["sample_id"] == sid)
        members = [s for s in samples if s["dom_hash"] == selected["dom_hash"]]
        st.caption(f"{sid} · {selected['split']} · " + t("同组样本：", "Group members: ") + ", ".join(s["sample_id"] for s in members))
        st.dataframe(pd.DataFrame([{k: s[k] for k in ("sample_id", "split", "label", "source", "hostname", "element_count", "raw_seen_in_train", "dom_seen_in_train")} for s in members]), hide_index=True, width="stretch")
        case = bundle["cases"][sid]
        raw_col, dom_col = st.columns(2)
        with raw_col:
            st.markdown(t("**原始 HTML 片段**", "**Raw HTML preview**"))
            st.code(case["raw_preview"], language="html", height=310)
        with dom_col:
            st.markdown(t("**规范 DOM 片段**", "**Canonical DOM preview**"))
            st.code(case["dom_preview"], language="json", height=310)
        if case["raw_preview_truncated"] or case["dom_preview_truncated"]:
            st.caption(t("展示片段已截断；指纹使用完整的已接受输入。", "Preview truncated; fingerprints use the complete accepted input."))
        st.caption(t("源码仅以文本显示，不执行脚本或表单。", "Source is displayed as inert text; scripts and forms are never executed."))

with exports:
    st.subheader(t("带走一份可复核的结果", "Take the evidence with you"))
    st.caption(t("报告包含样本明细、排除原因、规则版本与输入哈希。真实数据的源码片段可能包含私密内容，分享前请检查。",
                 "The bundle includes samples, exclusions, versions and input hashes. Real-data previews may contain private content; review before sharing."))
    for index, (name, content) in enumerate(bundle["downloads"].items()):
        mime = "text/csv" if name.endswith(".csv") else "application/json" if name.endswith(".json") else "text/plain"
        st.download_button(name, content, file_name=name, mime=mime, key=f"download_{index}")
    with st.expander(t("排除与解析记录", "Exclusions and parsing notes")):
        if bundle["issues"]:
            st.dataframe(pd.DataFrame(bundle["issues"]), hide_index=True, width="stretch")
        else:
            st.success(t("没有排除样本或解析警告。", "No exclusions or parsing warnings."))
    with st.expander(t("运行元数据", "Run metadata")):
        st.json(summary["metadata"])

st.divider()
st.caption(t("DOMScope 0.1 · 描述性结构审计 · 合成演示不能替代真实数据实验", "DOMScope 0.1 · Descriptive structure auditing · Synthetic examples are not empirical research"))
