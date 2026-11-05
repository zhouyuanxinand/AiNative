# 真实流程参数句界解析修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 用户项目说明在六参数后接中文句号和解释时，受控参数只采用该句明确声明的值，保留原文引用。

**Architecture:** 仅调整 analysis.py 的自然语言声明句切分；继续使用既有受控值、冲突检测、原文引用与明确采用规则。不修改原任务书生成引擎和交付门禁。

**Tech Stack:** Python、pytest，现有 React 页面真实复验。

**Spec:** 本轮用户要求真实走完可在浏览器查看的流程；既有六参数从资料与流程形成的约束。

## Global Constraints

- 保留受控身份、原文引用、冲突拒绝和用户明确采用；未知不可编造。
- 只运行本次失败用例及完整 test_source_analysis.py，不运行无筛选全量。
- 不提交、推送或清理其他未提交改动。

## Review Focus

- 中文句号后普通说明不能进入参数值。
- 分号、换行的已有声明保持可解析。
- 相邻句出现不同明确值仍需报告冲突。
- 小数点、型号标点不作为中文句界拆分。
- 引用必须仍可追溯至完整原文中的声明片段。

### Task 1: 修正参数声明句边界

**Files:** 修改 basic-service/app/src/service/rd_platform/analysis.py；扩展 basic-service/app/tests/rd_platform/test_source_analysis.py。

- [x] 添加并运行句号后说明导致组织范围未识别的定点失败用例。
- [x] 最小修复中文句界切分，不以模糊别名猜测受控值。
- [x] 验证冲突、原文引用、小数点边界；运行完整受影响测试文件，20项通过。
- [x] 重启实际后端，通过真实页面重新分析和明确采用，再继续需求、选型、模板和工作包操作。
- [x] 将实际截图、数据记录和未通过门禁原因写入本轮验收报告。
